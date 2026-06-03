"""
executor.py — Sequential agent executor with configurable invocation.

New in this version:
  - _render_value():   replaces {token} placeholders in template values
  - _render_body():    recursively renders body_template dict/list/str
  - _build_body():     produces the final request body from InvocationConfig
  - _extract_result(): walks response_result_path to find the result string
  - _call_agent():     uses invocation_config for method, content-type, body, timeout
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import Awaitable, Callable
from typing import Any

import auth_injector
import httpx
from execution_graph import build_execution_layers
from schema_mapper import SchemaMapError, build as schema_build
from schema_mapper import fields_from_config

log = logging.getLogger(__name__)

_GLOBAL_TIMEOUT = float(os.environ.get("AGENT_TIMEOUT_SECS", "45"))
_GLOBAL_MAX_RETRY = int(os.environ.get("AGENT_MAX_RETRIES", "2"))
_PARALLEL_EXEC = os.environ.get("ORCHESTRATOR_PARALLEL_EXEC", "true").lower() == "true"

StepProgressCallback = Callable[..., Awaitable[None]]


# =============================================================================
# Template rendering
# =============================================================================


def _render_value(val: Any, ctx: dict[str, Any]) -> Any:
    """
    Replace {token} placeholders inside a string value.

    Supported tokens (passed in ctx):
        {task}        — the plan step's task string
        {session_id}  — orchestrator session ID
        {customer_id} — customer ID (may be empty string)
        {context}     — JSON string of prior step outputs
        {step_N}      — output text of step N (e.g. {step_1})

    Non-string values are returned unchanged.
    A value that consists of ONLY a single token (e.g. "{context}") is
    replaced with the raw Python object — so {"context": "{context}"} becomes
    {"context": {"step_1": "...", "step_2": "..."}} rather than a JSON string.
    """
    if not isinstance(val, str):
        return val

    stripped = val.strip()
    # Single-token shorthand: return raw object for non-string types
    if stripped.startswith("{") and stripped.endswith("}"):
        token = stripped[1:-1]
        if token in ctx:
            return ctx[token]

    # Multi-token or mixed: string replacement only
    result = val
    for token, replacement in ctx.items():
        if isinstance(replacement, str):
            result = result.replace(f"{{{token}}}", replacement)
        else:
            result = result.replace(f"{{{token}}}", json.dumps(replacement))
    return result


def _render_body(template: Any, ctx: dict[str, Any]) -> Any:
    """Recursively render a body_template dict/list/scalar."""
    if isinstance(template, dict):
        return {k: _render_body(v, ctx) for k, v in template.items()}
    if isinstance(template, list):
        return [_render_body(item, ctx) for item in template]
    return _render_value(template, ctx)


def _build_context(
    task: str,
    session_id: str,
    customer_id: str | None,
    prior_outputs: dict[int, str],
    context_note: str,
    transcript: list[dict[str, str]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    ctx: dict[str, Any] = {
        "task": task,
        "session_id": session_id,
        "customer_id": customer_id or "",
    }
    for step_id, output in prior_outputs.items():
        ctx[f"step_{step_id}"] = output

    context_dict: dict[str, Any] = {}
    for dep_id, output in prior_outputs.items():
        context_dict[f"step_{dep_id}_output"] = output
    if context_note:
        context_dict["planner_note"] = context_note
    ctx["context"] = context_dict

    history_slice: list[dict[str, str]] = []
    if transcript:
        history_slice = [{"role": t["role"], "content": t["content"]} for t in transcript[-12:]]
    ctx["conversation_history"] = history_slice
    context_dict["conversation_history"] = history_slice

    return ctx, context_dict


async def _build_body(
    invocation_config: dict[str, Any],
    task: str,
    session_id: str,
    customer_id: str | None,
    prior_outputs: dict[int, str],
    context_note: str,
    transcript: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """
    Build the HTTP request body.

    Priority: body_template → request_schema (LLM mapper) → legacy AgentRequest.
    """
    body_template = invocation_config.get("body_template") or {}
    ctx, context_dict = _build_context(
        task, session_id, customer_id, prior_outputs, context_note, transcript
    )

    if body_template:
        return _render_body(body_template, ctx)

    request_schema = invocation_config.get("request_schema") or {}
    schema_fields = fields_from_config(request_schema)
    if schema_fields:
        strict = request_schema.get("strict", True)
        json_schema = request_schema.get("json_schema")
        mapping = await schema_build(
            schema_fields=schema_fields,
            strict=bool(strict),
            json_schema=json_schema,
            task=task,
            session_id=session_id,
            customer_id=customer_id,
            prior_outputs=prior_outputs,
            context_note=context_note,
        )
        return mapping.body

    return {
        "task": task,
        "session_id": session_id,
        "customer_id": customer_id,
        "context": context_dict,
        "conversation_history": context_dict.get("conversation_history", []),
    }


def _extract_result(response_body: dict[str, Any], result_path: str) -> str:
    """
    Walk a dot-notation path to extract the result string from the response.

    Examples:
        "result"                      → response_body["result"]
        "data.text"                   → response_body["data"]["text"]
        "choices.0.message.content"   → response_body["choices"][0]["message"]["content"]

    Returns str(entire response) when path is empty or navigation fails.
    """
    if not result_path:
        # Try common default keys before giving up
        for key in ("result", "output", "response", "text", "content", "message"):
            if key in response_body:
                val = response_body[key]
                return val if isinstance(val, str) else json.dumps(val)
        return json.dumps(response_body)

    parts = result_path.split(".")
    node: Any = response_body
    try:
        for part in parts:
            if isinstance(node, list):
                node = node[int(part)]
            else:
                node = node[part]
        return node if isinstance(node, str) else json.dumps(node)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        log.warning(
            "response_result_path '%s' failed navigation (%s) — returning full response",
            result_path,
            exc,
        )
        return json.dumps(response_body)


# =============================================================================
# Single agent call
# =============================================================================


async def _call_agent(
    step: Any,
    session_id: str,
    customer_id: str | None,
    prior_outputs: dict[int, str],
    http_client: httpx.AsyncClient,
    transcript: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """
    Build, auth-inject, and send the HTTP request to a remote agent.
    Returns a normalised dict: { result, actions_taken, suggestions, metadata }.
    """
    inv = step.invocation_config or {}
    method = (inv.get("http_method") or "POST").upper()
    content_type = inv.get("content_type") or "application/json"
    timeout = inv.get("timeout_seconds") or 0
    max_retries = inv.get("max_retries", -1)

    effective_timeout = float(timeout) if timeout > 0 else _GLOBAL_TIMEOUT
    effective_max_retry = max_retries if max_retries >= 0 else _GLOBAL_MAX_RETRY

    body = await _build_body(
        invocation_config=inv,
        task=step.task,
        session_id=session_id,
        customer_id=customer_id,
        prior_outputs=prior_outputs,
        context_note=getattr(step, "context_note", ""),
        transcript=transcript,
    )

    # Resolve authentication
    try:
        injected = await auth_injector.resolve(
            auth_config=step.auth_config or {},
            legacy_secret_name=step.api_key_secret_name,
        )
    except Exception as exc:
        raise RuntimeError(f"Auth resolution failed for {step.agent_name}: {exc}") from exc

    # Static extra headers from invocation_config (non-auth)
    base_headers = {
        "Content-Type": content_type,
        **(inv.get("extra_static_headers") or {}),
    }

    request_kwargs: dict[str, Any] = {
        "method": method,
        "url": step.agent_url,
        "headers": base_headers,
    }
    # Attach body based on content type
    if "json" in content_type.lower():
        request_kwargs["json"] = body
    else:
        request_kwargs["content"] = json.dumps(body).encode()

    request_kwargs = injected.apply_to_kwargs(request_kwargs)

    last_exc: Exception | None = None
    for attempt in range(1, effective_max_retry + 2):
        try:
            resp = await http_client.request(**request_kwargs, timeout=effective_timeout)
            resp.raise_for_status()

            resp_body = resp.json()
            result_path = inv.get("response_result_path") or ""
            result_text = _extract_result(resp_body, result_path)

            return {
                "result": result_text,
                "actions_taken": resp_body.get("actions_taken", []),
                "suggestions": resp_body.get("suggestions", []),
                "metadata": resp_body.get("metadata", {}),
            }

        except httpx.HTTPStatusError as e:
            log.warning("Agent %s HTTP %s (attempt %d)", step.agent_name, e.response.status_code, attempt)
            last_exc = e
            if e.response.status_code < 500:
                break
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            log.warning("Agent %s unreachable (attempt %d): %s", step.agent_name, attempt, e)
            last_exc = e
            if attempt <= effective_max_retry:
                await asyncio.sleep(2**attempt)

    raise RuntimeError(f"Agent {step.agent_name} failed after {effective_max_retry + 1} attempts: {last_exc}")


# =============================================================================
# Main execution loop
# =============================================================================


async def _execute_one_step(
    step: Any,
    session_id: str,
    customer_id: str | None,
    prior_outputs: dict[int, str],
    trace_ctx: Any | None,
    http_client: httpx.AsyncClient,
    on_step_progress: StepProgressCallback | None,
    transcript: list[dict[str, str]] | None = None,
) -> tuple[int, dict | None, str | None]:
    """Returns (step_id, response_dict or None, error or None)."""
    import memory

    log.info("Executing step %d: %s", step.step_id, step.agent_name)
    await memory.save_step_start(session_id, step.step_id, step.agent_name, step.task)

    if on_step_progress:
        await on_step_progress(step.step_id, step.agent_name, "running")

    body_preview = None
    if trace_ctx:
        await trace_ctx.record_event(
            stage="execution",
            status="running",
            message=f"Executing step {step.step_id} with agent {step.agent_name}.",
            metadata={"step_id": step.step_id, "agent_name": step.agent_name},
        )
        try:
            body_preview = await _build_body(
                invocation_config=step.invocation_config or {},
                task=step.task,
                session_id=session_id,
                customer_id=customer_id,
                prior_outputs=prior_outputs,
                context_note=getattr(step, "context_note", ""),
                transcript=transcript,
            )
        except Exception as preview_exc:
            log.warning("Body preview failed for step %d: %s", step.step_id, preview_exc)
            body_preview = {}
        trace_ctx.record_step_start(step, body_preview or {})

    t0 = time.monotonic()
    try:
        response = await _call_agent(
            step, session_id, customer_id, prior_outputs, http_client, transcript
        )
        latency_ms = int((time.monotonic() - t0) * 1000)

        await memory.save_step_result(
            session_id=session_id,
            step_id=step.step_id,
            agent_name=step.agent_name,
            result=response["result"],
            metadata={
                "actions_taken": response.get("actions_taken"),
                "suggestions": response.get("suggestions"),
                **response.get("metadata", {}),
            },
        )
        if trace_ctx:
            await trace_ctx.record_event(
                stage="execution",
                status="completed",
                message=f"Completed step {step.step_id} with agent {step.agent_name}.",
                metadata={"step_id": step.step_id, "agent_name": step.agent_name},
            )
            await trace_ctx.record_step_result(
                step_id=step.step_id,
                output=response,
                result=response["result"],
            )
        if on_step_progress:
            await on_step_progress(step.step_id, step.agent_name, "completed", latency_ms=latency_ms)
        log.info("Step %d (%s) completed", step.step_id, step.agent_name)
        return step.step_id, response, None

    except SchemaMapError as exc:
        err = f"Schema mapping failed: {exc}"
        if trace_ctx:
            try:
                await trace_ctx.record_step_schema_error(step.step_id, err)
            except Exception:
                pass
        if on_step_progress:
            await on_step_progress(step.step_id, step.agent_name, "failed", error=err)
        return step.step_id, None, err
    except Exception as exc:
        log.error("Step %d (%s) failed: %s", step.step_id, step.agent_name, exc)
        await memory.save_step_error(session_id, step.step_id, step.agent_name, str(exc))
        if trace_ctx:
            await trace_ctx.record_event(
                stage="execution",
                status="failed",
                message=f"Failed step {step.step_id} with agent {step.agent_name}.",
                metadata={"step_id": step.step_id, "agent_name": step.agent_name, "error": str(exc)},
            )
            await trace_ctx.record_step_error(step.step_id, str(exc))
        if on_step_progress:
            await on_step_progress(step.step_id, step.agent_name, "failed", error=str(exc))
        return step.step_id, None, str(exc)


async def execute_plan(
    plan: Any,
    session_id: str,
    customer_id: str | None,
    trace_ctx: Any | None = None,
    on_step_progress: StepProgressCallback | None = None,
    transcript: list[dict[str, str]] | None = None,
) -> dict:
    import memory

    results: dict[int, dict] = {}
    failed: set[int] = set()
    prior_outputs: dict[int, str] = {}

    await memory.update_session(session_id, status="executing")

    layers = build_execution_layers(plan.steps) if _PARALLEL_EXEC else [[s] for s in plan.steps]

    async with httpx.AsyncClient(timeout=_GLOBAL_TIMEOUT) as http_client:
        for layer in layers:
            runnable: list[Any] = []
            for step in layer:
                blocked = [d for d in step.depends_on if d in failed]
                if blocked:
                    log.warning(
                        "Skipping step %d (%s): deps %s failed",
                        step.step_id,
                        step.agent_name,
                        blocked,
                    )
                    failed.add(step.step_id)
                    await memory.save_step_error(
                        session_id,
                        step.step_id,
                        step.agent_name,
                        f"Skipped — deps {blocked} failed",
                    )
                    if trace_ctx:
                        await trace_ctx.record_event(
                            stage="execution",
                            status="skipped",
                            message=f"Skipped step {step.step_id} ({step.agent_name}) due to failed dependencies.",
                            metadata={
                                "step_id": step.step_id,
                                "agent_name": step.agent_name,
                                "blocked_by": blocked,
                            },
                        )
                        await trace_ctx.record_step_error(
                            step.step_id, f"Skipped — deps {blocked} failed", skipped=True
                        )
                    if on_step_progress:
                        await on_step_progress(step.step_id, step.agent_name, "skipped")
                    continue
                runnable.append(step)

            if not runnable:
                continue

            if len(runnable) == 1:
                step = runnable[0]
                sid, response, err = await _execute_one_step(
                    step,
                    session_id,
                    customer_id,
                    prior_outputs,
                    trace_ctx,
                    http_client,
                    on_step_progress,
                    transcript,
                )
                if err:
                    failed.add(sid)
                elif response:
                    results[sid] = response
                    prior_outputs[sid] = response["result"]
                continue

            tasks = [
                _execute_one_step(
                    step,
                    session_id,
                    customer_id,
                    dict(prior_outputs),
                    trace_ctx,
                    http_client,
                    on_step_progress,
                    transcript,
                )
                for step in runnable
            ]
            outcomes = await asyncio.gather(*tasks, return_exceptions=True)
            for outcome in outcomes:
                if isinstance(outcome, Exception):
                    log.error("Parallel step raised: %s", outcome)
                    continue
                sid, response, err = outcome
                if err:
                    failed.add(sid)
                elif response:
                    results[sid] = response
                    prior_outputs[sid] = response["result"]

    return results

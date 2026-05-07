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
from typing import Any

import auth_injector
import httpx

log = logging.getLogger(__name__)

_GLOBAL_TIMEOUT = float(os.environ.get("AGENT_TIMEOUT_SECS", "45"))
_GLOBAL_MAX_RETRY = int(os.environ.get("AGENT_MAX_RETRIES", "2"))


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


def _build_body(
    invocation_config: dict[str, Any],
    task: str,
    session_id: str,
    customer_id: str | None,
    prior_outputs: dict[int, str],
    context_note: str,
) -> dict[str, Any]:
    """
    Build the HTTP request body.

    If invocation_config.body_template is non-empty, render it.
    Otherwise fall back to the legacy AgentRequest schema.
    """
    body_template = invocation_config.get("body_template") or {}

    # Build context dict for template rendering
    ctx: dict[str, Any] = {
        "task": task,
        "session_id": session_id,
        "customer_id": customer_id or "",
    }
    # Step outputs available as {step_1}, {step_2}, etc.
    for step_id, output in prior_outputs.items():
        ctx[f"step_{step_id}"] = output

    # Full context dict available as {context}
    context_dict: dict[str, Any] = {}
    for dep_id, output in prior_outputs.items():
        context_dict[f"step_{dep_id}_output"] = output
    if context_note:
        context_dict["planner_note"] = context_note
    ctx["context"] = context_dict

    if body_template:
        return _render_body(body_template, ctx)

    # Legacy default — matches the original AgentRequest Pydantic model
    return {
        "task": task,
        "session_id": session_id,
        "customer_id": customer_id,
        "context": context_dict,
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

    body = _build_body(
        invocation_config=inv,
        task=step.task,
        session_id=session_id,
        customer_id=customer_id,
        prior_outputs=prior_outputs,
        context_note=getattr(step, "context_note", ""),
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
            async with httpx.AsyncClient(timeout=effective_timeout) as client:
                resp = await client.request(**request_kwargs)
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


async def execute_plan(
    plan: Any,
    session_id: str,
    customer_id: str | None,
    trace_ctx: Any | None = None,
) -> dict:
    import memory

    results: dict[int, dict] = {}
    failed: set[int] = set()
    prior_outputs: dict[int, str] = {}

    await memory.update_session(session_id, status="executing")

    for step in plan.steps:
        blocked = [d for d in step.depends_on if d in failed]
        if blocked:
            log.warning("Skipping step %d (%s): deps %s failed", step.step_id, step.agent_name, blocked)
            failed.add(step.step_id)
            await memory.save_step_error(session_id, step.step_id, step.agent_name, f"Skipped — deps {blocked} failed")
            if trace_ctx:
                await trace_ctx.record_event(
                    stage="execution",
                    status="skipped",
                    message=f"Skipped step {step.step_id} ({step.agent_name}) due to failed dependencies.",
                    metadata={"step_id": step.step_id, "agent_name": step.agent_name, "blocked_by": blocked},
                )
                await trace_ctx.record_step_error(step.step_id, f"Skipped — deps {blocked} failed", skipped=True)
            continue

        log.info("Executing step %d: %s", step.step_id, step.agent_name)
        await memory.save_step_start(session_id, step.step_id, step.agent_name, step.task)
        if trace_ctx:
            await trace_ctx.record_event(
                stage="execution",
                status="running",
                message=f"Executing step {step.step_id} with agent {step.agent_name}.",
                metadata={"step_id": step.step_id, "agent_name": step.agent_name},
            )
            body_preview = _build_body(
                invocation_config=step.invocation_config or {},
                task=step.task,
                session_id=session_id,
                customer_id=customer_id,
                prior_outputs=prior_outputs,
                context_note=getattr(step, "context_note", ""),
            )
            trace_ctx.record_step_start(step, body_preview)

        try:
            response = await _call_agent(step, session_id, customer_id, prior_outputs)
            results[step.step_id] = response
            prior_outputs[step.step_id] = response["result"]

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
            log.info("Step %d (%s) completed", step.step_id, step.agent_name)

        except Exception as exc:
            log.error("Step %d (%s) failed: %s", step.step_id, step.agent_name, exc)
            failed.add(step.step_id)
            await memory.save_step_error(session_id, step.step_id, step.agent_name, str(exc))
            if trace_ctx:
                await trace_ctx.record_event(
                    stage="execution",
                    status="failed",
                    message=f"Failed step {step.step_id} with agent {step.agent_name}.",
                    metadata={"step_id": step.step_id, "agent_name": step.agent_name, "error": str(exc)},
                )
                await trace_ctx.record_step_error(step.step_id, str(exc))

    return results

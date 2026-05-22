from __future__ import annotations
import asyncio
import json
import logging
import os
from typing import Any

import httpx

import auth_injector
import schema_mapper
from schema_mapper import SchemaMapError, MappingResult
from trace_writer import TraceContext
from models import ExecutionPlan, RequestSchemaField
import memory

log = logging.getLogger(__name__)

_GLOBAL_TIMEOUT = float(os.environ.get("AGENT_TIMEOUT_SECS", "45"))
_GLOBAL_MAX_RETRY = int(os.environ.get("AGENT_MAX_RETRIES", "2"))

def _render_value(val: Any, ctx: dict[str, Any]) -> Any:
    if not isinstance(val, str):
        return val
    stripped = val.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        token = stripped[1:-1]
        if token in ctx:
            return ctx[token]
    result = val
    for token, replacement in ctx.items():
        if isinstance(replacement, str):
            result = result.replace(f"{{{token}}}", replacement)
        else:
            result = result.replace(f"{{{token}}}", json.dumps(replacement))
    return result


def _render_body(template: Any, ctx: dict[str, Any]) -> Any:
    if isinstance(template, dict):
        return {k: _render_body(v, ctx) for k, v in template.items()}
    if isinstance(template, list):
        return [_render_body(item, ctx) for item in template]
    return _render_value(template, ctx)


def _build_body(
    invocation_config: dict[str, Any],
    task:              str,
    session_id:        str,
    customer_id:       str | None,
    prior_outputs:     dict[int, str],
    context_note:      str,
) -> dict[str, Any]:
    body_template = invocation_config.get("body_template") or {}
    ctx: dict[str, Any] = {
        "task":        task,
        "session_id":  session_id,
        "customer_id": customer_id or "",
    }
    for step_id, output in prior_outputs.items():
        ctx[f"step_{step_id}"] = output
    context_dict: dict[str, Any] = {
        f"step_{dep_id}_output": output
        for dep_id, output in prior_outputs.items()
    }
    if context_note:
        context_dict["planner_note"] = context_note
    ctx["context"] = context_dict

    if body_template:
        return _render_body(body_template, ctx)
    return {
        "task":        task,
        "session_id":  session_id,
        "customer_id": customer_id,
        "context":     context_dict,
    }


def _extract_result(response_body: dict[str, Any], result_path: str) -> str:
    if not result_path:
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
        log.warning("response_result_path '%s' failed navigation (%s) — returning full response", result_path, exc)
        return json.dumps(response_body)

async def _call_agent(
    step:          Any,
    session_id:    str,
    customer_id:   str | None,
    prior_outputs: dict[int, str],
    trace:         TraceContext | None,
) -> dict[str, Any]:
    inv         = step.invocation_config or {}
    method      = (inv.get("http_method") or "POST").upper()
    content_type = inv.get("content_type") or "application/json"
    timeout     = inv.get("timeout_seconds") or 0
    max_retries = inv.get("max_retries", -1)

    effective_timeout   = float(timeout)  if timeout   > 0 else _GLOBAL_TIMEOUT
    effective_max_retry = max_retries     if max_retries >= 0 else _GLOBAL_MAX_RETRY

    context_note = getattr(step, "context_note", "")

    # ── Body construction ─────────────────────────────────────────────────────
    mapping_result: MappingResult | None = None
    schema_fields = []

    # Check if schema-driven mode is active
    req_schema = inv.get("request_schema") or {}
    schema_fields = req_schema.get("fields") or []

    if schema_fields:
        # ── Schema-driven mode ────────────────────────────────────────────────
        log.info(
            "executor: using schema-driven body construction for %s (%d fields)",
            step.agent_name, len(schema_fields),
        )
        # Convert raw dicts to RequestSchemaField objects
        parsed_fields = [
            RequestSchemaField(**f) if isinstance(f, dict) else f
            for f in schema_fields
        ]
        strict      = req_schema.get("strict", True)
        json_schema = req_schema.get("json_schema")

        try:
            mapping_result = await schema_mapper.build(
                schema_fields=parsed_fields,
                strict=strict,
                json_schema=json_schema,
                task=step.task,
                session_id=session_id,
                customer_id=customer_id,
                prior_outputs=prior_outputs,
                context_note=context_note,
            )
            body = mapping_result.body

        except SchemaMapError as exc:
            # Required field could not be populated → fail this step immediately
            err_msg = str(exc)
            log.error("executor: schema mapping failed for %s: %s", step.agent_name, err_msg)
            if trace:
                # Record the mapping attempt before raising
                await trace.record_step_schema_error(
                    step_id=step.step_id,
                    error=err_msg,
                    mapping_result=None,
                )
            raise RuntimeError(
                f"Schema mapping failed for {step.agent_name}: {err_msg}"
            ) from exc

        # Log any mapping warnings
        if mapping_result.warnings:
            for w in mapping_result.warnings:
                log.warning("schema_mapper [%s]: %s", step.agent_name, w)

        # Capture input BEFORE auth injection
        if trace:
            trace.record_step_start(step, body, mapping_result=mapping_result)

    else:
        # ── Legacy mode ───────────────────────────
        body = _build_legacy_body(inv, step.task, session_id, customer_id,
                                  prior_outputs, context_note)
        if trace:
            trace.record_step_start(step, body, mapping_result=None)

    # ── Auth injection ─────────────────────────────────────────────
    try:
        injected = await auth_injector.resolve(
            auth_config=step.auth_config or {},
            legacy_secret_name=step.api_key_secret_name,
        )
    except Exception as exc:
        raise RuntimeError(f"Auth resolution failed for {step.agent_name}: {exc}") from exc

    base_headers = {
        "Content-Type": content_type,
        **(inv.get("extra_static_headers") or {}),
    }
    request_kwargs: dict[str, Any] = {
        "method":  method,
        "url":     step.agent_url,
        "headers": base_headers,
    }
    if "json" in content_type.lower():
        request_kwargs["json"] = body
    else:
        request_kwargs["content"] = json.dumps(body).encode()

    request_kwargs = injected.apply_to_kwargs(request_kwargs)

    # ── HTTP call with retry ───────────────────────────────────────────────────
    last_exc: Exception | None = None
    for attempt in range(1, effective_max_retry + 2):
        try:
            async with httpx.AsyncClient(timeout=effective_timeout) as client:
                resp = await client.request(**request_kwargs)
                resp.raise_for_status()

            resp_body   = resp.json()
            result_path = inv.get("response_result_path") or ""
            result_text = _extract_result(resp_body, result_path)

            response = {
                "result":        result_text,
                "actions_taken": resp_body.get("actions_taken", []),
                "suggestions":   resp_body.get("suggestions", []),
                "metadata":      resp_body.get("metadata", {}),
            }

            if trace:
                await trace.record_step_result(
                    step.step_id, resp_body, result_text,
                    mapping_result=mapping_result,
                )
            return response

        except httpx.HTTPStatusError as e:
            log.warning("Agent %s HTTP %s (attempt %d)",
                        step.agent_name, e.response.status_code, attempt)
            last_exc = e
            if e.response.status_code < 500:
                break
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            log.warning("Agent %s unreachable (attempt %d): %s", step.agent_name, attempt, e)
            last_exc = e
            if attempt <= effective_max_retry:
                await asyncio.sleep(2 ** attempt)

    raise RuntimeError(
        f"Agent {step.agent_name} failed after {effective_max_retry + 1} attempts: {last_exc}"
    )

async def execute_plan(
    plan: ExecutionPlan,
    session_id: str,
    customer_id: str | None,
    trace_ctx: TraceContext | None = None,
) -> dict:

    results: dict[int, dict] = {}
    failed: set[int] = set()
    prior_outputs: dict[int, str] = {}

    await memory.update_session(session_id, status="executing")

    for step in plan.steps:
        blocked = [d for d in step.depends_on if d in failed]
        if blocked:
            log.warning("Skipping step %d (%s): deps %s failed", step.step_id, step.agent_name, blocked)
            failed.add(step.step_id)
            if trace_ctx:
                await trace_ctx.record_event(
                    stage="execution",
                    status="skipped",
                    message=f"Skipped step {step.step_id} ({step.agent_name}) due to failed dependencies.",
                    metadata={"step_id": step.step_id, "agent_name": step.agent_name, "blocked_by": blocked},
                )
                await trace_ctx.record_step_error(step.step_id, f"Skipped — deps {blocked} failed", skipped=True)
            await memory.save_step_error(session_id, step.step_id, step.agent_name, f"Skipped — deps {blocked} failed")
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
                result=response["result"],
                step_id=step.step_id,
                agent_name=step.agent_name,
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

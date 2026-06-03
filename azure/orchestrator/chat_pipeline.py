"""
Shared chat orchestration pipeline for /api/chat and /api/chat/stream.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import evaluator
import executor
import input_guard
import memory
import planner
import response_formatter
import synthesizer
import trace_writer
from markdown_normalize import normalize_markdown
from models import ChatRequest, ProactiveTriggerRequest, SessionDoc, SessionStatus

log = logging.getLogger(__name__)

_DEMO_STEPS = os.environ.get("ORCHESTRATOR_DEMO_STEPS", "").lower() == "true"
_STREAM_PROGRESS = os.environ.get("ORCHESTRATOR_STREAM_PROGRESS", "").lower() == "true"


EventCallback = Callable[[str, dict[str, Any]], Awaitable[None]]


@dataclass
class PipelineResult:
    session_id: str
    response: str
    plan_id: str | None
    agents_used: list[str]
    steps_completed: int
    content_segments: list[dict[str, Any]]


async def _emit(on_event: EventCallback | None, event: str, data: dict[str, Any]) -> None:
    if on_event:
        await on_event(event, data)


async def _should_persist_trace_events() -> bool:
    return _DEMO_STEPS or _STREAM_PROGRESS


async def run_chat_pipeline(
    chat_req: ChatRequest | ProactiveTriggerRequest,
    *,
    on_event: EventCallback | None = None,
    stream_tokens: bool = False,
    trigger_type: str = "reactive",
) -> PipelineResult:
    metadata = None
    if trigger_type == "proactive":
        user_message = chat_req.message
        metadata = {
            "source_agent_name": getattr(chat_req, "agent_name", ""),
            "event_type": getattr(chat_req, "event_type", ""),
            "context": getattr(chat_req, "context", {}),
            "severity": getattr(chat_req, "severity", "medium"),
        }
    else:
        guard = input_guard.get_guardrails().validate(chat_req.message)
        if not guard.allowed:
            raise ValueError(guard.reason)
        user_message = guard.sanitized_query

    session_id_val = getattr(chat_req, "session_id", None)
    if session_id_val:
        existing = await memory.get_session(session_id_val)
        if existing:
            session = SessionDoc(**{k: v for k, v in existing.items() if k in SessionDoc.model_fields})
        else:
            session = SessionDoc(
                id=session_id_val,
                user_message=user_message,
                customer_id=chat_req.customer_id,
            )
            session = await memory.create_session(session)
    else:
        session = SessionDoc(
            user_message=user_message,
            customer_id=chat_req.customer_id,
        )
        session = await memory.create_session(session)

    session_id = session.id

    transcript: list[dict[str, str]] = []
    try:
        transcript = await memory.get_session_transcript(session_id)
    except Exception as exc:
        log.warning("Could not load session transcript for %s: %s", session_id, exc)

    if trigger_type == "proactive":
        await memory.save_proactive_message(session_id, user_message, metadata=metadata)
    else:
        await memory.save_user_message(session_id, user_message)

    await _emit(on_event, "session", {"session_id": session_id})

    trace_ctx = None
    try:
        trace_ctx = trace_writer.TraceContext(
            session_id=session_id,
            user_message=user_message,
            customer_id=chat_req.customer_id,
            trigger_type=trigger_type,
            proactive_meta=metadata,
        )
    except Exception as e:
        log.warning("Trace init failed (non-fatal): %s", e)

    persist_events = await _should_persist_trace_events()

    async def stage_event(stage: str, status: str, message: str, metadata: dict | None = None) -> None:
        await _emit(on_event, "stage", {"stage": stage, "status": status, "message": message, "metadata": metadata or {}})
        if trace_ctx and persist_events:
            await trace_ctx.record_event(stage, status, message, metadata)

    try:
        await stage_event("request", "running", "Received user request.")

        if trigger_type != "proactive":
            is_related = await input_guard.is_query_related_to_scenario(user_message)
            if not is_related:
                response_text = "It isn't related to scenario and cannot answer this question."
                await stage_event("request", "completed", "Request completed (unrelated query).")
                await memory.save_final_response(session_id, response_text)
                formatted = response_formatter.format_chat_response(response_text)
                if trace_ctx:
                    try:
                        await trace_ctx.finish(final_response=response_text)
                    except Exception as trace_err:
                        log.warning("Trace finish failed: %s", trace_err)
                return PipelineResult(
                    session_id=session_id,
                    response=formatted["response"],
                    plan_id=None,
                    agents_used=[],
                    steps_completed=0,
                    content_segments=formatted["content_segments"],
                )

        await stage_event("planning", "running", "Building execution plan.")
        plan = await planner.build_plan(
            user_message,
            chat_req.customer_id,
            session_id=session_id,
            transcript=transcript,
            trigger_type=trigger_type,
            args=metadata,
        )
        await memory.save_plan(session_id, plan)
        if trace_ctx:
            await trace_ctx.record_plan(plan)
        await stage_event("planning", "completed", f"Plan ready with {len(plan.steps)} step(s).", {"plan_id": plan.plan_id})
    except Exception as e:
        await stage_event("planning", "failed", "Planning failed.", {"error": str(e)})
        await memory.update_session(session_id, status=SessionStatus.FAILED)
        if trace_ctx:
            try:
                await trace_ctx.finish(error=f"Planning failed: {e}")
            except Exception:
                pass
        raise

    async def step_event(step_id: int, agent_name: str, status: str, latency_ms: int | None = None, error: str | None = None) -> None:
        payload: dict[str, Any] = {"step_id": step_id, "agent_name": agent_name, "status": status}
        if latency_ms is not None:
            payload["latency_ms"] = latency_ms
        if error:
            payload["error"] = error
        await _emit(on_event, "step", payload)

    step_results: dict[int, dict] = {}
    try:
        await stage_event("execution", "running", "Executing planned steps.")

        async def on_step_progress(step_id: int, agent_name: str, status: str, **extra: Any) -> None:
            await step_event(step_id, agent_name, status, extra.get("latency_ms"), extra.get("error"))

        if plan.steps:
            step_results = await executor.execute_plan(
                plan,
                session_id,
                chat_req.customer_id,
                trace_ctx=trace_ctx,
                on_step_progress=on_step_progress if on_event else None,
                transcript=transcript,
            )
        await stage_event("execution", "completed", f"Completed {len(step_results)} step(s).")
    except Exception as e:
        await stage_event("execution", "failed", "Execution failed.", {"error": str(e)})
        if trace_ctx:
            try:
                await trace_ctx.finish(error=f"Execution failed: {e}")
            except Exception:
                pass
        await memory.update_session(session_id, status=SessionStatus.FAILED)
        raise

    try:
        await memory.update_session(session_id, status=SessionStatus.SYNTHESIZING)
        await stage_event("synthesis", "running", "Synthesizing final answer.")

        async def on_token(delta: str) -> None:
            await _emit(on_event, "token", {"delta": delta})

        final = await synthesizer.synthesize(
            plan,
            step_results,
            user_message,
            transcript=transcript,
            on_token=on_token if stream_tokens else None,
            trigger_type=trigger_type,
            args=metadata,
        )

        agent_sections = "\n\n".join(
            str(payload.get("result") or "") for payload in step_results.values()
        )
        eval_result = await evaluator.evaluate_response(user_message, agent_sections, final)
        if not eval_result.get("pass", True):
            issues = "; ".join(eval_result.get("issues") or [])
            log.info("Synthesis repair pass triggered: %s", issues)
            final = await synthesizer.synthesize(
                plan,
                step_results,
                user_message,
                transcript=transcript,
                on_token=on_token if stream_tokens else None,
                repair_hint=issues,
                trigger_type=trigger_type,
                args=metadata,
            )

        final = normalize_markdown(final)
        await memory.save_final_response(session_id, final)
        formatted = response_formatter.format_chat_response(final)

        if trace_ctx:
            try:
                await trace_ctx.finish(final_response=final)
            except Exception as trace_err:
                log.warning("Trace finish failed: %s", trace_err)

        await stage_event("synthesis", "completed", "Response ready.")

        return PipelineResult(
            session_id=session_id,
            response=formatted["response"],
            plan_id=plan.plan_id,
            agents_used=[s.agent_name for s in plan.steps],
            steps_completed=len(step_results),
            content_segments=formatted["content_segments"],
        )
    except Exception as e:
        await stage_event("synthesis", "failed", "Synthesis failed.", {"error": str(e)})
        if trace_ctx:
            try:
                await trace_ctx.finish(error=f"Synthesis failed: {e}")
            except Exception:
                pass
        await memory.update_session(session_id, status=SessionStatus.FAILED)
        raise

from __future__ import annotations
import json
import logging
import os
import traceback

import azure.functions as func

log = logging.getLogger(__name__)

# Catch import errors at startup so /api/health can report them
_IMPORT_ERROR: str | None = None
try:
    from models import ChatRequest, ProactiveTriggerRequest, StandardResponse, SessionDoc, SessionStatus
    import memory
    import planner
    import executor
    import synthesizer
    from trace_writer import TraceContext
except Exception as _e:
    _IMPORT_ERROR = f"{type(_e).__name__}: {_e}\n{traceback.format_exc()}"
    log.critical("Startup import failed: %s", _IMPORT_ERROR)


app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ok(body: dict, status: int = 200) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps(body, default=str),
        status_code=status,
        mimetype="application/json",
    )


def _err(msg: str, status: int = 400, detail: str | None = None) -> func.HttpResponse:
    payload: dict = {"error": msg}
    if detail:
        payload["detail"] = detail
    return func.HttpResponse(
        json.dumps(payload),
        status_code=status,
        mimetype="application/json",
    )


# ── GET /api/health  (ANONYMOUS — no key required) ───────────────────────────

@app.route(route="health", methods=["GET"],
           auth_level=func.AuthLevel.ANONYMOUS)
async def health(req: func.HttpRequest) -> func.HttpResponse:
    """
    Liveness probe. Returns 200 when the worker is healthy.
    Returns 503 with the import_error field when startup failed,
    so you can see the root cause without digging through portal logs.
    """
    if _IMPORT_ERROR:
        return func.HttpResponse(
            json.dumps({"status": "unhealthy", "import_error": _IMPORT_ERROR}),
            status_code=503,
            mimetype="application/json",
        )

    missing = [
        v for v in [
            "COSMOS_ENDPOINT",
            "AZURE_OPENAI_ENDPOINT",
            "KEY_VAULT_URL",
        ]
        if not os.environ.get(v)
    ]
    if missing:
        return func.HttpResponse(
            json.dumps({"status": "misconfigured",
                        "missing_settings": missing}),
            status_code=503,
            mimetype="application/json",
        )

    return _ok({"status": "ok", "service": "orchestrator"})

# ── Common helpers ───────────────────────────

async def _safe_trace_finish(trace: TraceContext | None, error: str | None = None, final_response: str | None = None) -> None:
    if not trace:
        return

    try:
        await trace.finish(error=error, final_response=final_response)
    except Exception as e:
        pass

async def _handle_failure(session_id: str, trace: TraceContext | None, message: str, error: Exception):
    log.exception("%s for session %s", message, session_id)

    await memory.update_session(session_id, status=SessionStatus.FAILED)

    await _safe_trace_finish(
        trace,
        error=f"{message}: {error}",
    )

    return _err(message, 500, str(error))

async def _build_trace(session_id: str, message: str, customer_id: str) -> TraceContext | None:
    try:
        return TraceContext(
            session_id=session_id,
            user_message=message,
            customer_id=customer_id,
        )
    except Exception as e:
        log.error(
            "TraceContext creation failed (continuing without tracing): %s", e
        )
        return None

async def _create_or_load_session(session_id: str | None, message: str, customer_id: str) -> SessionDoc:
    if session_id:
        existing = await memory.get_session(session_id)

        if not existing:
            raise ValueError(f"Session '{session_id}' not found")

        return SessionDoc(**{
            k: v
            for k, v in existing.items()
            if k in SessionDoc.model_fields
        })

    return await memory.create_session(
        SessionDoc(
            user_message=message,
            customer_id=customer_id,
        )
    )

async def _process_request(message: str, customer_id: str, trigger_type: str, session_id: str | None = None, save_message_fn = None):
    try:
        session = await _create_or_load_session(
            session_id=session_id,
            message=message,
            customer_id=customer_id,
        )
    except ValueError as e:
        return _err(str(e), 404)

    except Exception as e:
        log.exception("Session init failed")
        return _err("Session creation failed", 500, str(e))

    session_id = session.id

    # Save incoming message
    if save_message_fn:
        try:
            await save_message_fn(session_id)
        except Exception as e:
            log.warning("Could not save message (non-fatal): %s", e)

    trace = await _build_trace(
        session_id=session_id,
        message=message,
        customer_id=customer_id,
    )

    # Planning

    try:
        plan = await planner.build_plan(
            message=message,
            customer_id=customer_id,
            trigger_type=trigger_type,
        )

        await memory.save_plan(session_id, plan)

        log.info(
            "Session %s: plan built — %d steps",
            session_id,
            len(plan.steps),
        )

    except Exception as e:
        return await _handle_failure(
            session_id=session_id,
            trace=trace,
            message="Planning failed",
            error=e,
        )

    if trace:
        try:
            await trace.record_plan(plan)
        except Exception as e:
            log.error("trace.record_plan failed (non-fatal): %s", e)

    # Execution

    try:
        step_results = await executor.execute_plan(
            plan,
            session_id,
            customer_id,
            trace=trace,
        )

    except Exception as e:
        return await _handle_failure(
            session_id=session_id,
            trace=trace,
            message="Execution failed",
            error=e,
        )

    # Synthesis

    try:
        await memory.update_session(
            session_id,
            status=SessionStatus.SYNTHESIZING,
        )

        final_response = await synthesizer.synthesize(
            plan,
            step_results,
            message,
            trigger_type=trigger_type,
        )

        await memory.save_final_response(
            session_id,
            final_response,
        )

    except Exception as e:
        log.exception("Synthesis failed for session %s", session_id)

        final_response = _fallback_response(step_results)

        await memory.update_session(
            session_id,
            status=SessionStatus.FAILED,
        )

        await _safe_trace_finish(
            trace,
            error=f"Synthesis failed: {e}",
        )

        return _err("Synthesis failed", 500, str(e))

    await _safe_trace_finish(
        trace,
        final_response=final_response,
    )

    log.info(
        "%s: session=%s completed",
        trigger_type,
        session_id,
    )

    return _ok(StandardResponse(
        session_id=session_id,
        response=final_response,
        plan_id=plan.plan_id,
        agents_used=[s.agent_name for s in plan.steps],
        steps_completed=len(step_results),
    ).model_dump())

# ── POST /api/chat ─────────────────────────────────────────────────────────────

@app.route(route="chat", methods=["POST"])
async def chat(req: func.HttpRequest) -> func.HttpResponse:
    if _IMPORT_ERROR:
        return _err("Worker failed to start", 503, _IMPORT_ERROR)

    try:
        body = req.get_json()
        chat_req = ChatRequest(**body)

    except Exception as e:
        return _err(f"Invalid request: {e}")

    return await _process_request(
        message=chat_req.message,
        customer_id=chat_req.customer_id,
        trigger_type="reactive",
        session_id=chat_req.session_id,
        save_message_fn=lambda sid: memory.save_user_message(
            sid,
            chat_req.message,
        ),
    )

# ── POST /api/proactive/trigger ─────────────────────────────────────────────────────────────

@app.route(route="proactive/trigger", methods=["POST"])
async def proactive_trigger(req: func.HttpRequest) -> func.HttpResponse:
    if _IMPORT_ERROR:
        return _err("Worker failed to start", 503, _IMPORT_ERROR)

    try:
        body = req.get_json()
        proactive_req = ProactiveTriggerRequest(**body)

    except Exception as e:
        return _err(f"Invalid request: {e}")

    return await _process_request(
        message=proactive_req.message,
        customer_id=proactive_req.customer_id,
        trigger_type="proactive",
        save_message_fn=lambda sid: memory.save_proactive_message(
            sid,
            proactive_req.message,
            metadata={
                "source_agent_name": proactive_req.agent_name,
                "event_type": proactive_req.event_type,
                "context": proactive_req.context,
                "severity": proactive_req.severity,
            },
        ),
    )


# ── GET /api/sessions/{session_id} ────────────────────────────────────────────

@app.route(route="sessions/{session_id}", methods=["GET"])
async def get_session(req: func.HttpRequest) -> func.HttpResponse:
    if _IMPORT_ERROR:
        return _err("Worker failed to start", 503, _IMPORT_ERROR)

    session_id = req.route_params.get("session_id")
    try:
        session = await memory.get_session(session_id)
        if not session:
            return _err("Session not found", 404)
        messages = await memory.get_step_results(session_id)
        return _ok({"session": session, "step_results": messages})
    except Exception as e:
        log.exception("get_session failed for %s", session_id)
        return _err(str(e), 500)
    
@app.route(route="proactive/messages/{customer_id}", methods=["GET"])
async def get_proactive_messages(req: func.HttpRequest) -> func.HttpResponse:
    if _IMPORT_ERROR:
        return _err("Worker failed to start", 503, _IMPORT_ERROR)

    customer_id = req.route_params["customer_id"]
    since       = req.params.get("since")
    limit       = int(req.params.get("limit", "50"))

    try:
        messages = await memory.get_proactive_messages(
            customer_id=customer_id,
            since_iso=since,
            limit=limit,
        )
        return _ok({
            "customer_id": customer_id,
            "count":       len(messages),
            "messages":    messages,
        })
    except Exception as exc:
        log.exception("get_proactive_messages failed")
        return _err(str(exc), 500)
    
def _fallback_response(results: dict) -> str:
    """Combine step results into a plain text fallback when synthesis fails."""
    parts = []
    for step_id in sorted(results):
        r = results[step_id]
        if isinstance(r, dict) and r.get("result"):
            parts.append(r["result"])
        elif isinstance(r, str):
            parts.append(r)
    return "\n\n".join(parts) if parts else "I was unable to generate a response."
"""
function_app.py — Azure Functions v2 HTTP entry point.

Fixes applied:
  1. /api/health uses AuthLevel.ANONYMOUS — no key needed for liveness probes.
  2. All handlers have a broad try/except that always returns valid JSON,
     so curl responses are never empty or unparseable.
  3. Startup import errors are caught and surfaced via /api/health.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import traceback

import azure.functions as func

log = logging.getLogger(__name__)

# Catch import errors at startup so /api/health can report them
_IMPORT_ERROR: str | None = None
try:
    import chat_pipeline
    import dashboard_views
    import executor
    import memory
    import planner
    import runtime_contract
    import sse_events
    import synthesizer
    import trace_writer
    from models import ChatRequest, ChatResponse, SessionDoc, SessionStatus
except Exception as _e:
    _IMPORT_ERROR = f"{type(_e).__name__}: {_e}\n{traceback.format_exc()}"
    log.critical("Startup import failed: %s", _IMPORT_ERROR)


_AUTH_LEVEL_BY_NAME: dict[str, func.AuthLevel] = {
    "ANONYMOUS": func.AuthLevel.ANONYMOUS,
    "FUNCTION": func.AuthLevel.FUNCTION,
    "ADMIN": func.AuthLevel.ADMIN,
}

_default_level = "ANONYMOUS" if os.environ.get("USE_LOCAL_EMULATORS", "").lower() == "true" else "FUNCTION"
_configured_level = os.environ.get("ORCHESTRATOR_HTTP_AUTH_LEVEL", _default_level).upper()
_DEMO_STEPS_ENABLED = os.environ.get("ORCHESTRATOR_DEMO_STEPS", "").lower() == "true"
_STREAM_PROGRESS_ENABLED = os.environ.get("ORCHESTRATOR_STREAM_PROGRESS", "").lower() == "true"

app = func.FunctionApp(http_auth_level=_AUTH_LEVEL_BY_NAME.get(_configured_level, func.AuthLevel.FUNCTION))

_CONFIG_ERRORS: list[str] = []
if not _IMPORT_ERROR:
    try:
        _CONFIG_ERRORS = runtime_contract.validate_runtime_contract()
        if _CONFIG_ERRORS:
            log.critical("Runtime contract validation failed: %s", "; ".join(_CONFIG_ERRORS))
    except Exception as _e:
        _CONFIG_ERRORS = [f"Runtime contract check failed: {_e}"]
        log.critical("Runtime contract validation raised: %s", _e)


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


def _runtime_error_response() -> func.HttpResponse | None:
    if _IMPORT_ERROR:
        return _err("Worker failed to start", 503, _IMPORT_ERROR)
    if _CONFIG_ERRORS:
        return _err("Runtime configuration is invalid", 503, "; ".join(_CONFIG_ERRORS))
    return None


# ── GET /api/health  (ANONYMOUS — no key required) ───────────────────────────


@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
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

    if _CONFIG_ERRORS:
        return func.HttpResponse(
            json.dumps({"status": "misconfigured", "errors": _CONFIG_ERRORS}),
            status_code=503,
            mimetype="application/json",
        )

    return _ok(
        {
            "status": "ok",
            "service": "orchestrator",
            "build": {
                "version": os.environ.get("BUILD_VERSION", "dev"),
                "sha": os.environ.get("BUILD_SHA", "unknown"),
            },
        }
    )


# ── POST /api/chat ─────────────────────────────────────────────────────────────


@app.route(route="chat", methods=["POST"])
async def chat(req: func.HttpRequest) -> func.HttpResponse:
    runtime_err = _runtime_error_response()
    if runtime_err:
        return runtime_err

    try:
        body = req.get_json()
    except Exception as e:
        return _err(f"Could not parse JSON body: {e}")

    try:
        chat_req = ChatRequest(**body)
    except Exception as e:
        return _err(f"Invalid request shape: {e}")

    try:
        result = await chat_pipeline.run_chat_pipeline(chat_req)
    except ValueError as e:
        return _err(str(e), 400)
    except LookupError as e:
        return _err(str(e), 404)
    except Exception as e:
        log.exception("Chat pipeline failed")
        return _err("Chat request failed", 500, str(e))

    return _ok(
        ChatResponse(
            session_id=result.session_id,
            response=result.response,
            plan_id=result.plan_id,
            agents_used=result.agents_used,
            steps_completed=result.steps_completed,
            content_segments=result.content_segments,
        ).model_dump()
    )


@app.route(route="chat/stream", methods=["POST"])
async def chat_stream(req: func.HttpRequest) -> func.HttpResponse:
    runtime_err = _runtime_error_response()
    if runtime_err:
        return runtime_err

    try:
        body = req.get_json()
    except Exception as e:
        return _err(f"Could not parse JSON body: {e}")

    try:
        chat_req = ChatRequest(**body)
    except Exception as e:
        return _err(f"Invalid request shape: {e}")

    # Azure Functions Python HttpResponse does not accept async generators; buffer SSE chunks.
    chunks: list[str] = []

    async def on_event(event: str, data: dict) -> None:
        chunks.append(sse_events.format_sse(event, data))

    try:
        result = await chat_pipeline.run_chat_pipeline(
            chat_req,
            on_event=on_event,
            stream_tokens=True,
        )
        chunks.append(
            sse_events.format_sse(
                "done",
                {
                    "session_id": result.session_id,
                    "response": result.response,
                    "plan_id": result.plan_id,
                    "agents_used": result.agents_used,
                    "steps_completed": result.steps_completed,
                    "content_segments": result.content_segments,
                },
            )
        )
    except ValueError as e:
        chunks.append(sse_events.format_sse("error", {"error": str(e), "status": 400}))
    except LookupError as e:
        chunks.append(sse_events.format_sse("error", {"error": str(e), "status": 404}))
    except Exception as e:
        log.exception("Streaming chat pipeline failed")
        chunks.append(
            sse_events.format_sse(
                "error",
                {"error": "Chat request failed", "detail": str(e)},
            )
        )

    return func.HttpResponse(
        body="".join(chunks),
        status_code=200,
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── GET /api/sessions/{session_id} ────────────────────────────────────────────


@app.route(route="sessions/{session_id}", methods=["GET"])
async def get_session(req: func.HttpRequest) -> func.HttpResponse:
    runtime_err = _runtime_error_response()
    if runtime_err:
        return runtime_err

    session_id = req.route_params.get("session_id")
    try:
        session = await memory.get_session(session_id)
        if not session:
            return _err("Session not found", 404)
        messages = await memory.get_step_results(session_id)
        payload = {"session": session, "step_results": messages}
        if _DEMO_STEPS_ENABLED or _STREAM_PROGRESS_ENABLED:
            payload["demo_events"] = await trace_writer.get_demo_events(session_id)
        return _ok(payload)
    except Exception as e:
        log.exception("get_session failed for %s", session_id)
        return _err(str(e), 500)


# ── GET /api/users/{customer_id}/sessions ─────────────────────────────────────


@app.route(route="users/{customer_id}/sessions", methods=["GET"])
async def get_user_sessions(req: func.HttpRequest) -> func.HttpResponse:
    runtime_err = _runtime_error_response()
    if runtime_err:
        return runtime_err

    customer_id = req.route_params.get("customer_id")
    if not customer_id:
        return _err("customer_id is required", 400)

    try:
        sessions = await memory.get_sessions_by_customer(customer_id)
        # Sort manually just in case cosmos _ts indexing is weird, but query does it too
        return _ok({"sessions": sessions})
    except Exception as e:
        log.exception("get_user_sessions failed for customer %s", customer_id)
        return _err(str(e), 500)


@app.route(route="insights", methods=["GET"])
async def get_insights(req: func.HttpRequest) -> func.HttpResponse:
    runtime_err = _runtime_error_response()
    if runtime_err:
        return runtime_err
    customer_id = req.params.get("customer_id")
    if not customer_id:
        return _err("customer_id is required", 400)
    try:
        since_hours = int(req.params.get("since_hours", "24"))
    except Exception:
        return _err("since_hours must be an integer", 400)
    try:
        insights = await dashboard_views.build_insights(customer_id=customer_id, since_hours=since_hours)
        return _ok({"customer_id": customer_id, "insights": insights})
    except Exception as e:
        log.exception("get_insights failed for customer %s", customer_id)
        return _err("Failed to build insights", 500, str(e))


@app.route(route="copilot/context", methods=["GET"])
async def get_copilot_context(req: func.HttpRequest) -> func.HttpResponse:
    runtime_err = _runtime_error_response()
    if runtime_err:
        return runtime_err
    customer_id = req.params.get("customer_id")
    date = req.params.get("date")
    if not customer_id:
        return _err("customer_id is required", 400)
    if not date:
        return _err("date is required", 400)
    try:
        context = await dashboard_views.build_copilot_context(customer_id=customer_id, date=date)
        return _ok({"customer_id": customer_id, "date": date, "context": context})
    except Exception as e:
        log.exception("get_copilot_context failed for customer %s", customer_id)
        return _err("Failed to build copilot context", 500, str(e))


@app.route(route="alerts", methods=["GET"])
async def get_alerts(req: func.HttpRequest) -> func.HttpResponse:
    runtime_err = _runtime_error_response()
    if runtime_err:
        return runtime_err
    customer_id = req.params.get("customer_id")
    status = (req.params.get("status") or "all").strip().lower()
    if not customer_id:
        return _err("customer_id is required", 400)
    if status not in {"all", "unread", "acked"}:
        return _err("status must be one of: all, unread, acked", 400)
    try:
        alerts = await dashboard_views.build_alerts(customer_id=customer_id, status=status)
        return _ok({"customer_id": customer_id, "status": status, "alerts": alerts})
    except Exception as e:
        log.exception("get_alerts failed for customer %s", customer_id)
        return _err("Failed to build alerts", 500, str(e))


@app.route(route="alerts/{alert_id}/ack", methods=["POST"])
async def ack_alert(req: func.HttpRequest) -> func.HttpResponse:
    runtime_err = _runtime_error_response()
    if runtime_err:
        return runtime_err
    alert_id = req.route_params.get("alert_id")
    if not alert_id:
        return _err("alert_id is required", 400)
    try:
        body = req.get_json()
    except Exception:
        body = {}
    action = (body.get("action") or "ack").strip().lower()
    customer_id = body.get("customer_id")
    if not customer_id:
        return _err("customer_id is required", 400)
    try:
        ack = await dashboard_views.acknowledge_alert(alert_id=alert_id, action=action, customer_id=customer_id)
        return _ok(ack)
    except ValueError as e:
        return _err(str(e), 404)
    except Exception as e:
        log.exception("ack_alert failed for alert %s", alert_id)
        return _err("Failed to acknowledge alert", 500, str(e))


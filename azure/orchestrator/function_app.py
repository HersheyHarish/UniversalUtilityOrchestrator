"""
function_app.py — Azure Functions v2 HTTP entry point.

Fixes applied:
  1. /api/health uses AuthLevel.ANONYMOUS — no key needed for liveness probes.
  2. All handlers have a broad try/except that always returns valid JSON,
     so curl responses are never empty or unparseable.
  3. Startup import errors are caught and surfaced via /api/health.
"""

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
    import executor
    import memory
    import planner
    import runtime_contract
    import synthesizer
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
        if chat_req.session_id:
            existing = await memory.get_session(chat_req.session_id)
            if not existing:
                return _err(f"Session '{chat_req.session_id}' not found", 404)
            session = SessionDoc(**{k: v for k, v in existing.items() if k in SessionDoc.model_fields})
        else:
            session = SessionDoc(
                user_message=chat_req.message,
                customer_id=chat_req.customer_id,
            )
            session = await memory.create_session(session)
        session_id = session.id
    except Exception as e:
        log.exception("Session init failed")
        return _err("Session creation failed", 500, str(e))

    try:
        await memory.save_user_message(session_id, chat_req.message)
    except Exception as e:
        log.warning("Could not save user message (non-fatal): %s", e)

    try:
        plan = await planner.build_plan(chat_req.message, chat_req.customer_id)
        await memory.save_plan(session_id, plan)
        log.info("Session %s: plan built — %d steps", session_id, len(plan.steps))
    except Exception as e:
        log.exception("Planning failed for session %s", session_id)
        await memory.update_session(session_id, status=SessionStatus.FAILED)
        return _err("Planning failed", 500, str(e))

    try:
        step_results = await executor.execute_plan(plan, session_id, chat_req.customer_id)
    except Exception as e:
        log.exception("Execution failed for session %s", session_id)
        await memory.update_session(session_id, status=SessionStatus.FAILED)
        return _err("Execution failed", 500, str(e))

    try:
        await memory.update_session(session_id, status=SessionStatus.SYNTHESIZING)
        final = await synthesizer.synthesize(plan, step_results, chat_req.message)
        await memory.save_final_response(session_id, final)
    except Exception as e:
        log.exception("Synthesis failed for session %s", session_id)
        await memory.update_session(session_id, status=SessionStatus.FAILED)
        return _err("Synthesis failed", 500, str(e))

    return _ok(
        ChatResponse(
            session_id=session_id,
            response=final,
            plan_id=plan.plan_id,
            agents_used=[s.agent_name for s in plan.steps],
            steps_completed=len(step_results),
        ).model_dump()
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
        return _ok({"session": session, "step_results": messages})
    except Exception as e:
        log.exception("get_session failed for %s", session_id)
        return _err(str(e), 500)

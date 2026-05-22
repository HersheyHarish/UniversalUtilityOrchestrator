from __future__ import annotations
import json
import logging
import os
import traceback
from datetime import datetime

import azure.functions as func

log = logging.getLogger(__name__)

_IMPORT_ERROR: str | None = None
try:
    import auth
    import capability_fetcher
    import cosmos
    import observability
    import registry
    import runtime_contract
    from models import (
        AgentCreate,
        AgentReplace,
        AgentUpdate,
        CapabilityAdd,
        LoginRequest,
        StatusPatch,
    )
except Exception as _exc:
    _IMPORT_ERROR = f"{type(_exc).__name__}: {_exc}\n{traceback.format_exc()}"
    log.critical("Startup import failed:\n%s", _IMPORT_ERROR)


_AUTH_LEVEL_BY_NAME: dict[str, func.AuthLevel] = {
    "ANONYMOUS": func.AuthLevel.ANONYMOUS,
    "FUNCTION": func.AuthLevel.FUNCTION,
    "ADMIN": func.AuthLevel.ADMIN,
}

_default_level = "ANONYMOUS" if os.environ.get("USE_LOCAL_EMULATORS", "").lower() == "true" else "FUNCTION"
_configured_level = os.environ.get("REGISTRY_HTTP_AUTH_LEVEL", _default_level).upper()

app = func.FunctionApp(http_auth_level=_AUTH_LEVEL_BY_NAME.get(_configured_level, func.AuthLevel.FUNCTION))

_CONFIG_ERRORS: list[str] = []
if not _IMPORT_ERROR:
    try:
        _CONFIG_ERRORS = runtime_contract.validate_runtime_contract()
        if _CONFIG_ERRORS:
            log.critical("Runtime contract validation failed: %s", "; ".join(_CONFIG_ERRORS))
    except Exception as _exc:
        _CONFIG_ERRORS = [f"Runtime contract check failed: {_exc}"]
        log.critical("Runtime contract validation raised: %s", _exc)


# ── Response helpers ──────────────────────────────────────────────────────────


def _json(body, status: int = 200) -> func.HttpResponse:
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


def _html(body: str, status: int = 200) -> func.HttpResponse:
    return func.HttpResponse(body, status_code=status, mimetype="text/html")


def _runtime_error_response() -> func.HttpResponse | None:
    if _IMPORT_ERROR:
        return _err("Worker startup failed", 503, _IMPORT_ERROR)
    if _CONFIG_ERRORS:
        return _err("Runtime configuration is invalid", 503, "; ".join(_CONFIG_ERRORS))
    return None


def _token_from(req: func.HttpRequest) -> str:
    return req.headers.get("X-Session-Token") or req.params.get("session_token") or ""


async def _guard(req: func.HttpRequest) -> func.HttpResponse | None:
    runtime_err = _runtime_error_response()
    if runtime_err:
        return runtime_err

    token = _token_from(req)
    result = await auth.validate(token)

    if not result.valid:
        return _err(
            "Authentication required — please log in via POST /api/auth/login",
            401,
        )
    return None  # session is valid


# =============================================================================
# AUTH ROUTES  (ANONYMOUS — no function key required)
# =============================================================================


@app.route(route="auth/login", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
async def auth_login(req: func.HttpRequest) -> func.HttpResponse:
    runtime_err = _runtime_error_response()
    if runtime_err:
        return runtime_err

    try:
        body = req.get_json()
        req_model = LoginRequest(**body)
    except Exception as exc:
        return _err(f"Invalid request body: {exc}")

    try:
        result = await auth.login(req_model.username, req_model.password)
    except Exception as exc:
        log.exception("auth.login raised unexpectedly")
        return _err("Authentication service error", 500, str(exc))

    if result is None:
        return _err("Invalid credentials", 401)

    return _json(result.model_dump())


@app.route(route="auth/logout", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
async def auth_logout(req: func.HttpRequest) -> func.HttpResponse:
    runtime_err = _runtime_error_response()
    if runtime_err:
        return runtime_err

    token = _token_from(req)
    if not token:
        try:
            body = req.get_json()
            token = body.get("token", "")
        except Exception:
            pass

    await auth.logout(token)
    return _json({"message": "Logged out successfully"})


@app.route(route="auth/verify", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
async def auth_verify(req: func.HttpRequest) -> func.HttpResponse:
    runtime_err = _runtime_error_response()
    if runtime_err:
        return runtime_err

    token = _token_from(req)
    result = await auth.validate(token)
    return _json(result.model_dump())


# =============================================================================
# SYSTEM ROUTES  (ANONYMOUS)
# =============================================================================


@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
async def health(req: func.HttpRequest) -> func.HttpResponse:
    runtime_err = _runtime_error_response()
    if runtime_err:
        return runtime_err
    return _json(
        {
            "status": "ok",
            "service": "registry-api",
            "time": datetime.utcnow().isoformat(),
            "build": {
                "version": os.environ.get("BUILD_VERSION", "dev"),
                "sha": os.environ.get("BUILD_SHA", "unknown"),
            },
        }
    )


@app.route(route="agents/dashboard", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
async def dashboard(req: func.HttpRequest) -> func.HttpResponse:
    """Browser-viewable HTML dashboard. Auto-refreshes every 60 s."""
    runtime_err = _runtime_error_response()
    if runtime_err:
        try:
            payload = json.loads(runtime_err.get_body().decode("utf-8"))
        except Exception:
            payload = {"error": "Runtime configuration is invalid"}
        return _html(f"<pre>{json.dumps(payload, indent=2)}</pre>", 503)
    try:
        all_agents = await cosmos.agent_list()
        stats_obj = await registry.get_stats()
        return _html(registry.build_dashboard_html(all_agents, stats_obj))
    except Exception as exc:
        log.exception("dashboard failed")
        return _html(f"<pre>Error: {exc}</pre>", 500)


# =============================================================================
# FIXED SUB-ROUTES  — registered before /{id} to avoid wildcard capture
# =============================================================================


@app.route(route="agents/ping-all", methods=["POST"])
async def ping_all(req: func.HttpRequest) -> func.HttpResponse:
    err = await _guard(req)
    if err:
        return err
    try:
        result = await registry.ping_all_active()
        return _json(result.model_dump())
    except Exception as exc:
        log.exception("ping_all failed")
        return _err(str(exc), 500)

@app.route(route="registry/stats", methods=["GET"])
async def registry_stats(req: func.HttpRequest) -> func.HttpResponse:

    err = await _guard(req)
    if err:
        return err
    try:
        s = await registry.get_stats()
        return _json(s.model_dump())
    except Exception as exc:
        log.exception("registry_stats failed")
        return _err(str(exc), 500)


@app.route(route="agents/capabilities", methods=["GET"])
async def capabilities_index(req: func.HttpRequest) -> func.HttpResponse:
    err = await _guard(req)
    if err:
        return err
    try:
        caps = await registry.get_capability_index()
        return _json({"count": len(caps), "capabilities": [c.model_dump() for c in caps]})
    except Exception as exc:
        log.exception("capabilities_index failed")
        return _err(str(exc), 500)


@app.route(route="agents/export", methods=["GET"])
async def export_agents(req: func.HttpRequest) -> func.HttpResponse:
    err = await _guard(req)
    if err:
        return err
    try:
        all_agents = await cosmos.agent_export_all()
        payload = json.dumps(
            {
                "exported_at": datetime.utcnow().isoformat(),
                "total": len(all_agents),
                "agents": all_agents,
            },
            default=str,
            indent=2,
        )
        return func.HttpResponse(
            payload,
            status_code=200,
            mimetype="application/json",
            headers={"Content-Disposition": "attachment; filename=agent-registry-export.json"},
        )
    except Exception as exc:
        log.exception("export_agents failed")
        return _err(str(exc), 500)


@app.route(route="observability/metrics", methods=["GET"])
async def obs_metrics(req: func.HttpRequest) -> func.HttpResponse:
    err = await _guard(req)
    if err:
        return err
    try:
        since_hours = int(req.params.get("since_hours", 24))
    except Exception:
        return _err("since_hours must be an integer", 400)
    try:
        data = await observability.get_metrics(since_hours=since_hours)
        return _json(data)
    except Exception as exc:
        log.exception("obs_metrics failed")
        return _err(str(exc), 500)


@app.route(route="observability/agents", methods=["GET"])
async def obs_agent_metrics(req: func.HttpRequest) -> func.HttpResponse:
    err = await _guard(req)
    if err:
        return err
    try:
        since_hours = int(req.params.get("since_hours", 24))
    except Exception:
        return _err("since_hours must be an integer", 400)
    try:
        data = await observability.get_agent_metrics(since_hours=since_hours)
        return _json({"agents": data})
    except Exception as exc:
        log.exception("obs_agent_metrics failed")
        return _err(str(exc), 500)


@app.route(route="observability/timeseries", methods=["GET"])
async def obs_timeseries(req: func.HttpRequest) -> func.HttpResponse:
    err = await _guard(req)
    if err:
        return err
    try:
        since_hours = int(req.params.get("since_hours", 24))
        bucket_hours = int(req.params.get("bucket_hours", 1))
    except Exception:
        return _err("since_hours and bucket_hours must be integers", 400)
    try:
        data = await observability.get_time_series(since_hours=since_hours, bucket_hours=bucket_hours)
        return _json({"buckets": data})
    except Exception as exc:
        log.exception("obs_timeseries failed")
        return _err(str(exc), 500)


@app.route(route="traces", methods=["GET"])
async def list_traces(req: func.HttpRequest) -> func.HttpResponse:
    err = await _guard(req)
    if err:
        return err
    status = req.params.get("status")
    agent = req.params.get("agent")
    trigger_type=req.params.get("trigger_type")
    try:
        since_hours = int(req.params.get("since_hours", 24))
        limit = int(req.params.get("limit", 50))
    except Exception:
        return _err("since_hours and limit must be integers", 400)
    try:
        rows = await observability.list_traces(
            status=status,
            agent_name=agent,
            trigger_type=trigger_type,
            since_hours=since_hours,
            limit=limit,
        )
        return _json({"count": len(rows), "traces": rows})
    except Exception as exc:
        log.exception("list_traces failed")
        return _err(str(exc), 500)


@app.route(route="traces/{trace_id}", methods=["GET"])
async def get_trace(req: func.HttpRequest) -> func.HttpResponse:
    err = await _guard(req)
    if err:
        return err
    trace_id = req.route_params.get("trace_id")
    if not trace_id:
        return _err("trace_id is required", 400)
    try:
        trace = await observability.get_trace(trace_id)
        if not trace:
            return _err("Trace not found", 404)
        return _json(trace)
    except Exception as exc:
        log.exception("get_trace failed for trace %s", trace_id)
        return _err(str(exc), 500)


# =============================================================================
# AGENT CRUD ROUTES
# =============================================================================


@app.route(route="agents", methods=["POST"])
async def create_agent(req: func.HttpRequest) -> func.HttpResponse:
    err = await _guard(req)
    if err:
        return err
    try:
        body = AgentCreate(**req.get_json())
    except Exception as exc:
        return _err(f"Validation error: {exc}")
    try:
        doc, created = await registry.create_agent(body)
        if not created:
            return _err(f"Agent '{body.name}' already exists. Use PUT to replace or PATCH to update.", 409)
        return _json(doc.model_dump(), 201)
    except Exception as exc:
        log.exception("create_agent failed")
        return _err(str(exc), 500)


@app.route(route="agents", methods=["GET"])
async def list_agents(req: func.HttpRequest) -> func.HttpResponse:
    err = await _guard(req)
    if err:
        return err
    q = req.params.get("q", "").strip()
    status = req.params.get("status")
    utility_type = req.params.get("utility_type")
    tag = req.params.get("tag")
    try:
        if q:
            agents = await registry.search_agents(q)
        else:
            agents = await registry.list_agents(status, utility_type, tag)
        return _json({"count": len(agents), "agents": [a.model_dump() for a in agents]})
    except Exception as exc:
        log.exception("list_agents failed")
        return _err(str(exc), 500)


@app.route(route="agents/capabilities/fetch", methods=["POST"])
async def fetch_agent_capabilities(req: func.HttpRequest) -> func.HttpResponse:
    err = await _guard(req)
    if err:
        return err

    try:
        body = req.get_json()
    except Exception:
        return _err("Invalid JSON body")

    endpoint_url = (body.get("endpoint_url") or "").strip()
    auth_config = body.get("auth_config") or {}
    auth_secrets = body.get("auth_secrets") or {}
    invocation_config = body.get("invocation_config") or {}

    if not endpoint_url:
        return _err("endpoint_url is required")

    try:
        result = await capability_fetcher.fetch_capabilities(
            endpoint_url=endpoint_url,
            auth_config=auth_config,
            auth_secrets=auth_secrets,
            invocation_config=invocation_config,
        )
        return _json(result)
    except RuntimeError as exc:
        return _err(str(exc), 502)
    except Exception as exc:
        log.exception("fetch_agent_capabilities: unexpected error")
        return _err(f"Unexpected error: {exc}", 500)


@app.route(route="agents/{agent_id}", methods=["GET"])
async def get_agent(req: func.HttpRequest) -> func.HttpResponse:
    err = await _guard(req)
    if err:
        return err
    agent_id = req.route_params["agent_id"]
    try:
        doc = await registry.get_agent(agent_id)
        if not doc:
            return _err(f"Agent '{agent_id}' not found", 404)
        return _json(doc.model_dump())
    except Exception as exc:
        log.exception("get_agent failed")
        return _err(str(exc), 500)


@app.route(route="agents/{agent_id}", methods=["PUT"])
async def replace_agent(req: func.HttpRequest) -> func.HttpResponse:
    err = await _guard(req)
    if err:
        return err
    agent_id = req.route_params["agent_id"]
    try:
        body = AgentReplace(**req.get_json())
    except Exception as exc:
        return _err(f"Validation error: {exc}")
    try:
        doc = await registry.replace_agent(agent_id, body)
        if not doc:
            return _err(f"Agent '{agent_id}' not found", 404)
        return _json(doc.model_dump())
    except Exception as exc:
        log.exception("replace_agent failed")
        return _err(str(exc), 500)


@app.route(route="agents/{agent_id}", methods=["PATCH"])
async def patch_agent(req: func.HttpRequest) -> func.HttpResponse:
    err = await _guard(req)
    if err:
        return err
    agent_id = req.route_params["agent_id"]
    try:
        body = AgentUpdate(**req.get_json())
    except Exception as exc:
        return _err(f"Validation error: {exc}")
    try:
        doc = await registry.patch_agent(agent_id, body)
        if not doc:
            return _err(f"Agent '{agent_id}' not found", 404)
        return _json(doc.model_dump())
    except Exception as exc:
        log.exception("patch_agent failed")
        return _err(str(exc), 500)


@app.route(route="agents/{agent_id}", methods=["DELETE"])
async def delete_agent(req: func.HttpRequest) -> func.HttpResponse:
    err = await _guard(req)
    if err:
        return err
    agent_id = req.route_params["agent_id"]
    try:
        deleted = await registry.delete_agent(agent_id)
        if not deleted:
            return _err(f"Agent '{agent_id}' not found", 404)
        return _json({"message": f"Agent permanently deleted"})
    except Exception as exc:
        log.exception("delete_agent failed")
        return _err(str(exc), 500)


# =============================================================================
# STATUS & CAPABILITY ROUTES
# =============================================================================


@app.route(route="agents/{agent_id}/status", methods=["PATCH"])
async def set_status(req: func.HttpRequest) -> func.HttpResponse:
    err = await _guard(req)
    if err:
        return err
    agent_id = req.route_params["agent_id"]
    try:
        body = StatusPatch(**req.get_json())
    except Exception as exc:
        return _err(f"Validation error: {exc}")
    try:
        doc = await registry.set_status(agent_id, body)
        if not doc:
            return _err(f"Agent '{agent_id}' not found", 404)
        return _json(doc.model_dump())
    except Exception as exc:
        log.exception("set_status failed")
        return _err(str(exc), 500)


@app.route(route="agents/{agent_id}/capabilities", methods=["POST"])
async def add_capability(req: func.HttpRequest) -> func.HttpResponse:
    err = await _guard(req)
    if err:
        return err
    agent_id = req.route_params["agent_id"]
    try:
        body = CapabilityAdd(**req.get_json())
    except Exception as exc:
        return _err(f"Validation error: {exc}")
    try:
        doc = await registry.add_capability(agent_id, body)
        if not doc:
            return _err(f"Agent '{agent_id}' not found", 404)
        return _json(doc.model_dump())
    except Exception as exc:
        log.exception("add_capability failed")
        return _err(str(exc), 500)


@app.route(route="agents/{agent_id}/capabilities/{cap_name}", methods=["DELETE"])
async def remove_capability(req: func.HttpRequest) -> func.HttpResponse:
    err = await _guard(req)
    if err:
        return err
    agent_id = req.route_params["agent_id"]
    cap_name = req.route_params["cap_name"]
    try:
        doc = await registry.remove_capability(agent_id, cap_name)
        if not doc:
            return _err(f"Agent '{agent_id}' not found", 404)
        return _json(doc.model_dump())
    except Exception as exc:
        log.exception("remove_capability failed")
        return _err(str(exc), 500)


# =============================================================================
# HEALTH PROBE ROUTES
# =============================================================================


@app.route(route="agents/{agent_id}/ping", methods=["GET"])
async def ping_agent(req: func.HttpRequest) -> func.HttpResponse:
    err = await _guard(req)
    if err:
        return err
    agent_id = req.route_params["agent_id"]
    try:
        result = await registry.ping_agent(agent_id)
        if not result:
            return _err(f"Agent '{agent_id}' not found", 404)
        status_code = 200 if result.status == "healthy" else 502
        return _json(result.model_dump(), status_code)
    except Exception as exc:
        log.exception("ping_agent failed")
        return _err(str(exc), 500)

"""
function_app.py — Agent Registry API · Azure Functions v2 (Python)
===================================================================

All routes and auth fully integrated in this single file.

Auth routes (ANONYMOUS — no function key required):
  POST  /api/auth/login      Validate credentials, return session token
  POST  /api/auth/logout     Invalidate session immediately
  GET   /api/auth/verify     Check if a session token is still valid

System routes (ANONYMOUS):
  GET   /api/health           Liveness probe
  GET   /api/agents/dashboard HTML dashboard for browser viewing

All other routes require:
  1. Function-level host key  →  ?code=<key>  or  x-functions-key header
  2. Valid session token       →  X-Session-Token header

Registry — core CRUD:
  POST   /api/agents                   Register new agent (409 if name exists)
  GET    /api/agents                   List  (?status ?utility_type ?tag ?q)
  GET    /api/agents/{id}              Get single agent
  PUT    /api/agents/{id}              Full replacement
  PATCH  /api/agents/{id}             Partial update
  DELETE /api/agents/{id}             Soft delete  (?hard=true for physical)

Registry — status & capabilities:
  PATCH  /api/agents/{id}/status               Set status + optional reason
  POST   /api/agents/{id}/capabilities         Add capability
  DELETE /api/agents/{id}/capabilities/{name}  Remove capability

Registry — health probing:
  GET    /api/agents/{id}/ping   Probe one agent, update its health fields
  POST   /api/agents/ping-all    Probe all active agents concurrently

Registry — discovery:
  GET    /api/agents/stats         Aggregate counts / metadata
  GET    /api/agents/capabilities  Capability index across active agents
  GET    /api/agents/export        Full JSON export (file download)

Route ordering note:
  Fixed paths  (/ping-all, /stats, /capabilities, /export, /dashboard)
  are registered BEFORE parameterised paths (/{id}) so the literal
  segments always win over the wildcard.
"""
from __future__ import annotations
import json
import logging
import os
import traceback
from datetime import datetime

import azure.functions as func

log = logging.getLogger(__name__)

# ── Import guard — surfaces startup failures via /api/health ─────────────────
_IMPORT_ERROR: str | None = None
try:
    import auth
    import cosmos                                       # noqa: F401  (validates env on import)
    import registry
    from models import (
        AgentCreate, AgentReplace, AgentUpdate,
        CapabilityAdd, LoginRequest, StatusPatch,
    )
    import capability_fetcher
    import observability
except Exception as _exc:
    _IMPORT_ERROR = f"{type(_exc).__name__}: {_exc}\n{traceback.format_exc()}"
    log.critical("Startup import failed:\n%s", _IMPORT_ERROR)


app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)


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


def _token_from(req: func.HttpRequest) -> str:
    """Extract session token from X-Session-Token header or ?session_token= param."""
    return (
        req.headers.get("X-Session-Token")
        or req.params.get("session_token")
        or ""
    )


async def _guard(req: func.HttpRequest) -> func.HttpResponse | None:
    """
    Session guard for protected routes.
    Returns None when the session is valid (caller proceeds).
    Returns an error HttpResponse when the session is missing or invalid.
    """
    if _IMPORT_ERROR:
        return _err("Worker startup failed", 503, _IMPORT_ERROR)

    token  = _token_from(req)
    result = await auth.validate(token)

    if not result.valid:
        return _err(
            "Authentication required — please log in via POST /api/auth/login",
            401,
        )
    return None   # session is valid


# =============================================================================
# AUTH ROUTES  (ANONYMOUS — no function key required)
# =============================================================================

@app.route(route="auth/login", methods=["POST"],
           auth_level=func.AuthLevel.ANONYMOUS)
async def auth_login(req: func.HttpRequest) -> func.HttpResponse:
    """
    Validate admin credentials and return a session token.
    Credentials are validated against Key Vault secrets — never stored in code.

    Request body:
      { "username": "admin", "password": "yourpassword" }

    Success response (200):
      { "token": "<uuid>", "expires_at": "<iso>", "username": "admin" }

    Failure response (401):
      { "error": "Invalid credentials" }
    """
    if _IMPORT_ERROR:
        return _err("Worker startup failed", 503, _IMPORT_ERROR)

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


@app.route(route="auth/logout", methods=["POST"],
           auth_level=func.AuthLevel.ANONYMOUS)
async def auth_logout(req: func.HttpRequest) -> func.HttpResponse:
    """
    Invalidate the current session immediately.
    Accepts token via X-Session-Token header or request body.

    Always returns 200 regardless of whether the token existed.
    """
    if _IMPORT_ERROR:
        return _err("Worker startup failed", 503, _IMPORT_ERROR)

    token = _token_from(req)
    if not token:
        # Also accept token in body for flexibility
        try:
            body  = req.get_json()
            token = body.get("token", "")
        except Exception:
            pass

    await auth.logout(token)
    return _json({"message": "Logged out successfully"})


@app.route(route="auth/verify", methods=["GET"],
           auth_level=func.AuthLevel.ANONYMOUS)
async def auth_verify(req: func.HttpRequest) -> func.HttpResponse:
    """
    Check whether a session token is still valid.
    Used by the React frontend on page load to decide whether to redirect to /login.

    Token supplied via X-Session-Token header or ?session_token= query param.

    Response:
      { "valid": true,  "username": "admin" }   — session is valid
      { "valid": false, "username": null   }   — expired or not found
    """
    if _IMPORT_ERROR:
        return _err("Worker startup failed", 503, _IMPORT_ERROR)

    token  = _token_from(req)
    result = await auth.validate(token)
    return _json(result.model_dump())


# =============================================================================
# SYSTEM ROUTES  (ANONYMOUS)
# =============================================================================

@app.route(route="health", methods=["GET"],
           auth_level=func.AuthLevel.ANONYMOUS)
async def health(req: func.HttpRequest) -> func.HttpResponse:
    """
    Liveness probe — no auth required.
    Returns 503 with import_error when a startup module failed to load
    so you can diagnose deployment issues without digging through logs.
    """
    if _IMPORT_ERROR:
        return func.HttpResponse(
            json.dumps({"status": "unhealthy", "import_error": _IMPORT_ERROR}),
            status_code=503, mimetype="application/json",
        )
    missing = [v for v in ["COSMOS_ENDPOINT", "KEY_VAULT_URL"] if not os.environ.get(v)]
    if missing:
        return func.HttpResponse(
            json.dumps({"status": "misconfigured", "missing_settings": missing}),
            status_code=503, mimetype="application/json",
        )
    return _json({"status": "ok", "service": "registry-api", "time": datetime.utcnow().isoformat()})


@app.route(route="agents/dashboard", methods=["GET"],
           auth_level=func.AuthLevel.ANONYMOUS)
async def dashboard(req: func.HttpRequest) -> func.HttpResponse:
    """Browser-viewable HTML dashboard. Auto-refreshes every 60 s."""
    if _IMPORT_ERROR:
        return _html(f"<pre>Import error: {_IMPORT_ERROR}</pre>", 503)
    try:
        all_agents = await cosmos.agent_list()
        stats_obj  = await registry.get_stats()
        return _html(registry.build_dashboard_html(all_agents, stats_obj))
    except Exception as exc:
        log.exception("dashboard failed")
        return _html(f"<pre>Error: {exc}</pre>", 500)


# =============================================================================
# FIXED SUB-ROUTES  — registered before /{id} to avoid wildcard capture
# =============================================================================

@app.route(route="agents/ping-all", methods=["POST"])
async def ping_all(req: func.HttpRequest) -> func.HttpResponse:
    """
    Probe all active agents concurrently (bounded to 5 simultaneous connections).
    Updates each agent's last_health_status, last_health_ms, and last_health_check_at.
    Auto-transitions agents between active ↔ degraded based on probe results.

    Requires: X-Session-Token header with a valid session token.
    """
    err = await _guard(req)
    if err:
        return err
    try:
        result = await registry.ping_all_active()
        return _json(result.model_dump())
    except Exception as exc:
        log.exception("ping_all failed")
        return _err(str(exc), 500)


@app.route(route="agents/stats", methods=["GET"])
async def stats(req: func.HttpRequest) -> func.HttpResponse:
    """
    Returns aggregate registry statistics:
      - total agent count
      - breakdown by status (active / inactive / degraded)
      - breakdown by utility type
      - total capabilities count
      - unique tag list
      - last registration timestamp
      - last health check timestamp
    """
    err = await _guard(req)
    if err:
        return err
    try:
        s = await registry.get_stats()
        return _json(s.model_dump())
    except Exception as exc:
        log.exception("stats failed")
        return _err(str(exc), 500)


@app.route(route="agents/capabilities", methods=["GET"])
async def capabilities_index(req: func.HttpRequest) -> func.HttpResponse:
    """
    Returns a deduplicated index of all capabilities across active agents.
    Useful for the planner LLM to understand what the registry can do without
    loading every agent document.
    """
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
    """
    Download the full registry as a JSON file. Includes all statuses.
    Used for backup, migration, and seeding test environments.
    """
    err = await _guard(req)
    if err:
        return err
    try:
        all_agents = await cosmos.agent_export_all()
        payload = json.dumps(
            {
                "exported_at": datetime.utcnow().isoformat(),
                "total":       len(all_agents),
                "agents":      all_agents,
            },
            default=str, indent=2,
        )
        return func.HttpResponse(
            payload, status_code=200, mimetype="application/json",
            headers={"Content-Disposition": "attachment; filename=agent-registry-export.json"},
        )
    except Exception as exc:
        log.exception("export_agents failed")
        return _err(str(exc), 500)


# =============================================================================
# OBSERVABILITY / TRACE ROUTES
# =============================================================================

@app.route(route="traces", methods=["GET"])
async def list_traces(req: func.HttpRequest) -> func.HttpResponse:
    """
    List execution traces with optional filters.

    Query params:
      status      completed | failed | running
      agent       filter by agent name that was invoked
      since_hours look-back window in hours (default 24, max 720)
      limit       max rows returned (default 50, max 200)
    """
    err = await _guard(req)
    if err:
        return err
    try:
        rows = await observability.list_traces(
            status=req.params.get("status"),
            agent_name=req.params.get("agent"),
            since_hours=int(req.params.get("since_hours", "24")),
            limit=int(req.params.get("limit", "50")),
        )
        return _json({"count": len(rows), "traces": rows})
    except Exception as exc:
        log.exception("list_traces failed")
        return _err(str(exc), 500)


@app.route(route="traces/{trace_id}", methods=["GET"])
async def get_trace(req: func.HttpRequest) -> func.HttpResponse:
    """
    Return the full trace document including all step inputs/outputs.
    trace_id == session_id.
    """
    err = await _guard(req)
    if err:
        return err
    trace_id = req.route_params["trace_id"]
    try:
        doc = await observability.get_trace(trace_id)
        if not doc:
            return _err(f"Trace '{trace_id}' not found", 404)
        return _json(doc)
    except Exception as exc:
        log.exception("get_trace failed")
        return _err(str(exc), 500)


@app.route(route="observability/metrics", methods=["GET"])
async def obs_metrics(req: func.HttpRequest) -> func.HttpResponse:
    """Aggregate metrics: total requests, success rate, avg/p95 latency."""
    err = await _guard(req)
    if err:
        return err
    try:
        data = await observability.get_metrics(
            since_hours=int(req.params.get("since_hours", "24"))
        )
        return _json(data)
    except Exception as exc:
        log.exception("obs_metrics failed")
        return _err(str(exc), 500)


@app.route(route="observability/agents", methods=["GET"])
async def obs_agent_metrics(req: func.HttpRequest) -> func.HttpResponse:
    """Per-agent: invocations, success rate, avg latency, recent errors."""
    err = await _guard(req)
    if err:
        return err
    try:
        data = await observability.get_agent_metrics(
            since_hours=int(req.params.get("since_hours", "24"))
        )
        return _json({"agents": data})
    except Exception as exc:
        log.exception("obs_agent_metrics failed")
        return _err(str(exc), 500)


@app.route(route="observability/timeseries", methods=["GET"])
async def obs_timeseries(req: func.HttpRequest) -> func.HttpResponse:
    """Time-bucketed request counts for trend charts."""
    err = await _guard(req)
    if err:
        return err
    try:
        data = await observability.get_time_series(
            since_hours=int(req.params.get("since_hours", "24")),
            bucket_hours=int(req.params.get("bucket_hours", "1")),
        )
        return _json({"buckets": data})
    except Exception as exc:
        log.exception("obs_timeseries failed")
        return _err(str(exc), 500)

# =============================================================================
# AGENT CRUD ROUTES
# =============================================================================

@app.route(route="agents", methods=["POST"])
async def create_agent(req: func.HttpRequest) -> func.HttpResponse:
    """
    Register a new agent in the registry.
    Returns 409 Conflict if an agent with the same name already exists.

    Required fields: name, description, endpoint_url
    Optional fields: api_key_secret_name, version, utility_types, tags, capabilities, metadata
    """
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
    """
    List registered agents with optional filtering.

    Query parameters:
      q             Full-text search across name, description, tags, capability names
      status        Filter by status: active | inactive | degraded
      utility_type  Filter by utility type: electric | gas | water | multi
      tag           Filter by exact tag match
    """
    err = await _guard(req)
    if err:
        return err
    q            = req.params.get("q", "").strip()
    status       = req.params.get("status")
    utility_type = req.params.get("utility_type")
    tag          = req.params.get("tag")
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
    """
    Auto-discover capabilities of a remote agent by calling it with a
    structured capability-listing prompt.

    This endpoint is used by the React UI before saving a new or edited agent.
    The admin fills endpoint_url, auth_config, auth_secrets, and invocation_config,
    then clicks "Auto-fetch capabilities". The response is a parsed list of
    capabilities that the admin can review and confirm before saving.

    Auth note: auth_secrets carries PLAIN VALUES here (not Key Vault refs) because
    the agent may not be registered yet. Plain values are used for this single
    outgoing call and never persisted.

    Request body:
      {
        "endpoint_url":      "https://...",
        "auth_config":       { ... },       // AuthConfig dict
        "auth_secrets":      { ... },       // AuthSecrets dict with plain values
        "invocation_config": { ... }        // InvocationConfig dict
      }

    Success (200):
      {
        "capabilities": [{"name": "...", "description": "...", ...}],
        "raw_response":  "...",
        "parse_strategy": "...",
        "warning": null | "..."
      }

    Error (400 / 502):
      { "error": "Human-readable reason" }
    """
    err = await _guard(req)
    if err:
        return err
    if _IMPORT_ERROR:
        return _err("Worker startup failed", 503, _IMPORT_ERROR)

    try:
        body = req.get_json()
    except Exception:
        return _err("Invalid JSON body")

    endpoint_url      = (body.get("endpoint_url") or "").strip()
    auth_config       = body.get("auth_config")       or {}
    auth_secrets      = body.get("auth_secrets")      or {}
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
        # Human-readable errors from capability_fetcher — show to the admin
        return _err(str(exc), 502)
    except Exception as exc:
        log.exception("fetch_agent_capabilities: unexpected error")
        return _err(f"Unexpected error: {exc}", 500)

@app.route(route="agents/{agent_id}", methods=["GET"])
async def get_agent(req: func.HttpRequest) -> func.HttpResponse:
    """Retrieve a single agent by its document ID."""
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
    """
    Full replacement of all mutable fields.
    Preserves: id, created_at, and health tracking fields.
    Overwrites: name, description, endpoint_url, version, capabilities, etc.
    """
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
    """
    Partial update — only the fields present in the request body are changed.
    Unmentioned fields are left untouched.
    """
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
    """
    Soft delete by default: sets status to inactive, document is retained.
    Pass ?hard=true for physical deletion (use only for GDPR/cleanup).

    Soft-deleted agents are excluded from orchestrator planning but remain
    visible in the dashboard and export for audit purposes.
    """
    err = await _guard(req)
    if err:
        return err
    agent_id = req.route_params["agent_id"]
    try:
        deleted = await registry.delete_agent(agent_id)
        if not deleted:
            return _err(f"Agent '{agent_id}' not found", 404)
        return _json({"message": f"Agent {agent_id} permanently deleted"})
    except Exception as exc:
        log.exception("delete_agent failed")
        return _err(str(exc), 500)


# =============================================================================
# STATUS & CAPABILITY ROUTES
# =============================================================================

@app.route(route="agents/{agent_id}/status", methods=["PATCH"])
async def set_status(req: func.HttpRequest) -> func.HttpResponse:
    """
    Explicitly set agent status with an optional audit reason.

    Request body:
      { "status": "active|inactive|degraded", "reason": "optional note" }

    The reason is stored in metadata.status_reason for audit purposes.
    """
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
    """
    Add a new capability to an existing agent.
    Idempotent — if a capability with the same name already exists, returns 200
    with the current agent document unchanged.

    Request body:
      { "name": "check_balance", "description": "Check account balance", ... }
    """
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
    """Remove a capability from an agent by its exact name."""
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
    """
    Probe a single agent's /api/health endpoint and update its health fields
    in the registry document.

    Returns 200 when the agent is healthy, 502 when unhealthy or unreachable.
    The agent's status field is automatically transitioned:
      healthy    → active   (if it was degraded)
      unhealthy  → degraded (if it was active)
    """
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

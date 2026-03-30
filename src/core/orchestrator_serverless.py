from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import azure.functions as func

CORE_DIR = Path(__file__).resolve().parent
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

from orchestrator import UniversalOrchestrator

LOGGER = logging.getLogger("orchestrator_serverless")

AUTH_LEVEL_BY_NAME: dict[str, func.AuthLevel] = {
    "ANONYMOUS": func.AuthLevel.ANONYMOUS,
    "FUNCTION": func.AuthLevel.FUNCTION,
    "ADMIN": func.AuthLevel.ADMIN,
}

HTTP_AUTH_LEVEL = AUTH_LEVEL_BY_NAME.get(
    os.getenv("ORCHESTRATOR_HTTP_AUTH_LEVEL", "FUNCTION").upper(),
    func.AuthLevel.FUNCTION,
)

app = func.FunctionApp(http_auth_level=HTTP_AUTH_LEVEL)
_ORCHESTRATOR: UniversalOrchestrator | None = None


def _get_orchestrator() -> UniversalOrchestrator:
    global _ORCHESTRATOR
    if _ORCHESTRATOR is not None:
        return _ORCHESTRATOR

    registry_path = os.getenv("ORCHESTRATOR_REGISTRY_PATH", str(CORE_DIR / "agents.json"))
    config_path = os.getenv("ORCHESTRATOR_CONFIG_PATH", str(CORE_DIR / "config.yaml"))
    _ORCHESTRATOR = UniversalOrchestrator(registry_path=registry_path, config_path=config_path)
    return _ORCHESTRATOR


def _try_parse_json(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except (TypeError, ValueError):
        pass
    return {}


def _extract_query(payload: dict[str, Any]) -> str:
    direct_candidates = ("query", "user_query", "prompt", "message", "input")
    for key in direct_candidates:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    nested = payload.get("data")
    if isinstance(nested, dict):
        return _extract_query(nested)

    if isinstance(nested, str) and nested.strip():
        nested_payload = _try_parse_json(nested.strip())
        if nested_payload:
            return _extract_query(nested_payload)
        return nested.strip()

    return ""


async def _run_orchestration(user_query: str, source: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    trace = await _get_orchestrator().run_with_trace(user_query)
    return {
        "source": source,
        "query": user_query,
        "status": trace.get("status"),
        "final_answer": trace.get("final_answer"),
        "trace": trace,
        "metadata": metadata or {},
    }


@app.function_name(name="orchestrator_http_ingress")
@app.route(route="orchestrator/run", methods=["POST"])
async def orchestrator_http_ingress(req: func.HttpRequest) -> func.HttpResponse:
    payload: dict[str, Any] = {}
    try:
        payload = req.get_json()
        if not isinstance(payload, dict):
            payload = {}
    except ValueError:
        payload = _try_parse_json(req.get_body().decode("utf-8", errors="ignore"))

    user_query = _extract_query(payload)
    if not user_query:
        user_query = (req.params.get("query") or "").strip()

    if not user_query:
        return func.HttpResponse(
            body=json.dumps(
                {
                    "error": "Missing query in request body or query string.",
                    "expected_fields": ["query", "user_query", "prompt", "message", "input"],
                }
            ),
            status_code=400,
            mimetype="application/json",
        )

    try:
        result = await _run_orchestration(user_query=user_query, source="http")
    except Exception as exc:  # pragma: no cover - runtime safety for serverless host
        LOGGER.exception("HTTP orchestration failed")
        return func.HttpResponse(
            body=json.dumps({"error": "Orchestration execution failed.", "details": str(exc)}),
            status_code=500,
            mimetype="application/json",
        )

    status = result.get("status")
    status_code = 200
    if status == "blocked":
        status_code = 422
    elif status == "failed":
        status_code = 500

    return func.HttpResponse(
        body=json.dumps(result, default=str),
        status_code=status_code,
        mimetype="application/json",
    )


@app.function_name(name="orchestrator_eventgrid_ingress")
@app.event_grid_trigger(arg_name="event")
async def orchestrator_eventgrid_ingress(event: func.EventGridEvent) -> None:
    try:
        event_payload = event.get_json()
        if not isinstance(event_payload, dict):
            event_payload = {"data": event_payload}
    except Exception:  # pragma: no cover - EventGrid payload can vary by publisher
        event_payload = {}

    user_query = _extract_query(event_payload)
    if not user_query:
        LOGGER.warning(
            "EventGrid event ignored: no query found. id=%s type=%s subject=%s",
            getattr(event, "id", "unknown"),
            getattr(event, "event_type", "unknown"),
            getattr(event, "subject", "unknown"),
        )
        return

    metadata = {
        "event_id": getattr(event, "id", None),
        "event_type": getattr(event, "event_type", None),
        "subject": getattr(event, "subject", None),
        "topic": getattr(event, "topic", None),
    }

    try:
        result = await _run_orchestration(user_query=user_query, source="event_grid", metadata=metadata)
        LOGGER.info(
            "EventGrid orchestration complete. id=%s status=%s",
            metadata.get("event_id"),
            result.get("status"),
        )
    except Exception:
        LOGGER.exception(
            "EventGrid orchestration failed. id=%s type=%s",
            metadata.get("event_id"),
            metadata.get("event_type"),
        )

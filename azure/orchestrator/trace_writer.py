from __future__ import annotations
import asyncio
import json as _json_mod
import logging
import os
from datetime import datetime, timezone
from typing import Any

from azure.cosmos.aio import CosmosClient
from azure.cosmos import exceptions as cosmos_exc
from azure.identity.aio import DefaultAzureCredential

log = logging.getLogger(__name__)

_ENDPOINT   = os.environ["COSMOS_ENDPOINT"]
_DATABASE   = os.environ.get("COSMOS_DATABASE", "utility_agent_db")
_CONTAINER  = "traces"
_TTL_SECS   = 2592000
_CREDENTIAL = DefaultAzureCredential()

_container_verified = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ms_since(started_at: str) -> int:
    try:
        start = datetime.fromisoformat(started_at)
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        return int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
    except Exception:
        return 0


async def _verify_container() -> None:
    global _container_verified
    if _container_verified:
        return
    try:
        async with CosmosClient(_ENDPOINT, credential=_CREDENTIAL) as c:
            await c.get_database_client(_DATABASE)\
                   .get_container_client(_CONTAINER).read()
        _container_verified = True
        log.info("trace_writer: traces container verified OK")
    except cosmos_exc.CosmosResourceNotFoundError:
        log.error("trace_writer: 'traces' container missing")
    except Exception as exc:
        log.error("trace_writer: container check failed (%s: %s)", type(exc).__name__, exc)


async def _upsert(doc: dict[str, Any]) -> None:
    try:
        await asyncio.wait_for(_upsert_inner(doc), timeout=10.0)
    except asyncio.TimeoutError:
        log.error("trace_writer: upsert timed out (doc id=%s)", doc.get("id"))
    except Exception as exc:
        log.error("trace_writer: upsert failed (doc id=%s): %s: %s",
                  doc.get("id"), type(exc).__name__, exc, exc_info=True)


async def _upsert_inner(doc: dict[str, Any]) -> None:
    async with CosmosClient(_ENDPOINT, credential=_CREDENTIAL) as c:
        ctr = c.get_database_client(_DATABASE).get_container_client(_CONTAINER)
        await ctr.upsert_item(doc)


class TraceContext:

    def __init__(self, session_id: str, user_message: str, customer_id: str | None, trigger_type: str = "reactive",proactive_meta: dict | None = None):
        self.session_id = session_id
        self._doc: dict[str, Any] = {
            "id":               session_id,
            "partition_key":    session_id,
            "session_id":       session_id,
            "user_message":     user_message,
            "customer_id":      customer_id or "",
            "trigger_type":     trigger_type,
            "proactive_meta":   proactive_meta,
            "status":           "running",
            "started_at":       _now(),
            "completed_at":     None,
            "total_latency_ms": 0,
            "agents_invoked":   0,
            "plan":             {},
            "steps":            [],
            "final_response":   None,
            "error":            None,
            "ttl":              _TTL_SECS,
        }
        self._step_start_times: dict[int, str] = {}
        log.info("TraceContext created for session %s trigger_type=%s", session_id, trigger_type)

    async def record_plan(self, plan: Any) -> None:
        await _verify_container()
        self._doc["plan"] = {
            "plan_id":               getattr(plan, "plan_id", ""),
            "user_intent":           getattr(plan, "user_intent", ""),
            "synthesis_instruction": getattr(plan, "synthesis_instruction", ""),
            "step_count":            len(getattr(plan, "steps", [])),
        }
        log.info("TraceContext: writing plan for session %s (%d steps)",
                 self.session_id, self._doc["plan"]["step_count"])
        await _upsert(self._doc)

    def record_step_start(
        self,
        step:           Any,
        input_payload:  dict[str, Any],
        mapping_result: Any | None = None,   # schema_mapper.MappingResult | None
    ) -> None:
        """
        Record the start of a step. Called synchronously before the HTTP call.
        mapping_result is populated when schema-driven mode was used.
        """
        now = _now()
        self._step_start_times[step.step_id] = now

        # Determine body construction mode for observability
        schema_mode = "default"
        inv = getattr(step, "invocation_config", None) or {}
        if isinstance(inv, dict):
            if inv.get("request_schema", {}).get("fields"):
                schema_mode = "schema_driven"
            elif inv.get("body_template"):
                schema_mode = "template"

        step_doc: dict[str, Any] = {
            "step_id":       step.step_id,
            "agent_name":    step.agent_name,
            "agent_url":     step.agent_url,
            "task":          step.task,
            "depends_on":    getattr(step, "depends_on", []),
            "input_payload": _sanitise_payload(input_payload),
            "output_raw":    None,
            "result":        None,
            "started_at":    now,
            "completed_at":  None,
            "latency_ms":    None,
            "status":        "running",
            "error":         None,
            "auth_type":     (getattr(step, "auth_config", None) or {}).get("auth_type", "none"),
            # Schema-driven observability
            "schema_mode":   schema_mode,
            "mapping_result": _serialise_mapping(mapping_result),
        }
        self._doc["steps"] = [
            s for s in self._doc["steps"] if s["step_id"] != step.step_id
        ] + [step_doc]

    async def record_step_result(
        self,
        step_id:        int,
        output:         Any,
        result:         str,
        mapping_result: Any | None = None,
    ) -> None:
        now     = _now()
        started = self._step_start_times.get(step_id, now)
        latency = _ms_since(started)

        updates: dict[str, Any] = {
            "output_raw":   _truncate(json_safe(output)),
            "result":       _truncate(result),
            "completed_at": now,
            "latency_ms":   latency,
            "status":       "completed",
        }
        if mapping_result is not None:
            updates["mapping_result"] = _serialise_mapping(mapping_result)

        self._update_step(step_id, updates)
        self._doc["agents_invoked"] = self._doc.get("agents_invoked", 0) + 1
        log.info("TraceContext: step %d completed (%dms) session %s",
                 step_id, latency, self.session_id)
        await _upsert(self._doc)

    async def record_step_error(
        self,
        step_id: int,
        error:   str,
        skipped: bool = False,
    ) -> None:
        now     = _now()
        started = self._step_start_times.get(step_id, now)
        latency = _ms_since(started)
        self._update_step(step_id, {
            "completed_at": now,
            "latency_ms":   latency,
            "status":       "skipped" if skipped else "failed",
            "error":        _truncate(error, 1000),
        })
        log.info("TraceContext: step %d %s for session %s",
                 step_id, "skipped" if skipped else "failed", self.session_id)
        await _upsert(self._doc)

    async def record_step_schema_error(
        self,
        step_id:        int,
        error:          str,
        mapping_result: Any | None,
    ) -> None:
        """Called when schema mapping itself fails before any HTTP call."""
        now = _now()
        self._update_step(step_id, {
            "completed_at":   now,
            "latency_ms":     _ms_since(self._step_start_times.get(step_id, now)),
            "status":         "failed",
            "error":          _truncate(error, 1000),
            "mapping_result": _serialise_mapping(mapping_result),
        })
        await _upsert(self._doc)

    async def finish(
        self,
        final_response: str | None = None,
        error:          str | None = None,
    ) -> None:
        now = _now()
        self._doc.update({
            "status":           "failed" if error else "completed",
            "completed_at":     now,
            "total_latency_ms": _ms_since(self._doc["started_at"]),
            "final_response":   _truncate(final_response or ""),
            "error":            _truncate(error, 2000) if error else None,
        })
        log.info("TraceContext: finishing session %s status=%s latency=%dms",
                 self.session_id, self._doc["status"], self._doc["total_latency_ms"])
        await _upsert(self._doc)

    def _update_step(self, step_id: int, updates: dict[str, Any]) -> None:
        for s in self._doc["steps"]:
            if s["step_id"] == step_id:
                s.update(updates)
                return
        log.warning("TraceContext._update_step: step_id %d not found", step_id)


def _serialise_mapping(mapping_result: Any | None) -> dict | None:
    if mapping_result is None:
        return None
    try:
        return {
            "fields_included":    mapping_result.fields_included,
            "fields_skipped":     mapping_result.fields_skipped,
            "llm_tokens_used":    mapping_result.llm_tokens_used,
            "mapping_latency_ms": mapping_result.mapping_latency_ms,
            "retry_count":        mapping_result.retry_count,
            "warnings":           mapping_result.warnings,
            "errors":             mapping_result.errors,
            "decisions": [
                {
                    "field_name": d.field_name,
                    "included":   d.included,
                    "reason":     d.reason,
                    "confidence": d.confidence,
                    "inferred":   d.inferred,
                }
                for d in (mapping_result.decisions or [])
            ],
        }
    except Exception:
        return None


def json_safe(obj: Any) -> str:
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj
    try:
        return _json_mod.dumps(obj, default=str)
    except Exception:
        return str(obj)


def _sanitise_payload(payload: Any) -> Any:
    REDACT = {"authorization", "x-api-key", "x-functions-key",
              "password", "token", "secret", "bearer"}
    if isinstance(payload, dict):
        return {
            k: "***redacted***" if (
                k.lower() in REDACT or
                any(r in k.lower() for r in ("key","token","secret","auth","password"))
            ) else _sanitise_payload(v)
            for k, v in payload.items()
        }
    if isinstance(payload, list):
        return [_sanitise_payload(i) for i in payload]
    return payload


def _truncate(text: str, max_chars: int = 8000) -> str:
    if not text:
        return text
    if len(text) > max_chars:
        return text[:max_chars] + f"\n…[{len(text) - max_chars} chars truncated]"
    return text

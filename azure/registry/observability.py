from __future__ import annotations
import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from azure.cosmos.aio import CosmosClient
from azure.identity.aio import DefaultAzureCredential

log = logging.getLogger(__name__)

_ENDPOINT   = os.environ["COSMOS_ENDPOINT"]
_DATABASE   = os.environ.get("COSMOS_DATABASE", "utility_agent_db")
_CONTAINER  = "traces"
_CREDENTIAL = DefaultAzureCredential()


def _client() -> CosmosClient:
    return CosmosClient(_ENDPOINT, credential=_CREDENTIAL)


async def _query(sql: str, params: list[dict] | None = None) -> list[dict[str, Any]]:
    """Cross-partition query on the traces container."""
    async with _client() as c:
        ctr = c.get_database_client(_DATABASE).get_container_client(_CONTAINER)
        return [
            item async for item in ctr.query_items(
                query=sql,
                parameters=params or [],
            )
        ]


async def _get_one(session_id: str) -> dict[str, Any] | None:
    from azure.cosmos import exceptions as cosmos_exc
    try:
        async with _client() as c:
            ctr = c.get_database_client(_DATABASE).get_container_client(_CONTAINER)
            return await ctr.read_item(item=session_id, partition_key=session_id)
    except cosmos_exc.CosmosResourceNotFoundError:
        return None


# =============================================================================
# Trace list with filters
# =============================================================================

async def list_traces(
    status:      str | None = None,
    agent_name:  str | None = None,
    trigger_type: str | None = None,
    since_hours: int        = 24,
    limit:       int        = 50,
) -> list[dict[str, Any]]:

    since_hours = min(since_hours, 720)
    since_iso   = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).isoformat()

    conditions = ["c.started_at >= @since"]
    params: list[dict] = [{"name": "@since", "value": since_iso}]

    if status:
        conditions.append("c.status = @status")
        params.append({"name": "@status", "value": status})
    
    if trigger_type:
        conditions.append("c.trigger_type = @trigger_type")
        params.append({"name": "@trigger_type", "value": trigger_type})

    # Filter by agent name: check if any step used that agent
    if agent_name:
        conditions.append(
            "EXISTS(SELECT VALUE s FROM s IN c.steps WHERE s.agent_name = @agent)"
        )
        params.append({"name": "@agent", "value": agent_name})

    sql = f"""
        SELECT c.id, c.session_id, c.user_message, c.customer_id,
               c.trigger_type, c.proactive_meta,
               c.status, c.started_at, c.completed_at, c.total_latency_ms,
               c.agents_invoked, c.error,
               c.plan.user_intent,
               ARRAY_LENGTH(c.steps) AS step_count
        FROM c
        WHERE {" AND ".join(conditions)}
        ORDER BY c.started_at DESC
        OFFSET 0 LIMIT {min(limit, 200)}
    """
    return await _query(sql, params)

async def list_proactive_traces(
    since_hours: int       = 24,
    customer_id: str | None = None,
    severity:    str | None = None,
    agent_name:  str | None = None,
    event_type:  str | None = None,
    limit:       int        = 50,
) -> list[dict]:

    since_hours = min(since_hours, 720)
    limit       = min(limit, 200)
    since_iso   = (
        datetime.now(timezone.utc) - timedelta(hours=since_hours)
    ).isoformat()

    conditions: list[str] = [
        "c.trigger_type = 'proactive'",
        "c.started_at >= @since",
    ]
    params: list[dict] = [{"name": "@since", "value": since_iso}]

    if customer_id:
        conditions.append("c.customer_id = @customer_id")
        params.append({"name": "@customer_id", "value": customer_id})

    if severity:
        conditions.append("c.proactive_meta.severity = @severity")
        params.append({"name": "@severity", "value": severity})

    if agent_name:
        conditions.append("c.proactive_meta.agent_name = @agent_name")
        params.append({"name": "@agent_name", "value": agent_name})

    if event_type:
        conditions.append("c.proactive_meta.event_type = @event_type")
        params.append({"name": "@event_type", "value": event_type})

    sql = f"""
        SELECT
            c.id, c.session_id, c.customer_id, c.trigger_type,
            c.status, c.started_at, c.completed_at,
            c.total_latency_ms, c.agents_invoked,
            c.final_response, c.error,
            c.proactive_meta
        FROM c
        WHERE {" AND ".join(conditions)}
        ORDER BY c.started_at DESC
        OFFSET 0 LIMIT {limit}
    """
    return await _query(sql, params)


# =============================================================================
# Full trace detail
# =============================================================================

async def get_trace(session_id: str) -> dict[str, Any] | None:
    return await _get_one(session_id)


# =============================================================================
# Aggregate metrics
# =============================================================================

async def get_metrics(since_hours: int = 24) -> dict[str, Any]:
    since_hours = min(since_hours, 720)
    since_iso   = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).isoformat()

    rows = await _query(
        """
        SELECT c.status, c.total_latency_ms, c.agents_invoked,
               c.started_at, c.completed_at
        FROM c
        WHERE c.started_at >= @since
        """,
        [{"name": "@since", "value": since_iso}],
    )

    if not rows:
        return {
            "total":         0,
            "completed":     0,
            "failed":        0,
            "running":       0,
            "success_rate":  0.0,
            "avg_latency_ms": 0,
            "p95_latency_ms": 0,
            "total_agent_invocations": 0,
            "since_hours":   since_hours,
        }

    total     = len(rows)
    completed = sum(1 for r in rows if r["status"] == "completed")
    failed    = sum(1 for r in rows if r["status"] == "failed")
    running   = sum(1 for r in rows if r["status"] == "running")

    latencies = sorted(
        [r.get("total_latency_ms") or 0 for r in rows if r.get("total_latency_ms")]
    )
    avg_lat = int(sum(latencies) / len(latencies)) if latencies else 0
    p95_lat = latencies[int(len(latencies) * 0.95)] if latencies else 0

    return {
        "total":           total,
        "completed":       completed,
        "failed":          failed,
        "running":         running,
        "success_rate":    round(completed / total * 100, 1) if total else 0.0,
        "avg_latency_ms":  avg_lat,
        "p95_latency_ms":  p95_lat,
        "total_agent_invocations": sum(r.get("agents_invoked") or 0 for r in rows),
        "since_hours":     since_hours,
    }

async def get_agent_metrics(since_hours: int = 24) -> list[dict[str, Any]]:
    """
    Per-agent metrics: invocations, avg latency, success rate, error rate.
    """
    since_hours = min(since_hours, 720)
    since_iso   = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).isoformat()

    rows = await _query(
        """
        SELECT s.agent_name, s.status, s.latency_ms, s.error
        FROM c
        JOIN s IN c.steps
        WHERE c.started_at >= @since
        """,
        [{"name": "@since", "value": since_iso}],
    )

    by_agent: dict[str, dict] = defaultdict(lambda: {
        "invocations": 0,
        "completed":   0,
        "failed":      0,
        "skipped":     0,
        "latencies":   [],
        "errors":      [],
    })

    for row in rows:
        name = row.get("agent_name", "unknown")
        d    = by_agent[name]
        d["invocations"] += 1
        if row.get("status") == "completed":
            d["completed"] += 1
        elif row.get("status") == "failed":
            d["failed"] += 1
            if row.get("error"):
                d["errors"].append(row["error"][:200])
        elif row.get("status") == "skipped":
            d["skipped"] += 1
        if row.get("latency_ms") is not None:
            d["latencies"].append(row["latency_ms"])

    result = []
    for name, d in sorted(by_agent.items()):
        lats   = sorted(d["latencies"])
        avg_ms = int(sum(lats) / len(lats)) if lats else 0
        p95_ms = lats[int(len(lats) * 0.95)] if lats else 0
        invoc  = d["invocations"]
        result.append({
            "agent_name":     name,
            "invocations":    invoc,
            "completed":      d["completed"],
            "failed":         d["failed"],
            "skipped":        d["skipped"],
            "success_rate":   round(d["completed"] / invoc * 100, 1) if invoc else 0.0,
            "avg_latency_ms": avg_ms,
            "p95_latency_ms": p95_ms,
            "recent_errors":  d["errors"][-3:],  # last 3 errors
        })

    return sorted(result, key=lambda x: x["invocations"], reverse=True)


async def get_time_series(since_hours: int = 24, bucket_hours: int = 1) -> list[dict[str, Any]]:
    """
    Requests per time bucket for the trend chart.
    Returns list of { bucket_start, total, completed, failed } dicts.
    """
    since_hours = min(since_hours, 720)
    since_iso   = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).isoformat()

    rows = await _query(
        "SELECT c.started_at, c.status FROM c WHERE c.started_at >= @since",
        [{"name": "@since", "value": since_iso}],
    )

    buckets: dict[str, dict] = defaultdict(lambda: {"total": 0, "completed": 0, "failed": 0})
    for row in rows:
        try:
            ts = datetime.fromisoformat(row["started_at"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            # Floor to bucket boundary
            floored = ts.replace(minute=0, second=0, microsecond=0)
            if bucket_hours > 1:
                hour_offset = (floored.hour // bucket_hours) * bucket_hours
                floored = floored.replace(hour=hour_offset)
            key = floored.isoformat()
            buckets[key]["total"]    += 1
            if row.get("status") == "completed":
                buckets[key]["completed"] += 1
            elif row.get("status") == "failed":
                buckets[key]["failed"] += 1
        except Exception:
            pass

    return [
        {"bucket_start": k, **v}
        for k, v in sorted(buckets.items())
    ]

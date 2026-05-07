"""
cosmos.py — Cosmos DB data layer for the Agent Registry.

Handles two containers:
  - agents          : partition_key = "agents"  (all registry docs)
  - admin_sessions  : partition_key = token id  (one session per partition)

Security:
  - DefaultAzureCredential (Managed Identity in Azure, CLI locally).
  - Single module-level credential to prevent aiohttp session leaks.
  - MSI requires "Cosmos DB Built-in Data Contributor" role on the account.
"""
from __future__ import annotations
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
_AGENTS_PK  = "agents"

# One credential instance — reused across all calls to prevent
# aiohttp ClientSession leaks.
_CREDENTIAL = DefaultAzureCredential()


# ── Client factory ────────────────────────────────────────────────────────────

def _client() -> CosmosClient:
    return CosmosClient(_ENDPOINT, credential=_CREDENTIAL)


# ── Generic helpers ───────────────────────────────────────────────────────────

async def _upsert(container_name: str, doc: dict[str, Any]) -> dict[str, Any]:
    doc["updated_at"] = datetime.now(timezone.utc).isoformat()
    async with _client() as c:
        ctr = c.get_database_client(_DATABASE).get_container_client(container_name)
        return await ctr.upsert_item(doc)


async def _read(container_name: str, item_id: str, pk: str) -> dict[str, Any] | None:
    try:
        async with _client() as c:
            ctr = c.get_database_client(_DATABASE).get_container_client(container_name)
            return await ctr.read_item(item=item_id, partition_key=pk)
    except cosmos_exc.CosmosResourceNotFoundError:
        return None


async def _delete(container_name: str, item_id: str, pk: str) -> bool:
    try:
        async with _client() as c:
            ctr = c.get_database_client(_DATABASE).get_container_client(container_name)
            await ctr.delete_item(item=item_id, partition_key=pk)
            return True
    except cosmos_exc.CosmosResourceNotFoundError:
        return False


async def _query(
    container_name: str,
    sql: str,
    params: list[dict] | None = None,
    pk: str | None = None,
) -> list[dict[str, Any]]:
    """
    Execute a SQL query.
    azure-cosmos 4.x removed enable_cross_partition_query —
    cross-partition queries run automatically when partition_key is omitted.
    """
    async with _client() as c:
        ctr = c.get_database_client(_DATABASE).get_container_client(container_name)
        kwargs: dict[str, Any] = {
            "query":      sql,
            "parameters": params or [],
        }
        if pk is not None:
            kwargs["partition_key"] = pk
        return [item async for item in ctr.query_items(**kwargs)]


# ── Agents ────────────────────────────────────────────────────────────────────

async def agent_get(agent_id: str) -> dict[str, Any] | None:
    return await _read("agents", agent_id, _AGENTS_PK)


async def agent_get_by_name(name: str) -> dict[str, Any] | None:
    rows = await _query(
        "agents",
        "SELECT * FROM c WHERE c.partition_key = 'agents' AND c.name = @name",
        [{"name": "@name", "value": name}],
        pk=_AGENTS_PK,
    )
    return rows[0] if rows else None


async def agent_list(
    status: str | None = None,
    utility_type: str | None = None,
    tag: str | None = None,
) -> list[dict[str, Any]]:
    conditions = ["c.partition_key = 'agents'"]
    params: list[dict] = []

    if status:
        conditions.append("c.status = @status")
        params.append({"name": "@status", "value": status})
    if utility_type:
        conditions.append("ARRAY_CONTAINS(c.utility_types, @utype)")
        params.append({"name": "@utype", "value": utility_type})
    if tag:
        conditions.append("ARRAY_CONTAINS(c.tags, @tag)")
        params.append({"name": "@tag", "value": tag})

    sql = (
        "SELECT * FROM c WHERE "
        + " AND ".join(conditions)
        + " ORDER BY c.created_at DESC"
    )
    return await _query("agents", sql, params, pk=_AGENTS_PK)


async def agent_search(q: str) -> list[dict[str, Any]]:
    return await _query(
        "agents",
        """SELECT * FROM c
           WHERE c.partition_key = 'agents'
             AND (
               CONTAINS(LOWER(c.name), @q)
               OR CONTAINS(LOWER(c.description), @q)
               OR EXISTS(
                 SELECT VALUE t FROM t IN c.tags WHERE CONTAINS(LOWER(t), @q)
               )
               OR EXISTS(
                 SELECT VALUE cap FROM cap IN c.capabilities
                 WHERE CONTAINS(LOWER(cap.name), @q)
                    OR CONTAINS(LOWER(cap.description), @q)
               )
             )
           ORDER BY c.created_at DESC""",
        [{"name": "@q", "value": q.strip().lower()}],
        pk=_AGENTS_PK,
    )


async def agent_upsert(doc: dict[str, Any]) -> dict[str, Any]:
    return await _upsert("agents", doc)



async def agent_hard_delete(agent_id: str) -> bool:
    return await _delete("agents", agent_id, _AGENTS_PK)


async def agent_capabilities_all() -> list[dict[str, Any]]:
    return await _query(
        "agents",
        """SELECT c.name AS agent_name,
                  cap.name AS cap_name,
                  cap.description AS cap_description
           FROM c
           JOIN cap IN c.capabilities
           WHERE c.partition_key = 'agents' AND c.status = 'active'
           ORDER BY cap.name""",
        pk=_AGENTS_PK,
    )


async def agent_stats_raw() -> list[dict[str, Any]]:
    return await _query(
        "agents",
        """SELECT c.id, c.status, c.utility_types, c.tags,
                  c.capabilities, c.created_at, c.last_health_check_at
           FROM c WHERE c.partition_key = 'agents'""",
        pk=_AGENTS_PK,
    )


async def agent_export_all() -> list[dict[str, Any]]:
    return await _query(
        "agents",
        "SELECT * FROM c WHERE c.partition_key = 'agents' ORDER BY c.created_at ASC",
        pk=_AGENTS_PK,
    )


# ── Admin sessions ────────────────────────────────────────────────────────────

async def session_create(doc: dict[str, Any]) -> dict[str, Any]:
    """
    Insert a new session document.
    The doc must have:
      id            : the session token (UUID)
      partition_key : same as id
      ttl           : seconds until Cosmos auto-deletes
    """
    async with _client() as c:
        ctr = c.get_database_client(_DATABASE).get_container_client("admin_sessions")
        return await ctr.upsert_item(doc)


async def session_get(token: str) -> dict[str, Any] | None:
    return await _read("admin_sessions", token, token)


async def session_delete(token: str) -> None:
    await _delete("admin_sessions", token, token)

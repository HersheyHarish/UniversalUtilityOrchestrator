"""
memory.py — Cosmos DB memory layer.

Security: DefaultAzureCredential (Managed Identity in Azure, CLI locally).
No connection strings or keys in this file.

Fix: a single module-level credential is created once and reused across all
calls. Previously a new DefaultAzureCredential() was instantiated inside
every _query()/_upsert() call; each credential spins up its own internal
aiohttp ClientSession which was never closed, producing the
"Unclosed client session" errors in the logs.
"""
from __future__ import annotations
import logging
import os
from typing import Any

from azure.cosmos.aio import CosmosClient
from azure.cosmos import exceptions as cosmos_exc
from azure.identity.aio import DefaultAzureCredential

from models import MessageRole, SessionDoc, MessageDoc, SessionStatus, MessageType, ExecutionPlan
from datetime import datetime, timezone

log = logging.getLogger(__name__)

_ENDPOINT = os.environ["COSMOS_ENDPOINT"]
_DATABASE = os.environ.get("COSMOS_DATABASE", "utility_agent_db")

_CREDENTIAL = DefaultAzureCredential()


# ── Low-level helpers ─────────────────────────────────────────────────────────

def _client() -> CosmosClient:

    return CosmosClient(_ENDPOINT, credential=_CREDENTIAL)


async def _upsert(container_name: str, doc: dict[str, Any]) -> dict[str, Any]:
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


async def _query(
    container_name: str,
    query: str,
    params: list[dict] | None = None,
    pk: str | None = None,
) -> list[dict[str, Any]]:
    """
    Execute a Cosmos DB SQL query.

    azure-cosmos 4.x removed enable_cross_partition_query — cross-partition
    queries run automatically when partition_key is omitted.
    """
    async with _client() as c:
        ctr = c.get_database_client(_DATABASE).get_container_client(container_name)
        kwargs: dict[str, Any] = {
            "query":      query,
            "parameters": params or [],
        }
        if pk is not None:
            kwargs["partition_key"] = pk
        return [item async for item in ctr.query_items(**kwargs)]


# ── Session operations ────────────────────────────────────────────────────────

async def create_session(doc: SessionDoc) -> SessionDoc:
    raw = await _upsert("sessions", doc.model_dump())
    return SessionDoc(**raw)


async def update_session(session_id: str, **fields) -> None:
    existing = await _read("sessions", session_id, session_id)
    if not existing:
        log.warning("update_session: session %s not found", session_id)
        return
    existing.update(fields)
    existing["updated_at"] = datetime.now(timezone.utc).isoformat()
    await _upsert("sessions", existing)


async def get_session(session_id: str) -> dict[str, Any] | None:
    return await _read("sessions", session_id, session_id)


# ── Message operations ────────────────────────────────────────────────────────

async def append_message(msg: MessageDoc) -> None:
    await _upsert("messages", msg.model_dump())


async def save_user_message(session_id: str, text: str) -> None:
    await append_message(MessageDoc(
        partition_key=session_id,
        session_id=session_id,
        role=MessageRole.USER,
        type=MessageType.USER_INPUT,
        content=text,
    ))

async def save_proactive_message(session_id: str, text: str, metadata: dict) -> None:
    await append_message(MessageDoc(
        partition_key=session_id,
        session_id=session_id,
        role=MessageRole.SYSTEM_TRIGGER,
        type=MessageType.PROACTIVE_TRIGGER,
        content=text,
        metadata=metadata
    ))

async def save_plan(session_id: str, plan: ExecutionPlan) -> None:
    await append_message(MessageDoc(
        partition_key=session_id,
        session_id=session_id,
        role=MessageRole.ORCHESTRATOR,
        type=MessageType.PLAN,
        content=plan.model_dump_json(),
        metadata={"plan_id": plan.plan_id, "num_steps": len(plan.steps)},
    ))
    await update_session(session_id,
                         status=SessionStatus.EXECUTING)


async def save_step_start(session_id: str, step_id: int, agent_name: str, task: str) -> None:
    await append_message(MessageDoc(
        partition_key=session_id,
        session_id=session_id,
        role=MessageRole.AGENT,
        type=MessageType.EXEC_START,
        step_id=step_id,
        agent_name=agent_name,
        content=task,
    ))


async def save_step_result(session_id: str, step_id: int,
                           agent_name: str, result: str,
                           metadata: dict | None = None) -> None:
    await append_message(MessageDoc(
        partition_key=session_id,
        session_id=session_id,
        role=MessageRole.AGENT,
        type=MessageType.EXEC_RESULT,
        step_id=step_id,
        agent_name=agent_name,
        content=result,
        metadata=metadata or {},
    ))


async def save_step_error(session_id: str, step_id: int,
                          agent_name: str, error: str) -> None:
    await append_message(MessageDoc(
        partition_key=session_id,
        session_id=session_id,
        role=MessageRole.AGENT,
        type=MessageType.EXEC_ERROR,
        step_id=step_id,
        agent_name=agent_name,
        content=error,
    ))


async def save_final_response(session_id: str, response: str) -> None:
    await append_message(MessageDoc(
        partition_key=session_id,
        session_id=session_id,
        role=MessageRole.SYSTEM,
        type=MessageType.FINAL,
        content=response,
    ))
    await update_session(session_id,
                         status=SessionStatus.COMPLETE)


async def get_step_results(session_id: str) -> list[dict[str, Any]]:
    return await _query(
        "messages",
        "SELECT * FROM c WHERE c.session_id = @sid AND c.type = @t ORDER BY c.step_id",
        params=[
            {"name": "@sid", "value": session_id},
            {"name": "@t",   "value": MessageType.EXEC_RESULT},
        ],
        pk=session_id,
    )

async def get_proactive_messages(
    customer_id: str,
    since_iso:   str | None = None,
    severity:    str | None = None,
    event_type:  str | None = None,
    agent_name:  str | None = None,
    limit:       int        = 50,
) -> list[dict[str, Any]]:
    conditions = [
        "c.message_type = 'proactive_trigger'",
        "c.customer_id  = @cid",
    ]
    params: list[dict] = [{"name": "@cid", "value": customer_id}]

    if since_iso:
        conditions.append("c.created_at >= @since")
        params.append({"name": "@since", "value": since_iso})

    if severity:
        conditions.append("c.metadata.severity = @severity")
        params.append({"name": "@severity", "value": severity})
 
    if event_type:
        conditions.append("c.metadata.event_type = @event_type")
        params.append({"name": "@event_type", "value": event_type})
 
    if agent_name:
        conditions.append("c.metadata.source_agent = @agent_name")
        params.append({"name": "@agent_name", "value": agent_name})

    query = (
        "SELECT * FROM c WHERE "
        + " AND ".join(conditions)
        + " ORDER BY c.created_at DESC"
        + f" OFFSET 0 LIMIT {min(limit, 200)}"
    )

    return await _query(
        "messages",
        query,
        params=params
    )
    return rows

# ── Agent registry ────────────────────────────────────────────────────────────

async def get_active_agents() -> list[dict[str, Any]]:
    return await _query(
        "agents",
        "SELECT * FROM c WHERE c.partition_key = 'agents' AND c.status = 'active'",
        pk="agents",
    )
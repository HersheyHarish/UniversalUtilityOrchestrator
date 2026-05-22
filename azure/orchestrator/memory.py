from __future__ import annotations

import json
import logging
import os
from typing import Any

from azure.cosmos import exceptions as cosmos_exc
from azure.cosmos.aio import CosmosClient
from azure.identity.aio import DefaultAzureCredential
from models import MessageRole, SessionDoc, MessageDoc, SessionStatus, MessageType, ExecutionPlan
from datetime import datetime, timezone

log = logging.getLogger(__name__)

_ENDPOINT = os.environ["COSMOS_ENDPOINT"]
_DATABASE = os.environ.get("COSMOS_DATABASE", "utility_agent_db")

_CREDENTIAL: DefaultAzureCredential | None = None


# ── Low-level helpers ─────────────────────────────────────────────────────────


def _client() -> CosmosClient:
    app_env = os.environ.get("APP_ENV", "local").strip().lower()
    use_local = os.environ.get("USE_LOCAL_EMULATORS", "").lower() == "true"
    if app_env in {"prod", "production"} and use_local:
        raise RuntimeError("USE_LOCAL_EMULATORS=true is forbidden when APP_ENV=prod")

    if use_local:
        return CosmosClient(
            _ENDPOINT,
            credential="C2y6yDjf5/R+ob0N8A7Cgv30VRDJIWEHLM+4QDU5DE2nQ9nDuVTqobD4b8mGGyPMbIZnqyMsEcaGQy67XIw/Jw==",
            connection_verify=False,
        )
    global _CREDENTIAL
    if _CREDENTIAL is None:
        _CREDENTIAL = DefaultAzureCredential()
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
    async with _client() as c:
        ctr = c.get_database_client(_DATABASE).get_container_client(container_name)
        kwargs: dict[str, Any] = {
            "query": query,
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
    if not existing.get("session_id"):
        existing["session_id"] = existing.get("id") or session_id
    if not existing.get("partition_key"):
        existing["partition_key"] = existing["session_id"]
    existing.update(fields)
    existing["updated_at"] = datetime.now(timezone.utc).isoformat()
    await _upsert("sessions", existing)


async def get_session(session_id: str) -> dict[str, Any] | None:
    return await _read("sessions", session_id, session_id)

async def append_message(msg: MessageDoc) -> None:
    await _upsert("messages", msg.model_dump())

async def get_sessions_by_customer(customer_id: str) -> list[dict[str, Any]]:
    rows = await _query(
        "sessions",
        "SELECT * FROM c WHERE c.customer_id = @cid",
        params=[{"name": "@cid", "value": customer_id}],
    )

    def _sort_key(doc: dict[str, Any]) -> tuple[int, str]:
        ts = doc.get("_ts")
        if isinstance(ts, (int, float)):
            return (int(ts), doc.get("created_at") or "")
        return (0, doc.get("created_at") or "")

    rows.sort(key=_sort_key, reverse=True)
    return rows


async def set_dashboard_alert_state(
    session_id: str,
    alert_id: str,
    status: str,
    action: str | None = None,
) -> None:
    session = await _read("sessions", session_id, session_id)
    if not session:
        return
    state = session.get("dashboard_alert_states") or {}
    alert_state = state.get(alert_id) or {}
    alert_state["status"] = status
    if action:
        alert_state["action"] = action
    state[alert_id] = alert_state
    session["dashboard_alert_states"] = state
    await _upsert("sessions", session)


# ── Message operations ────────────────────────────────────────────────────────


async def save_user_message(session_id: str, text: str) -> None:
    await append_message(
        MessageDoc(
            partition_key=session_id,
            session_id=session_id,
            role=MessageRole.USER,
            type=MessageType.USER_INPUT,
            content=text,
        )
    )

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
    await append_message(
        MessageDoc(
            partition_key=session_id,
            session_id=session_id,
            role=MessageRole.ORCHESTRATOR,
            type=MessageType.PLAN,
            content=json.dumps(plan.model_dump()),
            metadata={"plan_id": plan.plan_id, "num_steps": len(plan.steps)},
        )
    )
    await update_session(session_id, status=SessionStatus.EXECUTING)

async def save_step_start(session_id: str, step_id: int, agent_name: str, task: str) -> None:
    await append_message(
        MessageDoc(
            partition_key=session_id,
            session_id=session_id,
            role=MessageRole.AGENT,
            type=MessageType.EXEC_START,
            step_id=step_id,
            agent_name=agent_name,
            content=task,
        )
    )


async def save_step_result(session_id: str, step_id: int, agent_name: str, result: str, metadata: dict | None = None) -> None:
    await append_message(
        MessageDoc(
            partition_key=session_id,
            session_id=session_id,
            role=MessageRole.AGENT,
            type=MessageType.EXEC_RESULT,
            step_id=step_id,
            agent_name=agent_name,
            content=result,
            metadata=metadata or {},
        )
    )


async def save_step_error(session_id: str, step_id: int, agent_name: str, error: str) -> None:
    await append_message(
        MessageDoc(
            partition_key=session_id,
            session_id=session_id,
            role=MessageRole.AGENT,
            type=MessageType.EXEC_ERROR,
            step_id=step_id,
            agent_name=agent_name,
            content=error,
        )
    )


async def save_final_response(session_id: str, response: str) -> None:
    await append_message(
        MessageDoc(
            partition_key=session_id,
            session_id=session_id,
            role=MessageRole.SYSTEM,
            type=MessageType.FINAL,
            content=response,
        )
    )
    await update_session(session_id, status=SessionStatus.COMPLETE)


async def get_step_results(session_id: str) -> list[dict[str, Any]]:
    return await _query(
        "messages",
        "SELECT * FROM c WHERE c.session_id = @sid AND c.type = @t ORDER BY c.step_id",
        params=[
            {"name": "@sid", "value": session_id},
            {"name": "@t", "value": MessageType.EXEC_RESULT},
        ],
        pk=session_id,
    )

async def get_conversation_history(session_id: str, limit: int = 10) -> list[dict]:
    rows = await _query(
        "messages",
        "SELECT TOP @n c.role, c.content, c.created_at FROM c WHERE c.session_id  = @sid AND c.role IN ('user', 'assistant') AND c.message_type = 'reactive' ORDER BY c.created_at DESC",
        params=[
            {"name": "@sid", "value": session_id},
            {"name": "@n",   "value": limit},
        ],
        pk=session_id,
    )
    rows.reverse()
 
    return [
        {"role": row["role"], "content": row["content"]}
        for row in rows


# ── Agent registry ────────────────────────────────────────────────────────────


async def get_active_agents() -> list[dict[str, Any]]:
    return await _query(
        "agents",
        "SELECT * FROM c WHERE c.partition_key = 'agents' AND c.status = 'active'",
        pk="agents",
    )

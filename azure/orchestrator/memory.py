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

import json
import logging
import os
from typing import Any

import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from azure.cosmos import exceptions as cosmos_exc
from azure.cosmos.aio import CosmosClient
from azure.identity.aio import DefaultAzureCredential
from models import ExecutionPlan, MessageDoc, MessageType, SessionDoc, SessionStatus

log = logging.getLogger(__name__)

_ENDPOINT = os.environ["COSMOS_ENDPOINT"]
_DATABASE = os.environ.get("COSMOS_DATABASE", "utility_agent_db")

# Single credential instance — created once at module load, reused for every
# Cosmos call. DefaultAzureCredential internally caches its token and only
# fetches a new one when the current token is about to expire.
_CREDENTIAL: DefaultAzureCredential | None = None


# ── Low-level helpers ─────────────────────────────────────────────────────────


def _client() -> CosmosClient:
    """
    Return a CosmosClient that shares the module-level credential.
    Used as `async with _client() as c:` — the client is closed after each
    block but the underlying credential (and its token cache) persists.
    """
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
    """
    Execute a Cosmos DB SQL query.

    azure-cosmos 4.x removed enable_cross_partition_query — cross-partition
    queries run automatically when partition_key is omitted.
    """
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
    from datetime import datetime, timezone

    existing = await _read("sessions", session_id, session_id)
    if not existing:
        log.warning("update_session: session %s not found", session_id)
        return
    # Container partition path is /session_id — ensure persisted docs always have it
    if not existing.get("session_id"):
        existing["session_id"] = existing.get("id") or session_id
    if not existing.get("partition_key"):
        existing["partition_key"] = existing["session_id"]
    existing.update(fields)
    existing["updated_at"] = datetime.now(timezone.utc).isoformat()
    await _upsert("sessions", existing)


async def get_session(session_id: str) -> dict[str, Any] | None:
    return await _read("sessions", session_id, session_id)


async def get_sessions_by_customer(customer_id: str) -> list[dict[str, Any]]:
    # Avoid ORDER BY on _ts here: cross-partition ORDER BY often fails on the emulator
    # or without a composite index; sort in-process instead.
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
    """Persist dashboard alert acknowledgement state on the session doc."""
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


async def append_message(msg: MessageDoc) -> None:
    await _upsert("messages", msg.model_dump())


async def save_user_message(session_id: str, text: str) -> None:
    await append_message(
        MessageDoc(
            partition_key=session_id,
            session_id=session_id,
            type=MessageType.USER_INPUT,
            content=text,
        )
    )


async def save_plan(session_id: str, plan: ExecutionPlan) -> None:
    await append_message(
        MessageDoc(
            partition_key=session_id,
            session_id=session_id,
            type=MessageType.PLAN,
            content=json.dumps(plan.model_dump()),
            metadata={"plan_id": plan.plan_id, "num_steps": len(plan.steps)},
        )
    )
    await update_session(session_id, plan=plan.model_dump(), status=SessionStatus.EXECUTING)


async def save_step_start(session_id: str, step_id: int, agent_name: str, task: str) -> None:
    await append_message(
        MessageDoc(
            partition_key=session_id,
            session_id=session_id,
            type=MessageType.STEP_START,
            step_id=step_id,
            agent_name=agent_name,
            content=task,
        )
    )


async def save_step_result(
    session_id: str, step_id: int, agent_name: str, result: str, metadata: dict | None = None
) -> None:
    await append_message(
        MessageDoc(
            partition_key=session_id,
            session_id=session_id,
            type=MessageType.STEP_RESULT,
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
            type=MessageType.STEP_ERROR,
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
            type=MessageType.FINAL,
            content=response,
        )
    )
    await update_session(session_id, final_response=response, status=SessionStatus.COMPLETE)


async def get_step_results(session_id: str) -> list[dict[str, Any]]:
    return await _query(
        "messages",
        "SELECT * FROM c WHERE c.session_id = @sid AND c.type = @t ORDER BY c.step_id",
        params=[
            {"name": "@sid", "value": session_id},
            {"name": "@t", "value": MessageType.STEP_RESULT},
        ],
        pk=session_id,
    )


def _transcript_limits() -> tuple[int, int]:
    max_turns = int(os.environ.get("ORCHESTRATOR_TRANSCRIPT_MAX_TURNS", "20"))
    max_chars = int(os.environ.get("ORCHESTRATOR_TRANSCRIPT_MAX_CHARS", "12000"))
    return max_turns, max_chars


async def get_session_transcript(
    session_id: str,
    *,
    max_turns: int | None = None,
    max_chars_per_turn: int | None = None,
    exclude_current_user: bool = False,
) -> list[dict[str, str]]:
    """
    Chronological user/assistant turns from the messages container.
    """
    default_turns, default_chars = _transcript_limits()
    turn_limit = max_turns if max_turns is not None else default_turns
    char_limit = max_chars_per_turn if max_chars_per_turn is not None else default_chars

    rows = await _query(
        "messages",
        "SELECT c.type, c.content, c.created_at FROM c "
        "WHERE c.session_id = @sid AND (c.type = @user OR c.type = @final) "
        "ORDER BY c.created_at",
        params=[
            {"name": "@sid", "value": session_id},
            {"name": "@user", "value": MessageType.USER_INPUT},
            {"name": "@final", "value": MessageType.FINAL},
        ],
        pk=session_id,
    )

    transcript: list[dict[str, str]] = []
    for row in rows:
        role = "user" if row.get("type") == MessageType.USER_INPUT else "assistant"
        content = (row.get("content") or "").strip()
        if not content:
            continue
        entry: dict[str, str] = {
            "role": role,
            "content": content[:char_limit],
            "created_at": row.get("created_at") or "",
        }
        transcript.append(entry)

    if exclude_current_user and transcript and transcript[-1]["role"] == "user":
        transcript = transcript[:-1]

    if turn_limit > 0 and len(transcript) > turn_limit:
        transcript = transcript[-turn_limit:]

    return transcript


async def get_conversation_history(session_id: str, limit: int = 8) -> list[dict[str, str]]:
    """Backward-compatible wrapper for planner-style history."""
    rows = await get_session_transcript(session_id, max_turns=limit)
    return [{"role": r["role"], "content": r["content"]} for r in rows]


# ── Agent registry ────────────────────────────────────────────────────────────


async def get_active_agents() -> list[dict[str, Any]]:
    return await _query(
        "agents",
        "SELECT * FROM c WHERE c.partition_key = 'agents' AND c.status = 'active'",
        pk="agents",
    )

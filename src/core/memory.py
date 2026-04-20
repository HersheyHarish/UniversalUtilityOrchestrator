from __future__ import annotations

import json
import os
import logging
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class MemoryStore(ABC):
    @abstractmethod
    async def save_trace(self, session_id: str, trace_data: dict[str, Any]) -> None:
        pass

    @abstractmethod
    async def get_history(self, session_id: str) -> list[dict[str, Any]]:
        pass


class LocalFileMemoryStore(MemoryStore):
    """Persist traces as JSON files on disk.

    Layout: ``<base_dir>/<session_id>/<timestamp>_<uuid>.json``

    This is the default for local development when CosmosDB is not configured.
    """

    def __init__(self, base_dir: str | Path | None = None):
        if base_dir is None:
            base_dir = Path(__file__).resolve().parents[1] / "data" / "traces"
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"LocalFileMemoryStore initialized at {self.base_dir}")

    async def save_trace(self, session_id: str, trace_data: dict[str, Any]) -> None:
        session_dir = self.base_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        filename = f"{ts}_{uuid.uuid4().hex[:8]}.json"
        filepath = session_dir / filename

        document = {
            "id": str(uuid.uuid4()),
            "session_id": session_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trace": trace_data,
        }

        try:
            with filepath.open("w", encoding="utf-8") as fh:
                json.dump(document, fh, indent=2, default=str)
            logger.info(f"Saved trace to {filepath}")
        except OSError as exc:
            logger.error(f"Failed to save trace locally: {exc}")

    async def get_history(self, session_id: str) -> list[dict[str, Any]]:
        session_dir = self.base_dir / session_id
        if not session_dir.exists():
            return []

        history: list[dict[str, Any]] = []
        for filepath in sorted(session_dir.glob("*.json")):
            try:
                with filepath.open("r", encoding="utf-8") as fh:
                    history.append(json.load(fh))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning(f"Skipping corrupt trace file {filepath}: {exc}")
        return history


class CosmosDBMemoryStore(MemoryStore):
    def __init__(self):
        self.endpoint = os.getenv("COSMOS_DB_ENDPOINT")
        self.key = os.getenv("COSMOS_DB_KEY")
        self.database_name = os.getenv("COSMOS_DB_DATABASE", "orchestrator-db")
        self.container_name = os.getenv("COSMOS_DB_CONTAINER", "traces")

        self.client = None
        self.container = None
        if self.endpoint and self.key:
            from azure.cosmos.aio import CosmosClient
            self.client = CosmosClient(self.endpoint, credential=self.key)

    async def _init_container(self):
        if not self.container and self.client:
            database = self.client.get_database_client(self.database_name)
            self.container = database.get_container_client(self.container_name)

    async def save_trace(self, session_id: str, trace_data: dict[str, Any]) -> None:
        if not self.client:
            logger.debug(f"CosmosDB not configured. Skipping save for session: {session_id}")
            return

        await self._init_container()

        document = {
            "id": str(uuid.uuid4()),
            "session_id": session_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trace": trace_data,
        }

        try:
            await self.container.upsert_item(document)
            logger.info(f"Saved trace to CosmosDB for session: {session_id}")
        except Exception as e:
            logger.error(f"Failed to save trace to CosmosDB: {e}")

    async def get_history(self, session_id: str) -> list[dict[str, Any]]:
        if not self.client:
            logger.debug("CosmosDB not configured. Returning empty history.")
            return []

        await self._init_container()

        query = "SELECT * FROM c WHERE c.session_id = @session_id ORDER BY c.timestamp ASC"
        parameters = [{"name": "@session_id", "value": session_id}]

        history = []
        try:
            items = self.container.query_items(
                query=query,
                parameters=parameters,
                enable_cross_partition_query=True,
            )
            async for item in items:
                history.append(item)
            return history
        except Exception as e:
            logger.error(f"Failed to query history from CosmosDB: {e}")
            return []


def create_memory_store() -> MemoryStore:
    """Factory: returns CosmosDB store if configured, otherwise local file store."""
    if os.getenv("COSMOS_DB_ENDPOINT") and os.getenv("COSMOS_DB_KEY"):
        logger.info("Using CosmosDB memory store.")
        return CosmosDBMemoryStore()
    logger.info("COSMOS_DB_ENDPOINT not set — using local file memory store.")
    return LocalFileMemoryStore()

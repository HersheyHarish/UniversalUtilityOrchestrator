from __future__ import annotations

import os
import logging
from abc import ABC, abstractmethod
from typing import Any

from azure.cosmos.aio import CosmosClient
from azure.cosmos.exceptions import CosmosHttpResponseError

logger = logging.getLogger(__name__)

class MemoryStore(ABC):
    @abstractmethod
    async def save_trace(self, session_id: str, trace_data: dict[str, Any]) -> None:
        pass
        
    @abstractmethod
    async def get_history(self, session_id: str) -> list[dict[str, Any]]:
        pass

class CosmosDBMemoryStore(MemoryStore):
    def __init__(self):
        self.endpoint = os.getenv("COSMOS_DB_ENDPOINT")
        self.key = os.getenv("COSMOS_DB_KEY")
        self.database_name = os.getenv("COSMOS_DB_DATABASE", "orchestrator-db")
        self.container_name = os.getenv("COSMOS_DB_CONTAINER", "traces")
        
        self.client = None
        self.container = None
        if self.endpoint and self.key:
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
        
        import uuid
        document = {
            "id": str(uuid.uuid4()),
            "session_id": session_id,
            "trace": trace_data
        }
        
        try:
            await self.container.upsert_item(document)
            logger.info(f"Successfully saved trace to CosmosDB for session: {session_id}")
        except CosmosHttpResponseError as e:
            logger.error(f"Failed to save trace to CosmosDB: {e.message}")

    async def get_history(self, session_id: str) -> list[dict[str, Any]]:
        if not self.client:
            logger.debug("CosmosDB not configured. Returning empty history.")
            return []
            
        await self._init_container()
        
        query = "SELECT * FROM c WHERE c.session_id = @session_id"
        parameters = [{"name": "@session_id", "value": session_id}]
        
        history = []
        try:
            items = self.container.query_items(
                query=query,
                parameters=parameters,
                enable_cross_partition_query=True
            )
            async for item in items:
                history.append(item)
            return history
        except CosmosHttpResponseError as e:
            logger.error(f"Failed to query history from CosmosDB: {e.message}")
            return []

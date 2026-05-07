"""
init_cosmos_emulator.py — Bootstrap the Cosmos DB Emulator for local dev.

Creates the database and containers required by the orchestrator and registry.
Idempotent — safe to run multiple times.

Usage:
    docker exec azure_registry python /home/site/wwwroot/init_cosmos_emulator.py
"""

import asyncio
import os

from azure.cosmos import PartitionKey
from azure.cosmos.aio import CosmosClient

ENDPOINT = os.environ.get("COSMOS_ENDPOINT", "https://localhost:8081/")
KEY = "C2y6yDjf5/R+ob0N8A7Cgv30VRDJIWEHLM+4QDU5DE2nQ9nDuVTqobD4b8mGGyPMbIZnqyMsEcaGQy67XIw/Jw=="
DATABASE = os.environ.get("COSMOS_DATABASE", "utility_agent_db")

CONTAINERS = [
    {"id": "agents", "partition_key": "/partition_key"},
    {"id": "admin_sessions", "partition_key": "/partition_key", "ttl": True},
    {"id": "sessions", "partition_key": "/session_id"},
    {"id": "messages", "partition_key": "/session_id"},
    # Observability store: one trace document per session, partitioned by partition_key=session_id.
    {"id": "traces", "partition_key": "/partition_key", "ttl": True},
]

MAX_RETRIES = 10
RETRY_DELAY = 8  # seconds


async def main():
    print(f"Connecting to Cosmos Emulator at {ENDPOINT} ...")
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with CosmosClient(ENDPOINT, credential=KEY, connection_verify=False) as client:
                # Create database
                db = await client.create_database_if_not_exists(DATABASE)
                print(f"✓ Database '{DATABASE}' ready")

                # Create containers one at a time with retry
                for spec in CONTAINERS:
                    for c_attempt in range(1, MAX_RETRIES + 1):
                        try:
                            kwargs = {
                                "id": spec["id"],
                                "partition_key": PartitionKey(path=spec["partition_key"]),
                            }
                            if spec.get("ttl"):
                                kwargs["default_ttl"] = -1
                            await db.create_container_if_not_exists(**kwargs)
                            print(f"  ✓ Container '{spec['id']}' ready")
                            break
                        except Exception as e:
                            if c_attempt == MAX_RETRIES:
                                raise
                            print(
                                f"  ⏳ Container '{spec['id']}' attempt {c_attempt}/{MAX_RETRIES} "
                                f"failed ({type(e).__name__}), retrying in {RETRY_DELAY}s..."
                            )
                            await asyncio.sleep(RETRY_DELAY)

                print("\n🎉 Cosmos emulator initialised successfully!")
                return

        except Exception as e:
            if attempt == MAX_RETRIES:
                print(f"\n❌ Failed after {MAX_RETRIES} attempts: {e}")
                raise
            print(f"⏳ Attempt {attempt}/{MAX_RETRIES} failed ({type(e).__name__}), retrying in {RETRY_DELAY}s...")
            await asyncio.sleep(RETRY_DELAY)


if __name__ == "__main__":
    asyncio.run(main())

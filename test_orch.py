import asyncio
import logging
from src.core.orchestrator import UniversalOrchestrator

logging.basicConfig(level=logging.DEBUG)

async def main():
    orch = UniversalOrchestrator()
    print("Starting orchestrator run...")
    res = await orch.run("Why was customer CUST-1001 charged $250 for July 2019?", session_id="test")
    print(res)

asyncio.run(main())

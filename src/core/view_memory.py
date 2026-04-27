import asyncio
import json
import os
import sys
from pathlib import Path
from memory import create_memory_store

async def main():
    if len(sys.argv) < 2:
        print("Usage: python view_memory.py <session_id> [or 'list' to view latest sessions]")
        sys.exit(1)

    command_or_id = sys.argv[1]
    
    if command_or_id == "list":
        # Hack to just look at Local files for the sake of the demo debug tool
        base_dir = Path(__file__).resolve().parents[1] / "data" / "traces"
        if not base_dir.exists():
             print("No local traces directory found.")
             sys.exit(0)
             
        sessions = [d.name for d in base_dir.iterdir() if d.is_dir()]
        print(f"--- Found {len(sessions)} local sessions ---")
        for s in sessions:
            print(f"- {s}")
        sys.exit(0)
        
    session_id = command_or_id
    store = create_memory_store()
    history = await store.get_history(session_id)
    
    print(f"--- History for session '{session_id}' ---")
    print(f"Total entries: {len(history)}")
    for idx, entry in enumerate(history, start=1):
        timestamp = entry.get("timestamp")
        trace = entry.get("trace", {})
        plan = trace.get("plan", {})
        goal = plan.get("goal", "Unknown")
        final_answer = trace.get("final_answer", "")
        
        print(f"\n[ Entry {idx} | {timestamp} ]")
        print(f"Goal: {goal}")
        print(f"Final Answer: {final_answer}")
        
if __name__ == "__main__":
    asyncio.run(main())

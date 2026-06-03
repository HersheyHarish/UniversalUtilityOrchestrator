import json
import asyncio
import os
import cosmos

async def run():
    path = "/home/site/wwwroot/registry-export.json"
    if not os.path.exists(path):
        print(f"Error: {path} not found")
        return
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    print(f"Importing {len(data['agents'])} agents...")
    for agent in data["agents"]:
        # Map integer to number inside request_schema fields if present
        inv_config = agent.get("invocation_config") or {}
        req_schema = inv_config.get("request_schema") or {}
        fields = req_schema.get("fields") or []
        for field in fields:
            if field.get("field_type") == "integer":
                field["field_type"] = "number"
            # Nested fields
            nested = field.get("nested_fields") or []
            for nf in nested:
                if nf.get("field_type") == "integer":
                    nf["field_type"] = "number"

        # Strip cosmos-internal metadata keys if they start with underscore
        for k in list(agent.keys()):
            if k.startswith("_") and k != "_ts":
                del agent[k]

        # Set partition_key
        agent["partition_key"] = "agents"
        # Ensure ID is present
        if "id" not in agent:
            import uuid
            agent["id"] = str(uuid.uuid4())
        
        # Save to database
        saved = await cosmos.agent_upsert(agent)
        print(f"✓ Registered agent: {saved.get('name')}")

if __name__ == "__main__":
    asyncio.run(run())

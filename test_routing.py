import asyncio
import os
import sys
import json
from pathlib import Path

base_dir = Path(__file__).resolve().parent / "src" / "core"
sys.path.insert(0, str(base_dir))
from langchain_openai import ChatOpenAI
from planner import PlanningService
from agentRegistry import AgentRegistry

async def main():
    print("Testing Planner Routing Logic...")
    
    # Initialize the LLM exactly like Orchestrator does
    model_name = "gpt-5.4-nano"
    azure_key = os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("AZURE_OPENAI_KEY")
    azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    
    try:
        settings_file = Path(__file__).resolve().parent / "local.settings.json"
        if settings_file.exists():
             with open(settings_file, "r") as f:
                 data = json.load(f)
                 vals = data.get("Values", {})
                 if not azure_key:
                     azure_key = vals.get("AZURE_OPENAI_API_KEY") or vals.get("AZURE_OPENAI_KEY")
                 if not azure_endpoint:
                     azure_endpoint = vals.get("AZURE_OPENAI_ENDPOINT")
    except Exception as e:
        pass

    if not azure_key or not azure_endpoint:
        print("AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT must be set to run this test.")
        return
        
    model = ChatOpenAI(
        api_key=azure_key,
        base_url=azure_endpoint,
        model=model_name,
        temperature=0.0 # strict deterministic routing
    )
    
    planner = PlanningService(model=model, max_steps=6)
    
    registry_file = base_dir / "agents.json"
    registry = AgentRegistry.load(registry_file)
    
    tests = [
        {
            "name": "Single Agent Specialization (Billing)",
            "query": "Explain my billing charges for customer CUST-1001 for July 2019.",
            "expected_agents": ["billing_agent"]
        },
        {
            "name": "Single Agent Specialization (Anomaly)",
            "query": "Did customer CUST-1002 have any usage spikes in October 2019?",
            "expected_agents": ["anomaly_detection_agent"]
        },
        {
             "name": "Single Agent Specialization (Summarizer)",
             "query": "Summarize everything we just talked about.",
             "expected_agents": ["conversation_summary_agent"]
        },
        {
            "name": "Multi-Agent Routing (Billing + Profile)",
            "query": "Give me the profile details and a full billing breakdown for customer CUST-1002.",
            "expected_agents": ["customer_lookup_agent", "billing_agent"]
        }
    ]
    
    successes = 0
    
    for t in tests:
        print(f"\n--- Running Test: {t['name']} ---")
        print(f"Query: {t['query']}")
        
        plan = await planner.create_plan(t['query'], registry)
        
        planned_agents = []
        for step in plan.steps:
            # Figure out which agent the orchestrator would select based on capability matching
            # logic exactly matching `orchestrator._select_agent`
            selected = None
            if step.preferred_agent:
                selected = registry.get(step.preferred_agent)
            if not selected:
                selected = registry.select_by_capabilities(step.required_capabilities)
            if not selected:
                selected = registry.select_by_capabilities([step.objective])
                
            if selected:
                planned_agents.append(selected.name)
        
        print(f"Planned Agent Path: {planned_agents}")
        
        # Check if the expected agents are a subset of the planned agents,
        # OR exactly match depending on how strict we want the test.
        # Let's say all expected agents must be present, and it shouldn't randomly select ALL 4 agents for simple queries.
        missing = set(t['expected_agents']) - set(planned_agents)
        extra = set(planned_agents) - set(t['expected_agents'])
        
        if not missing and len(extra) == 0:
             print("✅ Test Passed: Exact routing match.")
             successes += 1
        elif not missing and len(extra) > 0:
             print(f"🟡 Test Warning: Handled required agents but added extra unexpected agents: {extra}")
        else:
             print(f"❌ Test Failed: Missing expected agents: {missing}")

    print(f"\nCompleted: {successes}/{len(tests)} tests passed strict specialization routing.")

if __name__ == "__main__":
    asyncio.run(main())

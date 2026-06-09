"""LangGraph baseline using create_react_agent (the prebuilt ReAct pattern).

Why this design:
  - Uses LangGraph's out-of-the-box ReAct agent rather than a hand-crafted
    StateGraph. This is the canonical "typical user deploys LangGraph"
    baseline — a fair comparison, not a strawman.
  - Wraps the same 9 production agent endpoints (from src/core/agents.json,
    skipping localhost ones) as LangChain tools with identical request bodies
    ({"query": ..., "customer_id": ...}) to what our orchestrator sends.
  - Same gpt-4o (via langchain-openai's AzureChatOpenAI) so the only
    variable is orchestration approach.
  - Tracks tool invocations and token usage from the response, returning the
    same dict shape as one_shot.run() / rag.run() so the scoring code needs
    no changes.

The dispatcher in run_eval.py loads this as `langgraph` system.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
from langchain_core.tools import tool
from langchain_openai import AzureChatOpenAI
from langgraph.prebuilt import create_react_agent

ROOT = Path(__file__).resolve().parents[2]
AGENTS_JSON = ROOT / "src" / "core" / "agents.json"

# Agent endpoints are static — load once at module import.
_AGENT_SPECS: list[dict[str, Any]] = []
for spec in json.loads(AGENTS_JSON.read_text())["agents"]:
    ep = spec.get("endpoint", "")
    if ep.startswith("http") and "localhost" not in ep:
        _AGENT_SPECS.append(spec)


def _make_tool(spec: dict[str, Any]):
    """Wrap a remote agent endpoint as a LangChain tool.

    The tool description comes from the agent's own description + capabilities,
    so the ReAct planner sees the same information our orchestrator's planner
    sees.
    """
    name = spec["name"]
    endpoint = spec["endpoint"]
    description = spec["description"]
    if spec.get("capabilities"):
        cap_lines = "\n".join(f"- {c}" for c in spec["capabilities"])
        description = f"{description}\n\nCapabilities:\n{cap_lines}"

    @tool(name, description=description)
    def _call(query: str, customer_id: str = "") -> str:
        """Call the remote agent and return its result as a string."""
        body = {"query": query}
        if customer_id:
            body["customer_id"] = customer_id
        try:
            with httpx.Client(timeout=120.0) as client:
                resp = client.post(endpoint, json=body)
                resp.raise_for_status()
                data = resp.json()
                # Common keys our agents return under.
                for key in ("result", "output", "response", "text", "content"):
                    if key in data:
                        v = data[key]
                        return v if isinstance(v, str) else json.dumps(v)
                return json.dumps(data)
        except Exception as exc:
            return f"[error calling {name}: {exc}]"

    return _call


_TOOLS = [_make_tool(s) for s in _AGENT_SPECS]


def _build_agent():
    """Create the ReAct agent. Built lazily so module import is cheap."""
    endpoint_raw = os.environ["AZURE_OPENAI_ENDPOINT"]
    endpoint = endpoint_raw.split("/openai")[0].split("/api/")[0].rstrip("/")
    llm = AzureChatOpenAI(
        azure_endpoint=endpoint,
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21"),
        azure_deployment=os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o"),
        temperature=0.2,
        max_tokens=1500,
    )

    system_prompt = (
        "You are a customer-support assistant for a utility company. "
        "You have access to specialist tools that fetch real customer data — "
        "billing, anomalies, weather, outages, solar, payment risk, etc. "
        "For any customer question, decide which tools to call and in what "
        "order, then synthesize a clear, grounded answer. Prefer calling "
        "tools to look things up rather than guessing."
    )

    return create_react_agent(llm, _TOOLS, prompt=system_prompt)


_AGENT_CACHE = None


def _get_agent():
    global _AGENT_CACHE
    if _AGENT_CACHE is None:
        _AGENT_CACHE = _build_agent()
    return _AGENT_CACHE


def run(query: str, customer_id: str | None = None) -> dict:
    """Invoke the ReAct agent and return run metrics in the standard shape."""
    agent = _get_agent()

    user_msg = query if not customer_id else f"[customer_id={customer_id}] {query}"

    started = time.perf_counter()
    result = agent.invoke({"messages": [{"role": "user", "content": user_msg}]})
    latency_ms = int((time.perf_counter() - started) * 1000)

    messages = result.get("messages", [])

    # Final assistant message — last AIMessage with non-empty content.
    response_text = ""
    for msg in reversed(messages):
        if getattr(msg, "type", None) == "ai" and getattr(msg, "content", ""):
            response_text = msg.content if isinstance(msg.content, str) else str(msg.content)
            break

    # Tool invocations in the order they were called.
    agents_used: list[str] = []
    for msg in messages:
        tool_calls = getattr(msg, "tool_calls", None) or []
        for tc in tool_calls:
            name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
            if name:
                agents_used.append(name)

    # Token usage: sum across all AIMessages.
    total_tokens = 0
    for msg in messages:
        usage = getattr(msg, "usage_metadata", None)
        if usage:
            total_tokens += int(usage.get("total_tokens") or 0)

    # Capture tool outputs (ToolMessage content) for fact-check fairness:
    # the fact-checker treats tool outputs as valid ground truth alongside src/data.
    tool_outputs: list[str] = []
    for msg in messages:
        if getattr(msg, "type", None) == "tool":
            content = getattr(msg, "content", "")
            if isinstance(content, str) and content:
                tool_outputs.append(content)

    return {
        "response": response_text,
        "agents_used": agents_used,
        "total_latency_ms": latency_ms,
        "planner_tokens": 0,
        "synth_tokens": 0,
        "total_tokens": total_tokens,
        "n_tool_calls": len(agents_used),
        "tool_outputs": tool_outputs,
    }


if __name__ == "__main__":
    out = run("Why was CUST-1001 charged so much for July 2019?", "CUST-1001")
    print(json.dumps({k: v for k, v in out.items() if k != "response"}, indent=2))
    print("\n--- response ---\n" + out["response"])

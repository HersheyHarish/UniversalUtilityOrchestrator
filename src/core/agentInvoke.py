from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from agentRegistry import AgentDefinition

@dataclass
class AgentInvocationResult:
    success: bool
    output: Any = None
    error: str = ""

# Class responsible for invoking agent endpoints with the appropriate payload and handling responses. 
# It includes a method for a demo invocation that simulates agent execution without making real HTTP calls, useful for testing and development.
class AgentInvoker:
    def __init__(self, timeout_seconds: int = 30):
        self.timeout_seconds = timeout_seconds

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def invoke(self, agent: AgentDefinition, payload: dict[str, Any]) -> AgentInvocationResult:
        """
        Invoke the agent endpoint with the given payload and return the result asynchronously.
        """
        import os
        headers = {}
        # Fetch an API key based on the agent's name (e.g. AGENT_KEY_PYTHONEXECUTOR)
        api_key = os.getenv(f"AGENT_KEY_{agent.name.upper().replace(' ', '_')}")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        try:
            timeout = getattr(agent, 'timeout_seconds', self.timeout_seconds) or self.timeout_seconds
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(agent.endpoint, json=payload, headers=headers)
                response.raise_for_status()
        except httpx.RequestError as exc:
            return AgentInvocationResult(success=False, error=f"HTTP request error for {agent.name}: {exc}")
        except httpx.HTTPStatusError as exc:
            return AgentInvocationResult(success=False, error=f"HTTP status error for {agent.name}: {exc}")

        try:
            return AgentInvocationResult(success=True, output=response.json())
        except ValueError:
            return AgentInvocationResult(success=True, output=response.text)

    async def demoInvoke(self, agent: AgentDefinition, payload: dict[str, Any]) -> AgentInvocationResult:
        step = payload.get("step", {})
        demo_output = {
            "mode": "demoInvoke",
            "message": (
                f"DEMO_INVOKE_OK: Orchestrator reached {agent.name} "
                f"for step `{step.get('id', 'unknown')}`."
            ),
            "agent": agent.name,
            "objective": step.get("objective", ""),
            "output_key": step.get("output_key", ""),
        }
        return AgentInvocationResult(success=True, output=demo_output)

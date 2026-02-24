from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import requests

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

    def invoke(self, agent: AgentDefinition, payload: dict[str, Any]) -> AgentInvocationResult:
        """
        Invoke the agent endpoint with the given payload and return the result.
        """
        try:
            response = requests.post(agent.endpoint, json=payload, timeout=self.timeout_seconds)
            response.raise_for_status()
        except requests.RequestException as exc:
            return AgentInvocationResult(success=False, error=f"HTTP failure for {agent.name}: {exc}")

        try:
            return AgentInvocationResult(success=True, output=response.json())
        except ValueError:
            return AgentInvocationResult(success=True, output=response.text)

    def demoInvoke(self, agent: AgentDefinition, payload: dict[str, Any]) -> AgentInvocationResult:
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

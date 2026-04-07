from __future__ import annotations

import json
from pydantic import BaseModel, Field
from typing import Any
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.language_models.chat_models import BaseChatModel
from agentRegistry import AgentRegistry
import logging

logger = logging.getLogger(__name__)

class PlanStep(BaseModel):
    id: str = Field(description="Unique identifier for the step (e.g., 'step_1')")
    objective: str = Field(description="A clear description of what this step must accomplish")
    required_capabilities: list[str] = Field(default_factory=list, description="List of capabilities needed to execute this step")
    dependencies: list[str] = Field(default_factory=list, description="List of step IDs that must complete before this step")
    preferred_agent: str | None = Field(default=None, description="Optional name of a specific agent to use")
    output_key: str | None = Field(default=None, description="Key to store the output of this step")

class ExecutionPlan(BaseModel):
    goal: str = Field(description="The overall goal being achieved")
    steps: list[PlanStep] = Field(description="Ordered list of steps to accomplish the goal")

class PlanningService:
    def __init__(self, model: BaseChatModel, max_steps: int = 6):
        # Wraps the model to enforce structured output against the Pydantic schema
        self.model = model.with_structured_output(ExecutionPlan)
        self.max_steps = max_steps

    async def create_plan(self, user_query: str, registry: AgentRegistry) -> ExecutionPlan:
        planning_prompt = self._build_prompt(user_query, registry)
        try:
            return await self.model.ainvoke(planning_prompt)
        except Exception as exc:  # pragma: no cover - protective fallback
            logger.warning(f"Failed to build plan with LLM: {exc}")
            return self._fallback_plan(user_query, registry)

    def _build_prompt(self, user_query: str, registry: AgentRegistry) -> list[Any]:
        planning_system_message = (
            "You are a planning service for a multi-agent orchestrator. "
            "Return a structured execution plan to achieve the user's goal.\n\n"
            f"Constraints:\n"
            f"- At most {self.max_steps} steps.\n"
            "- Dependencies must reference the `id` of earlier steps.\n"
            "- Keep steps concrete and agent-executable.\n"
            "- Use `required_capabilities` to map steps to available agents."
        )

        planning_user_message = (
            f"User request: {user_query}\n\n"
            f"Available agents:\n{json.dumps(registry.list_brief(), indent=2)}"
        )

        return [
            SystemMessage(content=planning_system_message),
            HumanMessage(content=planning_user_message),
        ]

    def _fallback_plan(self, user_query: str, registry: AgentRegistry) -> ExecutionPlan:
        default_agent = registry.agents[0].name if registry.agents else None
        return ExecutionPlan(
            goal=f"Resolve: {user_query}",
            steps=[
                PlanStep(
                    id="step_1",
                    objective="Handle the request end-to-end",
                    required_capabilities=["general task handling"],
                    dependencies=[],
                    preferred_agent=default_agent,
                    output_key="final_output",
                )
            ],
        )

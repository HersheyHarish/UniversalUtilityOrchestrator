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
    parameters: str = Field(default="{}", description="A valid JSON string containing the extracted parameters matching the chosen agent's input_schema. DO NOT USE MARKDOWN OR BACKTICKS around the JSON.")

class ExecutionPlan(BaseModel):
    goal: str = Field(description="The overall goal being achieved")
    steps: list[PlanStep] = Field(description="Ordered list of steps to accomplish the goal")

class PlanningService:
    def __init__(self, model: BaseChatModel, max_steps: int = 6):
        # Wraps the model to enforce structured output against the Pydantic schema
        self.model = model.with_structured_output(ExecutionPlan, strict=False)
        self.max_steps = max_steps

    async def create_plan(self, user_query: str, registry: AgentRegistry) -> ExecutionPlan:
        planning_prompt = self._build_prompt(user_query, registry)
        try:
            return await self.model.ainvoke(planning_prompt)
        except Exception as exc:  # pragma: no cover - protective fallback
            import traceback
            error_details = traceback.format_exc()
            logger.warning(f"Failed to build plan with LLM: {exc}")
            fallback = self._fallback_plan(user_query, registry)
            fallback.goal = f"Failure: {str(exc)}"
            # Save stack trace to local file for debug since func start is in user window
            logger.error(f"LLM Planner Crash Details: \n{error_details}")
            return fallback

    def _build_prompt(self, user_query: str, registry: AgentRegistry) -> list[Any]:
        planning_system_message = (
            "You are a planning service for a multi-agent orchestrator. "
            "Return a structured execution plan to achieve the user's goal.\n\n"
            f"Constraints:\n"
            f"- At most {self.max_steps} steps.\n"
            "- Dependencies must reference the `id` of earlier steps.\n"
            "- Keep steps concrete and agent-executable.\n"
            "- Use `required_capabilities` to map steps to available agents.\n"
            "- VERY IMPORTANT: You must extract arguments from the user query matching the chosen agent's `input_schema` and place them tightly in the `parameters` JSON string field. The value must be raw JSON textual format `{...}`.\n"
            "- If the schema needs dates (like `start_date`, `end_date`), convert rough phrases like 'last week' into standard ISO format dates.\n"
            "- For RAG-based agents: read the `query` field description in the schema carefully. If it says to embed identifiers or dates INTO the query string, you MUST compose a rich natural-language question that includes those values inline (e.g. 'Explain the billing charges for customer CUST-1001 from 2025-07-01 - 2025-07-31'). The agent uses the query text for retrieval, so vague queries will fail."
        )

        planning_user_message = (
            f"User request: {user_query}\n\n"
            f"Available agents (and their schemas):\n{json.dumps(registry.list_brief_with_schemas(), indent=2)}"
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
                    parameters="{}",
                )
            ],
        )

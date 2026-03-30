from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.language_models.chat_models import BaseChatModel
from agentRegistry import AgentRegistry

# Class that represents a single step in the execution plan. 
# Each step has an ID, an objective, 
# a list of required capabilities for agent selection, 
# a list of dependencies on other steps, an optional preferred agent, 
# and an optional output key for referencing its result in later steps.

@dataclass
class PlanStep:
    id: str
    objective: str
    required_capabilities: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    preferred_agent: str | None = None
    output_key: str | None = None


# Class that represents the overall execution plan, including the main goal and a list of ordered steps with their objectives, 
# required capabilities, dependencies, and preferred agents.
@dataclass
class ExecutionPlan:
    goal: str
    steps: list[PlanStep]

# Planning Service that interacts with the LLM to create a structured execution plan based on the user query and available agents. 
# It builds a prompt with constraints and parses the JSON response into an ExecutionPlan object. 
# If parsing fails, it falls back to a simple one-step plan.
class PlanningService:
    def __init__(self, model: BaseChatModel, max_steps: int = 6):
        self.model = model
        self.max_steps = max_steps

    async def create_plan(self, user_query: str, registry: AgentRegistry) -> ExecutionPlan:
        planning_prompt = self._build_prompt(user_query, registry)
        try:
            raw = (await self.model.ainvoke(planning_prompt)).content
            return self._parse_plan(raw)
        except Exception as exc:  # pragma: no cover - protective fallback
            print(f"[Planner] Failed to build plan with LLM: {exc}")
            return self._fallback_plan(user_query, registry)

    def _build_prompt(self, user_query: str, registry: AgentRegistry) -> list[Any]:
        planning_system_message = (
            "You are a planning service for a multi-agent orchestrator. "
            "Return ONLY valid JSON. Do not include markdown or explanations.\n\n"
            "JSON schema:\n"
            "{\n"
            '  "goal": "string",\n'
            '  "steps": [\n'
            "    {\n"
            '      "id": "step_1",\n'
            '      "objective": "string",\n'
            '      "required_capabilities": ["string"],\n'
            '      "dependencies": ["step_id"],\n'
            '      "preferred_agent": "string or null",\n'
            '      "output_key": "string"\n'
            "    }\n"
            "  ]\n"
            "}\n\n"
            f"Constraints:\n"
            f"- At most {self.max_steps} steps.\n"
            "- Dependencies must reference earlier steps.\n"
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

    def _parse_plan(self, raw_response: str) -> ExecutionPlan:
        """
        Parse the raw JSON response from the LLM into an ExecutionPlan object.
        """
        payload = self._extract_json_object(raw_response)
        raw_steps = payload.get("steps", [])
        steps: list[PlanStep] = []
        seen_step_ids: set[str] = set()

        for idx, raw_step in enumerate(raw_steps[: self.max_steps], start=1):
            step_id = str(raw_step.get("id") or f"step_{idx}").strip()
            if step_id in seen_step_ids:
                step_id = f"{step_id}_{idx}"
            seen_step_ids.add(step_id)

            objective = str(raw_step.get("objective") or "").strip()
            if not objective:
                objective = f"Execute task segment {idx}"

            dependencies = [str(dep).strip() for dep in raw_step.get("dependencies", []) if str(dep).strip()]
            required_capabilities = [
                str(cap).strip() for cap in raw_step.get("required_capabilities", []) if str(cap).strip()
            ]

            preferred_agent = raw_step.get("preferred_agent")
            if preferred_agent is not None:
                preferred_agent = str(preferred_agent).strip() or None

            output_key = str(raw_step.get("output_key") or f"output_{idx}").strip()

            steps.append(
                PlanStep(
                    id=step_id,
                    objective=objective,
                    required_capabilities=required_capabilities,
                    dependencies=dependencies,
                    preferred_agent=preferred_agent,
                    output_key=output_key,
                )
            )

        goal = str(payload.get("goal") or "Resolve the user request").strip()
        if not steps:
            raise ValueError("Plan contained no valid steps")

        return ExecutionPlan(goal=goal, steps=steps)

    def _fallback_plan(self, user_query: str, registry: AgentRegistry) -> ExecutionPlan:
        """
        Create a simple fallback plan with a single step.
        """
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

    @staticmethod
    def _extract_json_object(raw_response: str) -> dict[str, Any]:
        """
        Extract a JSON object from the raw LLM response, handling common formatting issues.
         - Strips markdown code fences if present.
         - Finds the first balanced JSON object in the text.
         - Raises ValueError if no valid JSON object is found.
        """
        raw_response = raw_response.strip()
        fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw_response, flags=re.DOTALL)
        candidate = fenced.group(1) if fenced else raw_response

        start = candidate.find("{")
        end = candidate.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("No JSON object found in planner response")

        json_blob = candidate[start : end + 1]
        return json.loads(json_blob)

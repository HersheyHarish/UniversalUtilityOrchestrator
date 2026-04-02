from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import AzureChatOpenAI, ChatOpenAI

from agentRegistry import AgentDefinition, AgentRegistry
from inputGuard import GuardrailResult, InputGuardrails
from planner import ExecutionPlan, PlanStep, PlanningService
from dagCreator import DAGCreator
from agentInvoke import AgentInvocationResult, AgentInvoker

# Class responsible for orchestrating the overall process. 
# It integrates the guardrails, planning service, DAG creation, 
# and agent invocation to execute the plan and synthesize a final answer for the user.
class UniversalOrchestrator:
    def __init__(self, registry_path: str = "agents.json", config_path: str = "config.yaml"):
        config_file = self._resolve_path(config_path)
        registry_file = self._resolve_path(registry_path)

        with config_file.open("r", encoding="utf-8") as handle:
            self.config = yaml.safe_load(handle) or {}

        self.registry = AgentRegistry.load(registry_file)

        llm_cfg = self.config.get("llm", {})
        
        # Pull model defaults and explicitly map Azure OpenAI environment variables
        # This supports custom naming like 'AZURE_OPENAI_KEY' or 'AZURE_OPENAI_DEPLOYMENT'
        model_name = llm_cfg.get("model", "gpt-5.4-nano")
        azure_key = os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("AZURE_OPENAI_KEY")
        azure_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME") or os.getenv("AZURE_OPENAI_DEPLOYMENT") or model_name
        azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        
        # Azure Foundry provides OpenAI Standard compatible endpoints (usually ending in /v1 or containing /v1)
        # These endpoints reject the 'api-version' parameter used by classic Azure OpenAI instances.
        if azure_endpoint and "/v1" in azure_endpoint:
            # For Foundry standard Endpoints, we use standard ChatOpenAI mapping
            self.model = ChatOpenAI(
                api_key=azure_key,
                base_url=azure_endpoint,
                model=model_name,
                temperature=float(llm_cfg.get("temperature", 0.4)),
            )
        else:
            api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")
            self.model = AzureChatOpenAI(
                api_key=azure_key,
                azure_endpoint=azure_endpoint,
                azure_deployment=azure_deployment,
                api_version=api_version,
                temperature=float(llm_cfg.get("temperature", 0.4)),
            )

        guardrail_cfg = self.config.get("guardrails", {})
        planning_cfg = self.config.get("planning", {})
        orchestration_cfg = self.config.get("orchestration", {})

        self.guardrails = InputGuardrails(guardrail_cfg)
        self.planner = PlanningService(self.model, max_steps=int(planning_cfg.get("max_steps", 6)))
        self.dag_creator = DAGCreator()
        self.agent_invoker = AgentInvoker(timeout_seconds=int(orchestration_cfg.get("timeout_seconds", 30)))
        self.halt_on_step_failure = bool(orchestration_cfg.get("halt_on_step_failure", True))
        self.use_demo_invoke = bool(orchestration_cfg.get("use_demo_invoke", False))

    async def run(self, user_query: str) -> str:
        trace = await self.run_with_trace(user_query)
        return trace["final_answer"]

    async def run_with_trace(self, user_query: str) -> dict[str, Any]:
        """
        Run the orchestration process with tracing enabled asynchronously.
        """
        # Step 1: Validate input against guardrails
        guardrail_result = self.guardrails.validate(user_query)
        if not guardrail_result.allowed:
            return {
                "status": "blocked",
                "guardrails": {
                    "reason": guardrail_result.reason,
                    "risk_flags": guardrail_result.risk_flags,
                },
                "final_answer": f"Request blocked by input guardrails: {guardrail_result.reason}",
            }

        # Step 2: Create execution plan using the planning service
        print("[Hub] Building execution plan...")
        plan = await self.planner.create_plan(guardrail_result.sanitized_query, self.registry)
        execution_layers = self.dag_creator.build_execution_layers(plan)

        # 3: Execute the plan layer by layer, invoking agents and collecting results
        step_results: dict[str, dict[str, Any]] = {}
        for layer_index, layer in enumerate(execution_layers, start=1):
            layer_steps = ", ".join(step.id for step in layer)
            print(f"[Hub] Executing layer {layer_index}: {layer_steps}")

            # Execute steps in the current layer concurrently
            tasks = [
                self._execute_step(step, guardrail_result.sanitized_query, step_results)
                for step in layer
            ]
            layer_results = await asyncio.gather(*tasks)

            for step, step_result in zip(layer, layer_results):
                step_results[step.id] = step_result
                if self.halt_on_step_failure and step_result["status"] == "failed":
                    return {
                        "status": "failed",
                        "plan": self._plan_to_dict(plan),
                        "steps": step_results,
                        "final_answer": self._summarize_failure(step, step_result),
                    }
        # 4: Synthesize final answer from execution trace
        final_answer = await self._synthesize_final_answer(guardrail_result.sanitized_query, plan, step_results)
        return {
            "status": "completed",
            "plan": self._plan_to_dict(plan),
            "steps": step_results,
            "final_answer": final_answer,
        }

    async def _execute_step(
        self,
        step: PlanStep,
        user_query: str,
        previous_step_results: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Execute a single step of the plan by invoking the appropriate agent.
        """
        agent = self._select_agent(step)
        if agent is None:
            return {
                "status": "failed",
                "agent": None,
                "objective": step.objective,
                "error": "No registered agent matches this step's capabilities.",
            }

        dependency_context = {
            dep: previous_step_results.get(dep, {}).get("output") for dep in step.dependencies
        }

        payload = {
            "query": user_query,
            "step": {
                "id": step.id,
                "objective": step.objective,
                "required_capabilities": step.required_capabilities,
                "dependencies": step.dependencies,
                "output_key": step.output_key,
            },
            "context": {
                "dependency_outputs": dependency_context,
                "all_step_results": previous_step_results,
            },
        }

        #using demo_invoke to simulate agent execution without making real API calls, will remove after agents are
        # implemented and integrated
        if self.use_demo_invoke:
            invocation_result = await self.agent_invoker.demoInvoke(agent, payload)
        else:
            invocation_result = await self.agent_invoker.invoke(agent, payload)

        if not invocation_result.success:
            return {
                "status": "failed",
                "agent": agent.name,
                "objective": step.objective,
                "error": invocation_result.error,
            }

        return {
            "status": "completed",
            "agent": agent.name,
            "objective": step.objective,
            "output": invocation_result.output,
        }

    def _select_agent(self, step: PlanStep) -> AgentDefinition | None:
        """
        Select an agent based on the step's requirements and preferences.
        """
        if step.preferred_agent:
            preferred = self.registry.get(step.preferred_agent)
            if preferred is not None:
                return preferred

        selected = self.registry.select_by_capabilities(step.required_capabilities)
        if selected is not None:
            return selected

        return self.registry.select_by_capabilities([step.objective])

    async def _synthesize_final_answer(
        self,
        user_query: str,
        plan: ExecutionPlan,
        step_results: dict[str, dict[str, Any]],
    ) -> str:
        synthesis_prompt = [
            SystemMessage(
                content=(
                    "You are the final response service for a multi-agent orchestrator. "
                    "Synthesize a concise, direct answer for the user using the execution trace. "
                    "If any step failed, explain what succeeded, what failed, and what is needed next."
                )
            ),
            HumanMessage(
                content=(
                    f"User query: {user_query}\n\n"
                    f"Plan: {json.dumps(self._plan_to_dict(plan), indent=2)}\n\n"
                    f"Step results: {json.dumps(step_results, indent=2, default=str)}"
                )
            ),
        ]

        try:
            response = (await self.model.ainvoke(synthesis_prompt)).content.strip()
            if response:
                return response
        except Exception as exc:  # pragma: no cover - protective fallback
            print(f"[Hub] Final synthesis failed: {exc}")

        return self._fallback_summary(step_results)

    @staticmethod
    def _summarize_failure(step: PlanStep, step_result: dict[str, Any]) -> str:
        error = step_result.get("error", "Unknown error")
        return (
            f"Execution stopped at `{step.id}` ({step.objective}). "
            f"Agent failure: {error}"
        )

    @staticmethod
    def _fallback_summary(step_results: dict[str, dict[str, Any]]) -> str:
        completed = [
            f"{step_id}: {result.get('output')}"
            for step_id, result in step_results.items()
            if result.get("status") == "completed"
        ]
        failed = [
            f"{step_id}: {result.get('error')}"
            for step_id, result in step_results.items()
            if result.get("status") == "failed"
        ]

        summary_parts: list[str] = []
        if completed:
            summary_parts.append("Completed steps -> " + " | ".join(completed))
        if failed:
            summary_parts.append("Failed steps -> " + " | ".join(failed))

        return "\n".join(summary_parts) if summary_parts else "No execution output was produced."

    @staticmethod
    def _plan_to_dict(plan: ExecutionPlan) -> dict[str, Any]:
        """
        Convert an ExecutionPlan object into a dictionary format for easier serialization and logging.
        """
        return {
            "goal": plan.goal,
            "steps": [
                {
                    "id": step.id,
                    "objective": step.objective,
                    "required_capabilities": step.required_capabilities,
                    "dependencies": step.dependencies,
                    "preferred_agent": step.preferred_agent,
                    "output_key": step.output_key,
                }
                for step in plan.steps
            ],
        }

    @staticmethod
    def _resolve_path(path_str: str) -> Path:
        """
        Resolve a file path to an absolute path, checking various locations.
        """
        candidate = Path(path_str)
        if candidate.is_absolute() and candidate.exists():
            return candidate

        if candidate.exists():
            return candidate.resolve()

        local_candidate = (Path(__file__).resolve().parent / candidate).resolve()
        if local_candidate.exists():
            return local_candidate

        raise FileNotFoundError(f"Unable to find file: {path_str}")


# Todo : implement CLI interface to continously accept user queries until exit
# Todo : Add logging db
# Todo : add azure monitoring/functions for serverless deployment
# Todo : Add plug and play for registry and agents
# Todo : implement persistent memory layer for context retention across queries
# Todo : Add support for multi-turn conversations
# Todo : implement testplan and test cases for all components

if __name__ == "__main__":
    orchestrator = UniversalOrchestrator()
    print(asyncio.run(orchestrator.run("I think my bill is too high this month, can you check it?")))

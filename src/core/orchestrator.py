from __future__ import annotations

import asyncio
import json
import os
import uuid
import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from evaluator import EvaluationService
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import AzureChatOpenAI, ChatOpenAI

from agentRegistry import AgentDefinition, AgentRegistry
from inputGuard import GuardrailResult, InputGuardrails
from planner import ExecutionPlan, PlanStep, PlanningService
from dagCreator import DAGCreator
from agentInvoke import AgentInvocationResult, AgentInvoker
from memory import CosmosDBMemoryStore, create_memory_store
from pii_masking import PIIMasker
from telemetry import get_tracer
import tiktoken

logger = logging.getLogger(__name__)
tracer = get_tracer(__name__)

class UniversalOrchestrator:
    def __init__(self, registry_path: str = "agents.json", config_path: str = "config.yaml"):
        config_file = self._resolve_path(config_path)
        registry_file = self._resolve_path(registry_path)

        with config_file.open("r", encoding="utf-8") as handle:
            self.config = yaml.safe_load(handle) or {}

        self.registry = AgentRegistry.load(registry_file)
        self.memory = create_memory_store()
        pii_cfg = self.config.get("pii_masking", {})

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
        evaluation_cfg = self.config.get("evaluation", {})

        self.guardrails = InputGuardrails(guardrail_cfg)
        self.planner = PlanningService(self.model, max_steps=int(planning_cfg.get("max_steps", 6)))
        self.dag_creator = DAGCreator()
        self.agent_invoker = AgentInvoker(timeout_seconds=int(orchestration_cfg.get("timeout_seconds", 30)))
        self.halt_on_step_failure = bool(orchestration_cfg.get("halt_on_step_failure", True))
        self.use_demo_invoke = bool(orchestration_cfg.get("use_demo_invoke", False))
        self.pii_masker = PIIMasker(patterns=pii_cfg.get("patterns"))
        
        self.evaluator = None
        if evaluation_cfg.get("enabled", True):
            eval_model = evaluation_cfg.get("model", "llama3.1:8b")
            eval_timeout = int(evaluation_cfg.get("timeout", 60))
            self.evaluator = EvaluationService(model_name=eval_model, timeout=eval_timeout)
        
        self.tokenizer = None
        try:
             self.tokenizer = tiktoken.get_encoding("cl100k_base")
        except Exception as e:
             logger.warning(f"Could not load tiktoken: {e}")

    async def run(self, user_query: str, session_id: str | None = None) -> str:
        trace = await self.run_with_trace(user_query, session_id)
        return trace["final_answer"]

    async def run_with_trace(self, user_query: str, session_id: str | None = None) -> dict[str, Any]:
        """
        Run the orchestration process with tracing enabled asynchronously.
        """
        session_id = session_id or str(uuid.uuid4())
        
        with tracer.start_as_current_span("orchestration_run") as span:
            span.set_attribute("session_id", session_id)
            
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
                    "session_id": session_id,
                }
            masked_query = self.pii_masker.mask_text(guardrail_result.sanitized_query)

            # Step 2: Create execution plan using the planning service
            logger.info("[Hub] Building execution plan...")
            with tracer.start_as_current_span("build_plan"):
                plan = await self.planner.create_plan(masked_query, self.registry)
                execution_layers = self.dag_creator.build_execution_layers(plan)

            # 3: Execute the plan layer by layer, invoking agents and collecting results
            step_results: dict[str, dict[str, Any]] = {}
            for layer_index, layer in enumerate(execution_layers, start=1):
                layer_steps = ", ".join(step.id for step in layer)
                logger.info(f"[Hub] Executing layer {layer_index}: {layer_steps}")

                with tracer.start_as_current_span(f"execute_layer_{layer_index}"):
                    # Execute steps in the current layer concurrently
                    tasks = [
                        self._execute_step(step, masked_query, step_results)
                        for step in layer
                    ]
                    layer_results = await asyncio.gather(*tasks)

                    for step, step_result in zip(layer, layer_results):
                        step_results[step.id] = step_result
                        if self.halt_on_step_failure and step_result["status"] == "failed":
                            safe_step_results = self.pii_masker.mask_any(step_results)
                            safe_step_result = self.pii_masker.mask_any(step_result)
                            result_val = {
                                "status": "failed",
                                "plan": plan.model_dump(),
                                "steps": safe_step_results,
                                "final_answer": self._summarize_failure(step, safe_step_result),
                                "session_id": session_id,
                            }
                            await self.memory.save_trace(session_id, result_val)
                            return result_val
            
            # 4: Synthesize final answer from execution trace
            safe_step_results = self.pii_masker.mask_any(step_results)
            with tracer.start_as_current_span("synthesize_answer"):
                final_answer = await self._synthesize_final_answer(masked_query, plan, safe_step_results)
            
            # 5: Optionally evaluate the run
            evaluation_blob = None
            if self.evaluator:
                logger.info("[Hub] Running evaluation...")
                with tracer.start_as_current_span("run_evaluation"):
                    try:
                        eval_result = await self.evaluator.aevaluate(
                            user_query=masked_query,
                            plan_dict=plan.model_dump(),
                            step_results=safe_step_results,
                            final_answer=final_answer
                        )
                        evaluation_blob = {
                            "goal_met": eval_result.goal_met,
                            "score": eval_result.score,
                            "summary": eval_result.summary,
                            "issues": eval_result.issues,
                            "retry_recommended": eval_result.retry_recommended
                        }
                    except Exception as e:
                        logger.error(f"[Hub] Evaluation failed: {e}")
            
            total_tokens = 0
            if self.tokenizer:
                 # roughly estimate input tokens used
                 content = str(plan.model_dump()) + str(safe_step_results) + final_answer
                 total_tokens = len(self.tokenizer.encode(content))
            
            result_val = {
                "status": "completed",
                "plan": plan.model_dump(),
                "steps": safe_step_results,
                "final_answer": final_answer,
                "session_id": session_id,
                "evaluation": evaluation_blob,
                "tokens": total_tokens
            }
            await self.memory.save_trace(session_id, result_val)
            return result_val

    async def _execute_step(
        self,
        step: PlanStep,
        user_query: str,
        previous_step_results: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Execute a single step of the plan by invoking the appropriate agent.
        """
        with tracer.start_as_current_span(f"execute_step_{step.id}") as span:
            agent = self._select_agent(step)
            if agent is None:
                span.set_attribute("status", "failed")
                return {
                    "status": "failed",
                    "agent": None,
                    "objective": step.objective,
                    "error": "No registered agent matches this step's capabilities.",
                }

            span.set_attribute("agent.name", agent.name)
            
            dependency_context = {
                dep: previous_step_results.get(dep, {}).get("output") for dep in step.dependencies
            }

            try:
                payload = json.loads(step.parameters) if step.parameters else {}
            except Exception:
                payload = {}
                
            if "query" not in payload:
                payload["query"] = user_query
                
            payload["step_metadata"] = {
                "id": step.id,
                "objective": step.objective,
                "required_capabilities": step.required_capabilities,
                "dependencies": step.dependencies,
                "output_key": step.output_key,
            }
            payload["context"] = {
                "dependency_outputs": dependency_context,
                "all_step_results": previous_step_results,
            }

            if self.use_demo_invoke:
                invocation_result = await self.agent_invoker.demoInvoke(agent, payload)
            else:
                invocation_result = await self.agent_invoker.invoke(agent, payload)

            if not invocation_result.success:
                span.set_attribute("status", "failed")
                span.set_attribute("error", invocation_result.error)
                return {
                    "status": "failed",
                    "agent": agent.name,
                    "objective": step.objective,
                    "error": invocation_result.error,
                }

            span.set_attribute("status", "completed")
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
                    "You are a helpful utility customer support agent responding directly to a customer. "
                    "You have access to findings from one or more specialized analysis tools. "
                    "Your job is to turn those findings into a clear, natural response — not a report.\n\n"
                    "Follow these principles:\n"
                    "1. Answer the customer's actual question first and directly.\n"
                    "2. If multiple findings exist, lead with the most important one for this customer's "
                    "situation. Urgency (e.g. shutoff warning, anomaly) takes priority over informational "
                    "content (e.g. program options).\n"
                    "3. For program or savings recommendations, present the top recommendation clearly. "
                    "Mention secondary options briefly only if they are meaningfully different or relevant.\n"
                    "4. If multiple dollar figures appear for different purposes (e.g. paying off an existing "
                    "balance vs. splitting a current bill), distinguish them clearly — never present them as "
                    "alternatives to the same problem.\n"
                    "5. Use plain language. Avoid bullet-pointing every finding as if reading from a checklist. "
                    "Write in flowing sentences where the content allows.\n"
                    "6. Match your tone to the situation — empathetic for hardship cases, "
                    "straightforward for factual questions.\n"
                    "7. If a step failed, briefly acknowledge the gap without making it the focus.\n"
                    "8. Be concise. Do not repeat information already stated.\n"
                    "9. Keep financial details high-level in the summary (e.g. 'save ~$33/month') — "
                    "do not re-explain rate structures or calculation mechanics that belong in the detail view."
                )
            ),
            HumanMessage(
                content=(
                    f"User query: {user_query}\n\n"
                    f"Plan: {json.dumps(plan.model_dump(), indent=2)}\n\n"
                    f"Step results: {json.dumps(step_results, indent=2, default=str)}"
                )
            ),
        ]

        try:
            response = (await self.model.ainvoke(synthesis_prompt)).content.strip()
            if response:
                return response
        except Exception as exc:  # pragma: no cover - protective fallback
            logger.warning(f"[Hub] Final synthesis failed: {exc}")

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


if __name__ == "__main__":
    from telemetry import setup_telemetry
    setup_telemetry()
    orchestrator = UniversalOrchestrator()
    print(asyncio.run(orchestrator.run("I think my bill is too high this month, can you check it?")))

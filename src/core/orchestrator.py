from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import requests
import yaml
from evaluator import EvaluationService
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

# Required fields every agent entry must provide.
_AGENT_REQUIRED_FIELDS = {"name", "description", "capabilities", "endpoint"}

# Pattern enforced on agent names (mirrors agents.schema.json).
_AGENT_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass
class AgentDefinition:
    name: str
    description: str
    capabilities: list[str]
    endpoint: str
    version: str = "1.0.0"
    status: str = "active"
    tags: list[str] = field(default_factory=list)
    health_check: str | None = None
    timeout_seconds: int = 30
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AgentDefinition":
        return cls(
            name=payload["name"],
            description=payload.get("description", ""),
            capabilities=payload.get("capabilities", []),
            endpoint=payload["endpoint"],
            version=payload.get("version", "1.0.0"),
            status=payload.get("status", "active"),
            tags=payload.get("tags", []),
            health_check=payload.get("health_check"),
            timeout_seconds=int(payload.get("timeout_seconds", 30)),
            input_schema=payload.get("input_schema", {}),
            output_schema=payload.get("output_schema", {}),
            metadata=payload.get("metadata", {}),
        )

    def to_dict(self) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "name": self.name,
            "version": self.version,
            "status": self.status,
            "description": self.description,
            "capabilities": self.capabilities,
            "tags": self.tags,
            "endpoint": self.endpoint,
            "timeout_seconds": self.timeout_seconds,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "metadata": self.metadata,
        }
        if self.health_check is not None:
            entry["health_check"] = self.health_check
        return entry


class AgentRegistry:
    def __init__(self, agents: list[AgentDefinition], registry_path: Path | None = None):
        self.agents = agents
        self.registry_path = registry_path

    @classmethod
    def load(cls, path: Path) -> "AgentRegistry":
        with path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
        agents = [AgentDefinition.from_dict(item) for item in raw.get("agents", [])]
        return cls(agents=agents, registry_path=path)

    # ------------------------------------------------------------------
    # Plug-and-play: add / remove / persist
    # ------------------------------------------------------------------

    def add_agent(self, agent_dict: dict[str, Any], *, persist: bool = True) -> AgentDefinition:
        """Register a new agent from a plain dictionary and optionally save to disk.

        Args:
            agent_dict: Must contain at minimum ``name``, ``description``,
                ``capabilities``, and ``endpoint``.  All other fields are
                optional and will receive sensible defaults.
            persist: When *True* (default) the updated registry is written back
                to ``registry_path`` immediately so the change survives restarts.

        Returns:
            The newly created :class:`AgentDefinition`.

        Raises:
            ValueError: If required fields are missing, the name violates the
                naming convention, the agent is a duplicate, or ``persist`` is
                requested but no ``registry_path`` was set.
        """
        self._validate_agent_dict(agent_dict)

        new_agent = AgentDefinition.from_dict(agent_dict)

        if self.get(new_agent.name) is not None:
            raise ValueError(
                f"An agent named '{new_agent.name}' is already registered. "
                "Use remove_agent() first or choose a different name."
            )

        today = str(date.today())
        new_agent.metadata.setdefault("created_at", today)
        new_agent.metadata.setdefault("updated_at", today)

        self.agents.append(new_agent)
        print(f"[Registry] Agent '{new_agent.name}' registered successfully.")

        if persist:
            self.save()

        return new_agent

    def remove_agent(self, agent_name: str, *, persist: bool = True) -> None:
        """Unregister an agent by name and optionally save to disk.

        Raises:
            ValueError: If no agent with ``agent_name`` exists.
        """
        before = len(self.agents)
        self.agents = [a for a in self.agents if a.name != agent_name]
        if len(self.agents) == before:
            raise ValueError(f"No agent named '{agent_name}' found in the registry.")
        print(f"[Registry] Agent '{agent_name}' removed.")
        if persist:
            self.save()

    def save(self) -> None:
        """Persist the current registry state back to ``registry_path``.

        Raises:
            RuntimeError: If ``registry_path`` is not set.
        """
        if self.registry_path is None:
            raise RuntimeError("Cannot save: registry_path is not set.")

        existing_schema_ref: str | None = None
        if self.registry_path.exists():
            try:
                with self.registry_path.open("r", encoding="utf-8") as fh:
                    existing = json.load(fh)
                existing_schema_ref = existing.get("$schema")
            except (json.JSONDecodeError, OSError):
                pass

        payload: dict[str, Any] = {"agents": [a.to_dict() for a in self.agents]}
        if existing_schema_ref:
            payload = {"$schema": existing_schema_ref, **payload}

        with self.registry_path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=4)
            fh.write("\n")

        print(f"[Registry] Saved {len(self.agents)} agent(s) to {self.registry_path}.")

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get(self, agent_name: str) -> AgentDefinition | None:
        return next((agent for agent in self.agents if agent.name == agent_name), None)

    def list_active(self) -> list[AgentDefinition]:
        """Return only agents whose status is 'active'."""
        return [a for a in self.agents if a.status == "active"]

    def list_brief(self) -> list[dict[str, Any]]:
        return [
            {
                "name": agent.name,
                "description": agent.description,
                "capabilities": agent.capabilities,
                "tags": agent.tags,
                "status": agent.status,
            }
            for agent in self.list_active()
        ]

    def select_by_capabilities(self, required_capabilities: list[str]) -> AgentDefinition | None:
        active = self.list_active()
        if not active:
            return None
        if not required_capabilities:
            return active[0]

        scored_agents: list[tuple[float, AgentDefinition]] = []
        for agent in active:
            score = self._match_score(required_capabilities, agent.capabilities)
            scored_agents.append((score, agent))

        scored_agents.sort(key=lambda item: item[0], reverse=True)
        top_score, top_agent = scored_agents[0]
        return top_agent if top_score > 0 else None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_agent_dict(agent_dict: dict[str, Any]) -> None:
        missing = _AGENT_REQUIRED_FIELDS - set(agent_dict.keys())
        if missing:
            raise ValueError(f"Agent definition is missing required fields: {sorted(missing)}")

        name = agent_dict["name"]
        if not isinstance(name, str) or not _AGENT_NAME_RE.match(name):
            raise ValueError(
                f"Agent name '{name}' is invalid. "
                "Names must start with a lowercase letter and contain only [a-z0-9_]."
            )

        if not isinstance(agent_dict.get("capabilities"), list) or not agent_dict["capabilities"]:
            raise ValueError("'capabilities' must be a non-empty list of strings.")

        status = agent_dict.get("status", "active")
        if status not in {"active", "inactive", "maintenance"}:
            raise ValueError(f"Invalid status '{status}'. Must be one of: active, inactive, maintenance.")

    def _match_score(self, required: list[str], offered: list[str]) -> float:
        offered_text = " ".join(offered).lower()
        offered_tokens = self._tokenize(offered_text)
        score = 0.0

        for capability in required:
            query = capability.lower().strip()
            if not query:
                continue
            if query in offered_text:
                score += 1.0
                continue

            req_tokens = self._tokenize(query)
            if not req_tokens:
                continue

            overlap = len(req_tokens.intersection(offered_tokens))
            score += overlap / len(req_tokens)

        return score

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        return set(re.findall(r"[a-zA-Z0-9_]+", text.lower()))


@dataclass
class GuardrailResult:
    allowed: bool
    sanitized_query: str
    reason: str = ""
    risk_flags: list[str] = field(default_factory=list)


class InputGuardrails:
    DEFAULT_BLOCKED_PATTERNS = [
        r"(?i)ignore\s+previous\s+instructions",
        r"(?i)reveal\s+(your\s+)?(system|developer)\s+prompt",
        r"(?i)bypass\s+(all\s+)?safety",
        r"(?i)act\s+as\s+root",
    ]

    def __init__(self, config: dict[str, Any] | None = None):
        cfg = config or {}
        self.max_input_chars = int(cfg.get("max_input_chars", 5000))
        self.min_input_chars = int(cfg.get("min_input_chars", 3))
        blocked_patterns = cfg.get("blocked_patterns", self.DEFAULT_BLOCKED_PATTERNS)
        self.blocked_regexes = [re.compile(pattern) for pattern in blocked_patterns]

    def validate(self, user_query: str) -> GuardrailResult:
        sanitized = self._sanitize(user_query)

        if len(sanitized) < self.min_input_chars:
            return GuardrailResult(
                allowed=False,
                sanitized_query=sanitized,
                reason="Input is too short. Please provide a more specific request.",
            )

        if len(sanitized) > self.max_input_chars:
            return GuardrailResult(
                allowed=False,
                sanitized_query=sanitized,
                reason=(
                    f"Input exceeds {self.max_input_chars} characters. "
                    "Please shorten your request."
                ),
            )

        for blocked_regex in self.blocked_regexes:
            if blocked_regex.search(sanitized):
                return GuardrailResult(
                    allowed=False,
                    sanitized_query=sanitized,
                    reason="Input blocked by safety guardrails.",
                    risk_flags=[blocked_regex.pattern],
                )

        risk_flags: list[str] = []
        if sanitized.count("```") > 2:
            risk_flags.append("multiple_code_blocks")
        if sanitized.count("http://") + sanitized.count("https://") > 8:
            risk_flags.append("high_link_density")

        return GuardrailResult(
            allowed=True,
            sanitized_query=sanitized,
            reason="",
            risk_flags=risk_flags,
        )

    @staticmethod
    def _sanitize(user_query: str) -> str:
        cleaned = user_query.replace("\x00", " ")
        cleaned = re.sub(r"[\r\t]+", " ", cleaned)
        return re.sub(r"\s+", " ", cleaned).strip()


@dataclass
class PlanStep:
    id: str
    objective: str
    required_capabilities: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    preferred_agent: str | None = None
    output_key: str | None = None


@dataclass
class ExecutionPlan:
    goal: str
    steps: list[PlanStep]


class PlanningService:
    def __init__(self, model: ChatOllama, max_steps: int = 6):
        self.model = model
        self.max_steps = max_steps

    def create_plan(self, user_query: str, registry: AgentRegistry) -> ExecutionPlan:
        planning_prompt = self._build_prompt(user_query, registry)
        try:
            raw = self.model.invoke(planning_prompt).content
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
        raw_response = raw_response.strip()
        fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw_response, flags=re.DOTALL)
        candidate = fenced.group(1) if fenced else raw_response

        start = candidate.find("{")
        end = candidate.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("No JSON object found in planner response")

        json_blob = candidate[start : end + 1]
        return json.loads(json_blob)


class DAGCreator:
    def build_execution_layers(self, plan: ExecutionPlan) -> list[list[PlanStep]]:
        step_lookup = {step.id: step for step in plan.steps}
        if len(step_lookup) != len(plan.steps):
            raise ValueError("Duplicate step IDs are not allowed")

        indegree: dict[str, int] = {step.id: 0 for step in plan.steps}
        graph: dict[str, list[str]] = {step.id: [] for step in plan.steps}

        for step in plan.steps:
            for dependency in step.dependencies:
                if dependency not in step_lookup:
                    raise ValueError(f"Plan references unknown dependency: {dependency}")
                graph[dependency].append(step.id)
                indegree[step.id] += 1

        ordered_ids = [step.id for step in plan.steps]
        ready = [step_id for step_id in ordered_ids if indegree[step_id] == 0]
        layers: list[list[PlanStep]] = []
        processed_count = 0

        while ready:
            current_layer_ids = ready
            layers.append([step_lookup[step_id] for step_id in current_layer_ids])
            processed_count += len(current_layer_ids)

            next_ready: list[str] = []
            for step_id in current_layer_ids:
                for child in graph[step_id]:
                    indegree[child] -= 1
                    if indegree[child] == 0:
                        next_ready.append(child)

            ready = sorted(next_ready, key=ordered_ids.index)

        if processed_count != len(plan.steps):
            raise ValueError("Plan has cyclic dependencies and cannot be executed")

        return layers


@dataclass
class AgentInvocationResult:
    success: bool
    output: Any = None
    error: str = ""


class AgentInvoker:
    def __init__(self, timeout_seconds: int = 30):
        self.timeout_seconds = timeout_seconds

    def invoke(self, agent: AgentDefinition, payload: dict[str, Any]) -> AgentInvocationResult:
        timeout = agent.timeout_seconds if agent.timeout_seconds else self.timeout_seconds
        try:
            response = requests.post(agent.endpoint, json=payload, timeout=timeout)
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

class UniversalOrchestrator:
    def __init__(self, registry_path: str = "agents.json", config_path: str = "config.yaml"):
        config_file = self._resolve_path(config_path)
        registry_file = self._resolve_path(registry_path)

        with config_file.open("r", encoding="utf-8") as handle:
            self.config = yaml.safe_load(handle) or {}

        self.registry = AgentRegistry.load(registry_file)

        llm_cfg = self.config.get("llm", {})
        self.model = ChatOllama(
            model=llm_cfg.get("model", "llama3.1:8b"),
            base_url=llm_cfg.get("base_url", "http://host.docker.internal:11434"),
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

        self.evaluation_enabled = bool(evaluation_cfg.get("enabled", False))
        self.evaluation_strict_mode = bool(evaluation_cfg.get("strict_mode", False))
        self.evaluation_service = EvaluationService(self.model) if self.evaluation_enabled else None

    def run(self, user_query: str) -> str:
        trace = self.run_with_trace(user_query)
        return trace["final_answer"]

    def run_with_trace(self, user_query: str) -> dict[str, Any]:
        """
        Run the orchestration process with tracing enabled.
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
        plan = self.planner.create_plan(guardrail_result.sanitized_query, self.registry)
        execution_layers = self.dag_creator.build_execution_layers(plan)

        # 3: Execute the plan layer by layer, invoking agents and collecting results
        step_results: dict[str, dict[str, Any]] = {}
        for layer_index, layer in enumerate(execution_layers, start=1):
            layer_steps = ", ".join(step.id for step in layer)
            print(f"[Hub] Executing layer {layer_index}: {layer_steps}")

            for step in layer:
                step_result = self._execute_step(step, guardrail_result.sanitized_query, step_results)
                step_results[step.id] = step_result

                if self.halt_on_step_failure and step_result["status"] == "failed":
                    plan_dict = self._plan_to_dict(plan)
                    final_answer = self._summarize_failure(step, step_result)
                    evaluation = self._evaluate_trace(
                        user_query=guardrail_result.sanitized_query,
                        plan_dict=plan_dict,
                        step_results=step_results,
                        final_answer=final_answer,
                    )
                    return {
                        "status": "failed",
                        "plan": plan_dict,
                        "steps": step_results,
                        "final_answer": final_answer,
                        "evaluation": evaluation,
                    }
        # 4: Synthesize final answer from execution trace
        plan_dict = self._plan_to_dict(plan)
        final_answer = self._synthesize_final_answer(guardrail_result.sanitized_query, plan, step_results)
        evaluation = self._evaluate_trace(
            user_query=guardrail_result.sanitized_query,
            plan_dict=plan_dict,
            step_results=step_results,
            final_answer=final_answer,
        )

        status = "completed"
        if (
            self.evaluation_strict_mode
            and evaluation is not None
            and not evaluation.get("goal_met", False)
        ):
            status = "failed_evaluation"

        return {
            "status": status,
            "plan": plan_dict,
            "steps": step_results,
            "final_answer": final_answer,
            "evaluation": evaluation,
        }

    def _evaluate_trace(
        self,
        user_query: str,
        plan_dict: dict[str, Any],
        step_results: dict[str, dict[str, Any]],
        final_answer: str,
    ) -> dict[str, Any] | None:
        """
        Evaluate a run trace and return a serialized evaluation payload.
        Returns None when evaluation is disabled.
        """
        if not self.evaluation_enabled or self.evaluation_service is None:
            return None

        result = self.evaluation_service.evaluate(
            user_query=user_query,
            plan_dict=plan_dict,
            step_results=step_results,
            final_answer=final_answer,
        )
        return {
            "goal_met": result.goal_met,
            "score": result.score,
            "summary": result.summary,
            "issues": result.issues,
            "retry_recommended": result.retry_recommended,
        }

    def _execute_step(
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
            invocation_result = self.agent_invoker.demoInvoke(agent, payload)
        else:
            invocation_result = self.agent_invoker.invoke(agent, payload)

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

    def _synthesize_final_answer(
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
            response = self.model.invoke(synthesis_prompt).content.strip()
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
    print(orchestrator.run("I think my bill is too high this month, can you check it?"))

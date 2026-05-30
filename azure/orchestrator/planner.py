"""
planner.py — Planning agent. Updated PlanStep to carry invocation_config
and health_check_config from the registry entry.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import memory
from json_utils import parse_json_object, strip_json_fences
from openai_client import get_chat_client, is_foundry_endpoint, model_name_for_role

log = logging.getLogger(__name__)

_MAX_PLANNER_RETRIES = 2
_HISTORY_TURNS = int(os.environ.get("ORCHESTRATOR_PLANNER_HISTORY_TURNS", "6"))


@dataclass
class PlanStep:
    step_id: int
    agent_name: str
    agent_url: str
    task: str
    depends_on: list[int] = field(default_factory=list)
    context_note: str = ""
    auth_config: dict[str, Any] = field(default_factory=dict)
    api_key_secret_name: str | None = None
    invocation_config: dict[str, Any] = field(default_factory=dict)
    health_check_config: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionPlan:
    plan_id: str
    user_intent: str
    steps: list[PlanStep]
    synthesis_instruction: str
    created_at: str

    def model_dump(self) -> dict:
        import dataclasses

        return dataclasses.asdict(self)


_SYSTEM = """You are a task-planning agent for a utility company support platform.
Given a user message and a list of available specialist agents, produce a
sequential execution plan as valid JSON.

Rules:
- Include ONLY agents genuinely needed to answer the user's request.
- steps must be ordered so every step's dependencies have lower step_id values.
- Each step's task must be a precise, self-contained instruction for that agent.
- synthesis_instruction tells the synthesizer how to combine outputs.
- Use conversation history when provided to resolve follow-up references.

Return ONLY a JSON object (no markdown, no prose):
{
  "user_intent": "<one-sentence summary>",
  "steps": [
    {
      "step_id": <int starting at 1>,
      "agent_name": "<exact name from the manifest>",
      "task": "<precise task for this agent>",
      "depends_on": [<step_id ints>],
      "context_note": "<optional extra context>"
    }
  ],
  "synthesis_instruction": "<how to combine all outputs>"
}"""


def _has_cycle(steps: list[PlanStep]) -> bool:
    graph = {s.step_id: [] for s in steps}
    in_degree = {s.step_id: 0 for s in steps}
    for s in steps:
        for dep in s.depends_on:
            if dep in graph:
                graph[dep].append(s.step_id)
                in_degree[s.step_id] += 1
    queue = deque(sid for sid, deg in in_degree.items() if deg == 0)
    visited = 0
    while queue:
        node = queue.popleft()
        visited += 1
        for nb in graph[node]:
            in_degree[nb] -= 1
            if in_degree[nb] == 0:
                queue.append(nb)
    return visited != len(steps)


def _topological_order(steps: list[PlanStep]) -> list[PlanStep]:
    graph = {s.step_id: [] for s in steps}
    in_degree = {s.step_id: 0 for s in steps}
    by_id = {s.step_id: s for s in steps}
    for s in steps:
        for dep in s.depends_on:
            if dep in graph:
                graph[dep].append(s.step_id)
                in_degree[s.step_id] += 1
    queue = deque(sid for sid, deg in in_degree.items() if deg == 0)
    result: list[PlanStep] = []
    while queue:
        sid = queue.popleft()
        result.append(by_id[sid])
        for nb in graph[sid]:
            in_degree[nb] -= 1
            if in_degree[nb] == 0:
                queue.append(nb)
    return result


def _build_manifest(agents: list[dict[str, Any]]) -> str:
    lines = []
    for a in agents:
        caps = "\n".join(f"    - {c['name']}: {c['description']}" for c in a.get("capabilities", []))
        lines.append(f"Agent: {a['name']}\n  Description: {a['description']}\n  Capabilities:\n{caps}")
    return "\n\n".join(lines)


def _format_history(history: list[dict[str, str]]) -> str:
    if not history:
        return ""
    lines = [f"{h['role']}: {h['content']}" for h in history]
    return "Prior conversation:\n" + "\n".join(lines) + "\n\n"


async def _call_planner_llm(user_prompt: str, strict_retry: bool) -> dict:
    client = await get_chat_client("planner")
    model = model_name_for_role("planner")
    system = _SYSTEM
    if strict_retry:
        system += "\n\nYour previous response was invalid JSON. Return ONLY a valid JSON object."

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
        "max_completion_tokens": 1500,
    }
    if not is_foundry_endpoint():
        kwargs["response_format"] = {"type": "json_object"}

    completion = await client.chat.completions.create(**kwargs)
    raw = completion.choices[0].message.content or "{}"
    return parse_json_object(strip_json_fences(raw))


async def build_plan(
    user_message: str,
    customer_id: str | None,
    session_id: str | None = None,
) -> ExecutionPlan:
    agents = await memory.get_active_agents()
    if not agents:
        raise RuntimeError("No active agents found in registry")

    agent_by_name = {a["name"]: a for a in agents}
    manifest = _build_manifest(agents)

    history_text = ""
    if session_id:
        try:
            history = await memory.get_conversation_history(session_id, limit=_HISTORY_TURNS)
            history_text = _format_history(history)
        except Exception as exc:
            log.warning("Could not load session history for planning: %s", exc)

    user_prompt = (
        f"{history_text}"
        f"User message: {user_message}\n"
        + (f"Customer ID: {customer_id}\n" if customer_id else "")
        + f"\nAvailable agents:\n{manifest}"
    )

    data: dict | None = None
    last_err: Exception | None = None
    for attempt in range(_MAX_PLANNER_RETRIES):
        try:
            data = await _call_planner_llm(user_prompt, strict_retry=attempt > 0)
            break
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            last_err = exc
            log.warning("Planner JSON parse failed (attempt %d): %s", attempt + 1, exc)

    if data is None:
        raise RuntimeError(f"Planner produced invalid JSON after {_MAX_PLANNER_RETRIES} attempts: {last_err}")

    steps: list[PlanStep] = []
    for s in data.get("steps", []):
        name = s["agent_name"]
        if name not in agent_by_name:
            log.warning("Planner referenced unknown agent '%s' — skipping", name)
            continue

        entry = agent_by_name[name]
        steps.append(
            PlanStep(
                step_id=s["step_id"],
                agent_name=name,
                agent_url=entry["endpoint_url"],
                task=s["task"],
                depends_on=s.get("depends_on", []),
                context_note=s.get("context_note", ""),
                auth_config=entry.get("auth_config") or {},
                api_key_secret_name=entry.get("api_key_secret_name"),
                invocation_config=entry.get("invocation_config") or {},
                health_check_config=entry.get("health_check_config") or {},
            )
        )

    if not steps:
        raise RuntimeError("Planner produced an empty execution plan")
    if _has_cycle(steps):
        raise RuntimeError("Planner produced a circular execution plan — rejecting")

    return ExecutionPlan(
        plan_id=str(uuid.uuid4()),
        user_intent=data.get("user_intent", user_message[:80]),
        steps=_topological_order(steps),
        synthesis_instruction=data.get(
            "synthesis_instruction",
            "Combine all agent outputs into one helpful response.",
        ),
        created_at=datetime.now(timezone.utc).isoformat(),
    )

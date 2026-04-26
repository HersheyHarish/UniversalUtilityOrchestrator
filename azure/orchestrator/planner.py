"""
planner.py — Planning agent. Updated PlanStep to carry invocation_config
and health_check_config from the registry entry.

The LLM never sees invocation_config, health_check_config, or auth_config.
These are enriched from the registry after the LLM produces its plan JSON.
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

from openai import AsyncOpenAI

import memory
from secret_provider import get_secret

log = logging.getLogger(__name__)

_OAI_ENDPOINT   = os.environ["AZURE_OPENAI_ENDPOINT"]
_OAI_DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
_OAI_API_VER    = "2024-10-21"
_OPENAI_SECRET  = os.environ.get("OPENAI_SECRET_NAME", "openai-api-key")


@dataclass
class PlanStep:
    step_id:             int
    agent_name:          str
    agent_url:           str
    task:                str
    depends_on:          list[int]       = field(default_factory=list)
    context_note:        str             = ""
    # Auth — from registry, never from LLM
    auth_config:         dict[str, Any]  = field(default_factory=dict)
    api_key_secret_name: str | None      = None  # legacy
    # Invocation — how to build the request body and extract the result
    invocation_config:   dict[str, Any]  = field(default_factory=dict)
    # Health check — carried for diagnostics / future per-step health assertions
    health_check_config: dict[str, Any]  = field(default_factory=dict)


@dataclass
class ExecutionPlan:
    plan_id:               str
    user_intent:           str
    steps:                 list[PlanStep]
    synthesis_instruction: str
    created_at:            str

    def model_dump(self) -> dict:
        import dataclasses
        return dataclasses.asdict(self)


async def _get_secret(name: str) -> str:
    return await get_secret(name, local_env_fallback="AZURE_OPENAI_API_KEY")


async def _openai_client() -> AsyncOpenAI:
    api_key = await _get_secret(_OPENAI_SECRET)
    return AsyncOpenAI(base_url=_OAI_ENDPOINT, api_key=api_key)


def _build_manifest(agents: list[dict[str, Any]]) -> str:
    """LLM-safe manifest — no auth, no invocation details, no endpoints."""
    lines = []
    for a in agents:
        caps = "\n".join(
            f"    - {c['name']}: {c['description']}"
            for c in a.get("capabilities", [])
        )
        lines.append(
            f"Agent: {a['name']}\n"
            f"  Description: {a['description']}\n"
            f"  Capabilities:\n{caps}"
        )
    return "\n\n".join(lines)


_SYSTEM = """You are a task-planning agent for a utility company support platform.
Given a user message and a list of available specialist agents, produce a
sequential execution plan as valid JSON.

Rules:
- Include ONLY agents genuinely needed to answer the user's request.
- steps must be ordered so every step's dependencies have lower step_id values.
- Each step's task must be a precise, self-contained instruction for that agent.
- synthesis_instruction tells the synthesizer how to combine outputs.

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
    graph     = {s.step_id: [] for s in steps}
    in_degree = {s.step_id: 0  for s in steps}
    for s in steps:
        for dep in s.depends_on:
            if dep in graph:
                graph[dep].append(s.step_id)
                in_degree[s.step_id] += 1
    queue   = deque(sid for sid, deg in in_degree.items() if deg == 0)
    visited = 0
    while queue:
        node = queue.popleft(); visited += 1
        for nb in graph[node]:
            in_degree[nb] -= 1
            if in_degree[nb] == 0: queue.append(nb)
    return visited != len(steps)


def _topological_order(steps: list[PlanStep]) -> list[PlanStep]:
    graph     = {s.step_id: [] for s in steps}
    in_degree = {s.step_id: 0  for s in steps}
    by_id     = {s.step_id: s  for s in steps}
    for s in steps:
        for dep in s.depends_on:
            if dep in graph:
                graph[dep].append(s.step_id)
                in_degree[s.step_id] += 1
    queue  = deque(sid for sid, deg in in_degree.items() if deg == 0)
    result: list[PlanStep] = []
    while queue:
        sid = queue.popleft(); result.append(by_id[sid])
        for nb in graph[sid]:
            in_degree[nb] -= 1
            if in_degree[nb] == 0: queue.append(nb)
    return result


async def build_plan(user_message: str, customer_id: str | None) -> ExecutionPlan:
    agents        = await memory.get_active_agents()
    if not agents:
        raise RuntimeError("No active agents found in registry")

    agent_by_name = {a["name"]: a for a in agents}
    manifest      = _build_manifest(agents)

    user_prompt = (
        f"User message: {user_message}\n"
        + (f"Customer ID: {customer_id}\n" if customer_id else "")
        + f"\nAvailable agents:\n{manifest}"
    )

    client     = await _openai_client()
    completion = await client.chat.completions.create(
        model=_OAI_DEPLOYMENT,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user",   "content": user_prompt},
        ],
        temperature=0.1,
        max_tokens=1500,
    )

    data = json.loads(completion.choices[0].message.content)

    steps: list[PlanStep] = []
    for s in data.get("steps", []):
        name = s["agent_name"]
        if name not in agent_by_name:
            log.warning("Planner referenced unknown agent '%s' — skipping", name)
            continue

        entry = agent_by_name[name]
        steps.append(PlanStep(
            step_id=s["step_id"],
            agent_name=name,
            agent_url=entry["endpoint_url"],
            task=s["task"],
            depends_on=s.get("depends_on", []),
            context_note=s.get("context_note", ""),
            # Server-side enrichment — never from LLM
            auth_config=entry.get("auth_config") or {},
            api_key_secret_name=entry.get("api_key_secret_name"),
            invocation_config=entry.get("invocation_config") or {},
            health_check_config=entry.get("health_check_config") or {},
        ))

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

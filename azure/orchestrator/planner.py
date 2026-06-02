from __future__ import annotations
import json
import logging
import os
import uuid
from collections import deque

from typing import Any

import memory
from models import PlanStep, ExecutionPlan
from openai import AsyncAzureOpenAI
from secret_provider import get_secret
from json_utils import parse_json_object, strip_json_fences
#from openai_client import get_chat_client, is_foundry_endpoint, model_name_for_role

log = logging.getLogger(__name__)

_MAX_PLANNER_RETRIES = 2
_HISTORY_TURNS = int(os.environ.get("ORCHESTRATOR_PLANNER_HISTORY_TURNS", "6"))

async def _get_secret(name: str) -> str:
    return await get_secret(name, local_env_fallback="AZURE_OPENAI_API_KEY")


async def _openai_client() -> AsyncAzureOpenAI:
    api_key = await _get_secret(_OPENAI_SECRET)
    return AsyncAzureOpenAI(
        azure_endpoint=_OAI_ENDPOINT,
        api_key=api_key,
        api_version=_OAI_API_VER,
    )

def _build_manifest(agents: list[dict[str, Any]]) -> str:
    lines = []
    for a in agents:
        caps = "\n".join(f"    - {c['name']}: {c['description']}" for c in a.get("capabilities", []))
        lines.append(f"Agent: {a['name']}\n  Description: {a['description']}\n  Capabilities:\n{caps}")
    return "\n\n".join(lines)


_REACTIVE_SYSTEM = """You are a task-planning agent for a utility company support platform.
Given a user message and a list of available specialist agents, produce a
sequential execution plan as valid JSON.

Rules:
- Include ONLY agents genuinely needed to answer the user's request, but you MAY use multiple agents if the request spans multiple domains (e.g. billing and usage).
- steps must be ordered so every step's dependencies have lower step_id values.
- Each step's task must be a precise, self-contained instruction for that agent. If date ranges or specific time windows are needed, always write them out as absolute calendar dates (e.g. "July 2019" or "2019-07-01 to 2019-07-31") rather than referring to other steps (e.g. "same window as step 1").
- If the user request or conversation history does not specify a date range, specific billing period, or timeframe, default to "July 2019" (or the appropriate range within July 2019) as the target timeframe inside each step's task description so that the specialist agents can successfully query the static demo dataset (which only covers 2019).
- synthesis_instruction tells the synthesizer how to combine outputs.
- Use conversation history when provided to resolve follow-up references.

Handling follow-ups and continuations:
- If the user message is a continuation or reference to the prior conversation
  (signals include: "proceed", "continue", "go ahead", "do it", "yes", "sure",
  "next steps", "the above", "previous message", "answer 1 and 2", short affirmations),
  AND the prior conversation transcript already contains the information needed
  to answer — return steps: [] and write the full answer plan into synthesis_instruction.
- The synthesizer has access to the full prior transcript, so synthesis_instruction
  can say things like: "The user said 'proceed'. Expand on the next steps already
  listed in the prior assistant message, specifically: [quote the steps here]."
- Only call agents for a follow-up if genuinely NEW data is required that is not
  already present in the transcript.

Return ONLY a JSON object (no markdown, no prose):
{
  "user_intent": "<one-sentence summary of what the user wants>",
  "steps": [
    {
      "step_id": <int starting at 1>,
      "agent_name": "<exact name from the manifest>",
      "task": "<precise task>",
      "depends_on": [<step_id ints>],
      "context_note": "<optional>"
    }
  ],
  "synthesis_instruction": "<how to combine all outputs, or how to answer from transcript if steps is empty>"
}"""


_PROACTIVE_SYSTEM = """You are a task-planning agent for a utility company proactive notification system.
A remote agent has detected an event that may affect a customer.
Your job is to plan which specialist agents should gather relevant data to ENRICH
this notification before it is delivered to the customer.

Rules:
- Include ONLY agents that can provide meaningful context for this specific event.
- Do not include agents unrelated to the event type.
- steps must be ordered so dependencies have lower step_id values.
- Each step's task must be specific: include the event type and customer ID.
- synthesis_instruction tells the synthesizer how to write a clear, concise,
  actionable notification for the customer (max 150 words, second person).

Return ONLY a JSON object (no markdown, no prose):
{
  "user_intent": "<one-sentence description of the enrichment goal>",
  "steps": [
    {
      "step_id": <int starting at 1>,
      "agent_name": "<exact name from the manifest>",
      "task": "<precise data-gathering task related to the event>",
      "depends_on": [<step_id ints>],
      "context_note": "<optional>"
    }
  ],
  "synthesis_instruction": "<how to write the enriched customer notification>"
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
    trigger_type: str = "reactive",
    chat_history: list[dict] | None = None,
    args: dict | None = None,
    transcript: list[dict[str, str]] | None = None,
) -> ExecutionPlan:
    agents = await memory.get_active_agents()
    if not agents:
        raise RuntimeError("No active agents found in registry")

    agent_by_name = {a["name"]: a for a in agents}
    manifest = _build_manifest(agents)

    system_prompt = (
        _PROACTIVE_SYSTEM if trigger_type == "proactive" else _REACTIVE_SYSTEM
    )

    user_prompt_parts = []

    if customer_id:
        user_prompt_parts.append(f"Customer ID: {customer_id}")

    history = chat_history

    if history:
        historical_messages = []
        for turn in history:
            if turn["role"] == "user":
                historical_messages.append({
                    "role": "user", "content": turn["content"],
                })
            else:
                historical_messages.append({
                    "role": "system", "content": turn["content"],
                })

        historical_str = '\n'.join(f'{m["role"]}: {m["content"]}' for m in historical_messages)
        user_prompt_parts.append(f"Historical Messages: {historical_str}")
    
    user_prompt_parts.append(f"Request: {message}")
    user_prompt_parts.append(f"Available agents:\n{manifest}")

    if trigger_type == "proactive":
        user_prompt_parts.append(f"Source Agent: {args.get('agent_name')}")
        user_prompt_parts.append(f"Event_type: {args.get('event_type')}")
        user_prompt_parts.append(f"Severity: {args.get('severity')}")

    user_prompt = "\n".join(user_prompt_parts)

    client = await _openai_client()
    completion = await client.chat.completions.create(
        model=_OAI_DEPLOYMENT,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        max_completion_tokens=1500,
    )

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
        # Follow-up turns may legitimately need zero agents; synthesizer uses transcript.
        return ExecutionPlan(
            plan_id=str(uuid.uuid4()),
            user_intent=data.get("user_intent", user_message[:80]),
            steps=[],
            synthesis_instruction=data.get(
                "synthesis_instruction",
                "Answer the customer using the prior conversation transcript and user message.",
            ),
            created_at=datetime.now(timezone.utc).isoformat(),
        )
    if _has_cycle(steps):
        raise RuntimeError("Planner produced a circular execution plan — rejecting")

    return ExecutionPlan(
        user_intent=data.get("user_intent", message[:80]),
        steps=_topological_order(steps),
        synthesis_instruction=data.get(
            "synthesis_instruction",
            "Combine all agent outputs into one helpful response.",
        )    
    )
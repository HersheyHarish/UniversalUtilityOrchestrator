"""
synthesizer.py — Synthesis agent with optional token streaming.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from openai_client import get_chat_client, model_name_for_role
from planner import ExecutionPlan

log = logging.getLogger(__name__)

_SYSTEM = """You are a response synthesis agent for a utility company support platform.
You receive outputs from multiple specialist agents and combine them into one
clear, empathetic, and actionable response for the customer.

Guidelines:
- Address the customer directly (use "you", not "the customer").
- Lead with what matters most to them.
- Present information in a logical flow — do not just concatenate agent outputs.
- Remove duplication and resolve contradictions across agent outputs.
- Keep tone warm and professional.
- End with 1-3 concrete next steps when appropriate. These next steps must be strictly grounded in the capabilities of the actual registry agents (e.g., billing_agent for invoices/policies, anomaly_detection_agent for usage spikes, solar_performance_credit_loss_agent for solar performance, bill_shock_forecast_agent for projections, program_enrollment_simulation_agent for Level Pay or TOU simulation, outage_detection_agent for power outages, payment_risk_hardship_agent for shutoff warnings/delinquency risk). Do NOT suggest arbitrary follow-ups or general support numbers if a specialist registry agent can handle it.
- Do NOT mention internal agent architecture or system details.
- Use GitHub-flavored markdown: ## and ### headings, - bullet lists, 1. numbered lists.
- For ASCII tables or box drawings use a single fenced code block with ```text on its own line.
- Do not mix GFM tables and ASCII box tables in the same answer.
- Do not invent citation brackets or "Sources:" lines unless the agent outputs included them.
- When the customer refers to numbered items from a prior assistant message (e.g. "answer 1 and 2"),
  use the prior conversation transcript to answer; do not ask them to repeat information already given.
"""


def _step_result_text(step_payload: object) -> str:
    if isinstance(step_payload, dict):
        return str(step_payload.get("result") or "")
    return str(getattr(step_payload, "result", "") or "")


def _agent_name_for_step(plan: ExecutionPlan, step_id: int) -> str:
    for s in plan.steps:
        if s.step_id == step_id:
            return s.agent_name
    return "Agent"


def _format_transcript(transcript: list[dict[str, str]] | None) -> str:
    if not transcript:
        return ""
    lines = []
    for turn in transcript:
        role = turn.get("role", "user")
        content = (turn.get("content") or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    if not lines:
        return ""
    return "Prior conversation (use for follow-ups):\n" + "\n\n".join(lines) + "\n\n"


async def synthesize(
    plan: ExecutionPlan,
    step_results: dict[int, dict],
    user_message: str,
    *,
    transcript: list[dict[str, str]] | None = None,
    on_token: Callable[[str], Awaitable[None]] | None = None,
    repair_hint: str | None = None,
) -> str:
    transcript_block = _format_transcript(transcript)

    if not step_results and not transcript_block:
        return (
            "I was unable to retrieve the information needed to answer your question "
            "right now. Please try again in a moment, or contact our support line at "
            "1-800-UTILITY."
        )

    agent_sections = [
        f"[{_agent_name_for_step(plan, step_id)}]\n{_step_result_text(payload)}"
        for step_id, payload in sorted(step_results.items())
    ]

    synthesis_prompt = (
        f"{transcript_block}"
        f"Original customer question: {user_message}\n\n"
        f"Synthesis instruction: {plan.synthesis_instruction}\n\n"
    )
    if agent_sections:
        synthesis_prompt += f"Agent outputs:\n" + "\n\n".join(agent_sections)
    else:
        synthesis_prompt += (
            "No new agent outputs this turn. Answer from the prior conversation and "
            "synthesis instruction only.\n"
        )

    if repair_hint:
        synthesis_prompt += (
            f"\n\nIMPORTANT: The previous draft had quality issues: {repair_hint}. "
            "Fix these while staying faithful to agent outputs and transcript only."
        )

    client = await get_chat_client("synthesizer")
    model = model_name_for_role("default")

    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": synthesis_prompt},
    ]

    if on_token:
        stream = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.5,
            max_completion_tokens=2500,
            stream=True,
        )
        parts: list[str] = []
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                parts.append(delta)
                await on_token(delta)
        content = "".join(parts)
    else:
        completion = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.5,
            max_completion_tokens=2500,
        )
        content = completion.choices[0].message.content

    return content if isinstance(content, str) and content.strip() else (
        "I could not generate a response. Please try again or contact support."
    )

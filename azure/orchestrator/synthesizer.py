"""
synthesizer.py — Synthesis agent.

Combines all step outputs into one final user-facing response via GPT-4o.

Fix: same api_version pin as planner.py (2024-10-21 GA).
     Same shared-credential pattern as memory.py.
"""

from __future__ import annotations

import logging
import os

from openai import AsyncAzureOpenAI
from planner import ExecutionPlan
from secret_provider import get_secret

log = logging.getLogger(__name__)

_OAI_ENDPOINT_RAW = os.environ["AZURE_OPENAI_ENDPOINT"]
_OAI_ENDPOINT = _OAI_ENDPOINT_RAW.split("/openai")[0].split("/api/")[0].rstrip("/")
_OAI_DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
_OAI_API_VER = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21")
_OPENAI_SECRET = os.environ.get("OPENAI_SECRET_NAME", "openai-api-key")


async def _get_secret(name: str) -> str:
    return await get_secret(name, local_env_fallback="AZURE_OPENAI_API_KEY")


_SYSTEM = """You are a response synthesis agent for a utility company support platform.
You receive outputs from multiple specialist agents and combine them into one
clear, empathetic, and actionable response for the customer.

Guidelines:
- Address the customer directly (use "you", not "the customer").
- Lead with what matters most to them.
- Present information in a logical flow — do not just concatenate agent outputs.
- Remove duplication and resolve contradictions across agent outputs.
- Keep tone warm and professional.
- End with 1-3 concrete next steps the customer can take.
- Do NOT mention internal agent architecture or system details.
"""


def _step_result_text(step_payload: object) -> str:
    """Executor returns dicts with a \"result\" key, not AgentResponse models."""
    if isinstance(step_payload, dict):
        return str(step_payload.get("result") or "")
    return str(getattr(step_payload, "result", "") or "")


def _agent_name_for_step(plan: ExecutionPlan, step_id: int) -> str:
    for s in plan.steps:
        if s.step_id == step_id:
            return s.agent_name
    return "Agent"


async def synthesize(
    plan: ExecutionPlan,
    step_results: dict[int, dict],
    user_message: str,
) -> str:
    if not step_results:
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
        f"Original customer question: {user_message}\n\n"
        f"Synthesis instruction: {plan.synthesis_instruction}\n\n"
        f"Agent outputs:\n" + "\n\n".join(agent_sections)
    )

    api_key = await _get_secret(_OPENAI_SECRET)
    client = AsyncAzureOpenAI(
        azure_endpoint=_OAI_ENDPOINT,
        api_key=api_key,
        api_version=_OAI_API_VER,
    )

    completion = await client.chat.completions.create(
        model=_OAI_DEPLOYMENT,
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": synthesis_prompt},
        ],
        temperature=0.5,
        max_completion_tokens=1000,
    )

    content = completion.choices[0].message.content
    return content if isinstance(content, str) and content.strip() else (
        "I could not generate a response. Please try again or contact support."
    )

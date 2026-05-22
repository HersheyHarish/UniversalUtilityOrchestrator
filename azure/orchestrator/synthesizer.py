from __future__ import annotations
import logging
import os

from openai import AsyncAzureOpenAI
from planner import ExecutionPlan
from secret_provider import get_secret

from models import ExecutionPlan, AgentResponse

log = logging.getLogger(__name__)

_OAI_ENDPOINT_RAW = os.environ["AZURE_OPENAI_ENDPOINT"]
_OAI_ENDPOINT = _OAI_ENDPOINT_RAW.split("/openai")[0].split("/api/")[0].rstrip("/")
_OAI_DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
_OAI_API_VER = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21")
_OPENAI_SECRET = os.environ.get("OPENAI_SECRET_NAME", "openai-api-key")


async def _get_secret(name: str) -> str:
    return await get_secret(name, local_env_fallback="AZURE_OPENAI_API_KEY")


_REACTIVE_SYSTEM = """You are a response synthesis agent for a utility company support platform.
You receive outputs from multiple specialist agents and combine them into one
clear, empathetic, and actionable response for the customer.

Guidelines:
- Address the customer directly.
- Write in second person ("your account", "you can").
- Lead with what matters most to them.
- Present information in a logical flow — do not just concatenate agent outputs.
- Integrate all relevant agent findings naturally.
- Be concise but complete.
- Keep tone warm and professional.
- End with 1-3 concrete next steps the customer can take.
- Do NOT mention agent names or internal agent architecture or system details.
"""

_PROACTIVE_SYSTEM = """You are a utility company notification writer.
Combine agent-gathered data into a clear, actionable proactive notification.

Rules:
- Lead with the key fact (what happened or requires attention).
- State the impact on the customer in one sentence.
- Provide 1-2 actionable next steps.
- Match tone to severity: high = urgent but calm, medium = informative, low = friendly.
- Keep under 150 words.
- Write in second person ("your account", "you can").
- Do NOT mention agent names or internal systems.
- Do NOT add generic disclaimers."""

async def synthesize(
    plan:         ExecutionPlan,
    step_results: dict[int, AgentResponse],
    message: str,
    trigger_type: str = "reactive",
    chat_history: list[dict] | None = None,
    args: dict | None = None
) -> str:
    if not step_results:
        return (
            "I was unable to retrieve the information needed to answer your question "
            "right now. Please try again in a moment, or contact our support line at "
            "1-800-UTILITY."
        )

    agent_sections = [
        f"{plan.steps[i].agent_name if i < len(plan.steps) else 'Agent'}: {r['result']}"
        for i, (_, r) in enumerate(sorted(step_results.items()))
    ]

    if trigger_type == "proactive":
        system_prompt = _PROACTIVE_SYSTEM
        user_prompt = "\n".join(filter(None, [
            f"Event type: {args.get('event_type')}"    if args.get('event_type') else None,
            f"Severity: {args.get('severity')}"        if args.get('severity')   else None,
            f"Original notification: {args.get('original_message') or args.get('user_message')}",
            f"\nAgent-gathered context:\n{agent_sections}",
            f"\nSynthesis guidance: {plan.synthesis_instruction}",
            "\nWrite the enriched customer notification now.",
        ]))
    else:
        if chat_history:
            history_sections = [
                f"{m['role'].capitalize()}: {m['content']}"
                for m in chat_history
            ]
        system_prompt = _REACTIVE_SYSTEM
        user_prompt = "\n".join(filter(None, [
            f"Original customer question: {message}",
            f"\nAgent outputs:\n{agent_sections}",
            f"\nHistorical Messages: {chr(10).join(history_sections)}" if chat_history else None,
            f"\nSynthesis instruction: {plan.synthesis_instruction}",
            "\nWrite the final response now.",
        ]))

    api_key = await _get_secret(_OPENAI_SECRET)
    client = AsyncAzureOpenAI(
        azure_endpoint=_OAI_ENDPOINT,
        api_key=api_key,
        api_version=_OAI_API_VER,
    )

    completion = await client.chat.completions.create(
        model=_OAI_DEPLOYMENT,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
        max_completion_tokens=1000,
    )

    content = completion.choices[0].message.content
    return content if isinstance(content, str) and content.strip() else (
        "I could not generate a response. Please try again or contact support."
    )

from __future__ import annotations
import logging
import os

from openai import AsyncOpenAI
from azure.keyvault.secrets.aio import SecretClient
from azure.identity.aio import DefaultAzureCredential

from models import ExecutionPlan, AgentResponse

log = logging.getLogger(__name__)

_OAI_ENDPOINT   = os.environ["AZURE_OPENAI_ENDPOINT"]
_OAI_DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
_KV_URL         = os.environ["KEY_VAULT_URL"]
_OPENAI_SECRET  = os.environ.get("OPENAI_SECRET_NAME", "openai-key")

_KV_CREDENTIAL  = DefaultAzureCredential()
_secret_cache:  dict[str, str] = {}


async def _get_secret(name: str) -> str:
    if name not in _secret_cache:
        async with SecretClient(_KV_URL, _KV_CREDENTIAL) as kv:
            _secret_cache[name] = (await kv.get_secret(name)).value
    return _secret_cache[name]


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
        system_prompt = _REACTIVE_SYSTEM
        user_prompt = "\n".join(filter(None, [
            f"Original customer question: {message}",
            f"\nAgent outputs:\n{agent_sections}",
            f"\nSynthesis instruction: {plan.synthesis_instruction}",
            "\nWrite the final response now.",
        ]))

    api_key = await _get_secret(_OPENAI_SECRET)
    client  = AsyncOpenAI(
        base_url=_OAI_ENDPOINT,
        api_key=api_key
    )

    completion = await client.chat.completions.create(
        model=_OAI_DEPLOYMENT,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        temperature=0.3,
        max_tokens=1000,
    )

    return completion.choices[0].message.content
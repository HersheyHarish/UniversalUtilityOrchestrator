"""Input guardrails for orchestrator chat ingress."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


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
        blocked = cfg.get("blocked_patterns", self.DEFAULT_BLOCKED_PATTERNS)
        self.blocked_regexes = [re.compile(p) for p in blocked]

    def _sanitize(self, text: str) -> str:
        return re.sub(r"\s+", " ", (text or "").strip())

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
                reason="Input is too long. Please shorten your message.",
            )

        for pattern in self.blocked_regexes:
            if pattern.search(sanitized):
                return GuardrailResult(
                    allowed=False,
                    sanitized_query=sanitized,
                    reason="Your message was blocked by safety policies.",
                    risk_flags=["blocked_pattern"],
                )

        fence_count = sanitized.count("```")
        if fence_count >= 6:
            return GuardrailResult(
                allowed=False,
                sanitized_query=sanitized,
                reason="Too many code blocks in one message.",
                risk_flags=["excessive_fences"],
            )

        return GuardrailResult(allowed=True, sanitized_query=sanitized)


_default_guard: InputGuardrails | None = None


def get_guardrails() -> InputGuardrails:
    global _default_guard
    if _default_guard is None:
        _default_guard = InputGuardrails()
    return _default_guard


_SCENARIO_GUARD_SYSTEM = """You are a classification assistant for a utility company support platform.
Your task is to determine whether the user's message is related to the utility customer support scenario.
The utility customer support scenario covers:
- Customer accounts, billing, invoices, billing cycles, charges, payment history, and payment policies.
- Electricity, gas, water, or general energy utility services.
- Power outages, local area grid issues, restoration times, and outage history.
- Household energy consumption, electricity usage patterns, spikes, anomalies, and weather/temperature context impacting usage.
- Solar panel performance, solar generation, solar credits, true-ups, and solar underperformance/credit loss.
- Bill forecasting, mid-cycle projections, billing shock warnings, and tariff details.
- Relief, payment, or enrollment support programs (e.g. Level Pay, Time-of-Use, low-income assistance, payment plans, due-date adjustments).
- Delinquency risk, shutoff warnings, payment difficulties, and financial hardships.
- Basic, polite conversational text that is part of a utility support interaction (e.g., greetings like "hello", "hi", "thank you", "thanks", "bye", "are you there", or positive/negative feedback about the utility service).

If the user's message is clearly unrelated to this utility scenario (for example, asking about skincare routines, programming code, general recipes, medical advice, generic history, writing stories, general trivia/questions not linked to their utility account or utilities), classify it as UNRELATED.

Respond with exactly "RELATED" or "UNRELATED" on a single line. Do not include any other text or explanation.
"""


async def is_query_related_to_scenario(user_query: str) -> bool:
    import openai_client

    sanitized = user_query.strip()
    if not sanitized:
        return True

    try:
        client = await openai_client.get_chat_client("input_guard")
        model = openai_client.model_name_for_role("default")

        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SCENARIO_GUARD_SYSTEM},
                {"role": "user", "content": sanitized},
            ],
            temperature=0.0,
            max_completion_tokens=5,
        )
        content = (response.choices[0].message.content or "").strip().upper()
        return "UNRELATED" not in content
    except Exception as e:
        import logging

        logging.getLogger(__name__).warning("Scenario check failed (defaulting to True): %s", e)
        return True


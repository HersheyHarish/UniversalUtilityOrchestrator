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

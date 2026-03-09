from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Class that represents the result of guardrail validation, including whether the input is allowed, a sanitized version of the query, and any reasons or risk flags if it's blocked.
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
        """
        Validate user input against guardrails.
         - Check for minimum and maximum length.
         - Check against blocked regex patterns.
         - Flag potential risks like multiple code blocks or high link density.
         """
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

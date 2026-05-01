from __future__ import annotations

import re
from typing import Any


class PIIMasker:
    """
    Lightweight regex-driven masker for common PII fields.
    The output is intended for logs and LLM-bound prompts.
    """

    DEFAULT_PATTERNS = [
        # Email addresses
        (r"(?i)\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", "[MASKED_EMAIL]"),
        # US phone numbers (very permissive)
        (r"\b(?:\+?1[\s\-\.]?)?(?:\(?\d{3}\)?[\s\-\.]?)\d{3}[\s\-\.]?\d{4}\b", "[MASKED_PHONE]"),
        # SSN
        (r"\b\d{3}-\d{2}-\d{4}\b", "[MASKED_SSN]"),
        # Long account-like numeric identifiers
        (r"\b\d{10,16}\b", "[MASKED_ACCOUNT]"),
    ]

    def __init__(self, patterns: list[dict[str, str]] | None = None):
        configured_patterns = patterns or []
        merged_patterns = self._normalize_patterns(configured_patterns)
        self._compiled_patterns = [
            (re.compile(rule["pattern"]), rule["replacement"]) for rule in merged_patterns
        ]

    def mask_text(self, value: str) -> str:
        masked = value
        for pattern, replacement in self._compiled_patterns:
            masked = pattern.sub(replacement, masked)
        return masked

    def mask_any(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.mask_text(value)
        if isinstance(value, dict):
            return {k: self.mask_any(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.mask_any(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self.mask_any(item) for item in value)
        return value

    @classmethod
    def _normalize_patterns(cls, configured_patterns: list[dict[str, str]]) -> list[dict[str, str]]:
        if not configured_patterns:
            return [
                {"pattern": pattern, "replacement": replacement}
                for pattern, replacement in cls.DEFAULT_PATTERNS
            ]

        normalized: list[dict[str, str]] = []
        for item in configured_patterns:
            pattern = item.get("pattern")
            replacement = item.get("replacement", "[MASKED_PII]")
            if pattern:
                normalized.append({"pattern": pattern, "replacement": replacement})

        if not normalized:
            return [
                {"pattern": pattern, "replacement": replacement}
                for pattern, replacement in cls.DEFAULT_PATTERNS
            ]
        return normalized

"""JSON parsing helpers for LLM outputs."""

from __future__ import annotations

import json
import re

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def strip_json_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = _FENCE_RE.sub("", cleaned).strip()
    return cleaned


def parse_json_object(text: str) -> dict:
    """Parse JSON object from LLM output, with fence stripping."""
    return json.loads(strip_json_fences(text))

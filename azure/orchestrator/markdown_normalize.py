"""Normalize assistant markdown before persistence and UI segmentation."""

from __future__ import annotations

import re

_CITATION_RE = re.compile(r"【[^】]*】")
_EXCESS_BLANK_LINES = re.compile(r"\n{3,}")


def normalize_markdown(text: str) -> str:
    if not text:
        return text

    cleaned = _CITATION_RE.sub("", text)
    cleaned = _EXCESS_BLANK_LINES.sub("\n\n", cleaned)

    # Collapse huge blank gaps inside fenced blocks
    def _tighten_fence(match: re.Match[str]) -> str:
        lang = match.group(1) or ""
        body = match.group(2) or ""
        body = re.sub(r"\n{3,}", "\n\n", body).strip("\n")
        return f"```{lang}\n{body}\n```"

    cleaned = re.sub(
        r"```([^\n`]*)\n?([\s\S]*?)```",
        _tighten_fence,
        cleaned,
    )

    return cleaned.strip()

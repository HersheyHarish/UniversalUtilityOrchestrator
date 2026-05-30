"""
Segment assistant text for UI rendering (prose vs code vs ASCII diagrams).
"""

from __future__ import annotations

import re
from typing import Any, Literal

SegmentType = Literal["prose", "code", "ascii"]

_BOX_DRAWING_RE = re.compile(r"[\u2500-\u257F\u2550-\u256C]")
_ASCII_DENSE_RE = re.compile(r"^[\s|+\-=_#*./\\]{8,}$", re.MULTILINE)
_FENCE_RE = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)


def _is_ascii_block(text: str) -> bool:
    if _BOX_DRAWING_RE.search(text):
        return True
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        return False
    ascii_lines = sum(1 for ln in lines if _ASCII_DENSE_RE.match(ln) or ("|" in ln and "+" in ln))
    return ascii_lines >= max(2, len(lines) // 2)


def segment_response(text: str) -> list[dict[str, Any]]:
    """Split response into renderable segments."""
    if not text:
        return [{"type": "prose", "content": ""}]

    segments: list[dict[str, Any]] = []
    last_end = 0

    for match in _FENCE_RE.finditer(text):
        if match.start() > last_end:
            segments.extend(_segment_prose(text[last_end:match.start()]))
        lang = (match.group(1) or "").lower()
        body = match.group(2)
        seg_type: SegmentType = "ascii" if lang in {"", "ascii", "text"} and _is_ascii_block(body) else "code"
        segments.append({"type": seg_type, "content": body.rstrip("\n")})
        last_end = match.end()

    if last_end < len(text):
        segments.extend(_segment_prose(text[last_end:]))

    return segments or [{"type": "prose", "content": text}]


def _segment_prose(prose: str) -> list[dict[str, Any]]:
    if not prose.strip():
        return []
    parts: list[dict[str, Any]] = []
    blocks = re.split(r"\n\n+", prose)
    for block in blocks:
        if _is_ascii_block(block):
            parts.append({"type": "ascii", "content": block.strip("\n")})
        else:
            parts.append({"type": "prose", "content": block})
    return parts


def format_chat_response(text: str) -> dict[str, Any]:
    return {
        "response": text,
        "content_segments": segment_response(text),
    }

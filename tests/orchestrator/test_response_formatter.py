import sys
from pathlib import Path

ORCH = Path(__file__).resolve().parents[2] / "azure" / "orchestrator"
sys.path.insert(0, str(ORCH))

from response_formatter import segment_response  # noqa: E402


def test_fenced_ascii_block():
    text = "Here is a diagram:\n```\n+-----+\n| A   |\n+-----+\n```\nDone."
    segments = segment_response(text)
    types = [s["type"] for s in segments]
    assert "ascii" in types or "code" in types


def test_plain_prose():
    segments = segment_response("Hello customer.")
    assert segments[0]["type"] == "prose"

def test_fence_without_lang_newline():
    text = "Title\n```text\n| A | B |\n|---|---|\n```\n"
    segments = segment_response(text)
    types = [s["type"] for s in segments]
    assert "code" in types or "ascii" in types
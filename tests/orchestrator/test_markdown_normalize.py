import sys
from pathlib import Path

ORCH = Path(__file__).resolve().parents[2] / "azure" / "orchestrator"
sys.path.insert(0, str(ORCH))

from markdown_normalize import normalize_markdown  # noqa: E402


def test_strips_citation_brackets():
    text = "Hello 【surcharge_policy_2】 world"
    assert "【" not in normalize_markdown(text)


def test_tightens_fenced_block():
    text = "See:\n```text\n\n+---+\n\n| A |\n\n+---+\n\n```\nDone."
    out = normalize_markdown(text)
    assert "```text" in out
    assert "【" not in out

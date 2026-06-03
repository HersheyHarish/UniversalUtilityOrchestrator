import sys
from pathlib import Path

ORCH = Path(__file__).resolve().parents[2] / "azure" / "orchestrator"
sys.path.insert(0, str(ORCH))

from synthesizer import _format_transcript  # noqa: E402


def test_format_transcript_includes_roles():
    block = _format_transcript(
        [
            {"role": "user", "content": "break down peak vs non-peak"},
            {"role": "assistant", "content": "Next steps: 1. split taxes 2. baseline"},
        ]
    )
    assert "Prior conversation" in block
    assert "user:" in block
    assert "assistant:" in block
    assert "Next steps" in block

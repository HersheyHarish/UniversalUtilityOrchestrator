import sys
from pathlib import Path

ORCH = Path(__file__).resolve().parents[2] / "azure" / "orchestrator"
sys.path.insert(0, str(ORCH))

from json_utils import parse_json_object, strip_json_fences  # noqa: E402


def test_strip_fences():
    raw = '```json\n{"a": 1}\n```'
    assert strip_json_fences(raw) == '{"a": 1}'


def test_parse_json_object():
    assert parse_json_object('{"steps": []}') == {"steps": []}

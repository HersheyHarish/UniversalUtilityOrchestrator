import sys
from pathlib import Path

ORCH = Path(__file__).resolve().parents[2] / "azure" / "orchestrator"
sys.path.insert(0, str(ORCH))

from execution_graph import build_execution_layers  # noqa: E402


class Step:
    def __init__(self, step_id, depends_on=None):
        self.step_id = step_id
        self.depends_on = depends_on or []


def test_single_layer_independent_steps():
    steps = [Step(1), Step(2), Step(3)]
    layers = build_execution_layers(steps)
    assert len(layers) == 1
    assert len(layers[0]) == 3


def test_two_layers_with_dependency():
    steps = [Step(1), Step(2, depends_on=[1]), Step(3, depends_on=[1])]
    layers = build_execution_layers(steps)
    assert len(layers) == 2
    assert len(layers[0]) == 1
    assert len(layers[1]) == 2

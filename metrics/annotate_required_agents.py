"""Augment tasks.json with required vs optional agent splits.

Rationale: not all agents in `expected_agents` are equally critical to
answering the query. A billing question NEEDS billing_agent; weather and
anomaly add context but their absence does not make the answer wrong.

We define `required_agents` (the minimum set without which the question is
unanswerable) and `optional_agents` (helpful context that improves the answer).
Weighted F1 then assigns weight 1.0 to required and 0.3 to optional.

Heuristic for splitting (deterministic, applied per task):
  - Single-agent tasks: that agent is required.
  - Multi-hop tasks: the "primary" agent (matching the task's category) is
    required. The others are optional.
  - Special cases for multi-step dependency tasks (customer_lookup before
    per-customer agents): customer_lookup is optional context unless the
    task explicitly asks for account profile information.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TASKS = ROOT / "tasks.json"

# Map task_id -> (required, optional). Manual annotation for multi-hop tasks
# where the split isn't trivial.
SPLITS: dict[str, tuple[list[str], list[str]]] = {
    # Multi-hop tasks: required agents are those whose absence makes the
    # response materially incomplete; optional are context-adders.
    "multihop_01": (
        ["billing_agent"],
        ["anomaly_detection_agent",
         "weather_context_agent", "outage_detection_agent"],
    ),
    "multihop_02": (
        ["outage_detection_agent", "billing_agent"],
        [],
    ),
    "multihop_03": (
        ["anomaly_detection_agent"],
        ["weather_context_agent"],
    ),
    "multihop_04": (
        ["bill_shock_forecast_agent", "payment_risk_hardship_agent"],
        [],
    ),
    "multihop_05": (
        ["billing_agent", "customer_lookup_agent"],
        [],
    ),
    "multihop_06": (
        ["outage_detection_agent", "payment_risk_hardship_agent"],
        ["bill_shock_forecast_agent"],
    ),
    "multihop_07": (
        ["solar_performance_credit_loss_agent", "billing_agent"],
        ["weather_context_agent"],
    ),
    "multihop_08": (
        ["anomaly_detection_agent", "program_enrollment_simulation_agent", "customer_lookup_agent"],
        [],
    ),
    "multihop_09": (
        ["bill_shock_forecast_agent", "payment_risk_hardship_agent"],
        ["program_enrollment_simulation_agent"],
    ),
    "multihop_10": (
        ["billing_agent"],
        ["anomaly_detection_agent", "weather_context_agent",
         "outage_detection_agent"],
    ),
}


def main() -> int:
    data = json.loads(TASKS.read_text())
    for t in data["tasks"]:
        tid = t["task_id"]
        expected = list(t.get("expected_agents", []))
        if tid in SPLITS:
            req, opt = SPLITS[tid]
            # Sanity: every entry must be in expected_agents.
            missing = set(req + opt) - set(expected)
            assert not missing, f"{tid}: annotated agents {missing} not in expected_agents"
        elif len(expected) == 1:
            req, opt = expected, []
        else:
            # Default for unhandled multi-agent tasks: first = required, rest optional.
            req, opt = [expected[0]], expected[1:]
        t["required_agents"] = req
        t["optional_agents"] = opt

    TASKS.write_text(json.dumps(data, indent=2) + "\n")
    print(f"annotated {len(data['tasks'])} tasks with required/optional splits")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

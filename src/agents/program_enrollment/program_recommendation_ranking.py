"""Pick the best program from simulated results."""

from __future__ import annotations

from typing import Any, Optional


def pick_recommendation(programs: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Return the program with the largest positive monthly impact, or None."""
    def score(p: dict[str, Any]) -> float:
        if not p.get("eligible"):
            return float("-inf")
        if p["name"] == "level_pay":
            return float(p.get("this_cycle_delta_usd", 0.0))
        if p["name"] == "installment_plan":
            return float("-inf")  # cash-flow only, no savings — always shown as an option, never auto-recommended
        if p["name"] == "low_income_assistance":
            return float("-inf")  # requires eligibility verification — never auto-recommend
        if p["name"] == "time_of_use":
            return float(p.get("monthly_savings_usd", 0.0))
        return 0.0

    candidates = [p for p in programs if p.get("eligible")]
    if not candidates:
        return None
    best = max(candidates, key=score)
    if score(best) <= 0:
        return None
    return best

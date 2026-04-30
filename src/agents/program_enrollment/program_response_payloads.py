"""Assemble the final response from resolved inputs and per-program simulators."""

from __future__ import annotations

from typing import Any

from .program_data_sources import cached_meter_data
from .program_recommendation_ranking import pick_recommendation
from .program_simulation_models import ProgramSimRequest
from .program_impact_simulations import (
    simulate_installment_plan,
    simulate_level_pay,
    simulate_low_income,
    simulate_time_of_use,
)


def build_response(resolved: dict[str, Any]) -> dict[str, Any]:
    customer_id = resolved["customer_id"]
    account = resolved["account"]
    invoices = resolved["invoices"]
    current_bill = resolved["current_bill_usd"]
    current_kwh = resolved["current_kwh"]
    cycle_start = resolved["cycle_start"]
    cycle_end = resolved["cycle_end"]
    params: ProgramSimRequest = resolved["params"]
    requested = resolved["programs"]

    results: list[dict[str, Any]] = []

    if "level_pay" in requested:
        results.append(simulate_level_pay(invoices, params.lookback_months, current_bill))

    if "installment_plan" in requested:
        results.append(simulate_installment_plan(current_bill, params.installment_count))

    if "low_income_assistance" in requested:
        results.append(
            simulate_low_income(
                current_bill,
                account["plan"],
                current_kwh,
                params.low_income_discount_pct,
                params.assume_eligible,
            )
        )

    if "time_of_use" in requested:
        meter_df = cached_meter_data()
        results.append(
            simulate_time_of_use(
                meter_df,
                int(account["meter_dataid"]),
                account["plan"],
                cycle_start,
                cycle_end,
                params.tou_peak_rate,
                params.tou_off_peak_rate,
            )
        )

    recommendation = pick_recommendation(results)
    rec_name = recommendation["name"] if recommendation else None

    # Installment plan note — always appended as a cash-flow option, never auto-recommended.
    installment = next((p for p in results if p["name"] == "installment_plan" and p.get("eligible")), None)
    installment_note = (
        f" If you need to spread the payment, an installment plan of "
        f"${installment['per_installment_usd']:.2f}/month over {installment['installments']} months is available."
    ) if installment else ""

    # Low income note — always appended when simulated, never auto-recommended.
    low_income = next((p for p in results if p["name"] == "low_income_assistance" and p.get("eligible")), None)
    low_income_note = (
        f" Additionally, low income assistance could save ~${low_income['monthly_savings_usd']:.0f}/month "
        f"(~${low_income['annualized_savings_usd']:.0f}/year) if eligible — "
        "customer should call to verify qualification."
    ) if low_income else ""

    if recommendation:
        rec_summary = recommendation.get("summary", "")
        summary = (
            f"For customer {customer_id} (current cycle bill ~${current_bill:.0f}), "
            f"the top recommendation is `{rec_name}`. {rec_summary}{installment_note}{low_income_note}"
        )
    else:
        summary = (
            f"For customer {customer_id} (current cycle bill ~${current_bill:.0f}), "
            f"no enrollment program produces material monthly savings.{installment_note}{low_income_note}"
        )

    return {
        "agent": "program_enrollment_simulation_agent",
        "status": "completed",
        "customer_id": customer_id,
        "plan_name": account["plan"]["name"],
        "context": {
            "current_bill_usd": round(current_bill, 2),
            "current_kwh": round(current_kwh, 2) if current_kwh else None,
            "bill_source": resolved["bill_source"],
            "cycle_start": cycle_start.isoformat() if cycle_start is not None else None,
            "cycle_end": cycle_end.isoformat() if cycle_end is not None else None,
        },
        "programs": results,
        "recommendation": rec_name,
        "summary": summary,
    }

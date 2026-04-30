"""Per-program simulators: level pay, installments, low-income, time-of-use."""

from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd

from .program_data_sources import INTERVAL_HOURS


def simulate_level_pay(
    invoices: list[dict[str, Any]],
    lookback_months: int,
    current_bill: float,
) -> dict[str, Any]:
    recent = invoices[-lookback_months:] if invoices else []
    totals = [float(inv["total"]) for inv in recent if "total" in inv]
    if len(totals) < 2:
        return {
            "name": "level_pay",
            "eligible": False,
            "reason": f"Need ≥2 months of billing history (have {len(totals)}).",
        }
    avg = float(np.mean(totals))
    swing = float(max(totals) - min(totals))
    delta = current_bill - avg
    direction = "reduce" if delta > 0 else "increase"
    return {
        "name": "level_pay",
        "eligible": True,
        "level_pay_amount_usd": round(avg, 2),
        "this_cycle_delta_usd": round(delta, 2),
        "max_swing_avoided_usd": round(swing, 2),
        "history_window_months": len(totals),
        "mechanism": f"Charges the {len(totals)}-month average each month; trues up annually.",
        "summary": (
            f"Level pay would charge ~${avg:.0f}/month, which would {direction} this cycle "
            f"by ${abs(delta):.0f}. Smooths a max ${swing:.0f} swing seen over the lookback."
        ),
    }


def simulate_installment_plan(current_bill: float, installment_count: int) -> dict[str, Any]:
    if current_bill <= 0:
        return {"name": "installment_plan", "eligible": False, "reason": "No balance to split."}
    per = current_bill / installment_count
    return {
        "name": "installment_plan",
        "eligible": True,
        "installments": installment_count,
        "per_installment_usd": round(per, 2),
        "total_repayment_usd": round(current_bill, 2),
        "monthly_savings_usd": 0.0,
        "mechanism": "Splits the cycle balance into equal payments. Cash-flow only — no net savings.",
        "summary": f"Pay ${per:.2f} per installment over {installment_count} months.",
    }


def simulate_low_income(
    current_bill: float,
    plan: dict[str, Any],
    current_kwh: float,
    discount_pct: float,
    assume_eligible: bool,
) -> dict[str, Any]:
    if not assume_eligible:
        return {
            "name": "low_income_assistance",
            "eligible": False,
            "reason": "assume_eligible=false — eligibility not asserted.",
        }
    base = float(plan["base_charge"])
    baseline_kwh = float(plan["baseline_kwh"])
    rate = float(plan["overage_rate"])
    overage = max(0.0, current_kwh - baseline_kwh) * rate if current_kwh else 0.0
    energy_charge = base + overage
    discount = energy_charge * discount_pct
    simulated = max(0.0, current_bill - discount)
    return {
        "name": "low_income_assistance",
        "eligible": True,
        "discount_pct": discount_pct,
        "discount_basis_usd": round(energy_charge, 2),
        "monthly_savings_usd": round(discount, 2),
        "annualized_savings_usd": round(discount * 12, 2),
        "simulated_total_usd": round(simulated, 2),
        "mechanism": (
            f"Applies a {discount_pct * 100:.0f}% discount on energy charges (base + overage). "
            "Eligibility is assumed for this simulation; real enrollment requires income verification."
        ),
        "summary": (
            f"If eligible, this customer would save ~${discount:.0f} this cycle "
            f"(~${discount * 12:.0f}/year)."
        ),
    }


def simulate_time_of_use(
    meter_df: pd.DataFrame,
    dataid: int,
    plan: dict[str, Any],
    cycle_start: Optional[pd.Timestamp],
    cycle_end: Optional[pd.Timestamp],
    peak_rate: float,
    off_peak_rate: float,
) -> dict[str, Any]:
    if cycle_start is None or cycle_end is None:
        return {
            "name": "time_of_use",
            "eligible": False,
            "reason": "cycle_start and cycle_end required for TOU simulation.",
        }
    rows = meter_df[
        (meter_df["dataid"] == int(dataid))
        & (meter_df["local_15min"] >= cycle_start)
        & (meter_df["local_15min"] <= cycle_end)
    ]
    if rows.empty:
        return {
            "name": "time_of_use",
            "eligible": False,
            "reason": "No meter data in the requested cycle.",
        }

    rows = rows.set_index("local_15min").sort_index()
    if "grid" not in rows.columns or rows["grid"].isna().all():
        return {
            "name": "time_of_use",
            "eligible": False,
            "reason": "No grid signal available for this customer.",
        }

    consumption_kw = rows["grid"].clip(lower=0).fillna(0.0)
    consumption_kwh = consumption_kw * INTERVAL_HOURS

    weekday = consumption_kwh.index.weekday < 5
    hour = consumption_kwh.index.hour
    is_peak = weekday & (hour >= 16) & (hour < 21)

    peak_kwh = float(consumption_kwh[is_peak].sum())
    off_peak_kwh = float(consumption_kwh[~is_peak].sum())
    total_kwh = peak_kwh + off_peak_kwh
    if total_kwh <= 0:
        return {"name": "time_of_use", "eligible": False, "reason": "Zero consumption in cycle."}

    flat_rate = float(plan["overage_rate"])
    flat_cost = total_kwh * flat_rate
    tou_cost = peak_kwh * peak_rate + off_peak_kwh * off_peak_rate
    delta = flat_cost - tou_cost
    peak_share_pct = (peak_kwh / total_kwh) * 100

    peak_share_label = f"{peak_share_pct:.1f}".rstrip("0").rstrip(".")
    return {
        "name": "time_of_use",
        "eligible": True,
        "total_kwh": round(total_kwh, 2),
        "peak_kwh": round(peak_kwh, 2),
        "off_peak_kwh": round(off_peak_kwh, 2),
        "peak_share_pct": round(peak_share_pct, 1),
        "flat_rate_energy_cost_usd": round(flat_cost, 2),
        "tou_energy_cost_usd": round(tou_cost, 2),
        "monthly_savings_usd": round(delta, 2),
        "annualized_savings_usd": round(delta * 12, 2),
        "rates": {
            "peak_per_kwh": peak_rate,
            "off_peak_per_kwh": off_peak_rate,
            "flat_per_kwh": flat_rate,
            "peak_window": "Mon–Fri 16:00–21:00",
        },
        "mechanism": (
            f"Instead of paying a flat ${flat_rate}/kWh on all usage, TOU charges "
            f"${peak_rate}/kWh during peak hours (Mon–Fri 4–9pm) and ${off_peak_rate}/kWh "
            "at all other times. This is a permanent rate plan switch, not a one-time program."
        ),
        "summary": (
            f"Currently paying a flat ${flat_rate}/kWh on all usage (energy cost ~${flat_cost:.0f} this cycle). "
            f"Switching to TOU would charge ${peak_rate}/kWh at peak and ${off_peak_rate}/kWh off-peak — "
            f"energy cost drops to ~${tou_cost:.0f} this cycle, saving ~${abs(delta):.0f}. "
            f"Only {peak_share_label}% of usage falls in peak hours, making TOU advantageous for this customer. "
            "Note: TOU is a permanent rate plan change — future bills will always use peak/off-peak pricing."
        ),
    }

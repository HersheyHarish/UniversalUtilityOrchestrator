"""Profile-weighted projection, tariff application, and bill-shock z-scoring.

ROLE IN THE FLOW
----------------
This file contains the three core math steps that turn "kWh consumed so far"
into "projected bill" and then "is this bill abnormally high?".

The three functions are called in order by build_response() in
forecast_response_payloads.py:

  Step 1: build_cycle_profile(kwh_series, exclude_period)
          → learns the customer's typical daily consumption shape from past months
          → returns a per-day-of-month cumulative-fraction profile

  Step 2: project_cycle_kwh(kwh_so_far, days_elapsed, days_in_cycle, profile)
          → uses the profile to project end-of-month kWh total
          → returns (projected_kwh, method_name)

  Step 3: apply_tariff(projected_kwh, plan, invoices)
          → applies the customer's rate plan to the projected kWh
          → returns a breakdown dict: base + overage + taxes/fees + total

  Step 4: detect_shock(projected_total, invoices, lookback_months)
          → compares the projected total against recent invoice history
          → returns a z-score and severity label

FLOW POSITION: kwh_series → build_cycle_profile → project_cycle_kwh
                                                 → apply_tariff → detect_shock
               (all called inside forecast_response_payloads.build_response)
"""

from __future__ import annotations

from calendar import monthrange
from typing import Any, Optional

import numpy as np
import pandas as pd


def build_cycle_profile(
    consumption_kwh: pd.Series,
    exclude_period: pd.Period,
) -> Optional[pd.Series]:
    """Learn a customer's typical daily cumulative-consumption shape from past months.

    The "profile" answers: "By day N of the month, what fraction of the month's
    total kWh has historically been consumed?" This shape is what makes the
    projection smarter than naive linear scaling.

    Why cumulative fraction instead of raw daily kWh?
      A customer might use 20% of their monthly kWh in the first week due to
      weekday work-from-home patterns. A linear scale (days_elapsed/days_in_month)
      would assume 25% by week one. The profile corrects for that shape.

    Args:
        consumption_kwh: Time-indexed kWh Series (output of consumption_series_kwh).
        exclude_period:  The billing cycle currently being forecast (as a pd.Period).
                         We exclude it so we don't train on partial-month data.

    Returns:
        A pd.Series indexed by day-of-month (1–31) where each value is the
        average cumulative fraction across all qualifying past months.
        Returns None if there aren't enough complete historical months to learn from.

    Example output (a customer who front-loads usage):
        day
        1     0.04   ← by end of day 1, ~4% of the month is done
        7     0.22   ← by end of day 7, ~22% done (higher than 7/31 ≈ 22.6%)
        15    0.49
        31    1.00
    """
    if consumption_kwh.empty:
        return None

    # Resample 15-min intervals → daily totals. Index becomes date (midnight).
    daily = consumption_kwh.resample("D").sum()
    if daily.empty:
        return None

    frame = pd.DataFrame({"kwh": daily})
    frame["year_month"] = frame.index.to_period("M")  # e.g. Period("2019-06", "M")
    frame["day"] = frame.index.day                     # 1, 2, ..., 31

    fractions_by_day: dict[int, list[float]] = {}

    for ym, group in frame.groupby("year_month"):
        # Skip the month being forecast — we don't want partial data polluting the profile.
        if ym == exclude_period:
            continue

        group = group.sort_values("day")
        days_in_month = monthrange(ym.year, ym.month)[1]

        # Only use complete months (the last day present must equal the month's last day).
        # An incomplete month would give a cumulative fraction that never reaches 1.0.
        if int(group["day"].max()) < days_in_month:
            continue

        total = float(group["kwh"].sum())
        if total <= 0:
            continue  # skip months with no consumption (data gaps)

        # cumsum() / total gives the cumulative fraction at each day.
        # Example: [10, 8, 12, ...] → cumsum → [10, 18, 30, ...] → / total
        cum = group["kwh"].cumsum() / total
        for day_value, frac in zip(group["day"].astype(int).values, cum.astype(float).values):
            fractions_by_day.setdefault(int(day_value), []).append(float(frac))

    if not fractions_by_day:
        return None  # no complete historical months → caller will use naive linear

    # Average the cumulative fractions across all qualifying months for each day.
    return pd.Series(
        {day: float(np.mean(values)) for day, values in fractions_by_day.items()}
    ).sort_index()


def project_cycle_kwh(
    kwh_so_far: float,
    days_elapsed: int,
    days_in_cycle: int,
    profile: Optional[pd.Series],
) -> tuple[float, str]:
    """Project the end-of-cycle kWh total from partial-cycle meter data.

    Three projection strategies, tried in order:

      "actual"          — cycle is already complete; return kwh_so_far as-is.
      "profile_weighted" — divide kwh_so_far by the historical fraction for this
                           day-of-month to get the full-month estimate.
      "naive_linear"    — fallback when no profile is available; scale linearly
                          by days remaining.

    Args:
        kwh_so_far:    Total kWh consumed from cycle_start through as_of.
        days_elapsed:  Number of days from cycle_start through as_of (inclusive).
        days_in_cycle: Total days in the billing cycle (e.g. 31 for July).
        profile:       The cumulative-fraction profile from build_cycle_profile().
                       None if there was insufficient history.

    Returns:
        (projected_kwh, method) where method is one of the three strings above.

    Example (profile-weighted):
        kwh_so_far = 240 kWh, days_elapsed = 15, profile[15] = 0.48
        projected  = 240 / 0.48 = 500 kWh
        (The customer has used 48% of their typical month by day 15,
         so the full month is projected at 500 kWh.)

    Example (naive linear):
        kwh_so_far = 240, days_elapsed = 15, days_in_cycle = 31
        projected  = 240 × (31/15) = 496 kWh
    """
    if days_elapsed <= 0:
        return 0.0, "no_data"

    # Cycle is already complete — use the actual reading.
    if days_elapsed >= days_in_cycle:
        return kwh_so_far, "actual"

    # No usable profile → fall back to simple linear scaling.
    if profile is None or len(profile) < 2:
        return kwh_so_far * (days_in_cycle / days_elapsed), "naive_linear"

    # Look up the historical cumulative fraction for the current day-of-month.
    # If the exact day isn't in the profile index, use the nearest neighbour.
    if days_elapsed in profile.index:
        fraction = float(profile.loc[days_elapsed])
    else:
        idx = profile.index.get_indexer([days_elapsed], method="nearest")[0]
        fraction = float(profile.iloc[idx])

    # Guard: a fraction of 0 or ≥1 would cause division by zero or underestimate.
    if fraction <= 0 or fraction >= 1.0:
        return kwh_so_far * (days_in_cycle / days_elapsed), "naive_linear"

    # Profile-weighted projection: kwh_so_far is `fraction` of the total.
    return kwh_so_far / fraction, "profile_weighted"


def apply_tariff(
    projected_kwh: float,
    plan: dict[str, Any],
    invoices: list[dict[str, Any]],
) -> dict[str, float]:
    """Apply the customer's rate plan to a projected kWh total.

    The plan has three components:
      base_charge    — flat monthly fee regardless of usage (e.g. $10.00)
      baseline_kwh   — the kWh allowance included in base_charge (e.g. 500 kWh)
      overage_rate   — $/kWh charged for every kWh above baseline (e.g. $0.12/kWh)

    Taxes, fees, and surcharges ("soft costs") are NOT in the plan dict directly.
    Instead, they are estimated from the gap between what the hard tariff math
    predicts and what was actually invoiced historically. The per-kWh soft cost
    rate is averaged across the last 12 invoices and applied to the projection.

    Args:
        projected_kwh: The output of project_cycle_kwh().
        plan:          The customer's plan dict from the billing JSON.
        invoices:      The customer's invoice list from the billing JSON.

    Returns:
        A dict with keys: base, overage, estimated_taxes_fees_and_surcharges, total.

    Example:
        projected_kwh = 600, baseline_kwh = 500, overage_rate = 0.12, base = 10
        overage = (600 - 500) × 0.12 = $12.00
        soft_costs ≈ $8.50 (learned from recent invoices)
        total = 10 + 12 + 8.50 = $30.50
    """
    base = float(plan["base_charge"])
    baseline = float(plan["baseline_kwh"])
    rate = float(plan["overage_rate"])

    overage_kwh = max(0.0, projected_kwh - baseline)
    overage = overage_kwh * rate

    # Estimate soft costs (taxes, fees, surcharges) per kWh from invoice history.
    # For each past invoice: soft_cost = actual_total - (base + hard_overage).
    # Then average soft_cost/kWh across invoices to get a per-kWh soft rate.
    soft_per_kwh_samples: list[float] = []
    for inv in invoices[-12:]:
        total_kwh = float(inv.get("total_kwh", 0.0))
        if total_kwh <= 0:
            continue
        inv_overage = max(0.0, total_kwh - baseline) * rate
        hard = base + inv_overage
        soft = float(inv.get("total", 0.0)) - hard
        soft_per_kwh_samples.append(soft / total_kwh)

    soft_per_kwh = float(np.mean(soft_per_kwh_samples)) if soft_per_kwh_samples else 0.0
    soft_costs = max(0.0, projected_kwh * soft_per_kwh)

    return {
        "base": round(base, 2),
        "overage": round(overage, 2),
        "estimated_taxes_fees_and_surcharges": round(soft_costs, 2),
        "total": round(base + overage + soft_costs, 2),
    }


def detect_shock(
    projected_total: float,
    invoices: list[dict[str, Any]],
    lookback_months: int,
) -> dict[str, Any]:
    """Compare the projected bill total against the customer's recent invoice history.

    Uses both a z-score and a percent increase over the customer's historical
    mean. A high z-score alone can be misleading when bills are extremely stable
    and the absolute increase is only a few dollars.

    The z-score denominator is floored at $1.00 to prevent division by near-zero
    standard deviation (e.g. a customer whose bills are always exactly $50.00).

    Severity thresholds require both statistical and practical significance:
        critical → z > 3.0 and >= 25% above average
        high     → z > 2.0 and >= 20% above average
        medium   → z > 1.5 and >= 10% above average
        low      → above average but below medium threshold
        none     → at or below average

    Args:
        projected_total:  The "total" value from apply_tariff().
        invoices:         The customer's full invoice list from the billing JSON.
        lookback_months:  How many recent invoices to include (from BillShockRequest).

    Returns:
        A dict with: historical_mean_usd, historical_std_usd, shock_score,
        shock_detected (bool), shock_severity (str).
        Returns None values and shock_detected=False if fewer than 2 invoices exist.

    Example:
        Recent 6 invoices: [$55, $60, $58, $62, $57, $59] → mean=$58.50, std=$2.42
        projected_total = $80
        z = (80 - 58.50) / 2.42 = 8.9 → severity = "critical", shock_detected = True
    """
    recent = invoices[-lookback_months:] if invoices else []
    totals = [float(inv["total"]) for inv in recent if "total" in inv]

    # Need at least 2 data points to compute a meaningful standard deviation.
    if len(totals) < 2:
        return {
            "historical_mean_usd": None,
            "historical_std_usd": None,
            "shock_score": None,
            "shock_detected": False,
            "shock_severity": "unknown",
        }

    mean_t = float(np.mean(totals))
    std_t = float(np.std(totals, ddof=1))           # sample std (ddof=1)
    z = (projected_total - mean_t) / max(std_t, 1.0) # floor std at $1 to avoid div/0
    delta_pct = ((projected_total - mean_t) / mean_t) if mean_t > 0 else 0.0

    if z > 3 and delta_pct >= 0.25:
        severity = "critical"
    elif z > 2 and delta_pct >= 0.20:
        severity = "high"
    elif z > 1.5 and delta_pct >= 0.10:
        severity = "medium"
    elif projected_total > mean_t:
        severity = "low"
    else:
        severity = "none"

    return {
        "historical_mean_usd": round(mean_t, 2),
        "historical_std_usd": round(std_t, 2),
        "shock_score": round(float(z), 2),
        "shock_delta_pct": round(float(delta_pct * 100), 1),
        "shock_detected": severity in {"medium", "high", "critical"},
        "shock_severity": severity,
    }

"""Assemble the final response from resolved inputs and forecast outputs.

ROLE IN THE FLOW
----------------
This is the last stage before the JSON is returned to the orchestrator.
It orchestrates all the math files and turns their outputs into the final
dict that the HTTP handler sends back.

Calling order:
  1. consumption_series_kwh()  → get kWh time series for the customer
  2. sum in-cycle rows         → kwh_so_far (how much used between cycle_start and as_of)
  3. build_cycle_profile()     → learn the customer's daily consumption shape from past months
  4. project_cycle_kwh()       → extrapolate to end-of-month kWh
  5. apply_tariff()            → convert projected kWh → projected $$ breakdown
  6. detect_shock()            → z-score vs. recent invoice history
  7. build contributing_factors list (plain-English explanation of why the bill is high)
  8. assemble and return the response dict

FLOW POSITION (end-to-end):
  HTTP POST → bill_shock_service.py
           → cached_meter_data(), cached_billing_data()
           → resolve_inputs()           [forecast_request_resolution.py]
           → build_response()           [THIS FILE]
               → consumption_series_kwh()   [consumption_series.py]
               → build_cycle_profile()      [bill_projection_math.py]
               → project_cycle_kwh()        [bill_projection_math.py]
               → apply_tariff()             [bill_projection_math.py]
               → detect_shock()             [bill_projection_math.py]
           → JSON response to orchestrator
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from .consumption_series import consumption_series_kwh
from .bill_projection_math import (
    apply_tariff,
    build_cycle_profile,
    detect_shock,
    project_cycle_kwh,
)


def build_response(
    resolved: dict[str, Any],
    df: pd.DataFrame,
    billing: dict[str, Any],
) -> dict[str, Any]:
    """Build the final JSON response for the bill shock forecast agent.

    Args:
        resolved: The output of resolve_inputs() — a fully-specified dict with
                  customer_id, account, dataid, as_of, cycle_start, cycle_end,
                  lookback_months.
        df:       Full meter DataFrame from cached_meter_data().
        billing:  Full billing JSON from cached_billing_data().

    Returns:
        A flat dict ready to be serialized to JSON and returned by the HTTP handler.
    """
    customer_id = resolved["customer_id"]
    account = resolved["account"]
    dataid = resolved["dataid"]
    as_of = resolved["as_of"]
    cycle_start = resolved["cycle_start"]
    cycle_end = resolved["cycle_end"]
    lookback_months = resolved["lookback_months"]

    # --- Step 1: Get the full kWh time series for this customer ----------------
    # Returns a pd.Series indexed by local_15min Timestamps, values in kWh.
    # Example: 15-min intervals for dataid=5997 across all available history.
    kwh_series = consumption_series_kwh(df, dataid)
    if kwh_series.empty:
        raise ValueError(f"No consumption data for {customer_id}.")

    # --- Step 2: Sum the kWh consumed so far in the current cycle --------------
    # "So far" = cycle_start through as_of (the forecast boundary date).
    # Example: 15 days into July → sum of all 15-min intervals July 1–15.
    in_cycle = kwh_series[(kwh_series.index >= cycle_start) & (kwh_series.index <= as_of)]
    kwh_so_far = float(in_cycle.sum())

    # --- Step 3: Compute cycle timing metrics ----------------------------------
    # days_elapsed: number of days from the start of the cycle through as_of.
    #   +1 because if as_of IS cycle_start, that's 1 day elapsed, not 0.
    # days_in_cycle: total length of the billing cycle (e.g. 31 for July).
    # days_remaining: how many more days the cycle has after as_of.
    days_elapsed = max(1, (as_of.normalize() - cycle_start.normalize()).days + 1)
    days_in_cycle = (cycle_end.normalize() - cycle_start.normalize()).days + 1
    days_remaining = max(0, days_in_cycle - days_elapsed)

    # --- Step 4: Build the usage profile from past complete months -------------
    # exclude_period = the cycle being forecast, so we don't train on partial data.
    # The profile maps day-of-month → average cumulative fraction consumed.
    # Example: profile[15] = 0.48 means "by day 15, this customer has historically
    # used 48% of their monthly total."
    cycle_period = pd.Period(year=cycle_start.year, month=cycle_start.month, freq="M")
    profile = build_cycle_profile(kwh_series, exclude_period=cycle_period)

    # --- Step 5: Project end-of-cycle kWh --------------------------------------
    # method is one of: "actual", "profile_weighted", "naive_linear"
    # Example (profile_weighted): kwh_so_far=240, profile[15]=0.48 → projected=500
    projected_kwh, method = project_cycle_kwh(
        kwh_so_far, days_elapsed, days_in_cycle, profile
    )

    # --- Step 6: Apply tariff to get projected $ breakdown ---------------------
    # Fetches the customer's plan (base_charge, baseline_kwh, overage_rate) from
    # the account dict and returns: base, overage, taxes/fees, total.
    all_invoices = billing.get("invoices", {}).get(customer_id, [])
    invoices = [
        inv for inv in all_invoices
        if inv.get("billing_end", "") < cycle_start.strftime("%Y-%m-%d")
    ]
    breakdown = apply_tariff(projected_kwh, account["plan"], invoices)

    # --- Step 7: Bill shock z-score detection ----------------------------------
    # Compares breakdown["total"] against the last `lookback_months` invoices.
    # Returns: historical_mean_usd, historical_std_usd, shock_score, shock_detected, shock_severity.
    shock = detect_shock(breakdown["total"], invoices, lookback_months)

    # --- Step 8: Build plain-English contributing factors list -----------------
    # These are human-readable strings surfaced to the orchestrator/customer.
    factors: list[str] = []

    # Factor A: Is the current daily kWh rate above the historical average?
    # Compare: avg daily kWh this cycle (so far) vs. avg daily kWh from recent invoices.
    # Example: "Daily kWh tracking 35% above 6-month average."
    recent_kwh = [
        float(inv.get("total_kwh", 0.0))
        for inv in invoices[-lookback_months:]
        if float(inv.get("total_kwh", 0.0)) > 0
    ]
    if recent_kwh and days_elapsed > 0:
        avg_daily_hist = (sum(recent_kwh) / len(recent_kwh)) / 30.0  # rough 30-day month
        avg_daily_now = kwh_so_far / days_elapsed
        if avg_daily_hist > 0:
            delta_pct = (avg_daily_now / avg_daily_hist - 1.0) * 100
            if delta_pct > 10:
                factors.append(
                    f"Daily kWh tracking {delta_pct:.0f}% above {lookback_months}-month average."
                )
            elif delta_pct < -10:
                factors.append(
                    f"Daily kWh tracking {abs(delta_pct):.0f}% below {lookback_months}-month average."
                )

    # Factor B: Will the customer exceed their plan's baseline (included) kWh?
    # Exceeding baseline triggers overage charges at the higher overage_rate.
    # Example: "Projected to exceed baseline_kwh (500) by ~100 kWh."
    baseline_kwh = float(account["plan"]["baseline_kwh"])
    if projected_kwh > baseline_kwh:
        factors.append(
            f"Projected to exceed baseline_kwh ({int(baseline_kwh)}) by ~{round(projected_kwh - baseline_kwh)} kWh."
        )

    # --- Step 9: Build one-sentence human-readable summary --------------------
    # Example: "Customer CUST-1001 is on track for a ~$85 bill
    #           (47% above their $58 6-month average). Projection method: profile_weighted."
    summary_parts = [
        f"Customer {customer_id} is on track for a ~${breakdown['total']:.0f} bill"
    ]
    if shock["historical_mean_usd"] is not None:
        diff_pct = (breakdown["total"] / shock["historical_mean_usd"] - 1.0) * 100
        direction = "above" if diff_pct >= 0 else "below"
        summary_parts.append(
            f"({abs(diff_pct):.0f}% {direction} their ${shock['historical_mean_usd']:.0f} {lookback_months}-month average)."
        )
    else:
        summary_parts.append("(insufficient history to compare).")
    summary_parts.append(f"Projection method: {method}.")

    # **shock is unpacked inline — it adds: historical_mean_usd, historical_std_usd,
    # shock_score, shock_detected, shock_severity directly into the response dict.
    return {
        "agent": "bill_shock_forecast_agent",
        "status": "completed",
        "customer_id": customer_id,
        "plan_name": account["plan"]["name"],
        "cycle_start": cycle_start.isoformat(),
        "cycle_end": cycle_end.isoformat(),
        "as_of": as_of.isoformat(),
        "days_elapsed": days_elapsed,
        "days_remaining": days_remaining,
        "kwh_used_to_date": round(kwh_so_far, 2),
        "projected_kwh": round(projected_kwh, 2),
        "projection_method": method,
        "projected_breakdown": breakdown,        # {base, overage, taxes/fees, total}
        "projected_total_usd": breakdown["total"],
        **shock,                                 # shock_score, severity, etc. merged flat
        "contributing_factors": factors,
        "summary": " ".join(summary_parts),
    }

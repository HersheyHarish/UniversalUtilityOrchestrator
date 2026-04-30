"""Severity classification, customer-facing narrative, and final response shape.

WHAT THIS FILE DOES
-------------------
Takes the raw analysis outputs (DataFrames, metrics, metadata) and assembles
the final JSON response the HTTP caller receives. This is the only file in the
module that knows what the response looks like — all other files are pure analysis.

SEVERITY CLASSIFICATION
-----------------------
Severity is based on three signals combined:
  1. lost_pct      — what fraction of expected generation was lost
  2. lost_kwh      — absolute energy lost (size-independent of window length)
  3. underperforming_days — how many calendar days had sustained underperformance
  4. partial_issue — whether one feed is dropped while another is normal

Thresholds (checked in order, highest severity wins):
  critical  → ≥ 50% lost, OR ≥ 100 kWh lost, OR ≥ 7 bad days
  high      → partial inverter issue, OR ≥ 30% lost, OR ≥ 40 kWh lost, OR ≥ 4 bad days
  medium    → ≥ 15% lost, OR ≥ 10 kWh lost, OR ≥ 2 bad days
  low       → detected but below medium thresholds
  none      → not detected

LIKELY CAUSE CLASSIFICATION
-----------------------------
  "weather-related"                    — weather context was used AND adverse_ratio ≥ 0.35
                                         AND severity is low/medium (not catastrophic)
  "possible partial inverter/feed issue" — one feed dropped while another is normal
  "broad underperformance"              — everything else

FINANCIAL PROJECTION
--------------------
  lost_value = lost_kwh × credit_rate
  projected_30d = (lost_kwh / window_days) × 30 × credit_rate

The 30-day projection assumes the current underperformance rate continues.
It's a rough estimate intended to help the orchestrator communicate urgency.
"""

from __future__ import annotations

from typing import Any

from .solar_underperformance_analysis import (
    build_analysis_frame,
    grid_context,
    summarize_daily,
    summarize_feeds,
)


def classify_severity(
    detected: bool,
    lost_pct: float,
    lost_kwh: float,
    underperforming_days: int,
    partial_issue: bool,
) -> str:
    """Map analysis metrics to a severity tier.

    Args:
        detected:           Whether underperformance was flagged at all.
        lost_pct:           Fraction of expected generation lost (0.0–1.0).
        lost_kwh:           Absolute lost generation in kWh.
        underperforming_days: Number of calendar days below the performance threshold.
        partial_issue:      True if one solar feed is dropped while another is normal.

    Returns one of: "none", "low", "medium", "high", "critical"
    """
    if not detected:
        return "none"
    if lost_pct >= 0.50 or lost_kwh >= 100 or underperforming_days >= 7:
        return "critical"
    if partial_issue or lost_pct >= 0.30 or lost_kwh >= 40 or underperforming_days >= 4:
        return "high"
    if lost_pct >= 0.15 or lost_kwh >= 10 or underperforming_days >= 2:
        return "medium"
    return "low"


def likely_cause(
    detected: bool,
    partial_issue: bool,
    weather: dict[str, Any],
    severity: str,
) -> str:
    """Infer the most likely cause of the underperformance.

    Logic:
      1. Not detected → "none"
      2. One feed dropped, other normal → "possible partial inverter/feed issue"
      3. Weather was applied AND caused significant reduction AND severity is low/medium
         (if severity is high/critical despite weather adjustment, it's probably not just weather)
         → "weather-related"
      4. Everything else → "broad underperformance"

    Returns a human-readable string for the likely_cause_category field.
    """
    if not detected:
        return "none"
    if partial_issue:
        return "possible partial inverter/feed issue"
    if weather.get("weather_context_used") and weather.get("adverse_weather_ratio", 0) >= 0.35:
        if severity in {"low", "medium"}:
            return "weather-related"
        return "broad underperformance"
    return "broad underperformance"


def build_customer_summary(
    customer_id: str,
    detected: bool,
    severity: str,
    cause: str,
    lost_kwh: float,
    lost_value: float,
    projected_value: float,
    lost_pct: float,
    weather_used: bool,
) -> str:
    """Build a single human-readable summary sentence for the response.

    When no underperformance is detected, returns a "looks fine" message.
    When detected, includes: how far below baseline, estimated lost kWh and credit value,
    likely cause, and a 30-day projection of the financial impact if it continues.

    Example (detected):
        "Solar production for CUST-1001 is about 23% below the weather-adjusted baseline
        in this window, with an estimated 18.4 kWh not generated (roughly $2.58 in credit
        value). Likely cause: broad underperformance. If this continues for 30 days,
        the rough impact is about $11.07."
    """
    if not detected:
        return (
            f"Solar production for {customer_id} is tracking close to its historical pattern "
            "for the requested window. No early underperformance warning is recommended."
        )

    pct = lost_pct * 100
    if cause == "weather-related":
        cause_text = "weather appears to explain much of the drop"
    elif cause == "possible partial inverter/feed issue":
        cause_text = "one solar feed appears weaker while another remains normal"
    else:
        cause_text = "production is broadly below its normal pattern"

    baseline_label = "weather-adjusted baseline" if weather_used else "historical baseline"
    return (
        f"Solar production for {customer_id} is about {pct:.0f}% below the {baseline_label} "
        f"in this window, with an estimated {lost_kwh:.1f} kWh not generated "
        f"(roughly ${lost_value:.2f} in credit value). Likely cause: {cause_text}. "
        f"If this continues for 30 days, the rough impact is about ${projected_value:.2f}."
    )


def build_response(resolved: dict[str, Any]) -> dict[str, Any]:
    """Run the full analysis pipeline and assemble the final JSON response.

    Steps:
      1. build_analysis_frame() — per-interval baseline + weather + underperformance flags
      2. summarize_daily()      — per-day aggregation, worst 5 days
      3. summarize_feeds()      — per-feed totals, partial issue detection
      4. grid_context()         — import/export totals from grid column
      5. Aggregate totals       — total expected, actual, lost kWh, performance ratio
      6. Detect underperformance — requires min intervals AND min days both met
      7. classify_severity()    — map metrics to none/low/medium/high/critical
      8. likely_cause()         — infer weather vs. partial vs. broad
      9. Financial math         — lost value, 30-day projection
     10. build_customer_summary() — one-sentence narrative
     11. Assemble and return the final dict

    The detection check (step 6) requires ALL of the following:
      - expected_kwh > 0 (there was sunlight to compare against)
      - aggregate ratio < 0.85 (overall production is below 85% of expected)
      - underperforming_intervals ≥ min_underperforming_intervals (sustained, not a blip)
      - underperforming_days ≥ min_underperforming_days (spread across multiple days)
    """
    # --- Run analysis ----------------------------------------------------------
    analysis, metadata = build_analysis_frame(resolved)
    interval_hours = float(metadata["interval_hours"])
    weather = metadata["weather_adjustment"]
    daily, worst_days = summarize_daily(analysis)

    # --- Aggregate window-level totals -----------------------------------------
    # Only count daylight intervals (filter out night readings with expected ≈ 0).
    daylight = analysis[analysis["is_daylight_expected"]]
    expected_kwh = float(daylight["expected_solar_kwh"].sum()) if not daylight.empty else 0.0
    actual_kwh = float(daylight["actual_solar_kwh"].sum()) if not daylight.empty else 0.0
    lost_kwh = max(0.0, expected_kwh - actual_kwh)
    underperforming_intervals = int(daylight["underperforming_interval"].sum()) if not daylight.empty else 0
    underperforming_days = int(daily["underperforming_day"].sum()) if not daily.empty else 0
    daylight_intervals = int(len(daylight))

    lost_pct = lost_kwh / expected_kwh if expected_kwh > 0 else 0.0
    aggregate_ratio = actual_kwh / expected_kwh if expected_kwh > 0 else 0.0

    # --- Detection gate --------------------------------------------------------
    # All four conditions must be true to flag underperformance.
    # This prevents spurious detections on short windows or noisy data.
    detected = bool(
        expected_kwh > 0
        and aggregate_ratio < 0.85
        and underperforming_intervals >= resolved["min_underperforming_intervals"]
        and underperforming_days >= resolved["min_underperforming_days"]
    )

    # --- Per-feed summary and partial issue detection --------------------------
    feed_summaries, partial_issue = summarize_feeds(
        analysis,
        resolved["solar_feeds"],
        weather_factor=float(weather["expected_generation_factor"]),
        interval_hours=interval_hours,
    )

    # --- Classification --------------------------------------------------------
    severity = classify_severity(
        detected=detected,
        lost_pct=lost_pct,
        lost_kwh=lost_kwh,
        underperforming_days=underperforming_days,
        partial_issue=partial_issue,
    )
    cause = likely_cause(detected, partial_issue, weather, severity)

    # --- Financial impact ------------------------------------------------------
    credit_rate = float(resolved["credit_rate_usd_per_kwh"])
    lost_value = lost_kwh * credit_rate
    total_window_days = max(
        1.0,
        (resolved["end_ts"] - resolved["start_ts"]).total_seconds() / 86400.0,
    )
    # Project the current daily loss rate forward 30 days.
    projected_30d_lost_kwh = (lost_kwh / total_window_days) * 30.0
    projected_30d_value = projected_30d_lost_kwh * credit_rate

    # --- Assemble response -----------------------------------------------------
    return {
        "agent": "solar_performance_credit_loss_agent",
        "status": "completed",
        "customer_id": resolved["customer_id"],
        "dataid": resolved["dataid"],
        "start_date": resolved["start_ts"].isoformat(),
        "end_date": resolved["end_ts"].isoformat(),
        "solar_feeds_evaluated": resolved["solar_feeds"],
        "underperformance_detected": detected,
        "severity": severity,
        "likely_cause_category": cause,
        # --- Generation metrics ---
        "estimated_expected_generation_kwh": round(expected_kwh, 2),
        "actual_generation_kwh": round(actual_kwh, 2),
        "estimated_lost_generation_kwh": round(lost_kwh, 2),
        "lost_generation_pct_of_expected": round(lost_pct * 100, 1),
        "window_performance_ratio": round(aggregate_ratio, 3) if expected_kwh > 0 else None,
        # --- Detection counts ---
        "underperforming_interval_count": underperforming_intervals,
        "underperforming_day_count": underperforming_days,
        "daylight_interval_count": daylight_intervals,
        # --- Financial impact ---
        "credit_rate_usd_per_kwh": round(credit_rate, 4),
        "credit_rate_source": resolved["credit_rate_source"],
        "estimated_lost_credit_value_usd": round(lost_value, 2),
        "projected_30_day_lost_generation_kwh": round(projected_30d_lost_kwh, 2),
        "rough_financial_impact_if_continues_30d_usd": round(projected_30d_value, 2),
        # --- Contextual details ---
        "grid_context": grid_context(resolved["window"], interval_hours),
        "weather_adjustment": weather,
        "baseline_context": {
            "lookback_days": resolved["lookback_days"],
            "baseline_reference_source": metadata["baseline_reference_source"],
            "baseline_interval_count": metadata["baseline_interval_count"],
            "baseline_start": metadata["baseline_start"],
            "baseline_end": metadata["baseline_end"],
            "baseline_method": (
                "Historical production by same 15-minute time-of-day slot and season/month, "
                "with same-hour fallback when buckets are sparse."
            ),
        },
        "feed_performance": feed_summaries,   # per-feed expected vs actual
        "worst_days": worst_days,              # top 5 days by lost kWh
        "summary": build_customer_summary(
            resolved["customer_id"],
            detected,
            severity,
            cause,
            lost_kwh,
            lost_value,
            projected_30d_value,
            lost_pct,
            bool(weather.get("weather_context_used")),
        ),
    }

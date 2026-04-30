"""Per-interval / per-day / per-feed analysis of the solar window.

WHAT THIS FILE DOES
-------------------
Takes the resolved request dict and composes all the pieces from baseline_history,
data_sources, and weather_adjustment into a single analysis DataFrame, then
summarizes it into the metrics the response builder needs.

MAIN FUNCTION: build_analysis_frame()
--------------------------------------
Returns (analysis, metadata):
  - analysis: the window DataFrame with these columns added per feed:
      {feed}_expected_kw         expected generation from the 3-tier baseline
      {feed}_baseline_source     which tier was used
      expected_solar_kw_unadjusted  sum across all feeds before weather scaling
      expected_solar_kw          after weather factor applied
      lost_kw                    max(0, expected - actual) per interval
      lost_kwh                   lost_kw × interval_hours
      actual_solar_kwh           actual_solar_kw × interval_hours
      performance_ratio          actual / expected (NaN if expected = 0)
      is_daylight_expected       True when expected ≥ 0.20 kW (filters nighttime)
      underperforming_interval   True when daylight AND ratio < threshold AND lost ≥ 0.1 kW

  - metadata: dict with interval_hours, baseline source label, baseline date range,
              and the full weather_adjustment result.

UNDERPERFORMANCE FLAG LOGIC
----------------------------
An interval is flagged as underperforming only when ALL three conditions are true:
  1. is_daylight_expected — expected generation ≥ 0.20 kW (not nighttime or near-zero)
  2. performance_ratio < underperformance_ratio — actual is below the threshold
  3. lost_kw ≥ MATERIAL_LOSS_KW (0.10 kW) — the gap is physically meaningful

This three-way AND prevents false positives from:
  - Nighttime readings where both actual and expected are 0
  - Sensor noise that causes tiny absolute deviations near 0

DAILY SUMMARY: summarize_daily()
----------------------------------
Aggregates the interval-level analysis to one row per day. Only daylight intervals
are included. Flags a day as underperforming if:
  - expected ≥ MIN_DAY_EXPECTED_KWH (1.0) — enough expected generation to matter
  - daily performance ratio < 0.75 — actual is less than 75% of expected for the day

Returns the top 5 worst days sorted by lost_kwh (then underperforming interval count).

FEED COMPARISON: summarize_feeds()
------------------------------------
Computes expected vs actual for each feed (solar, solar2) separately.
If one feed is "dropped" (ratio < 0.50) while another is "normal" (ratio ≥ 0.75),
it sets partial_issue=True — a strong signal of a partial inverter/wiring problem.

GRID CONTEXT: grid_context()
------------------------------
Reads the grid column (positive = importing, negative = exporting) to provide
additional context about how much power the customer is drawing from / selling to
the grid. Useful for understanding the net impact of solar underperformance.
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd

from .solar_baseline_history import attach_feed_baseline, select_baseline_rows
from .solar_data_sources import add_time_features, infer_interval_hours
from .solar_weather_adjustment import weather_adjustment


# Minimum absolute lost_kw to count as material underperformance (filters sensor noise).
MATERIAL_LOSS_KW = 0.10

# Minimum expected daily generation (kWh) for a day to be evaluated.
# Days with < 1 kWh expected (very cloudy, or short winter days) are excluded.
MIN_DAY_EXPECTED_KWH = 1.0


def build_analysis_frame(resolved: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Build the per-interval analysis DataFrame with baseline and underperformance flags.

    Steps:
      1. Infer the recording interval from timestamp diffs (usually 0.25h = 15 min).
      2. Add time-feature columns (slot, season, hour, date) to the window.
      3. Select historical baseline rows (prior N days before the window).
      4. Add time features to the baseline too (needed for slot/season grouping).
      5. For each solar feed, attach 3-tier expected kW via attach_feed_baseline().
      6. Sum feeds → expected_solar_kw_unadjusted.
      7. Apply weather adjustment factor → expected_solar_kw.
      8. Compute lost_kw, lost_kwh, performance_ratio, and underperforming_interval flags.

    Args:
        resolved: Output of resolve_inputs() from solar_request_resolution.py.

    Returns:
        (analysis, metadata) where analysis is the annotated window DataFrame
        and metadata is a dict with interval_hours, baseline stats, and weather info.

    Raises:
        ValueError — if there aren't enough historical rows to build any baseline.
    """
    feeds = resolved["solar_feeds"]
    interval_hours = infer_interval_hours(resolved["customer_rows"])

    # Add time features to the analysis window (slot, season, hour, date, solar_total_kw).
    window = add_time_features(resolved["window"], feeds)

    # Select prior rows for the baseline and add the same time features.
    raw_baseline, baseline_source = select_baseline_rows(
        resolved["customer_rows"],
        resolved["start_ts"],
        resolved["end_ts"],
        resolved["lookback_days"],
    )
    if raw_baseline.empty:
        raise ValueError("Not enough historical solar data to build a baseline.")
    baseline = add_time_features(raw_baseline, feeds)

    # Attach 3-tier expected kW for each feed independently.
    analysis = window
    for feed in feeds:
        analysis = attach_feed_baseline(analysis, baseline, feed)

    # Sum all feed expected values into one unadjusted total.
    # min_count=1 means NaN if ALL feeds are NaN (shouldn't happen after baseline fill).
    analysis["expected_solar_kw_unadjusted"] = analysis[
        [f"{feed}_expected_kw" for feed in feeds]
    ].sum(axis=1, min_count=1).fillna(0.0)

    # Apply weather adjustment — scales expected down on cloudy/rainy days.
    weather = weather_adjustment(resolved["weather_context"])
    factor = float(weather["expected_generation_factor"])
    analysis["expected_solar_kw"] = analysis["expected_solar_kw_unadjusted"] * factor

    # Compute per-interval generation and performance metrics.
    analysis["lost_kw"] = (analysis["expected_solar_kw"] - analysis["solar_total_kw"]).clip(lower=0.0)
    analysis["lost_kwh"] = analysis["lost_kw"] * interval_hours
    analysis["actual_solar_kwh"] = analysis["solar_total_kw"] * interval_hours
    analysis["expected_solar_kwh"] = analysis["expected_solar_kw"] * interval_hours
    analysis["performance_ratio"] = np.where(
        analysis["expected_solar_kw"] > 0,
        analysis["solar_total_kw"] / analysis["expected_solar_kw"],
        np.nan,  # NaN when expected = 0 (nighttime) — don't compute ratio for these
    )

    # is_daylight_expected: filter out nighttime intervals where expected ≈ 0.
    # Threshold 0.20 kW is ~200W — low enough to catch dawn/dusk, high enough to
    # exclude true night readings with sensor noise.
    analysis["is_daylight_expected"] = analysis["expected_solar_kw"] >= 0.20

    # An interval is underperforming only when all three conditions are true.
    analysis["underperforming_interval"] = (
        analysis["is_daylight_expected"]
        & analysis["performance_ratio"].lt(resolved["underperformance_ratio"])
        & analysis["lost_kw"].ge(MATERIAL_LOSS_KW)
    )

    metadata = {
        "interval_hours": interval_hours,
        "baseline_reference_source": baseline_source,
        "baseline_interval_count": int(len(baseline)),
        "baseline_start": baseline["local_15min"].min().isoformat(),
        "baseline_end": baseline["local_15min"].max().isoformat(),
        "weather_adjustment": weather,
    }
    return analysis, metadata


def summarize_daily(analysis: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Aggregate interval analysis to per-day metrics and return the 5 worst days.

    Only daylight intervals (is_daylight_expected=True) are included in the daily
    aggregation. This prevents nighttime zeros from diluting the daily totals.

    A day is flagged underperforming if:
      - expected_kwh ≥ MIN_DAY_EXPECTED_KWH (1.0) — enough expected to matter
      - performance_ratio < 0.75 — actual is less than 75% of expected for the day

    Returns:
        (daily_df, worst_days_list) where worst_days_list is the top 5 days
        by lost_kwh, serialized as dicts for inclusion in the JSON response.
    """
    daylight = analysis[analysis["is_daylight_expected"]].copy()
    if daylight.empty:
        empty = pd.DataFrame(
            columns=[
                "date", "expected_kwh", "actual_kwh", "lost_kwh",
                "underperforming_intervals", "daylight_intervals",
                "performance_ratio", "underperforming_day",
            ]
        )
        return empty, []

    daily = (
        daylight.groupby("date")
        .agg(
            expected_kwh=("expected_solar_kwh", "sum"),
            actual_kwh=("actual_solar_kwh", "sum"),
            interval_lost_kwh=("lost_kwh", "sum"),
            underperforming_intervals=("underperforming_interval", "sum"),
            daylight_intervals=("is_daylight_expected", "sum"),
        )
        .reset_index()
    )

    # Recompute lost_kwh at the day level from expected-actual to avoid double-counting.
    daily["lost_kwh"] = (daily["expected_kwh"] - daily["actual_kwh"]).clip(lower=0.0)
    daily["performance_ratio"] = np.where(
        daily["expected_kwh"] > 0,
        daily["actual_kwh"] / daily["expected_kwh"],
        np.nan,
    )
    # A day is underperforming if expected is meaningful AND ratio is below 75%.
    daily["underperforming_day"] = (
        daily["expected_kwh"].ge(MIN_DAY_EXPECTED_KWH)
        & daily["performance_ratio"].lt(0.75)
    )

    # Return the 5 worst days (most lost kWh) for the response's worst_days field.
    worst_days = (
        daily.sort_values(["lost_kwh", "underperforming_intervals"], ascending=[False, False])
        .head(5)
    )
    serialized: list[dict[str, Any]] = []
    for _, row in worst_days.iterrows():
        serialized.append(
            {
                "date": str(row["date"]),
                "expected_kwh": round(float(row["expected_kwh"]), 2),
                "actual_kwh": round(float(row["actual_kwh"]), 2),
                "estimated_lost_kwh": round(float(row["lost_kwh"]), 2),
                "performance_ratio": round(float(row["performance_ratio"]), 3)
                if pd.notna(row["performance_ratio"])
                else None,
                "underperforming_intervals": int(row["underperforming_intervals"]),
                "daylight_intervals": int(row["daylight_intervals"]),
            }
        )
    return daily, serialized


def feed_status(ratio: Optional[float], expected_kwh: float) -> str:
    """Classify a feed's performance into a status label.

    Used by summarize_feeds() to determine whether one feed looks normal while
    another is dropped — the partial inverter/wiring issue signal.

    Status labels:
      "insufficient_expected_generation" — not enough expected production to judge
      "dropped"  — ratio < 0.50 (feed is generating less than half of expected)
      "low"      — ratio < 0.75 (underperforming materially)
      "below_expected" — ratio < 0.85 (below the detection gate but not a feed drop)
      "normal"   — ratio ≥ 0.85 (tracking close to expected)
    """
    if ratio is None or expected_kwh < MIN_DAY_EXPECTED_KWH:
        return "insufficient_expected_generation"
    if ratio < 0.50:
        return "dropped"
    if ratio < 0.75:
        return "low"
    if ratio < 0.85:
        return "below_expected"
    return "normal"


def summarize_feeds(
    analysis: pd.DataFrame,
    feeds: list[str],
    weather_factor: float,
    interval_hours: float,
) -> tuple[list[dict[str, Any]], bool]:
    """Compute per-feed expected vs actual totals and detect partial inverter issues.

    For each feed, computes expected kWh (baseline × weather factor) and actual kWh,
    then assigns a status label. If one feed is "dropped" while another is "normal",
    sets partial_issue=True — a signal that one inverter or wiring leg may have failed
    while the other is working correctly.

    Returns:
        (feed_summaries, partial_issue) where:
          feed_summaries — list of per-feed dicts for the response
          partial_issue  — True if one feed is dropped while another is normal
    """
    summaries: list[dict[str, Any]] = []
    for feed in feeds:
        # Apply the weather factor to get the weather-adjusted expected kWh for this feed.
        expected_kw = analysis[f"{feed}_expected_kw"] * weather_factor
        expected_kwh = float((expected_kw * interval_hours).sum())
        actual_kwh = float((analysis[feed] * interval_hours).sum())
        ratio = actual_kwh / expected_kwh if expected_kwh > 0 else None
        summaries.append(
            {
                "feed": feed,
                "expected_kwh": round(expected_kwh, 2),
                "actual_kwh": round(actual_kwh, 2),
                "performance_ratio": round(float(ratio), 3) if ratio is not None else None,
                "status": feed_status(ratio, expected_kwh),
            }
        )

    # Partial issue: at least one feed dropped AND at least one feed normal.
    # Only count feeds with sufficient expected generation to judge.
    dropped = [
        item for item in summaries
        if item["status"] == "dropped" and item["expected_kwh"] >= MIN_DAY_EXPECTED_KWH
    ]
    normal = [
        item for item in summaries
        if item["status"] == "normal" and item["expected_kwh"] >= MIN_DAY_EXPECTED_KWH
    ]
    return summaries, bool(dropped and normal)


def grid_context(window: pd.DataFrame, interval_hours: float) -> dict[str, Any]:
    """Compute grid import/export context from the grid column.

    The grid column represents net exchange with the utility grid:
      positive values → customer is importing (drawing from grid)
      negative values → customer is exporting (selling back / net metering)

    If the grid column is absent or all-null, returns grid_data_available=False.

    Returns a dict with:
      grid_data_available    — bool
      import_kwh             — total kWh drawn from grid in the window
      export_kwh             — total kWh exported to grid (net metering credit source)
      export_interval_count  — number of 15-min intervals where export occurred
    """
    if "grid" not in window.columns or window["grid"].isna().all():
        return {
            "grid_data_available": False,
            "import_kwh": None,
            "export_kwh": None,
            "export_interval_count": None,
        }
    grid = pd.to_numeric(window["grid"], errors="coerce").fillna(0.0)
    return {
        "grid_data_available": True,
        "import_kwh": round(float(grid.clip(lower=0.0).sum() * interval_hours), 2),
        "export_kwh": round(float(grid.clip(upper=0.0).abs().sum() * interval_hours), 2),
        "export_interval_count": int((grid < 0).sum()),
    }

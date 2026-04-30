"""I/O, caching, and time-feature helpers for the Solar Performance agent.

RESPONSIBILITIES
----------------
1. Load and cache the 15-min meter CSV and billing JSON (same mtime_cached pattern
   used by every other agent in this fleet — re-reads from disk only when the file changes).
2. Validate required columns on load (dataid, local_15min, solar).
3. Parse timestamps to UTC-aware, then strip timezone for uniform tz-naive math downstream.
4. Attach time-feature columns (hour, slot, season, date) used by the baseline builder.
5. Provide small utility functions used by other files in this module.

SOLAR COLUMNS IN THE CSV
-------------------------
  solar    → primary inverter feed (kW, positive = generating)
  solar2   → secondary inverter feed if present (some homes have two inverters)
  grid     → net grid exchange (positive = importing, negative = exporting/selling back)

Both solar feeds are clipped to 0.0 — negative values are sensor noise, not real.

TIME SLOTS
----------
The baseline builder works at 15-min slot resolution. Each day has 96 slots:
  slot = hour * 4 + (minute // 15)
  e.g. 14:30 → slot 58  (hour 14, minute 30 → 14*4 + 30//15 = 56+2 = 58)

Comparing "what did this customer generate at slot 58 in July historically?"
gives a much more precise expected value than "what did they generate in July on average?"
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

from src.agents.shared.loaders import load_json, mtime_cached
from src.agents.shared.query_parsing import to_naive


BASE_DIR = Path(__file__).resolve().parents[2]

# Paths can be overridden via environment variables for Docker/CI deployments.
DEFAULT_METER_FILE = Path(
    os.getenv("SOLAR_PERFORMANCE_METER_FILE", str(BASE_DIR / "data" / "15minute_data_sample.csv"))
)
DEFAULT_BILLING_FILE = Path(
    os.getenv("SOLAR_PERFORMANCE_BILLING_FILE", str(BASE_DIR / "data" / "demo_billing_data.json"))
)

# The two solar feed column names the agent knows about.
# Only feeds that are present AND have non-null data are used for a given customer.
SOLAR_FEED_COLUMNS = ("solar", "solar2")

# Fallback interval duration (hours) if it cannot be inferred from timestamp diffs.
DEFAULT_INTERVAL_HOURS = 0.25  # 15 minutes = 0.25 hours


def load_meter_data(path: Path) -> pd.DataFrame:
    """Load and validate the 15-min meter CSV.

    Steps:
      1. Read CSV with low_memory=False (mixed-type columns like solar are common).
      2. Verify that dataid, local_15min, and solar columns are present.
      3. Parse local_15min as UTC-aware datetimes, then strip timezone → tz-naive.
         Stripping timezone makes all subsequent date arithmetic simpler and avoids
         pandas timezone-comparison warnings.
      4. Coerce solar, solar2, and grid to float (CSV may store them as strings).
      5. Sort by dataid then timestamp for deterministic baseline slicing.

    Raises:
      FileNotFoundError — if the CSV doesn't exist at path.
      ValueError        — if required columns are missing or timestamps are invalid.
    """
    if not path.exists():
        raise FileNotFoundError(f"Meter file not found: {path}")
    df = pd.read_csv(path, low_memory=False)

    # Validate required columns before doing any further work.
    required = {"dataid", "local_15min", "solar"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Meter file is missing required columns: {sorted(missing)}")

    # Parse timestamps. utc=True interprets the offset suffix (-05:00) correctly.
    # tz_localize(None) then strips it back to naive — all math stays in local time.
    parsed = pd.to_datetime(df["local_15min"], errors="coerce", utc=True)
    if parsed.isna().any():
        raise ValueError("Invalid timestamps in local_15min.")
    df["local_15min"] = parsed.dt.tz_localize(None)

    # Coerce numeric columns — they may have been read as object dtype from CSV.
    for feed in SOLAR_FEED_COLUMNS:
        if feed in df.columns:
            df[feed] = pd.to_numeric(df[feed], errors="coerce")
    if "grid" in df.columns:
        df["grid"] = pd.to_numeric(df["grid"], errors="coerce")

    return df.sort_values(["dataid", "local_15min"]).reset_index(drop=True)


# Module-level cached loaders — re-read from disk only if the file's mtime changes.
# This is the same pattern used by the anomaly, outage, and weather agents.
cached_meter_data = mtime_cached(load_meter_data, DEFAULT_METER_FILE)
cached_billing_data = mtime_cached(load_json, DEFAULT_BILLING_FILE)


def parse_date_boundary(value: str | pd.Timestamp, *, is_end: bool) -> pd.Timestamp:
    """Convert a YYYY-MM-DD string to a tz-naive Timestamp at start or end of day.

    If the value is already a full ISO datetime (has a 'T' in it), it passes through
    to_naive() directly. If it's a date-only string (10 chars, YYYY-MM-DD), we append
    T00:00:00 (start) or T23:59:59 (end) before converting.

    Example:
        parse_date_boundary("2019-07-01", is_end=False) → Timestamp("2019-07-01 00:00:00")
        parse_date_boundary("2019-07-31", is_end=True)  → Timestamp("2019-07-31 23:59:59")
    """
    text = str(value)
    if (
        len(text) == 10
        and text[4] == "-"
        and text[7] == "-"
        and text.replace("-", "").isdigit()
    ):
        suffix = "T23:59:59" if is_end else "T00:00:00"
        return to_naive(text + suffix)
    return to_naive(value)


def season_for_month(month: int) -> str:
    """Map a month number to a season string used for baseline bucketing.

    Seasons are used as a fallback grouping key when same-month data is sparse.
    Example: month=7 → "summer", month=1 → "winter"
    """
    if month in {12, 1, 2}:
        return "winter"
    if month in {3, 4, 5}:
        return "spring"
    if month in {6, 7, 8}:
        return "summer"
    return "fall"


def infer_interval_hours(rows: pd.DataFrame) -> float:
    """Infer the actual recording interval from timestamp diffs in the data.

    Rather than hardcoding 15 minutes, we compute the median gap between
    consecutive readings. This makes the kWh calculations correct even if the
    data ever comes in at a different resolution (e.g. hourly for some meters).

    Returns DEFAULT_INTERVAL_HOURS (0.25h) if the inference produces a nonsensical result.
    """
    diffs = (
        rows.sort_values("local_15min")["local_15min"]
        .diff()
        .dt.total_seconds()
        .div(3600)
    )
    positive = diffs[diffs > 0]
    if positive.empty:
        return DEFAULT_INTERVAL_HOURS
    median = float(positive.median())
    if not np.isfinite(median) or median <= 0:
        return DEFAULT_INTERVAL_HOURS
    # Clamp to [1 minute, 24 hours] to guard against corrupt data.
    return round(min(max(median, 1 / 60), 24), 4)


def add_time_features(df: pd.DataFrame, feeds: list[str]) -> pd.DataFrame:
    """Attach time-feature columns and a clipped solar_total_kw aggregate.

    Columns added:
      solar_total_kw  — sum of all solar feeds (clipped to 0, NaN-safe)
      month           — 1–12 (used for same-month baseline bucketing)
      hour            — 0–23 (used for same-hour fallback bucketing)
      slot            — 0–95 (15-min slot index: hour*4 + minute//15)
      season          — "winter" / "spring" / "summer" / "fall"
      date            — Python date object (used for per-day aggregation)

    Each feed is also clipped to 0.0 — negative values are sensor noise.
    """
    result = df.copy()
    for feed in feeds:
        result[feed] = pd.to_numeric(result[feed], errors="coerce").fillna(0.0).clip(lower=0.0)

    # Sum all solar feeds into one aggregate column. min_count=1 means NaN if ALL feeds are NaN.
    result["solar_total_kw"] = result[feeds].sum(axis=1, min_count=1).fillna(0.0)

    result["month"] = result["local_15min"].dt.month
    result["hour"] = result["local_15min"].dt.hour
    # slot = which 15-min block of the day: 0 = midnight, 56 = 2pm, 95 = 11:45pm
    result["slot"] = result["local_15min"].dt.hour * 4 + (result["local_15min"].dt.minute // 15)
    result["season"] = result["month"].map(season_for_month)
    result["date"] = result["local_15min"].dt.date
    return result

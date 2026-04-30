"""Multi-tier baseline construction for solar production.

WHAT THIS FILE DOES
-------------------
Builds a per-interval "expected kW" value for every row in the analysis window,
using the customer's own historical data. The expected value answers: "How much
solar should this customer have generated at this time of day, on this type of day?"

WHY A BASELINE IS NEEDED
-------------------------
We can't just compare one month's production to the previous month — solar output
depends heavily on the time of day and the season. A flat monthly average would
say "July production was 30% below June" without accounting for the fact that
June days are longer and sun angles differ. The slot-level baseline removes that
noise by comparing like-for-like intervals.

3-TIER BASELINE LOGIC
---------------------
For each 15-min reading in the window, we look up its expected kW from three
progressively broader groupings, using the next tier only when the narrower one
doesn't have enough samples (< MIN_BUCKET_SAMPLES = 8):

  Tier 1 — same month + same slot  (e.g. "July, 2pm–2:15pm")
            Most precise. Accounts for both season and time-of-day.

  Tier 2 — same season + same slot  (e.g. "summer, 2pm–2:15pm")
            Broader. Used when this customer doesn't have 8+ July readings
            at this slot (e.g. the data only covers a few months).

  Tier 3 — same hour  (e.g. "2pm–3pm")
            Last resort. Very broad — averages across all seasons and days.
            Used when even the season bucket is sparse.

BASELINE ROWS
-------------
The baseline is built from data BEFORE the analysis window (not including the
window itself, which would be circular). By default we look back 90 days.
If there aren't 96+ intervals in that lookback, we fall back to all other
data outside the window.

MIN_BASELINE_INTERVALS = 96 — at least 24 hours of 15-min readings before
proceeding. Below that the baseline is too unreliable to use.
"""

from __future__ import annotations

import pandas as pd


MIN_BASELINE_INTERVALS = 96   # minimum rows needed in the baseline (= 24 hours of 15-min data)
MIN_BUCKET_SAMPLES = 8        # minimum samples per slot bucket before falling back to next tier


def select_baseline_rows(
    customer_rows: pd.DataFrame,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
    lookback_days: int,
) -> tuple[pd.DataFrame, str]:
    """Select historical rows to use as the baseline, with a fallback.

    Primary: rows in the `lookback_days` window immediately before start_ts.
    Fallback: all rows outside the analysis window (before OR after).

    Returns:
        (baseline_df, source_label) where source_label is one of:
          "prior_lookback"            — primary lookback had enough data
          "all_other_history_fallback" — not enough data in lookback, used everything else

    Example:
        Analysis window: 2019-07-01 → 2019-07-31
        lookback_days = 90 → baseline = 2019-04-02 → 2019-06-30
        If that window has < 96 intervals, fallback = all rows outside July.
    """
    lookback_start = start_ts - pd.Timedelta(days=lookback_days)
    prior = customer_rows[
        (customer_rows["local_15min"] < start_ts)
        & (customer_rows["local_15min"] >= lookback_start)
    ].copy()
    if len(prior) >= MIN_BASELINE_INTERVALS:
        return prior, "prior_lookback"

    # Not enough data in the lookback — use all history outside the window.
    fallback = customer_rows[
        (customer_rows["local_15min"] < start_ts)
        | (customer_rows["local_15min"] > end_ts)
    ].copy()
    return fallback, "all_other_history_fallback"


def _aggregate_baseline(
    baseline: pd.DataFrame,
    feed: str,
    keys: list[str],
    prefix: str,
) -> pd.DataFrame:
    """Compute mean, std, and sample count for a feed grouped by keys.

    Used internally to build Tier 1 (month+slot), Tier 2 (season+slot),
    and Tier 3 (hour) lookup tables that get merged onto the analysis window.

    Args:
        baseline: Historical rows (before the analysis window).
        feed:     Column name, e.g. "solar" or "solar2".
        keys:     Group-by columns, e.g. ["month", "slot"] for Tier 1.
        prefix:   Column name prefix for the output, e.g. "solar_primary".
    """
    return (
        baseline.groupby(keys)[feed]
        .agg(["mean", "std", "count"])
        .reset_index()
        .rename(
            columns={
                "mean": f"{prefix}_mean",
                "std": f"{prefix}_std",
                "count": f"{prefix}_count",
            }
        )
    )


def attach_feed_baseline(
    window: pd.DataFrame,
    baseline: pd.DataFrame,
    feed: str,
) -> pd.DataFrame:
    """Attach per-row expected kW, baseline source, sample count, and std for one feed.

    Merges all three tier lookup tables onto the window, then fills the
    `{feed}_expected_kw` column from the best available tier per row.

    Result columns added (example for feed="solar"):
      solar_expected_kw           — the best available expected kW for this interval
      solar_baseline_source       — which tier was used: "same_month_interval",
                                    "same_season_interval", or "same_hour_fallback"
      solar_baseline_sample_count — how many historical readings backed this estimate
      solar_baseline_std_kw       — standard deviation of the baseline bucket

    The temporary merge columns (solar_primary_mean, etc.) are dropped at the end
    to keep the DataFrame clean for downstream analysis.

    Example:
        A row at 2019-07-15 14:00 (month=7, slot=56):
          - Tier 1: finds 45 July readings at slot 56 → uses their mean (45 ≥ 8) ✓
        A row at 2019-07-15 06:00 (month=7, slot=24, early morning):
          - Tier 1: only 3 July readings at slot 24 (< 8) → try Tier 2
          - Tier 2: 12 summer readings at slot 24 → uses their mean ✓
    """
    result = window.copy()

    # Build the three tier lookup tables from the baseline.
    primary = _aggregate_baseline(baseline, feed, ["month", "slot"], f"{feed}_primary")
    seasonal = _aggregate_baseline(baseline, feed, ["season", "slot"], f"{feed}_season")
    hourly = _aggregate_baseline(baseline, feed, ["hour"], f"{feed}_hour")

    # Merge all three tiers onto the window rows by their grouping keys.
    result = result.merge(primary, on=["month", "slot"], how="left")
    result = result.merge(seasonal, on=["season", "slot"], how="left")
    result = result.merge(hourly, on=["hour"], how="left")

    # Column names for the output we're building.
    expected_col = f"{feed}_expected_kw"
    source_col = f"{feed}_baseline_source"
    count_col = f"{feed}_baseline_sample_count"
    std_col = f"{feed}_baseline_std_kw"

    # Start with Tier 1 (most precise).
    result[expected_col] = result[f"{feed}_primary_mean"]
    result[source_col] = "same_month_interval"
    result[count_col] = result[f"{feed}_primary_count"]
    result[std_col] = result[f"{feed}_primary_std"]

    # Where Tier 1 is missing or sparse, fill with Tier 2.
    primary_sparse = (
        result[expected_col].isna()
        | result[count_col].fillna(0).lt(MIN_BUCKET_SAMPLES)
    )
    seasonal_ok = result[f"{feed}_season_count"].fillna(0).ge(MIN_BUCKET_SAMPLES)
    use_seasonal = primary_sparse & seasonal_ok
    result.loc[use_seasonal, expected_col] = result.loc[use_seasonal, f"{feed}_season_mean"]
    result.loc[use_seasonal, source_col] = "same_season_interval"
    result.loc[use_seasonal, count_col] = result.loc[use_seasonal, f"{feed}_season_count"]
    result.loc[use_seasonal, std_col] = result.loc[use_seasonal, f"{feed}_season_std"]

    # Where Tier 2 is also sparse, fill with Tier 3 (last resort).
    still_sparse = result[expected_col].isna() | result[count_col].fillna(0).lt(MIN_BUCKET_SAMPLES)
    hourly_ok = result[f"{feed}_hour_count"].fillna(0).ge(MIN_BUCKET_SAMPLES)
    use_hourly = still_sparse & hourly_ok
    result.loc[use_hourly, expected_col] = result.loc[use_hourly, f"{feed}_hour_mean"]
    result.loc[use_hourly, source_col] = "same_hour_fallback"
    result.loc[use_hourly, count_col] = result.loc[use_hourly, f"{feed}_hour_count"]
    result.loc[use_hourly, std_col] = result.loc[use_hourly, f"{feed}_hour_std"]

    # Clip expected to 0 — negative expected generation is not physically meaningful.
    result[expected_col] = result[expected_col].fillna(0.0).clip(lower=0.0)
    result[count_col] = result[count_col].fillna(0).astype(int)
    result[std_col] = result[std_col].fillna(0.0)

    # Drop the temporary merge columns — they're not needed downstream.
    drop_cols = [
        col
        for col in result.columns
        if col.startswith(f"{feed}_primary_")
        or col.startswith(f"{feed}_season_")
        or col.startswith(f"{feed}_hour_")
    ]
    return result.drop(columns=drop_cols)

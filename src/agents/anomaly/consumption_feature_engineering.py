"""Feature engineering for the anomaly detector.

Produces the per-row features the IsolationForest model trains on:
- total_consumption (kW), grid_import / grid_export
- hour, is_weekend, month
- delta_from_prev (kW change vs. previous interval)
- rolling 7-day mean and ratio_to_rolling_mean
- monthly hour-of-day bucket means/stds with a same-hour fallback
- hourly_zscore against that bucket
"""

from __future__ import annotations

import numpy as np
import pandas as pd

NON_APPLIANCE_COLS = {
    "dataid",
    "local_15min",
    "grid",
    "solar",
    "solar2",
    "leg1v",
    "leg2v",
}

MIN_OBS_PER_USER = 96
ROLLING_WINDOW = 672

def appliance_columns(df: pd.DataFrame) -> list[str]:
    cols: list[str] = []
    for col in df.columns:
        if col in NON_APPLIANCE_COLS:
            continue
        if pd.api.types.is_numeric_dtype(df[col]) and df[col].notna().any():
            cols.append(col)
    return cols

def build_features(df: pd.DataFrame) -> pd.DataFrame:
    cols = appliance_columns(df)
    print('appliance cols are ', cols)
    appliance_sum = (
        df[cols].sum(axis=1, min_count=1) if cols else pd.Series(np.nan, index=df.index)
    )

    if "grid" in df.columns and df["grid"].notna().any():
        df["grid_import"] = df["grid"].clip(lower=0)
        df["grid_export"] = df["grid"].clip(upper=0).abs()
        df["is_solar_household"] = (
            df.groupby("dataid")["grid"].transform(lambda x: (x < 0).any()).astype(int)
        )
        df["total_consumption"] = df["grid_import"].where(df["grid"].notna(), appliance_sum)
    else:
        df["grid_import"] = appliance_sum
        df["grid_export"] = 0.0
        df["is_solar_household"] = 0
        df["total_consumption"] = appliance_sum

    df = df[df["total_consumption"].notna()].copy()

    df["hour"] = df["local_15min"].dt.hour
    df["is_weekend"] = (df["local_15min"].dt.dayofweek >= 5).astype(int)
    df["month"] = df["local_15min"].dt.month
    df["delta_from_prev"] = df.groupby("dataid")["total_consumption"].diff().abs().fillna(0)

    grouped = df.groupby("dataid")["total_consumption"]
    df["rolling_mean_7d"] = grouped.transform(
        lambda x: x.rolling(window=ROLLING_WINDOW, min_periods=MIN_OBS_PER_USER).mean()
    )
    df["ratio_to_rolling_mean"] = df["total_consumption"] / (df["rolling_mean_7d"] + 0.001)

    monthly = (
        df.groupby(["dataid", "hour", "is_weekend", "month"])["total_consumption"]
        .agg(["mean", "std", "count"])
        .reset_index()
    )
    monthly.columns = [
        "dataid",
        "hour",
        "is_weekend",
        "month",
        "hourly_mean",
        "hourly_std",
        "bucket_count",
    ]

    fallback = (
        df.groupby(["dataid", "hour", "is_weekend"])["total_consumption"]
        .agg(["mean", "std"])
        .reset_index()
    )
    fallback.columns = ["dataid", "hour", "is_weekend", "fallback_mean", "fallback_std"]

    monthly = monthly.merge(fallback, on=["dataid", "hour", "is_weekend"], how="left")
    use_fallback = monthly["bucket_count"] < 10
    monthly.loc[use_fallback, "hourly_mean"] = monthly.loc[use_fallback, "fallback_mean"]
    monthly.loc[use_fallback, "hourly_std"] = monthly.loc[use_fallback, "fallback_std"]

    df = df.merge(
        monthly[["dataid", "hour", "is_weekend", "month", "hourly_mean", "hourly_std"]],
        on=["dataid", "hour", "is_weekend", "month"],
        how="left",
    )
    df["hourly_zscore"] = (
        (df["total_consumption"] - df["hourly_mean"]) / (df["hourly_std"] + 0.001)
    )
    return df

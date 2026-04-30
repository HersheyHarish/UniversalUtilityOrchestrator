"""Serialize scored rows into the agent's output payload."""

from __future__ import annotations

from typing import Any

import pandas as pd

from .cached_detection_pipeline import normalize_timestamp
from .anomaly_models import ResolvedAnomalyRequest

def serialize_spikes(rows: pd.DataFrame, limit: int) -> list[dict[str, Any]]:
    if rows.empty:
        return []

    ranked = rows.copy()
    ranked["abs_zscore"] = ranked["hourly_zscore"].abs().fillna(0)
    ranked = ranked.sort_values(
        ["anomaly_signals", "abs_zscore", "if_score"],
        ascending=[False, False, True],
    ).head(limit)

    spikes: list[dict[str, Any]] = []
    for _, row in ranked.iterrows():
        signals: list[str] = []
        if int(row["if_anomaly"]) == 1:
            signals.append("isolation_forest")
        if int(row["zscore_spike"]) == 1:
            signals.append("zscore_spike")

        spikes.append(
            {
                "user_id": int(row["dataid"]),
                "timestamp": row["local_15min"].isoformat(),
                "total_consumption_kw": round(float(row["total_consumption"]), 3),
                "hourly_mean_kw": round(float(row["hourly_mean"]), 3)
                if pd.notna(row["hourly_mean"])
                else None,
                "hourly_std_kw": round(float(row["hourly_std"]), 3)
                if pd.notna(row["hourly_std"])
                else None,
                "hourly_zscore": round(float(row["hourly_zscore"]), 3)
                if pd.notna(row["hourly_zscore"])
                else None,
                "if_score": round(float(row["if_score"]), 6)
                if pd.notna(row["if_score"])
                else None,
                "anomaly_signals": int(row["anomaly_signals"]),
                "signals": signals,
            }
        )
    return spikes

def response_severity(spikes: pd.DataFrame) -> str:
    if spikes.empty:
        return "low"

    if (
        int(spikes["anomaly_signals"].max()) >= 2
        and float(spikes["hourly_zscore"].abs().max()) >= 6
    ):
        return "critical"
    if int(spikes["anomaly_signals"].max()) >= 2 or len(spikes) >= 3:
        return "high"
    return "medium"

def response_summary(request: ResolvedAnomalyRequest, spikes: pd.DataFrame, severity: str) -> str:
    if spikes.empty:
        return (
            f"No interval-level usage anomalies were detected for {request.customer_id or request.user_id} "
            f"in the requested window."
        )

    return (
        f"Detected {len(spikes)} interval-level usage anomalies for "
        f"{request.customer_id or request.user_id} in the requested window; "
        f"top events are shown below. Severity is {severity}."
    )

def build_response(request: ResolvedAnomalyRequest, df: pd.DataFrame) -> dict[str, Any]:
    reference_end = df["local_15min"].max()
    start_ts = normalize_timestamp(request.start_date, reference_end)
    end_ts = normalize_timestamp(request.end_date, reference_end)

    if start_ts > end_ts:
        raise ValueError("start_date must be earlier than or equal to end_date.")

    user_id = int(request.user_id)
    if user_id not in set(df["dataid"].unique()):
        raise ValueError(f"Unknown user_id: {user_id}")

    window = df[(df["local_15min"] >= start_ts) & (df["local_15min"] <= end_ts)].copy()
    if window.empty:
        raise ValueError("No usage records were found in the requested time window.")

    household_rows = window[window["dataid"] == user_id].copy()
    if household_rows.empty:
        raise ValueError(
            f"No usage records were found for household {user_id} in the requested time window."
        )

    household_spikes = household_rows[household_rows["is_anomaly"] == 1].copy()
    other_spikes = window[(window["dataid"] != user_id) & (window["is_anomaly"] == 1)].copy()
    other_households = sorted(other_spikes["dataid"].unique().tolist())
    severity = response_severity(household_spikes)

    return {
        "user_id": user_id,
        "customer_id": request.customer_id,
        "start_date": start_ts.isoformat(),
        "end_date": end_ts.isoformat(),
        "spike_detected": bool(len(household_spikes) > 0),
        "spike_count": int(len(household_spikes)),
        "only_this_house_had_spike": bool(
            len(household_spikes) > 0 and len(other_households) == 0
        ),
        "other_households_with_spikes_count": int(len(other_households)),
        "severity": severity,
        "summary": response_summary(request, household_spikes, severity),
        "spikes": serialize_spikes(household_spikes, request.max_results),
    }

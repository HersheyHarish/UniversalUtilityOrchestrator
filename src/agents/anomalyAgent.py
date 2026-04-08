from __future__ import annotations

import os
import re
import threading
import warnings
from calendar import monthrange
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler


warnings.filterwarnings("ignore")


app = FastAPI(title="Anomaly Detection Agent")


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_FILE = Path(
    os.getenv("ANOMALY_INPUT_FILE", str(BASE_DIR / "data" / "15minute_data_sample.csv"))
)
CUSTOMER_TO_USER_ID = {
    "CUST-1001": 5997,
    "CUST-1002": 3488,
}

IF_CONTAMINATION = 0.02
ZSCORE_THRESHOLD = 3.0
MIN_OBS_PER_USER = 96
TRAIN_FRACTION = 0.80
ROLLING_WINDOW = 672

NON_APPLIANCE_COLS = {
    "dataid",
    "local_15min",
    "grid",
    "solar",
    "solar2",
    "leg1v",
    "leg2v",
}

_CACHE_LOCK = threading.Lock()
_SCORED_DATA_CACHE: tuple[int, pd.DataFrame] | None = None


class AnomalyRequest(BaseModel):
    query: str = "Check spikes"
    user_id: Optional[int] = None
    customer_id: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    max_results: int = Field(default=5, ge=1, le=20)


class ResolvedAnomalyRequest(BaseModel):
    query: str
    user_id: int
    customer_id: Optional[str] = None
    start_date: str
    end_date: str
    max_results: int = Field(default=5, ge=1, le=20)


def normalize_timestamp(value: str | pd.Timestamp, reference: pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if reference.tzinfo is not None:
        if ts.tzinfo is None:
            return ts.tz_localize(reference.tzinfo)
        return ts.tz_convert(reference.tzinfo)
    if ts.tzinfo is not None:
        return ts.tz_localize(None)
    return ts


def normalize_customer_id(customer_id: str | int) -> str:
    text = str(customer_id).strip().upper()
    match = re.search(r"(\d+)", text)
    if not match:
        return text
    return f"CUST-{int(match.group(1)):04d}"


def resolve_anomaly_inputs(request: AnomalyRequest, df: pd.DataFrame) -> ResolvedAnomalyRequest:
    user_id = request.user_id
    customer_id = request.customer_id
    start_date = request.start_date
    end_date = request.end_date
    query = request.query or "Check spikes"

    if customer_id is None:
        customer_match = re.search(
            r"\b(?:customer|account|acct|cust|user)\s*(?:id\s*)?(?:#|:|=)?\s*((?:CUST-)?\d+)\b",
            query,
            flags=re.IGNORECASE,
        )
        if customer_match:
            customer_id = customer_match.group(1)

    if start_date is None or end_date is None:
        date_match = re.search(
            r"\b(\d{4}-\d{2}-\d{2})\s*-\s*(\d{4}-\d{2}-\d{2})\b",
            query,
        )
        if date_match:
            start_date = f"{date_match.group(1)}T00:00:00"
            end_date = f"{date_match.group(2)}T23:59:59"
        else:
            month_match = re.search(
                r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})\b",
                query,
                flags=re.IGNORECASE,
            )
            if month_match:
                month = datetime.strptime(month_match.group(1), "%B").month
                year = int(month_match.group(2))
                last_day = monthrange(year, month)[1]
                start_date = f"{year:04d}-{month:02d}-01T00:00:00"
                end_date = f"{year:04d}-{month:02d}-{last_day:02d}T23:59:59"

    if user_id is None and customer_id is not None:
        normalized_customer_id = normalize_customer_id(customer_id)
        if normalized_customer_id not in CUSTOMER_TO_USER_ID:
            raise ValueError(f"Unknown customer_id: {customer_id}")
        user_id = CUSTOMER_TO_USER_ID[normalized_customer_id]
        customer_id = normalized_customer_id

    if user_id is None:
        raise ValueError(
            "Anomaly queries must include customer CUST-1001 or CUST-1002, or an explicit numeric user_id."
        )
    if start_date is None or end_date is None:
        raise ValueError(
            "Anomaly queries must include a date range like `2019-07-01 - 2019-07-31` or a month and year like `July 2019`."
        )

    if int(user_id) not in set(df["dataid"].unique()):
        raise ValueError(f"Unknown user_id: {user_id}")

    return ResolvedAnomalyRequest(
        query=query,
        user_id=int(user_id),
        customer_id=normalize_customer_id(customer_id) if customer_id is not None else None,
        start_date=start_date,
        end_date=end_date,
        max_results=request.max_results,
    )


def load_data(input_file: Path) -> pd.DataFrame:
    if not input_file.exists():
        raise FileNotFoundError(f"Input file not found: {input_file}")

    df = pd.read_csv(input_file, low_memory=False)
    required = {"dataid", "local_15min"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Input file is missing required columns: {sorted(missing)}")

    df["local_15min"] = pd.to_datetime(df["local_15min"], utc=False, errors="coerce")
    if df["local_15min"].isna().any():
        raise ValueError("Found invalid timestamps in local_15min.")

    return df.sort_values(["dataid", "local_15min"]).reset_index(drop=True)


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


def score_anomalies(df: pd.DataFrame) -> pd.DataFrame:
    feature_cols = [
        "total_consumption",
        "grid_export",
        "hour",
        "is_weekend",
        "delta_from_prev",
        "ratio_to_rolling_mean",
        "hourly_zscore",
    ]

    df["if_anomaly"] = 0
    df["if_score"] = np.nan
    df["has_model"] = False
    df["split"] = "excluded"

    for user_id in df["dataid"].unique():
        user_rows = df[df["dataid"] == user_id]
        if len(user_rows) < MIN_OBS_PER_USER:
            continue

        split_point = int(len(user_rows) * TRAIN_FRACTION)
        train_rows = user_rows.iloc[:split_point]
        holdout_rows = user_rows.iloc[split_point:]
        df.loc[train_rows.index, "split"] = "train"
        df.loc[holdout_rows.index, "split"] = "holdout"

        train_data = train_rows[feature_cols].dropna()
        if len(train_data) < MIN_OBS_PER_USER:
            continue

        model = IsolationForest(
            n_estimators=200,
            contamination=IF_CONTAMINATION,
            random_state=42,
            n_jobs=-1,
        )
        scaler = StandardScaler()
        x_train = scaler.fit_transform(train_data)
        model.fit(x_train)

        usable_rows = user_rows[feature_cols].dropna()
        if usable_rows.empty:
            continue

        x_all = scaler.transform(usable_rows)
        df.loc[usable_rows.index, "if_score"] = model.decision_function(x_all)
        df.loc[usable_rows.index, "if_anomaly"] = (model.predict(x_all) == -1).astype(int)
        df.loc[user_rows.index, "has_model"] = True

    df["zscore_spike"] = (df["hourly_zscore"].abs() > ZSCORE_THRESHOLD).astype(int)
    df["anomaly_signals"] = df["if_anomaly"] + df["zscore_spike"]
    df["is_anomaly"] = (df["anomaly_signals"] >= 1).astype(int)
    return df


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
        "severity": response_severity(household_spikes),
        "spikes": serialize_spikes(household_spikes, request.max_results),
    }


def run_detection(input_file: Path) -> pd.DataFrame:
    global _SCORED_DATA_CACHE

    resolved_input = input_file.resolve()
    file_mtime_ns = resolved_input.stat().st_mtime_ns

    with _CACHE_LOCK:
        if _SCORED_DATA_CACHE is not None:
            cached_mtime_ns, cached_df = _SCORED_DATA_CACHE
            if cached_mtime_ns == file_mtime_ns:
                return cached_df

    df = load_data(resolved_input)
    df = build_features(df)
    scored = score_anomalies(df)

    with _CACHE_LOCK:
        _SCORED_DATA_CACHE = (file_mtime_ns, scored)

    return scored


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "agent": "anomaly_detection_agent"}


@app.post("/api/anomaly_detection_agent")
def anomaly_detection_agent(request: AnomalyRequest) -> dict[str, Any]:
    try:
        scored = run_detection(DEFAULT_INPUT_FILE)
        resolved = resolve_anomaly_inputs(request, scored)
        return build_response(resolved, scored)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))

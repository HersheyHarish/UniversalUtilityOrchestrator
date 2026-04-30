"""I/O and the cached scoring pipeline for the anomaly detector.

`run_detection()` returns the fully scored DataFrame. The result is cached
behind `mtime_cached`, so the IsolationForest trains once per CSV mtime and
all subsequent requests reuse the scored frame.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from src.agents.shared.loaders import load_json, mtime_cached

from .consumption_feature_engineering import build_features
from .isolation_forest_scoring import score_anomalies

BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_INPUT_FILE = Path(
    os.getenv("ANOMALY_INPUT_FILE", str(BASE_DIR / "data" / "15minute_data_sample.csv"))
)
DEFAULT_BILLING_FILE = Path(
    os.getenv("ANOMALY_BILLING_FILE", str(BASE_DIR / "data" / "demo_billing_data.json"))
)

# Cached loader for the billing JSON. Provides the customer → meter_dataid mapping
# so we don't hardcode it in Python. Same mtime_cached pattern as all other agents.
cached_billing_data = mtime_cached(load_json, DEFAULT_BILLING_FILE)

def normalize_timestamp(value: str | pd.Timestamp, reference: pd.Timestamp) -> pd.Timestamp:
    """Align an incoming timestamp to the tz of a reference timestamp from the data."""
    ts = pd.Timestamp(value)
    if reference.tzinfo is not None:
        if ts.tzinfo is None:
            return ts.tz_localize(reference.tzinfo)
        return ts.tz_convert(reference.tzinfo)
    if ts.tzinfo is not None:
        return ts.tz_localize(None)
    return ts

def load_data(input_file: Path) -> pd.DataFrame:
    if not input_file.exists():
        raise FileNotFoundError(f"Input file not found: {input_file}")

    df = pd.read_csv(input_file, low_memory=False)
    required = {"dataid", "local_15min"}
    missing = required - set(df.columns)
    print('missing is ', missing)
    if missing:
        raise ValueError(f"Input file is missing required columns: {sorted(missing)}")

    df["local_15min"] = pd.to_datetime(df["local_15min"], utc=False, errors="coerce")
    if df["local_15min"].isna().any():
        raise ValueError("Found invalid timestamps in local_15min.")

    return df.sort_values(["dataid", "local_15min"]).reset_index(drop=True)

def _load_features_score(input_file: Path) -> pd.DataFrame:
    df = load_data(input_file)
    df = build_features(df)
    return score_anomalies(df)

run_detection = mtime_cached(_load_features_score, DEFAULT_INPUT_FILE)

if __name__ == "__main__":
      df = run_detection()                                                                                                                      
      print(df.shape)
      print(df[df["is_anomaly"]==1][["dataid","local_15min","hourly_zscore"]].head(10)) 
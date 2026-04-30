"""I/O and cache wiring for the Bill Shock Forecast Agent.

ROLE IN THE FLOW
----------------
This file owns the two data sources the agent needs:

  1. METER DATA  — the 15-minute CSV (same file as the anomaly agent uses).
                   Columns: dataid, local_15min, grid, solar, appliances…
                   Loaded once, then cached by file mtime via `mtime_cached`.

  2. BILLING DATA — a JSON file containing account profiles and invoice history.
                   Structure:
                       {
                         "accounts": {
                           "CUST-1001": {
                             "meter_dataid": 5997,
                             "plan": { "name": "...", "base_charge": 10.0,
                                       "baseline_kwh": 500, "overage_rate": 0.12 },
                             ...
                           }
                         },
                         "invoices": {
                           "CUST-1001": [
                             { "period": "2019-06", "total_kwh": 480, "total": 67.60 },
                             ...
                           ]
                         }
                       }

FLOW POSITION: disk → load_meter_data / load_json → cached_* → bill_shock_service
The two cached callables are imported directly by bill_shock_service.py and
called at the top of every request handler.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from src.agents.shared.loaders import load_json, mtime_cached


BASE_DIR = Path(__file__).resolve().parents[2]

# Resolved from env var if set (useful for Docker / CI), otherwise the repo's
# sample data file. The anomaly agent uses the same CSV.
DEFAULT_METER_FILE = Path(
    os.getenv("BILL_SHOCK_METER_FILE", str(BASE_DIR / "data" / "15minute_data_sample.csv"))
)
DEFAULT_BILLING_FILE = Path(
    os.getenv("BILL_SHOCK_BILLING_FILE", str(BASE_DIR / "data" / "demo_billing_data.json"))
)


def load_meter_data(path: Path) -> pd.DataFrame:
    """Read and normalize the raw 15-min CSV.

    Key transformation: timestamps are parsed as UTC then stripped of timezone
    info (tz_localize(None)) so all later comparisons are tz-naive. This differs
    slightly from the anomaly agent which preserves the original tz.

    Returns a DataFrame sorted by (dataid, local_15min) — same shape the
    anomaly agent works with, so both agents can share the same CSV.
    """
    if not path.exists():
        raise FileNotFoundError(f"Meter file not found: {path}")
    df = pd.read_csv(path, low_memory=False)

    # Parse with utc=True to handle any tz-aware strings, then strip tz so all
    # downstream comparisons use simple tz-naive Timestamps.
    parsed = pd.to_datetime(df["local_15min"], errors="coerce", utc=True)
    if parsed.isna().any():
        raise ValueError("Invalid timestamps in local_15min.")
    df["local_15min"] = parsed.dt.tz_localize(None)

    return df.sort_values(["dataid", "local_15min"]).reset_index(drop=True)


# These are the two callables imported by bill_shock_service.py.
# Each call checks the file's mtime; if it hasn't changed the cached result is
# returned instantly (no re-parse, no re-read). If the file changes on disk the
# cache is automatically invalidated on the next request.
#
# Usage in bill_shock_service.py:
#   df      = cached_meter_data()   # → pd.DataFrame
#   billing = cached_billing_data() # → dict with "accounts" and "invoices" keys
cached_meter_data = mtime_cached(load_meter_data, DEFAULT_METER_FILE)
cached_billing_data = mtime_cached(load_json, DEFAULT_BILLING_FILE)

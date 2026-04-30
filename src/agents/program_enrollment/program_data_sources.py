"""I/O and cache wiring for the Program Enrollment Simulation Agent."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from src.agents.shared.loaders import load_json, mtime_cached
from src.agents.shared.query_parsing import to_naive


BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_BILLING_FILE = Path(
    os.getenv("PROGRAM_BILLING_FILE", str(BASE_DIR / "data" / "demo_billing_data.json"))
)
DEFAULT_METER_FILE = Path(
    os.getenv("PROGRAM_METER_FILE", str(BASE_DIR / "data" / "15minute_data_sample.csv"))
)

INTERVAL_HOURS = 0.25

NON_APPLIANCE_COLS = {
    "dataid", "local_15min", "grid", "solar", "solar2", "leg1v", "leg2v",
}


def load_meter_data(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Meter file not found: {path}")
    df = pd.read_csv(path, low_memory=False)
    parsed = pd.to_datetime(df["local_15min"], errors="coerce", utc=True)
    if parsed.isna().any():
        raise ValueError("Invalid timestamps in local_15min.")
    df["local_15min"] = parsed.dt.tz_localize(None)
    return df.sort_values(["dataid", "local_15min"]).reset_index(drop=True)


cached_billing_data = mtime_cached(load_json, DEFAULT_BILLING_FILE)
cached_meter_data = mtime_cached(load_meter_data, DEFAULT_METER_FILE)


def find_invoice_for_cycle(
    invoices: list[dict[str, Any]],
    cycle_start: Optional[pd.Timestamp],
    cycle_end: Optional[pd.Timestamp],
) -> Optional[dict[str, Any]]:
    if not invoices:
        return None
    if cycle_start is None or cycle_end is None:
        return invoices[-1]
    cs = cycle_start.normalize()
    ce = cycle_end.normalize()
    for inv in invoices:
        try:
            inv_start = to_naive(inv["billing_start"]).normalize()
            inv_end = to_naive(inv["billing_end"]).normalize()
        except (KeyError, ValueError):
            continue
        if inv_start <= ce and inv_end >= cs:
            return inv
    return invoices[-1]

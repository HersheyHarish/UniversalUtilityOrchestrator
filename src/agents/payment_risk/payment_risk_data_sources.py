"""I/O and cache wiring for the Payment Risk & Hardship Agent."""

from __future__ import annotations

import os
from pathlib import Path

from src.agents.shared.loaders import load_json, mtime_cached


BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_BILLING_FILE = Path(
    os.getenv("PAYMENT_RISK_BILLING_FILE", str(BASE_DIR / "data" / "demo_billing_data.json"))
)
DEFAULT_PAYMENTS_FILE = Path(
    os.getenv("PAYMENT_RISK_PAYMENTS_FILE", str(BASE_DIR / "data" / "demo_payments.json"))
)


cached_billing_data = mtime_cached(load_json, DEFAULT_BILLING_FILE)
cached_payments_data = mtime_cached(load_json, DEFAULT_PAYMENTS_FILE)

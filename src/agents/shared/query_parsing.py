"""Shared query-parsing helpers used by every agent that accepts a NL `query`.

These primitives handle the common boilerplate of pulling a customer id, a date
range or month/year, and an `as of` date out of a free-text request string. Each
agent's own `resolve_*_inputs` function composes these to build its own
domain-specific resolved request.
"""

from __future__ import annotations

import re
from calendar import monthrange
from datetime import datetime
from typing import Optional

import pandas as pd


BARE_CUSTOMER_ID_PATTERN = re.compile(r"\bCUST-\d+\b", re.IGNORECASE)
CUSTOMER_ID_PATTERN = re.compile(
    r"\b(?:customer|account|acct|cust)\s*(?:id\s*)?(?:#|:|=)?\s*((?:CUST-)?\d+)\b",
    re.IGNORECASE,
)
DATE_RANGE_PATTERN = re.compile(r"\b(\d{4}-\d{2}-\d{2})\s*-\s*(\d{4}-\d{2}-\d{2})\b")
MONTH_YEAR_PATTERN = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})\b",
    re.IGNORECASE,
)
AS_OF_PATTERN = re.compile(r"\bas\s*[-_]?\s*of\s+(\d{4}-\d{2}-\d{2})\b", re.IGNORECASE)


def normalize_customer_id(value: str | int) -> str:
    """Coerce variants like `customer 1001`, `1001`, `cust-1001` → `CUST-1001`."""
    text = str(value).strip().upper()
    match = re.search(r"(\d+)", text)
    if not match:
        return text
    return f"CUST-{int(match.group(1)):04d}"


def to_naive(value: str | pd.Timestamp) -> pd.Timestamp:
    """Return a tz-naive pandas Timestamp; tz-aware inputs are converted to UTC then stripped."""
    ts = pd.Timestamp(value)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return ts


def extract_customer_id(query: str) -> Optional[str]:
    """Pull a CUST-style id out of a natural-language query, or None if absent."""
    bare_match = BARE_CUSTOMER_ID_PATTERN.search(query)
    if bare_match:
        return bare_match.group(0)
    match = CUSTOMER_ID_PATTERN.search(query)
    return match.group(1) if match else None


def parse_query_dates(query: str) -> tuple[Optional[pd.Timestamp], Optional[pd.Timestamp]]:
    """Return (cycle_start, cycle_end) parsed from a query, or (None, None).

    Recognises:
      - explicit ISO ranges like `2019-07-01 - 2019-07-31`
      - month/year phrases like `July 2019` (full calendar month)
    """
    range_match = DATE_RANGE_PATTERN.search(query)
    if range_match:
        return (
            to_naive(f"{range_match.group(1)}T00:00:00"),
            to_naive(f"{range_match.group(2)}T23:59:59"),
        )
    month_match = MONTH_YEAR_PATTERN.search(query)
    if month_match:
        month = datetime.strptime(month_match.group(1), "%B").month
        year = int(month_match.group(2))
        last_day = monthrange(year, month)[1]
        return (
            pd.Timestamp(year=year, month=month, day=1),
            pd.Timestamp(year=year, month=month, day=last_day, hour=23, minute=59, second=59),
        )
    return None, None


def parse_as_of(query: str) -> Optional[pd.Timestamp]:
    """Pull an `as of YYYY-MM-DD` mid-cycle date out of a query, or None."""
    match = AS_OF_PATTERN.search(query)
    return to_naive(match.group(1)) if match else None

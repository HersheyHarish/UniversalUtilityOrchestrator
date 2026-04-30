"""Resolve a BillShockRequest to a fully-specified set of inputs.

ROLE IN THE FLOW
----------------
This is the second stage after the raw HTTP request is parsed by Pydantic.
Its job is to take the "maybe-null" BillShockRequest fields and produce a
complete, validated dict that every downstream function can use without
any further null-checking.

Resolution order for each field:
  customer_id  → explicit field → extracted from query string
  cycle_start  → explicit field → parsed from query ("July 2019" → 2019-07-01)
                                → first day of the as_of month (fallback)
  cycle_end    → explicit field → parsed from query ("July 2019" → 2019-07-31)
                                → last day of cycle_start's month (fallback)
  as_of        → explicit field → parsed from query ("as of 2019-07-15")
                                → latest meter reading inside the cycle (fallback)

The shared query_parsing helpers (extract_customer_id, parse_query_dates,
parse_as_of) are the same ones used by the anomaly and billing agents.

FLOW POSITION: BillShockRequest → resolve_inputs → build_response (in forecast_response_payloads.py)

Example input (what the orchestrator typically sends):
    query = "Will CUST-1002 have bill shock for July 2019 as of 2019-07-15?"
    customer_id = None, as_of = None, cycle_start = None, cycle_end = None

Example output dict:
    {
      "query": "Will CUST-1002 have bill shock for July 2019 as of 2019-07-15?",
      "customer_id": "CUST-1002",
      "account": { "meter_dataid": 3488, "plan": {...}, ... },
      "dataid": 3488,
      "as_of": Timestamp("2019-07-15"),
      "cycle_start": Timestamp("2019-07-01"),
      "cycle_end": Timestamp("2019-07-31 23:59:59"),
      "lookback_months": 6
    }
"""

from __future__ import annotations

from calendar import monthrange
from typing import Any

import pandas as pd

from src.agents.shared.query_parsing import (
    extract_customer_id,
    normalize_customer_id,
    parse_as_of,
    parse_query_dates,
    to_naive,
)

from .bill_shock_models import BillShockRequest


def resolve_inputs(
    request: BillShockRequest,
    df: pd.DataFrame,
    billing: dict[str, Any],
) -> dict[str, Any]:
    """Return a fully-resolved input dict from a partially-specified BillShockRequest.

    Args:
        request: The validated Pydantic request object from the HTTP caller.
        df:      The full tz-naive meter DataFrame (all customers, all time).
        billing: The billing JSON dict with "accounts" and "invoices" keys.

    Raises:
        ValueError: If customer_id is missing/unknown, date logic is invalid,
                    or there is no meter data for the customer in the cycle.
    """
    query = (request.query or "Forecast bill").strip()

    # --- 1. Resolve customer_id --------------------------------------------------
    # Try the explicit field first; fall back to regex-parsing the query string.
    # normalize_customer_id coerces any variant ("1001", "cust1001") → "CUST-1001".
    customer_id = request.customer_id or extract_customer_id(query)
    if customer_id is None:
        raise ValueError(
            "Bill-shock queries must include a customer id, for example `customer CUST-1001`."
        )
    customer_id = normalize_customer_id(customer_id)

    # --- 2. Look up account in billing JSON -------------------------------------
    # The account dict contains the plan details (base_charge, overage_rate, etc.)
    # and the numeric meter_dataid needed to look up rows in the meter CSV.
    accounts = billing.get("accounts", {})
    if customer_id not in accounts:
        raise ValueError(f"Unknown customer_id: {customer_id}")
    account = accounts[customer_id]
    dataid = int(account["meter_dataid"])  # e.g. 5997 for CUST-1001

    # Confirm the dataid actually has rows in the meter data before going further.
    customer_rows = df[df["dataid"] == dataid]
    if customer_rows.empty:
        raise ValueError(f"No meter data for {customer_id} (dataid {dataid}).")

    # --- 3. Parse dates from query (used as fallbacks below) --------------------
    # parse_as_of: looks for "as of YYYY-MM-DD" pattern
    # parse_query_dates: looks for "YYYY-MM-DD - YYYY-MM-DD" or "July 2019"
    parsed_as_of = parse_as_of(query)
    parsed_start, parsed_end = parse_query_dates(query)

    # --- 4. Resolve cycle_start -------------------------------------------------
    # Priority: explicit field → parsed from query → first day of as_of's month
    if request.cycle_start:
        cycle_start = to_naive(request.cycle_start)
    elif parsed_start is not None:
        cycle_start = parsed_start
    else:
        # Fall back: use as_of (or the latest meter timestamp) to anchor the month.
        ref = to_naive(request.as_of) if request.as_of else pd.Timestamp(customer_rows["local_15min"].max())
        cycle_start = ref.normalize().replace(day=1)  # midnight on the 1st of that month

    # --- 5. Resolve cycle_end ---------------------------------------------------
    # Priority: explicit field → parsed from query → last second of cycle_start's month
    if request.cycle_end:
        cycle_end = to_naive(request.cycle_end)
    elif parsed_end is not None:
        cycle_end = parsed_end
    else:
        last_day = monthrange(cycle_start.year, cycle_start.month)[1]
        # e.g. July → last_day=31 → 2019-07-31 23:59:59 (inclusive end)
        cycle_end = cycle_start.replace(day=last_day, hour=23, minute=59, second=59)

    if cycle_start >= cycle_end:
        raise ValueError("cycle_start must be earlier than cycle_end.")

    # --- 6. Resolve as_of -------------------------------------------------------
    # Priority: explicit field → parsed from query → latest meter reading in cycle
    # as_of represents "forecast today" — the last day we have real data for.
    if request.as_of:
        as_of = to_naive(request.as_of)
    elif parsed_as_of is not None:
        as_of = parsed_as_of
    else:
        # Default: use the latest meter reading that falls within the billing cycle.
        in_cycle = customer_rows[
            (customer_rows["local_15min"] >= cycle_start)
            & (customer_rows["local_15min"] <= cycle_end)
        ]
        if in_cycle.empty:
            raise ValueError(
                f"No meter data for {customer_id} in cycle "
                f"{cycle_start.date()} – {cycle_end.date()}."
            )
        as_of = pd.Timestamp(in_cycle["local_15min"].max())

    if as_of < cycle_start or as_of > cycle_end:
        raise ValueError("as_of must fall within [cycle_start, cycle_end].")

    # Return a plain dict (not a Pydantic model) because it contains Timestamps
    # and nested account dicts that don't map cleanly to a fixed schema.
    return {
        "query": query,
        "customer_id": customer_id,
        "account": account,       # full plan dict — passed to apply_tariff()
        "dataid": dataid,         # numeric meter id — passed to consumption_series_kwh()
        "as_of": as_of,           # Timestamp — the "forecast today" boundary
        "cycle_start": cycle_start,
        "cycle_end": cycle_end,
        "lookback_months": request.lookback_months,
    }

"""Translate a SolarPerformanceRequest into the resolved dict the analysis pipeline consumes.

WHAT THIS FILE DOES
-------------------
Takes the raw HTTP request (which may have most fields missing) and produces a fully
resolved dict with everything the analysis pipeline needs:
  - customer_id (normalized)
  - dataid (the numeric meter ID from billing JSON)
  - customer_rows (all 15-min readings for this customer)
  - window (the subset of rows inside the requested date range)
  - solar_feeds (which feed columns have real data: ["solar"] or ["solar", "solar2"])
  - start_ts / end_ts (tz-naive Timestamps)
  - credit_rate_usd_per_kwh (explicit or defaulted from plan)
  - weather_context (extracted from request.weather_context or request.context)

RESOLUTION ORDER
----------------
  customer_id  → explicit field → extracted from query string
  start_date   → explicit field → parsed from query → (end_ts - recent_days)
  end_date     → explicit field → parsed from query → latest meter timestamp

SOLAR FEED DETECTION
--------------------
Not every customer has a solar2 column with real data. This file checks which feeds
are present in the CSV AND have at least one non-null value for this customer, then
passes only those feeds to the analysis pipeline.

CREDIT RATE
-----------
The financial impact calculation needs a $/kWh rate. If the caller doesn't provide
credit_rate_usd_per_kwh, we use the customer's plan.overage_rate as a proxy for their
net-metering credit rate. This isn't perfectly accurate but is a reasonable estimate
for a demo.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.agents.shared.query_parsing import (
    extract_customer_id,
    normalize_customer_id,
    parse_query_dates,
)

from .solar_data_sources import SOLAR_FEED_COLUMNS, parse_date_boundary
from .solar_monitoring_models import SolarPerformanceRequest
from .solar_weather_adjustment import extract_weather_context


def resolve_inputs(
    request: SolarPerformanceRequest,
    df: pd.DataFrame,
    billing: dict[str, Any],
) -> dict[str, Any]:
    """Parse and validate the request into a fully-resolved dict.

    Args:
        request: Validated Pydantic request from the HTTP caller.
        df:      Full meter DataFrame from cached_meter_data().
        billing: Parsed billing JSON from cached_billing_data().

    Returns:
        A dict containing all data the analysis pipeline needs. Keys:
          query, customer_id, account, dataid, customer_rows, window,
          solar_feeds, start_ts, end_ts, lookback_days, underperformance_ratio,
          min_underperforming_intervals, min_underperforming_days,
          credit_rate_usd_per_kwh, credit_rate_source, weather_context

    Raises:
        ValueError — missing customer_id, unknown customer, no solar data,
                     no meter data in window, bad date order.
    """
    query = (request.query or "Check solar performance").strip()

    # --- Resolve customer_id ---------------------------------------------------
    customer_id = request.customer_id or extract_customer_id(query)
    if not customer_id:
        raise ValueError(
            "Solar performance queries must include a customer id, for example `customer CUST-1001`."
        )
    customer_id = normalize_customer_id(customer_id)

    accounts = billing.get("accounts", {})
    if customer_id not in accounts:
        raise ValueError(f"Unknown customer_id: {customer_id}")

    # --- Get this customer's meter rows ----------------------------------------
    account = accounts[customer_id]
    dataid = int(account["meter_dataid"])  # numeric meter ID in the CSV
    customer_rows = df[df["dataid"] == dataid].copy()
    if customer_rows.empty:
        raise ValueError(f"No meter data for {customer_id} (dataid {dataid}).")

    # --- Detect which solar feeds have real data --------------------------------
    # A feed is usable only if the column exists AND has at least one non-null value.
    # This is how the agent auto-detects whether solar2 is wired up for this customer.
    feeds = [
        feed
        for feed in SOLAR_FEED_COLUMNS
        if feed in customer_rows.columns and customer_rows[feed].notna().any()
    ]
    if not feeds:
        raise ValueError(f"No solar production columns with data were found for {customer_id}.")

    # --- Resolve date range ----------------------------------------------------
    # Priority: explicit field > parsed from query > default (recent_days / latest reading)
    parsed_start, parsed_end = parse_query_dates(query)
    start_ts = parse_date_boundary(request.start_date, is_end=False) if request.start_date else parsed_start
    end_ts = parse_date_boundary(request.end_date, is_end=True) if request.end_date else parsed_end

    latest_ts = pd.Timestamp(customer_rows["local_15min"].max())
    if end_ts is None:
        end_ts = latest_ts  # default end = last available reading
    if start_ts is None:
        start_ts = end_ts - pd.Timedelta(days=request.recent_days)  # default start = end - recent_days

    start_ts = pd.Timestamp(start_ts)
    end_ts = pd.Timestamp(end_ts)
    if start_ts > end_ts:
        raise ValueError("start_date must be earlier than or equal to end_date.")

    # --- Slice the window -------------------------------------------------------
    window = customer_rows[
        (customer_rows["local_15min"] >= start_ts)
        & (customer_rows["local_15min"] <= end_ts)
    ].copy()
    if window.empty:
        raise ValueError(
            f"No solar records were found for {customer_id} in the requested time window."
        )

    # --- Credit rate -----------------------------------------------------------
    # Used to convert lost kWh → lost credit value in dollars.
    # Falls back to plan.overage_rate as a rough proxy for the net-metering rate.
    plan = account.get("plan", {})
    if request.credit_rate_usd_per_kwh is not None:
        credit_rate = float(request.credit_rate_usd_per_kwh)
        credit_rate_source = "request.credit_rate_usd_per_kwh"
    else:
        credit_rate = float(plan.get("overage_rate", 0.14))
        credit_rate_source = "plan.overage_rate_proxy"

    return {
        "query": query,
        "customer_id": customer_id,
        "account": account,
        "dataid": dataid,
        "customer_rows": customer_rows,   # all rows for this customer (used for baseline)
        "window": window,                 # only rows inside the requested date range
        "solar_feeds": feeds,             # e.g. ["solar"] or ["solar", "solar2"]
        "start_ts": start_ts,
        "end_ts": end_ts,
        "lookback_days": request.lookback_days,
        "underperformance_ratio": request.underperformance_ratio,
        "min_underperforming_intervals": request.min_underperforming_intervals,
        "min_underperforming_days": request.min_underperforming_days,
        "credit_rate_usd_per_kwh": credit_rate,
        "credit_rate_source": credit_rate_source,
        # Extract weather context from the explicit field or search the orchestrator context.
        "weather_context": extract_weather_context(request.weather_context, request.context),
    }

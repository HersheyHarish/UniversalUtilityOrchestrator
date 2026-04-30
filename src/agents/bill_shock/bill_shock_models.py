"""Request schema and shared constants for the Bill Shock Forecast Agent.

ROLE IN THE FLOW
----------------
This file is the first thing touched when a request arrives. Pydantic uses
`BillShockRequest` to parse and validate the raw JSON body from the HTTP caller
(usually the orchestrator). The constants here are imported by the other files
so every file agrees on what a "15-minute interval" means in hours.

FLOW POSITION: HTTP body → BillShockRequest → resolve_inputs → build_response
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


# Each CSV row is one 15-minute reading in kW. Multiplying kW × 0.25 h = kWh.
# This constant is used in consumption_series.py when converting kW readings to kWh.
INTERVAL_HOURS = 0.25  # 15-min readings expressed as fraction of an hour

# Columns in the meter CSV that are NOT individual appliance readings.
# Used in consumption_series.py to identify which columns to sum when there is
# no "grid" column (i.e., sum all appliance channels instead).
# Example columns that ARE appliances (not in this set): "dishwasher", "ac", "dryer"
NON_APPLIANCE_COLS = {
    "dataid",       # household identifier
    "local_15min",  # timestamp
    "grid",         # net grid draw (kW); positive = import, negative = export (solar)
    "solar",        # solar production channel
    "solar2",       # second solar feed (some households have two inverters)
    "leg1v",        # voltage leg 1 (not consumption)
    "leg2v",        # voltage leg 2 (not consumption)
}


class BillShockRequest(BaseModel):
    """The wire-format request body accepted by POST /api/bill_shock_forecast_agent.

    All fields except `query` are optional — the agent will parse them out of
    the natural-language query string if they are missing.

    Example minimal call (orchestrator only sends query):
        {"query": "Will CUST-1002 have bill shock for July 2019 as of 2019-07-15?"}

    Example fully-specified call (direct test):
        {
            "query": "Forecast bill",
            "customer_id": "CUST-1001",
            "as_of": "2019-07-15",
            "cycle_start": "2019-07-01",
            "cycle_end": "2019-07-31",
            "lookback_months": 6
        }
    """

    query: str = "Forecast bill"

    # The billing customer ID, e.g. "CUST-1001". If None, resolve_inputs will
    # call extract_customer_id() to parse it from the query string.
    customer_id: Optional[str] = None

    # The "forecast today" date — how far into the billing cycle we are.
    # If None, resolve_inputs defaults to the latest meter reading in the cycle.
    # Example: "2019-07-15" means we have 15 days of data and project the rest.
    as_of: Optional[str] = None

    # Explicit cycle boundaries. If None, resolve_inputs infers them from the
    # as_of date (first and last day of that calendar month).
    cycle_start: Optional[str] = None
    cycle_end: Optional[str] = None

    # How many past invoices to compare the projected bill against when computing
    # the bill-shock z-score. Default: last 6 months.
    lookback_months: int = Field(default=6, ge=1, le=24)

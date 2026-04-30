"""FastAPI entry point for the Bill Shock Forecast Agent.

ROLE IN THE FLOW
----------------
This is the outermost layer — the HTTP server. It wires together the four other
modules in a strict pipeline:

  1. cached_meter_data()   → load (or return cached) 15-min meter DataFrame
  2. cached_billing_data() → load (or return cached) billing JSON
  3. resolve_inputs()      → parse/validate the request into a fully-specified dict
  4. build_response()      → run the math and build the JSON response

Every request goes through all four steps in that order. The caching in step 1
and 2 means the CSV and JSON are only read from disk when the file changes;
otherwise they are returned instantly from memory.

ENDPOINTS
---------
  GET  /api/health                    → liveness probe
  POST /api/bill_shock_forecast_agent → main forecast endpoint

Example POST body (minimal — orchestrator usually sends just the query):
  {
    "query": "Will CUST-1002 have bill shock for July 2019 as of 2019-07-15?"
  }

Example POST body (fully specified — useful for direct testing):
  {
    "query": "Forecast bill",
    "customer_id": "CUST-1001",
    "as_of": "2019-07-15",
    "cycle_start": "2019-07-01",
    "cycle_end": "2019-07-31",
    "lookback_months": 6
  }

ERROR CODES
-----------
  400 Bad Request  — missing customer_id, invalid dates, no meter data in cycle
  404 Not Found    — meter CSV or billing JSON file not found on disk
  500 Server Error — unexpected runtime error
"""

from __future__ import annotations

import warnings
from typing import Any

from fastapi import FastAPI, HTTPException

from .forecast_data_sources import cached_billing_data, cached_meter_data
from .forecast_request_resolution import resolve_inputs
from .forecast_response_payloads import build_response
from .bill_shock_models import BillShockRequest


warnings.filterwarnings("ignore")


app = FastAPI(title="Bill Shock Forecast Agent")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "agent": "bill_shock_forecast_agent"}


@app.post("/api/bill_shock_forecast_agent")
def bill_shock_forecast_agent(request: BillShockRequest) -> dict[str, Any]:
    """Main forecast endpoint.

    The handler is intentionally thin — it delegates all logic to the pipeline
    below and maps Python exceptions to appropriate HTTP status codes.

    Pipeline:
      cached_meter_data()   → pd.DataFrame (all customers, all 15-min intervals)
      cached_billing_data() → dict { "accounts": {...}, "invoices": {...} }
      resolve_inputs()      → validated dict with Timestamps and account details
      build_response()      → final JSON dict
    """
    try:
        # Load data (both calls return instantly from cache on warm requests).
        df = cached_meter_data()
        billing = cached_billing_data()

        # Parse, validate, and fill in any missing fields from the query string.
        resolved = resolve_inputs(request, df, billing)

        # Run all the math and assemble the response.
        return build_response(resolved, df, billing)

    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

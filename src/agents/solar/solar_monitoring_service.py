"""FastAPI entry point for the Solar Performance & Credit Loss Agent.

BIG PICTURE
-----------
This agent answers: "Is this customer's rooftop solar underperforming, and if so
how much generation and credit value have they lost?"

It detects underperformance BEFORE the customer sees it on a bill or true-up by
comparing actual 15-min production readings against a historical baseline built
from the customer's own prior data. It also estimates financial impact and flags
likely causes (weather vs. system problem vs. partial inverter failure).

FULL PIPELINE (one request)
---------------------------
  HTTP POST /api/solar_performance_credit_loss_agent
    │
    ├─ cached_meter_data()        load (or cache) 15minute_data_sample.csv
    ├─ cached_billing_data()      load (or cache) demo_billing_data.json
    ├─ resolve_inputs()           parse customer_id, dates, feeds, credit rate
    │                             → solar_request_resolution.py
    └─ build_response()
         ├─ build_analysis_frame()
         │    ├─ select_baseline_rows()    prior N days of history before the window
         │    ├─ attach_feed_baseline()    3-tier expected kW per 15-min slot
         │    ├─ weather_adjustment()      scale expected kW down for cloudy periods
         │    └─ flag underperforming intervals (ratio < threshold AND lost_kw > 0.1)
         ├─ summarize_daily()      per-day actual vs expected, worst 5 days
         ├─ summarize_feeds()      solar vs solar2 — detects partial inverter issues
         ├─ grid_context()         grid import/export kWh
         └─ classify + narrative  severity, lost kWh, credit value, 30-day projection

ORCHESTRATOR INTEGRATION
------------------------
Designed to run after weather_context_agent. If the orchestrator passes the weather
agent's output in request.weather_context (or anywhere in request.context), the
solar agent automatically picks it up and adjusts its expected-generation baseline
downward for cloudy/rainy periods — preventing false alarms on bad weather days.

FILES IN THIS MODULE
--------------------
  solar_monitoring_service.py       ← you are here (HTTP entry point)
  solar_monitoring_models.py        request/response Pydantic models
  solar_data_sources.py             CSV/JSON loading, caching, time-feature helpers
  solar_request_resolution.py       parse + validate raw request → resolved dict
  solar_baseline_history.py         3-tier historical baseline construction
  solar_underperformance_analysis.py interval/daily/feed analysis + grid context
  solar_weather_adjustment.py       weather signal → generation factor
  solar_response_payloads.py        severity classification + final response shape
"""

from __future__ import annotations

import warnings
from typing import Any

from fastapi import FastAPI, HTTPException

from .solar_data_sources import cached_billing_data, cached_meter_data
from .solar_request_resolution import resolve_inputs
from .solar_response_payloads import build_response
from .solar_monitoring_models import SolarPerformanceRequest


warnings.filterwarnings("ignore")


app = FastAPI(title="Solar Performance & Credit Loss Agent")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "agent": "solar_performance_credit_loss_agent"}


@app.post("/api/solar_performance_credit_loss_agent")
def solar_performance_credit_loss_agent(request: SolarPerformanceRequest) -> dict[str, Any]:
    """Main solar performance endpoint.

    Four-step pipeline:
      1. cached_meter_data()    → load (or return cached) 15-min CSV
      2. cached_billing_data()  → load (or return cached) billing JSON for customer/plan lookup
      3. resolve_inputs()       → parse customer_id, dates, solar feeds, credit rate
      4. build_response()       → run full analysis pipeline and return JSON

    HTTP errors:
      400 — missing customer_id, unknown customer, no solar data in window, bad date range
      404 — meter CSV or billing JSON not found on disk
      500 — unexpected runtime error
    """
    try:
        # Load cached data — both re-read from disk only if the file has changed since last request.
        df = cached_meter_data()
        billing = cached_billing_data()

        # Parse and validate the request into a fully-resolved dict the analysis pipeline consumes.
        resolved = resolve_inputs(request, df, billing)

        # Run the full analysis: baseline → weather adjustment → underperformance detection → response.
        return build_response(resolved)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

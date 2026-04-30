"""Outage Detection Agent — FastAPI microservice.

BIG PICTURE
-----------
This agent answers: "Was there a power outage affecting this customer's area
during this billing window?" It is intentionally simple — no ML, no CSV, no
feature engineering. It just loads a JSON file of known outage events and checks
whether any of them overlap with the requested date range.

The agent is most useful when composed AFTER the billing or anomaly agent finds
something suspicious. The orchestrator can ask "did the customer have anomalous
usage in July 2019?" and then ask this agent "were there outages in July 2019?"
to help explain (or rule out) the anomaly.

DATA MODEL (demo_outages.json)
------------------------------
The JSON file has three top-level keys:

  "areas"                   — metadata per service area (zip code → city, state, tz)
  "customer_to_service_area" — maps CUST-XXXX → zip code (e.g. "CUST-1001" → "78712")
  "outages"                 — maps zip code → list of outage event dicts

Each outage event looks like:
  {
    "outage_id": "OUT-78712-20190721",
    "event_start": "2019-07-21T14:00:00-05:00",
    "event_end":   "2019-07-21T22:30:00-05:00",
    "duration_minutes": 510,
    "cause": "severe_weather",        # severe_weather / equipment_failure / scheduled_maintenance
    "scope": "regional",              # regional / neighborhood / block
    "estimated_customers_affected": 18500
  }

FULL PIPELINE (one request)
---------------------------
  HTTP POST
    │
    ├─ cached_outage_data()         load (or return cached) demo_outages.json
    ├─ resolve_outage_inputs()      parse customer_id and dates from request/query
    └─ build_response()
         ├─ resolve_area_timezone() look up the service area's local timezone
         ├─ parse_iso() × N         convert all timestamps to tz-aware datetimes
         ├─ event_overlap_minutes() for each outage event, compute overlap with window
         ├─ derive_severity()       classify total disruption as none/low/medium/high/critical
         └─ return JSON             with events, total minutes, severity, billing_impact_hint
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from src.agents.shared.loaders import load_json, mtime_cached
from src.agents.shared.query_parsing import (
    extract_customer_id,
    normalize_customer_id,
    parse_query_dates,
)


app = FastAPI(title="Outage Detection Agent")


# Resolve the outage data file path from an env var (for Docker/CI) or fall back
# to the repo's demo file. This is the same mtime_cached pattern all agents use.
BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_OUTAGE_FILE = Path(
    os.getenv("OUTAGE_INPUT_FILE", str(BASE_DIR / "data" / "demo_outages.json"))
)
DEFAULT_BILLING_FILE = Path(
    os.getenv("OUTAGE_BILLING_FILE", str(BASE_DIR / "data" / "demo_billing_data.json"))
)


class OutageRequest(BaseModel):
    """Wire-format body for POST /api/outage_detection_agent.

    All fields except `query` are optional. The agent will parse customer_id
    and dates from the query string if they are not provided explicitly.

    Example (minimal — orchestrator sends just the query):
        {"query": "Was there an outage affecting CUST-1001 in July 2019?"}

    Example (fully specified — direct test):
        {
          "query": "Check outages",
          "customer_id": "CUST-1001",
          "start_date": "2019-07-01",
          "end_date": "2019-07-31",
          "min_outage_minutes": 30
        }
    """

    query: str = "Check outages"
    customer_id: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None

    # An outage event must overlap the requested window by at least this many
    # minutes to be included in the results. Default 15 min filters out blips.
    # Maximum 720 min (12 hours) — set high to catch long outages.
    min_outage_minutes: int = Field(default=15, ge=1, le=720)


def parse_iso(value: str, default_tz: ZoneInfo | timezone = timezone.utc) -> datetime:
    """Parse an ISO timestamp string into a tz-aware datetime.

    If the string has no timezone offset (a "naive" timestamp like "2019-07-01T00:00:00"),
    we attach `default_tz` — usually the customer's local service-area timezone.
    This ensures window boundaries align with local time rather than UTC, which
    matters for events like "outage from 2pm–10:30pm local time".

    If the string already carries a timezone offset (e.g. "2019-07-21T14:00:00-05:00"),
    it is parsed as-is and `default_tz` is ignored.

    Args:
        value:      ISO 8601 string, with or without timezone offset.
        default_tz: Timezone to attach if the string is naive.

    Example:
        parse_iso("2019-07-01T00:00:00", ZoneInfo("America/Chicago"))
        → datetime(2019, 7, 1, 0, 0, tzinfo=ZoneInfo("America/Chicago"))
    """
    ts = datetime.fromisoformat(value)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=default_tz)
    return ts


def resolve_area_timezone(area: dict[str, Any]) -> ZoneInfo | timezone:
    """Return the ZoneInfo for the service area, falling back to UTC if unknown.

    The area dict comes from demo_outages.json's "areas" block, e.g.:
        {"service_area": "78712", "city": "Austin", "timezone": "America/Chicago"}

    ZoneInfoNotFoundError is caught so a bad timezone string in the data never
    crashes the request — it just silently falls back to UTC.
    """
    tz_name = area.get("timezone")
    if not tz_name:
        return timezone.utc
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return timezone.utc


def resolve_outage_inputs(request: OutageRequest, dataset: dict[str, Any], billing: dict[str, Any]) -> dict[str, Any]:
    """Parse and validate a raw OutageRequest into a fully-resolved input dict.

    Resolution order:
      customer_id  → explicit field → extracted from query string
      start_date   → explicit field → parsed from query ("July 2019" → "2019-07-01T00:00:00")
      end_date     → explicit field → parsed from query ("July 2019" → "2019-07-31T23:59:59")

    After extracting customer_id, it is normalized (e.g. "cust 1001" → "CUST-1001") and
    then looked up in the dataset's customer_to_service_area map to find the zip code.

    Returns a dict containing:
      customer_id  — normalized, e.g. "CUST-1001"
      service_area — zip code string, e.g. "78712"
      start_date   — ISO string
      end_date     — ISO string

    Raises ValueError if customer_id is missing, unknown, or dates are missing.
    """
    query = (request.query or "Check outages").strip()
    customer_id = request.customer_id
    start_date = request.start_date
    end_date = request.end_date

    # Fall back to parsing the query string if fields weren't provided explicitly.
    if customer_id is None:
        customer_id = extract_customer_id(query)

    if start_date is None or end_date is None:
        parsed_start, parsed_end = parse_query_dates(query)
        if start_date is None and parsed_start is not None:
            start_date = parsed_start.isoformat()
        if end_date is None and parsed_end is not None:
            end_date = parsed_end.isoformat()

    if customer_id is None:
        raise ValueError(
            "Outage queries must include a customer id, for example `customer CUST-1001`."
        )
    if start_date is None or end_date is None:
        raise ValueError(
            "Outage queries must include a date range like `2019-07-01 - 2019-07-31` or a month like `July 2019`."
        )

    # Normalize "cust 1001" / "CUST-1001" / "1001" → "CUST-1001"
    normalized = normalize_customer_id(customer_id)

    # Read the customer's zip from billing — the single source of truth for location.
    # demo_billing_data.json accounts[id]["service_address"]["zip"] is the service area.
    accounts = billing.get("accounts", {})
    if normalized not in accounts:
        raise ValueError(f"Unknown customer_id: {customer_id}")
    service_area = accounts[normalized]["service_address"]["zip"]  # e.g. "78712"

    return {
        "query": query,
        "customer_id": normalized,
        "service_area": service_area,
        "start_date": start_date,
        "end_date": end_date,
    }


# Both callables follow the same mtime_cached pattern — re-read only when the file changes.
# cached_outage_data: outage events and area metadata (areas, outages keys)
# cached_billing_data: single source of truth for customer location (service_address.zip)
cached_outage_data = mtime_cached(load_json, DEFAULT_OUTAGE_FILE)
cached_billing_data = mtime_cached(load_json, DEFAULT_BILLING_FILE)


def event_overlap_minutes(
    event_start: datetime,
    event_end: datetime,
    window_start: datetime,
    window_end: datetime,
) -> float:
    """Return how many minutes an outage event overlaps with the requested window.

    This handles four possible relationships between event and window:

      1. Event is entirely INSIDE the window      → full event duration counts
      2. Event STRADDLES the window start         → only the portion inside counts
      3. Event STRADDLES the window end           → only the portion inside counts
      4. Event is entirely OUTSIDE the window     → returns 0.0

    The overlap is clamped to [overlap_start, overlap_end]:
      overlap_start = max(event_start, window_start)  ← the later of the two starts
      overlap_end   = min(event_end,   window_end)    ← the earlier of the two ends
    If overlap_end ≤ overlap_start, there is no overlap → 0.0.

    Example:
        Event:  2019-07-21 14:00 → 22:30  (8.5 hours)
        Window: 2019-07-01 00:00 → 2019-07-31 23:59
        Overlap: full 8.5 hours = 510 minutes (event is inside the window)

    Example (partial overlap):
        Event:  2019-06-28 20:00 → 2019-07-02 06:00
        Window: 2019-07-01 00:00 → 2019-07-31 23:59
        Overlap: 2019-07-01 00:00 → 2019-07-02 06:00 = 30 hours = 1800 minutes
    """
    overlap_start = max(event_start, window_start)
    overlap_end = min(event_end, window_end)
    if overlap_end <= overlap_start:
        return 0.0
    return (overlap_end - overlap_start).total_seconds() / 60.0


def derive_severity(total_minutes: float, longest_event: dict[str, Any] | None) -> str:
    """Classify the total disruption as none / low / medium / high / critical.

    Thresholds are based on cumulative minutes of outage overlap in the window.
    A regional-scope outage also bumps the severity to at least "high" regardless
    of duration, because regional outages affect billing evidence more broadly.

    Thresholds:
        ≥ 720 min (12 h)   → "critical"  (half a day without power)
        ≥ 240 min (4 h)    → "high"      (multiple hours)
        OR longest event is "regional" scope
        ≥ 60 min (1 h)     → "medium"
        > 0                → "low"
        0                  → "none"

    Args:
        total_minutes: Sum of overlap_with_window_minutes across all matched events.
        longest_event: The matched event with the most overlap minutes (or None).
    """
    if total_minutes >= 12 * 60:
        return "critical"
    if total_minutes >= 4 * 60 or (longest_event and longest_event.get("scope") == "regional"):
        return "high"
    if total_minutes >= 60:
        return "medium"
    if total_minutes > 0:
        return "low"
    return "none"


def build_response(
    resolved: dict[str, Any],
    dataset: dict[str, Any],
    min_outage_minutes: int,
) -> dict[str, Any]:
    """Filter outage events to the requested window and build the final JSON response.

    Steps:
      1. Look up service area metadata (city, state, timezone) from the dataset.
      2. Look up the list of outage events for this service area.
      3. Parse window start/end as tz-aware datetimes using the area's local timezone.
      4. For each event, compute how many minutes it overlaps with the window.
         Skip events whose overlap is below min_outage_minutes.
      5. Sort matched events by start time.
      6. Sum total overlap minutes; find the longest event.
      7. Derive severity from total minutes and the longest event's scope.
      8. Build a one-sentence summary and an optional billing_impact_hint.

    The `billing_impact_hint` is a plain-English string specifically designed to
    be passed to the billing_agent — it tells the billing agent that the customer
    was without power for N minutes, which may justify a service credit.
    It is only set when total_overlap >= 30 minutes (a meaningful disruption).

    Returns a flat dict with: customer_id, service_area, city, outage_detected,
    outage_count, total_outage_minutes, severity, events[], summary,
    and billing_impact_hint.
    """
    service_area = resolved["service_area"]  # e.g. "78712"

    # Look up area metadata. Fall back gracefully if the area has no metadata entry.
    area = dataset.get("areas", {}).get(service_area, {"service_area": service_area})

    # All outage events for this zip code, regardless of date.
    events = dataset.get("outages", {}).get(service_area, [])

    # Get the area's local timezone so naive query dates are interpreted correctly.
    # Example: "2019-07-01T00:00:00" → 2019-07-01 00:00 America/Chicago
    area_tz = resolve_area_timezone(area)
    window_start = parse_iso(resolved["start_date"], default_tz=area_tz)
    window_end = parse_iso(resolved["end_date"], default_tz=area_tz)
    if window_start > window_end:
        raise ValueError("start_date must be earlier than or equal to end_date.")

    # --- Filter and annotate events that overlap with the window ---------------
    matched_events: list[dict[str, Any]] = []
    for event in events:
        evt_start = parse_iso(event["event_start"], default_tz=area_tz)
        evt_end = parse_iso(event["event_end"], default_tz=area_tz)

        # How many minutes of this event fall inside the requested window?
        overlap = event_overlap_minutes(evt_start, evt_end, window_start, window_end)

        # Skip events that barely touch the window (shorter than min_outage_minutes).
        # Default threshold is 15 min — filters out transient blips.
        if overlap < min_outage_minutes:
            continue

        matched_events.append(
            {
                "outage_id": event.get("outage_id"),
                "event_start": event["event_start"],
                "event_end": event["event_end"],
                # Use stored duration_minutes if present; otherwise compute from timestamps.
                "duration_minutes": event.get(
                    "duration_minutes",
                    round((evt_end - evt_start).total_seconds() / 60.0, 1),
                ),
                # How much of this event actually falls inside the requested window.
                # This is what matters for billing impact — not the raw event duration.
                "overlap_with_window_minutes": round(overlap, 1),
                "cause": event.get("cause"),    # e.g. "severe_weather"
                "scope": event.get("scope"),    # e.g. "regional" / "neighborhood" / "block"
                "estimated_customers_affected": event.get("estimated_customers_affected"),
                "source": event.get("source"),
            }
        )

    # Sort chronologically for readability.
    matched_events.sort(key=lambda e: e["event_start"])

    # Aggregate metrics across all matched events.
    total_overlap = sum(e["overlap_with_window_minutes"] for e in matched_events)

    # The longest event is used by derive_severity() to check if it was "regional".
    longest = (
        max(matched_events, key=lambda e: e["overlap_with_window_minutes"])
        if matched_events
        else None
    )
    severity = derive_severity(total_overlap, longest)

    # --- Build human-readable summary ------------------------------------------
    if matched_events:
        summary = (
            f"{area.get('city', service_area)} experienced {len(matched_events)} reported outage(s) "
            f"during the requested window, totaling {round(total_overlap):.0f} minutes of disruption "
            f"affecting customer {resolved['customer_id']}."
        )
    else:
        # Explicitly tell the orchestrator there were NO outages — this is useful
        # context: if billing is high but there were no outages, the cause is elsewhere.
        summary = (
            f"No outages were reported in {area.get('city', service_area)} during the requested window. "
            "Elevated usage during this period is unlikely to be explained by power interruption."
        )

    # --- Build billing impact hint ---------------------------------------------
    # This is a structured handoff to the billing_agent. Only set when the outage
    # was long enough to meaningfully affect a billing dispute (≥ 30 minutes).
    # Example output: "Customer CUST-1001 was without utility power for ~510 min
    #                  during this billing window."
    billing_impact_hint: str | None = None
    if total_overlap >= 30:
        billing_impact_hint = (
            f"Customer {resolved['customer_id']} was without utility power for ~"
            f"{round(total_overlap):.0f} min during this billing window."
        )

    return {
        "agent": "outage_detection_agent",
        "status": "completed",
        "customer_id": resolved["customer_id"],
        "service_area": service_area,
        "city": area.get("city"),
        "state": area.get("state"),
        "utility": area.get("utility"),
        "start_date": resolved["start_date"],
        "end_date": resolved["end_date"],
        "outage_detected": bool(matched_events),
        "outage_count": len(matched_events),
        "total_outage_minutes": round(total_overlap, 1),
        "longest_outage_minutes": round(longest["overlap_with_window_minutes"], 1)
        if longest
        else 0.0,
        "severity": severity,
        "events": matched_events,          # full list of matched events
        "summary": summary,                # one-sentence human-readable result
        "billing_impact_hint": billing_impact_hint,  # None if no significant outage
    }


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "agent": "outage_detection_agent"}


@app.post("/api/outage_detection_agent")
def outage_detection_agent(request: OutageRequest) -> dict[str, Any]:
    """Main outage detection endpoint.

    Three-step pipeline:
      1. cached_outage_data()      → load (or return cached) demo_outages.json
      2. resolve_outage_inputs()   → parse customer_id, service area, and dates
      3. build_response()          → filter events, compute overlap, return JSON

    HTTP errors:
      400 — missing/unknown customer_id, invalid date range
      404 — outage JSON file not found on disk
      500 — unexpected runtime error
    """
    try:
        dataset = cached_outage_data()
        billing = cached_billing_data()
        resolved = resolve_outage_inputs(request, dataset, billing)
        return build_response(resolved, dataset, request.min_outage_minutes)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

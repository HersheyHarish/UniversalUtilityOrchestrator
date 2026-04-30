"""Weather Context Agent — FastAPI microservice.

BIG PICTURE
-----------
This agent answers: "What was the weather like for this customer during this
billing window, and could it explain elevated energy usage?"

It is the only agent in the fleet that makes a live external API call —
every other agent reads from local files. It calls the Open-Meteo historical
archive API (free, no key required) to fetch real daily temperature and
weather condition data for the customer's lat/long coordinates.

The agent does NOT detect anomalies or explain bills itself. Its output is
context — the orchestrator's synthesizer (or another agent like billing_agent)
uses the weather signal to help explain WHY usage was high.

WHAT MAKES THIS AGENT DIFFERENT
--------------------------------
- Live external HTTP call (Open-Meteo archive API) on every request
- No local data file for the core data — weather comes from the internet
- Customer location (lat/long) is read from demo_billing_data.json,
  the single source of truth for customer data across the fleet
- WEATHER_CODE_LABELS stays in Python — it's a static API translation
  table, not customer data, so it belongs in code not config

FULL PIPELINE (one request)
---------------------------
  HTTP POST
    │
    ├─ cached_billing_data()       load customer location from billing JSON
    ├─ resolve_request_inputs()    parse customer_id and dates from request/query
    ├─ fetch_weather()             call Open-Meteo API → raw daily temps + codes
    └─ build_weather_response()
         ├─ count hot/cold days against thresholds
         ├─ tally weather condition codes
         ├─ assign weather_usage_correlation label
         └─ return JSON with summary, highlights, condition counts

FLOW POSITION IN THE ORCHESTRATOR
----------------------------------
Typically called after billing_agent or anomaly_detection_agent finds something
suspicious. The orchestrator asks: "There was a spike in July 2019 — was it hot?"
The weather agent confirms or rules out weather as a contributing factor.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import openmeteo_requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from src.agents.shared.loaders import load_json, mtime_cached
from src.agents.shared.query_parsing import (
    extract_customer_id,
    normalize_customer_id,
    parse_query_dates,
)


app = FastAPI(title="Weather Context Agent")

# Open-Meteo historical archive endpoint — free, no API key, goes back to 1940.
# We always request Fahrenheit so all temperature math in this file stays in °F.
OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

# Thresholds for classifying a day as "hot" or "cold".
# A day counts as hot if its MAX temp hits 90°F (likely AC usage).
# A day counts as cold if its MIN temp hits 40°F (likely heating usage).
# These are intentionally conservative — 90°F is a common AC trigger in Texas.
HEAT_THRESHOLD_F = 90
COLD_THRESHOLD_F = 40

# Module-level client instance — reused across all requests (no reconnect overhead).
OPEN_METEO_CLIENT = openmeteo_requests.Client()

# Customer location is read from demo_billing_data.json (service_address.lat/long).
# This is the single source of truth for location across the fleet — the outage
# agent also reads its service area zip from the same file.
BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_BILLING_FILE = Path(
    os.getenv("WEATHER_BILLING_FILE", str(BASE_DIR / "data" / "demo_billing_data.json"))
)
cached_billing_data = mtime_cached(load_json, DEFAULT_BILLING_FILE)

# WMO weather interpretation codes returned by Open-Meteo → human-readable label.
# These are standardized WMO codes — the full table is defined by the WMO standard.
# Gaps in the numbering (e.g. 4–44) are codes not used by Open-Meteo.
# Any code not in this dict falls back to f"code_{code}" so we never crash on
# an unknown value.
WEATHER_CODE_LABELS: dict[int, str] = {
    0: "clear_sky",
    1: "mainly_clear",
    2: "partly_cloudy",
    3: "overcast",
    45: "fog",
    48: "depositing_rime_fog",
    51: "light_drizzle",
    53: "moderate_drizzle",
    55: "dense_drizzle",
    56: "light_freezing_drizzle",
    57: "dense_freezing_drizzle",
    61: "slight_rain",
    63: "moderate_rain",
    65: "heavy_rain",
    66: "light_freezing_rain",
    67: "heavy_freezing_rain",
    71: "slight_snow",
    73: "moderate_snow",
    75: "heavy_snow",
    77: "snow_grains",
    80: "slight_rain_showers",
    81: "moderate_rain_showers",
    82: "violent_rain_showers",
    85: "slight_snow_showers",
    86: "heavy_snow_showers",
    95: "thunderstorm",
    96: "thunderstorm_with_slight_hail",
    99: "thunderstorm_with_heavy_hail",
}


class WeatherContextRequest(BaseModel):
    """Wire-format body for POST /api/weather_context_agent.

    All fields except `query` are optional — customer_id and dates are parsed
    from the query string if not provided explicitly.

    Example (minimal — orchestrator sends just the query):
        {"query": "Check whether weather explains high usage for CUST-1001 in July 2019."}

    Example (fully specified):
        {
          "query": "Weather check",
          "customer_id": "CUST-1001",
          "start_date": "2019-07-01",
          "end_date": "2019-07-31"
        }

    Note: dates must be YYYY-MM-DD strings (not full ISO timestamps) because
    Open-Meteo's archive API only accepts date-only strings, not datetimes.
    """
    query: str
    customer_id: str | None = None
    start_date: str | None = None
    end_date: str | None = None


def resolve_request_inputs(request: WeatherContextRequest, billing: dict[str, Any]) -> dict[str, str]:
    """Parse and validate the request into a fully-resolved input dict.

    Resolution order:
      customer_id  → explicit field → extracted from query string
      start_date   → explicit field → parsed from query ("July 2019" → "2019-07-01")
      end_date     → explicit field → parsed from query ("July 2019" → "2019-07-31")

    Note: dates are formatted as "YYYY-MM-DD" strings (not full ISO timestamps)
    because that is what Open-Meteo's archive API expects as input.

    The customer is validated against billing["accounts"] — the same registry
    used by the anomaly and bill shock agents. If the customer isn't in billing,
    we raise ValueError rather than making an API call with no coordinates.

    Args:
        request: Validated Pydantic request from the HTTP caller.
        billing: Parsed billing JSON from cached_billing_data().

    Returns:
        Dict with: query, customer_id (normalized), start_date, end_date.

    Example output:
        {
          "query": "Check weather for CUST-1001 in July 2019",
          "customer_id": "CUST-1001",
          "start_date": "2019-07-01",
          "end_date": "2019-07-31"
        }
    """
    query = request.query.strip()
    customer_id = request.customer_id
    start_date = request.start_date
    end_date = request.end_date

    # Fall back to parsing customer_id and dates from the natural-language query.
    if customer_id is None:
        customer_id = extract_customer_id(query)

    if start_date is None or end_date is None:
        parsed_start, parsed_end = parse_query_dates(query)
        # strftime("%Y-%m-%d") strips the time component — Open-Meteo wants date-only.
        if start_date is None and parsed_start is not None:
            start_date = parsed_start.strftime("%Y-%m-%d")
        if end_date is None and parsed_end is not None:
            end_date = parsed_end.strftime("%Y-%m-%d")

    if customer_id is None:
        raise ValueError("Weather context queries must include a customer id, for example `customer CUST-1001`.")
    if start_date is None or end_date is None:
        raise ValueError("Weather context queries must include a date range or a month like `July 2019`.")

    # Normalize and validate against billing — this also confirms lat/long exist.
    normalized_customer_id = normalize_customer_id(customer_id)
    accounts = billing.get("accounts", {})
    if normalized_customer_id not in accounts:
        raise ValueError(f"Unknown customer_id: {customer_id}")

    return {
        "query": query,
        "customer_id": normalized_customer_id,
        "start_date": start_date,
        "end_date": end_date,
    }


def celsius_to_fahrenheit(value: float | None) -> float | None:
    """Convert Celsius to Fahrenheit. Returns None if input is None.

    Unused after switching to temperature_unit="fahrenheit" in the API call,
    but kept as a utility in case future callers request Celsius from Open-Meteo.
    """
    if value is None:
        return None
    return (value * 9 / 5) + 32


def fetch_weather(latitude: float, longitude: float, start_date: str, end_date: str) -> dict[str, Any]:
    """Call the Open-Meteo historical archive API and return normalized daily data.

    This is the only function in the entire agent fleet that makes a live
    external HTTP call. Everything else reads from local files.

    Open-Meteo returns a binary FlatBuffers response (not JSON) which the
    openmeteo_requests library decodes into Python objects. The API is free,
    requires no API key, and covers historical data back to 1940.

    WHAT WE REQUEST
    ---------------
    Four daily variables per day in the date range:
      temperature_2m_max  → daily high temp at 2m above ground (°F)
      temperature_2m_min  → daily low temp at 2m above ground (°F)
      temperature_2m_mean → daily average temp at 2m above ground (°F)
      weather_code        → WMO weather interpretation code (int, e.g. 95 = thunderstorm)

    timezone="auto" lets Open-Meteo pick the correct local timezone for the
    coordinates so daily boundaries align with local midnight, not UTC midnight.

    HOW THE RESPONSE IS DECODED
    ---------------------------
    The library returns:
      daily.Time()         → Unix timestamp of the first interval start
      daily.TimeEnd()      → Unix timestamp of the last interval end
      daily.Interval()     → seconds per interval (86400 for daily = one day)
      daily.Variables(n)   → the nth requested variable as a numpy array

    We reconstruct the date list by stepping from Time() to TimeEnd() in
    Interval()-second increments. This is more robust than trusting a "dates"
    field (which the API doesn't return directly).

    Args:
        latitude:   Decimal degrees, e.g. 30.2849 (Austin, TX)
        longitude:  Decimal degrees, e.g. -97.7341
        start_date: "YYYY-MM-DD" string, e.g. "2019-07-01"
        end_date:   "YYYY-MM-DD" string, e.g. "2019-07-31"

    Returns:
        Dict with a single "daily" key containing parallel lists of equal length:
        {
          "daily": {
            "time":               ["2019-07-01", "2019-07-02", ...],  # 31 entries
            "temperature_2m_max": [98.2, 101.4, ...],
            "temperature_2m_min": [74.1, 76.8, ...],
            "temperature_2m_mean":[86.2, 89.1, ...],
            "weather_code":       [0, 1, 95, ...]
          }
        }

    Raises:
        ValueError: If the API returns an invalid interval or mismatched list lengths.
    """
    responses = OPEN_METEO_CLIENT.weather_api(
        OPEN_METEO_ARCHIVE_URL,
        params={
            "latitude": latitude,
            "longitude": longitude,
            "start_date": start_date,
            "end_date": end_date,
            "daily": ["temperature_2m_max", "temperature_2m_min", "temperature_2m_mean", "weather_code"],
            "temperature_unit": "fahrenheit",
            "timezone": "auto",
        },
    )

    # The API always returns a list of responses (one per location requested).
    # We only request one location so we always take index 0.
    response = responses[0]
    daily = response.Daily()

    # Reconstruct the date list from the FlatBuffers time metadata.
    # Time() and TimeEnd() are Unix timestamps in seconds.
    # Interval() is seconds per step — 86400 for daily data.
    start = datetime.fromtimestamp(daily.Time(), tz=timezone.utc)
    end = datetime.fromtimestamp(daily.TimeEnd(), tz=timezone.utc)
    interval_seconds = daily.Interval()
    if interval_seconds <= 0:
        raise ValueError("Weather API returned an invalid daily interval.")

    interval_days = interval_seconds / 86400  # convert seconds → fractional days
    if interval_days <= 0:
        raise ValueError("Weather API returned an invalid daily interval.")

    # Build the date list: step from start to end in interval_days increments.
    # Example: start=2019-07-01, end=2019-08-01, interval=1 day → 31 dates.
    total_days = int((end - start).total_seconds() / interval_seconds)
    dates = [
        (start + timedelta(days=index * interval_days)).strftime("%Y-%m-%d")
        for index in range(total_days)
    ]

    # Variables(n) returns the nth variable in the order we requested in "daily" above:
    #   0 → temperature_2m_max
    #   1 → temperature_2m_min
    #   2 → temperature_2m_mean
    #   3 → weather_code
    # ValuesAsNumpy() decodes the FlatBuffer array → numpy array → .tolist() → Python list.
    max_temps = daily.Variables(0).ValuesAsNumpy().tolist()
    min_temps = daily.Variables(1).ValuesAsNumpy().tolist()
    mean_temps = daily.Variables(2).ValuesAsNumpy().tolist()
    weather_codes = daily.Variables(3).ValuesAsNumpy().tolist()

    # Sanity check: all lists must be the same length as the date list.
    # A mismatch means the API returned partial data (network issue, API bug, etc.).
    if (
        not dates
        or len(dates) != len(max_temps)
        or len(dates) != len(min_temps)
        or len(dates) != len(mean_temps)
        or len(dates) != len(weather_codes)
    ):
        raise ValueError("Weather API returned incomplete daily data.")

    return {
        "daily": {
            "time": dates,
            "temperature_2m_max": max_temps,
            "temperature_2m_min": min_temps,
            "temperature_2m_mean": mean_temps,
            "weather_code": weather_codes,
        }
    }


def build_weather_response(resolved: dict[str, str], payload: dict[str, Any], billing: dict[str, Any]) -> dict[str, Any]:
    """Analyze the raw weather data and build the final JSON response.

    Steps:
      1. Read customer location from billing (city, state, lat/long, zip).
      2. Unpack the parallel daily lists from fetch_weather()'s payload.
      3. Count hot days (max ≥ 90°F) and cold days (min ≤ 40°F).
      4. Tally weather condition codes into a frequency dict.
      5. Assign a weather_usage_correlation label based on hot/cold day counts.
      6. Find the hottest and coldest individual days for the highlights block.
      7. Return the final response dict.

    WEATHER_USAGE_CORRELATION LOGIC
    --------------------------------
    The correlation label is intentionally simple — 3 days is the threshold
    because a single hot day rarely drives a monthly bill spike, but 3+ hot
    days in a row or spread across a month plausibly explain sustained AC load.

      hot_days >= 3  → "possible_high_ac_usage"
      cold_days >= 3 → "possible_high_heating_usage"
      otherwise      → "weather_unlikely_primary_driver"

    Note: hot check takes priority over cold. A month can't be both hot and cold
    enough to trigger both thresholds in practice, but the if/elif enforces it.

    Args:
        resolved: Output of resolve_request_inputs() — customer_id, dates.
        payload:  Output of fetch_weather() — raw daily lists.
        billing:  Parsed billing JSON — used to read service_address for location.

    Example response (abbreviated):
        {
          "customer_id": "CUST-1001",
          "location": "Austin, TX",
          "avg_temp_f": 94.2,
          "hot_days_count": 28,
          "weather_usage_correlation": "possible_high_ac_usage",
          "summary": "The requested period included multiple hot days...",
          "highlights": {
            "hottest_day": {"date": "2019-07-19", "max_temp_f": 104.1},
            "coldest_day": {"date": "2019-07-03", "min_temp_f": 68.9}
          },
          "weather_condition_counts": {"clear_sky": 18, "partly_cloudy": 9, ...}
        }
    """
    # Pull the customer's service address from billing — single source of truth.
    # lat/long were added to service_address so the weather and outage agents
    # both derive location from the same place.
    addr = billing["accounts"][resolved["customer_id"]]["service_address"]
    location = {
        "latitude": addr["latitude"],
        "longitude": addr["longitude"],
        "label": f"{addr['city']}, {addr['state']}",  # e.g. "Austin, TX"
        "zip_code": addr["zip"],
    }

    # Unpack the parallel daily lists. All four lists have the same length
    # (guaranteed by the validation in fetch_weather).
    daily = payload["daily"]
    dates = daily["time"]
    max_temps = [float(value) for value in daily["temperature_2m_max"]]
    min_temps = [float(value) for value in daily["temperature_2m_min"]]
    mean_temps = [float(value) for value in daily["temperature_2m_mean"]]
    weather_codes = [int(value) for value in daily["weather_code"]]

    # Tally condition codes → human-readable labels using the WMO lookup table.
    # Example output: {"clear_sky": 18, "thunderstorm": 3, "partly_cloudy": 9}
    # Any unknown code becomes f"code_{code}" so we never silently drop data.
    weather_condition_counts: dict[str, int] = {}
    for code in weather_codes:
        label = WEATHER_CODE_LABELS.get(code, f"code_{code}")
        weather_condition_counts[label] = weather_condition_counts.get(label, 0) + 1

    # Count hot and cold days against fixed thresholds.
    # hot_days: days where the HIGH was at or above 90°F — AC likely running.
    # cold_days: days where the LOW was at or below 40°F — heating likely running.
    hot_days = sum(1 for value in max_temps if value >= HEAT_THRESHOLD_F)
    cold_days = sum(1 for value in min_temps if value <= COLD_THRESHOLD_F)

    # Assign correlation label and summary. 3-day threshold is the minimum to
    # claim weather as a plausible driver of monthly energy bill elevation.
    if hot_days >= 3:
        weather_usage_correlation = "possible_high_ac_usage"
        summary = "The requested period included multiple hot days, which may have increased air conditioning usage."
    elif cold_days >= 3:
        weather_usage_correlation = "possible_high_heating_usage"
        summary = "The requested period included multiple cold days, which may have increased heating usage."
    else:
        weather_usage_correlation = "weather_unlikely_primary_driver"
        summary = "Weather conditions during the requested period were not extreme enough to strongly explain elevated usage."

    # Find the index of the hottest and coldest days for the highlights block.
    # max(..., key=max_temps.__getitem__) → index of the largest value in max_temps.
    # min(..., key=min_temps.__getitem__) → index of the smallest value in min_temps.
    hottest_day_index = max(range(len(max_temps)), key=max_temps.__getitem__)
    coldest_day_index = min(range(len(min_temps)), key=min_temps.__getitem__)

    return {
        "agent": "weather_context_agent",
        "status": "completed",
        "customer_id": resolved["customer_id"],
        "location": location["label"],          # e.g. "Austin, TX"
        "zip_code": location["zip_code"],
        "start_date": resolved["start_date"],
        "end_date": resolved["end_date"],
        "avg_temp_f": round(sum(mean_temps) / len(mean_temps), 1),
        "max_temp_f": round(max(max_temps), 1), # hottest daily high in the window
        "min_temp_f": round(min(min_temps), 1), # coldest daily low in the window
        "hot_days_count": hot_days,             # days where high ≥ 90°F
        "cold_days_count": cold_days,           # days where low ≤ 40°F
        "heat_days_detected_above_threshold": hot_days > 0,
        "cold_days_detected_below_threshold": cold_days > 0,
        "weather_usage_correlation": weather_usage_correlation,
        "summary": summary,
        "highlights": {
            # The single hottest and coldest days — useful for the orchestrator's
            # synthesizer to cite a specific date when explaining usage spikes.
            "hottest_day": {
                "date": dates[hottest_day_index],
                "max_temp_f": round(max_temps[hottest_day_index], 1),
            },
            "coldest_day": {
                "date": dates[coldest_day_index],
                "min_temp_f": round(min_temps[coldest_day_index], 1),
            },
        },
        # How many days had each weather condition. Useful for context:
        # e.g. "18 clear days + 3 thunderstorms" tells a different story than
        # "28 overcast days" even if average temps are similar.
        "weather_condition_counts": weather_condition_counts,
    }


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "agent": "weather_context_agent"}


@app.post("/api/weather_context_agent")
def weather_context_agent(request: WeatherContextRequest) -> dict[str, Any]:
    """Main weather context endpoint.

    Four-step pipeline:
      1. cached_billing_data()       → load (or return cached) billing JSON
                                       for customer validation and lat/long lookup
      2. resolve_request_inputs()    → parse customer_id and dates from request/query
      3. fetch_weather()             → live call to Open-Meteo archive API
      4. build_weather_response()    → analyze temps, assign correlation, return JSON

    Note: step 3 is the only step that can fail due to external network issues.
    All other failures are local (bad input, unknown customer, missing file).

    HTTP errors:
      400 — missing/unknown customer_id, invalid date range, bad API response
      404 — billing JSON file not found on disk
      500 — network failure calling Open-Meteo, or unexpected runtime error
    """
    try:
        # Load customer data (cached — only re-reads if the file changes on disk).
        billing = cached_billing_data()

        # Parse and validate the request. Raises ValueError if customer or dates missing.
        resolved = resolve_request_inputs(request, billing)

        # Look up this customer's coordinates from billing.
        # These were added to service_address so location data has one source of truth.
        addr = billing["accounts"][resolved["customer_id"]]["service_address"]

        # Live API call — this is the only network-dependent step in the agent.
        payload = fetch_weather(
            latitude=float(addr["latitude"]),
            longitude=float(addr["longitude"]),
            start_date=resolved["start_date"],
            end_date=resolved["end_date"],
        )

        # Analyze the raw data and build the final response dict.
        return build_weather_response(resolved, payload, billing)

    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

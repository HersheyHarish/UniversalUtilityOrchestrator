"""Wire-format model for the Solar Performance agent.

This is the Pydantic model that validates the HTTP request body. All fields
except `query` are optional — the agent parses customer_id and dates from the
query string if not provided explicitly, matching the pattern used by all other
agents in this fleet.

TUNING PARAMETERS
-----------------
The numerical fields below control detection sensitivity. The defaults are set
conservatively — they require repeated underperformance across multiple days and
intervals before raising a flag, which reduces false positives on noisy data.

  underperformance_ratio        How far actual must fall below expected to count
                                as underperforming (default 0.65 = 35% below baseline).
  min_underperforming_intervals Minimum 15-min intervals flagged before detection triggers.
                                Default 8 = 2 hours of sustained underperformance.
  min_underperforming_days      Minimum calendar days with underperformance before detection.
                                Default 2 prevents a single bad day from triggering.
  lookback_days                 How many prior days to use for the historical baseline.
                                Default 90 = one full season of history.
  recent_days                   When no date range is supplied, how many recent days
                                to evaluate. Default 7 = one week.

WEATHER CONTEXT PASSTHROUGH
----------------------------
The `weather_context` field accepts the raw JSON output from `weather_context_agent`
directly. The solar agent uses it to scale down expected generation on cloudy/rainy
days so legitimate weather-related dips don't trigger false alarms.

If omitted, the agent also searches `context.dependency_outputs` automatically —
so the orchestrator doesn't need to explicitly wire weather → solar.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class SolarPerformanceRequest(BaseModel):
    # Primary field — the orchestrator always sends at minimum a natural-language query.
    # Customer ID and dates are parsed from this string if not provided explicitly.
    query: str = "Check solar performance"

    # Optional explicit fields — if provided, these take priority over query parsing.
    customer_id: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None

    # When no date range is supplied, evaluate the most recent `recent_days` days of data.
    recent_days: int = Field(default=7, ge=1, le=31)

    # How many prior days to use for the historical baseline before the window.
    lookback_days: int = Field(default=90, ge=14, le=365)

    # Observed/expected ratio below which a 15-min interval counts as underperforming.
    # 0.65 means actual production must be less than 65% of expected to flag the interval.
    underperformance_ratio: float = Field(default=0.65, ge=0.1, le=0.95)

    # Minimum number of flagged 15-min intervals before detection triggers.
    # Guards against a single bad interval causing a false positive.
    min_underperforming_intervals: int = Field(default=8, ge=1, le=500)

    # Minimum number of calendar days with underperformance before detection triggers.
    # Guards against a single bad day (e.g. temporary shading) causing a false positive.
    min_underperforming_days: int = Field(default=2, ge=1, le=31)

    # Override the net-metering credit rate used to calculate lost credit value.
    # If None, defaults to the customer's plan.overage_rate as a proxy.
    credit_rate_usd_per_kwh: Optional[float] = Field(default=None, ge=0.0, le=5.0)

    # Optional weather context from weather_context_agent. Used to scale down expected
    # generation on cloudy/rainy/stormy days. Prevents false alarms due to bad weather.
    weather_context: Optional[dict[str, Any]] = None

    # Broader orchestrator context — the agent searches this for a weather_context_agent
    # output if weather_context is not provided explicitly.
    context: Optional[dict[str, Any]] = None

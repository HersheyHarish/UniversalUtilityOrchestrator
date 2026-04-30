"""Weather-aware adjustment of expected solar generation.

WHY THIS EXISTS
---------------
A customer whose solar dropped 30% in July might have a system problem — or it
might have just been a cloudy month. Without weather context, the agent can't
tell the difference and will produce false alarms.

This file reads the output from weather_context_agent (if provided) and computes
an `expected_generation_factor` between 0.5 and 1.0. The baseline is multiplied
by this factor before comparing against actual production. A factor of 0.75 means
"we expect 25% less generation than the historical average because of weather."

HOW THE FACTOR IS CALCULATED
-----------------------------
1. Count how many of the days in the window had adverse weather conditions
   (cloudy, rainy, foggy, snowy, stormy) based on WMO weather codes.
2. Map the adverse-day ratio to a factor:
     ≥ 60% adverse days → factor = 0.65  (very cloudy month)
     ≥ 35% adverse days → factor = 0.75  (moderately cloudy)
     >  0% adverse days → factor = 0.85  (some clouds)
        0% adverse days → factor = 1.00  (clear month)
3. Apply an additional 5% derate (× 0.95) if there were 3+ hot days,
   because high panel temperatures reduce photovoltaic efficiency.
4. Clamp the final factor to [0.50, 1.00].

WEATHER CONTEXT EXTRACTION
---------------------------
The weather context can arrive in two ways:
  1. Explicit: request.weather_context = <weather agent output dict>
  2. Implicit: the orchestrator passes all upstream results in request.context,
     and extract_weather_context() searches that nested dict for a response
     that looks like it came from weather_context_agent.

This makes the solar agent robust whether the orchestrator explicitly wires
weather → solar or just passes the full context blob.
"""

from __future__ import annotations

from typing import Any, Optional


# WMO weather condition labels that reduce solar irradiance.
# Copied from weatherContextAgent.py's WEATHER_CODE_LABELS — must stay in sync.
ADVERSE_WEATHER_LABELS = {
    "overcast",
    "fog",
    "depositing_rime_fog",
    "light_drizzle",
    "moderate_drizzle",
    "dense_drizzle",
    "light_freezing_drizzle",
    "dense_freezing_drizzle",
    "slight_rain",
    "moderate_rain",
    "heavy_rain",
    "light_freezing_rain",
    "heavy_freezing_rain",
    "slight_rain_showers",
    "moderate_rain_showers",
    "violent_rain_showers",
    "thunderstorm",
    "thunderstorm_with_slight_hail",
    "thunderstorm_with_heavy_hail",
    "slight_snow",
    "moderate_snow",
    "heavy_snow",
    "snow_grains",
    "slight_snow_showers",
    "heavy_snow_showers",
}


def extract_weather_context(
    weather_context: Optional[dict[str, Any]],
    fallback_context: Optional[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    """Use the explicit weather_context if provided, else search the orchestrator context.

    The orchestrator may pass all upstream agent results in a nested context dict.
    This function recursively searches that dict for a response that looks like it
    came from weather_context_agent (identified by the "agent" key or the presence
    of "weather_condition_counts" or "weather_usage_correlation").

    Returns the weather context dict if found, otherwise None.
    """
    if weather_context and (
        weather_context.get("agent") == "weather_context_agent"
        or "weather_condition_counts" in weather_context
        or "weather_usage_correlation" in weather_context
    ):
        return weather_context

    def find_weather(obj: Any) -> Optional[dict[str, Any]]:
        if isinstance(obj, dict):
            candidate = obj.get("output") if isinstance(obj.get("output"), dict) else obj
            if (
                candidate.get("agent") == "weather_context_agent"
                or "weather_condition_counts" in candidate
                or "weather_usage_correlation" in candidate
            ):
                return candidate
            for value in obj.values():
                found = find_weather(value)
                if found:
                    return found
        elif isinstance(obj, list):
            for item in obj:
                found = find_weather(item)
                if found:
                    return found
        return None

    return find_weather(fallback_context) if fallback_context else None


def weather_adjustment(weather_context: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Compute the expected_generation_factor from weather context.

    If no weather context is provided, returns factor=1.0 (no adjustment).
    The factor is used in solar_underperformance_analysis.py to scale down
    the historical baseline before comparing against actual production.

    Returns a dict with:
      weather_context_used        — bool, whether context was applied
      expected_generation_factor  — float [0.50, 1.00], multiply baseline by this
      adverse_weather_ratio       — fraction of days with adverse conditions
      hot_days_count              — number of hot days (adds panel efficiency derate)
      weather_usage_correlation   — string from weather agent (passthrough)
      rationale                   — human-readable explanation of the factor chosen

    Example:
        Portland July 2019: 22/31 days overcast or rainy → adverse_ratio = 0.71
        → factor = 0.65 (very cloudy)
        → rationale: "22/31 weather days were cloudy, rainy, foggy, snowy, or stormy."
    """
    if not weather_context:
        return {
            "weather_context_used": False,
            "expected_generation_factor": 1.0,
            "adverse_weather_ratio": 0.0,
            "rationale": "No weather context was supplied; baseline was not weather-adjusted.",
        }

    # Count total days and adverse days from weather_condition_counts.
    # weather_condition_counts looks like: {"clear_sky": 4, "overcast": 13, "light_drizzle": 5, ...}
    counts = weather_context.get("weather_condition_counts") or {}
    total_days = sum(int(value) for value in counts.values() if value is not None)
    adverse_days = sum(
        int(value)
        for label, value in counts.items()
        if str(label) in ADVERSE_WEATHER_LABELS and value is not None
    )
    adverse_ratio = adverse_days / total_days if total_days else 0.0

    # Map adverse ratio to a generation factor.
    if adverse_ratio >= 0.60:
        factor = 0.65   # heavily cloudy/rainy month — expect 35% less generation
    elif adverse_ratio >= 0.35:
        factor = 0.75   # moderately cloudy — expect 25% less
    elif adverse_ratio > 0:
        factor = 0.85   # some clouds — expect 15% less
    else:
        factor = 1.0    # clear month — no adjustment

    # Additional 5% derate for 3+ hot days — high panel temperature reduces efficiency.
    hot_days = int(weather_context.get("hot_days_count") or 0)
    if hot_days >= 3:
        factor *= 0.95

    # Clamp to [0.50, 1.00] — never adjust by more than 50% regardless of conditions.
    factor = round(max(0.50, min(1.0, factor)), 3)

    rationale_parts: list[str] = []
    if total_days:
        rationale_parts.append(
            f"{adverse_days}/{total_days} weather days were cloudy, rainy, foggy, snowy, or stormy."
        )
    if hot_days >= 3:
        rationale_parts.append(f"{hot_days} hot day(s) may have reduced panel efficiency.")
    if not rationale_parts:
        rationale_parts.append("Weather context did not indicate material solar-limiting conditions.")

    return {
        "weather_context_used": True,
        "expected_generation_factor": factor,
        "adverse_weather_ratio": round(adverse_ratio, 3),
        "hot_days_count": hot_days,
        "weather_usage_correlation": weather_context.get("weather_usage_correlation"),
        "rationale": " ".join(rationale_parts),
    }

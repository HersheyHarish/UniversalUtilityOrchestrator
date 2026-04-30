# Weather Context Agent

Provides historical weather context for a billing or anomaly window. Answers: *"Could weather explain why this customer's energy usage was high?"*

This is the only agent in the fleet that makes a live external API call — it hits the [Open-Meteo historical archive](https://open-meteo.com/) (free, no API key) on every request.

---

## When it gets called

Typically called **after** `anomaly_detection_agent` or `billing_agent` finds a spike. The orchestrator asks the weather agent to confirm or rule out weather as a contributing factor before synthesizing a final explanation to the user.

Example trigger: *"CUST-1001 had a usage spike in July 2019 — was it unusually hot?"*

---

## Endpoint

| | |
|---|---|
| **Local** | `POST http://localhost:8004/api/weather_context_agent` |
| **Deployed** | `POST https://weather-agent.wonderfulrock-687dfc24.eastus2.azurecontainerapps.io/api/weather_context_agent` |
| **Health** | `GET <base>/api/health` |

---

## Request payload

```json
{
  "query": "Check whether weather may explain high usage for customer CUST-1001 in July 2019."
}
```

All fields except `query` are optional — the agent parses `customer_id` and dates out of the query string automatically.

| Field | Type | Required | Description |
|---|---|---|---|
| `query` | string | yes | Natural-language question. Embed customer ID and date range here. |
| `customer_id` | string | no | e.g. `CUST-1001`. Parsed from query if omitted. |
| `start_date` | string | no | ISO date `YYYY-MM-DD`. Parsed from query if omitted. |
| `end_date` | string | no | ISO date `YYYY-MM-DD`. Parsed from query if omitted. |

**Demo customers:** `CUST-1001` (Austin, TX) · `CUST-1002` (Portland, OR)

---

## Response

```json
{
  "agent": "weather_context_agent",
  "status": "completed",
  "customer_id": "CUST-1001",
  "location": "Austin, TX",
  "zip_code": "78712",
  "start_date": "2019-07-01",
  "end_date": "2019-07-31",
  "avg_temp_f": 94.2,
  "max_temp_f": 104.1,
  "min_temp_f": 68.9,
  "hot_days_count": 28,
  "cold_days_count": 0,
  "heat_days_detected_above_threshold": true,
  "cold_days_detected_below_threshold": false,
  "weather_usage_correlation": "possible_high_ac_usage",
  "summary": "The requested period included multiple hot days, which may have increased air conditioning usage.",
  "highlights": {
    "hottest_day": { "date": "2019-07-19", "max_temp_f": 104.1 },
    "coldest_day": { "date": "2019-07-03", "min_temp_f": 68.9 }
  },
  "weather_condition_counts": {
    "clear_sky": 18,
    "partly_cloudy": 9,
    "thunderstorm": 3,
    "moderate_rain": 1
  }
}
```

### `weather_usage_correlation` values

| Value | Meaning |
|---|---|
| `possible_high_ac_usage` | 3+ days where daily high ≥ 90°F |
| `possible_high_heating_usage` | 3+ days where daily low ≤ 40°F |
| `weather_unlikely_primary_driver` | Neither threshold met |

---

## How to run locally

```bash
# From repo root
PYTHONPATH=. uvicorn src.agents.weather.weatherContextAgent:app --host 0.0.0.0 --port 8004
```

Install dependencies first if needed:
```bash
pip install -r src/agents/weather/requirements.txt
```

---

## How to test (Postman)

`POST https://weather-agent.wonderfulrock-687dfc24.eastus2.azurecontainerapps.io/api/weather_context_agent`

Body → raw → JSON:
```json
{
  "query": "Check whether weather may explain high usage for customer CUST-1001 in July 2019."
}
```

Try `CUST-1002` in February 2019 for a contrasting result (Portland winter vs Austin summer).

> **Use `https://` not `http://`** — Azure Container Apps enforces HTTPS and POST requests will 405 on HTTP.

---

## Data dependencies

| File | Purpose |
|---|---|
| `src/data/demo_billing_data.json` | Customer lat/long and location — single source of truth |
| Open-Meteo archive API | Live weather data — requires internet access |

Customer location (lat, long, city, state, zip) is read from `demo_billing_data.json → accounts → service_address`. To add a new customer, update that file only — no Python changes needed.

---
# Solar Performance & Credit Loss Agent

Answers: *"Is this customer's rooftop solar underperforming, and if so how much generation and credit value have they lost?"*

Detects underperformance **before** the customer sees it on a bill by comparing actual 15-min meter readings against a historical baseline built from the customer's own prior data. No external API calls — runs entirely on local CSV and JSON files.

---

## When it gets called

- Proactively, on a schedule, to catch problems before the billing cycle closes
- After `anomaly_detection_agent` flags high grid usage (customer may be compensating for poor solar)
- Composes with `weather_context_agent` — pass weather output in `weather_context` to avoid false alarms on legitimately cloudy periods

---

## Endpoint

| | |
|---|---|
| **Local** | `POST http://localhost:8010/api/solar_performance_credit_loss_agent` |
| **Health** | `GET http://localhost:8010/api/health` |

> Not yet deployed to Azure — runs locally only.

---

## Request payload

```json
{
  "query": "Check solar underperformance for customer CUST-1001 in October 2019."
}
```

All fields except `query` are optional.

| Field | Type | Default | Description |
|---|---|---|---|
| `query` | string | required | Natural-language question. Embed customer ID and date range. |
| `customer_id` | string | parsed from query | e.g. `CUST-1001` |
| `start_date` | string | parsed from query | ISO date `YYYY-MM-DD` |
| `end_date` | string | parsed from query | ISO date `YYYY-MM-DD` |
| `recent_days` | int | 7 | When no date range given, how many recent days to evaluate |
| `lookback_days` | int | 90 | How many prior days to use for the historical baseline |
| `underperformance_ratio` | float | 0.65 | Actual/expected ratio below which an interval is flagged |
| `min_underperforming_intervals` | int | 8 | Min flagged intervals before detection triggers |
| `min_underperforming_days` | int | 2 | Min underperforming days before detection triggers |
| `credit_rate_usd_per_kwh` | float | plan rate | Net-metering credit rate for financial calculations |
| `weather_context` | object | null | Raw output from `weather_context_agent` — adjusts expected generation |

**Demo customers:** `CUST-1001` (Austin, TX) · `CUST-1002` (Portland, OR)

---

## Response

```json
{
  "agent": "solar_performance_credit_loss_agent",
  "status": "completed",
  "customer_id": "CUST-1001",
  "dataid": 5997,
  "start_date": "2019-10-01T00:00:00",
  "end_date": "2019-10-31T23:59:59",
  "solar_feeds_evaluated": ["solar"],
  "underperformance_detected": true,
  "severity": "critical",
  "likely_cause_category": "broad underperformance",
  "estimated_expected_generation_kwh": 1081.02,
  "actual_generation_kwh": 708.16,
  "estimated_lost_generation_kwh": 372.86,
  "lost_generation_pct_of_expected": 34.5,
  "window_performance_ratio": 0.655,
  "underperforming_interval_count": 885,
  "underperforming_day_count": 18,
  "daylight_interval_count": 1333,
  "credit_rate_usd_per_kwh": 0.14,
  "credit_rate_source": "plan.overage_rate_proxy",
  "estimated_lost_credit_value_usd": 52.20,
  "projected_30_day_lost_generation_kwh": 360.83,
  "rough_financial_impact_if_continues_30d_usd": 50.52,
  "grid_context": { ... },
  "weather_adjustment": { ... },
  "baseline_context": { ... },
  "feed_performance": [ ... ],
  "worst_days": [ ... ],
  "summary": "Solar production for CUST-1001 is about 34% below..."
}
```

---

## Response field reference

### Identity

| Field | How it's found |
|---|---|
| `customer_id` | Normalized from `query` or explicit field via `query_parsing.py` |
| `dataid` | Looked up from `demo_billing_data.json → accounts → meter_dataid` |
| `start_date` / `end_date` | Parsed from query ("October 2019" → Oct 1–31) or explicit fields |
| `solar_feeds_evaluated` | Which of `["solar", "solar2"]` have non-null data for this customer in the CSV |

---

### Detection

| Field | How it's found |
|---|---|
| `underperformance_detected` | `true` only when ALL four pass: `expected_kwh > 0`, `ratio < 0.85`, `intervals ≥ min_underperforming_intervals`, `days ≥ min_underperforming_days` |
| `severity` | Classified from `lost_pct`, `lost_kwh`, `underperforming_days`, and whether a partial inverter issue was found. Tiers: `none / low / medium / high / critical` |
| `likely_cause_category` | `"weather-related"` if weather context was used and adverse ratio ≥ 35%. `"possible partial inverter/feed issue"` if one feed is dropped while another is normal. Otherwise `"broad underperformance"` |

---

### Generation metrics

| Field | How it's found |
|---|---|
| `estimated_expected_generation_kwh` | Sum of per-slot expected kW × 0.25h across all daylight intervals. Each slot's expected kW comes from the 3-tier baseline (see below). |
| `actual_generation_kwh` | Sum of actual `solar` (+ `solar2`) readings × 0.25h across all daylight intervals |
| `estimated_lost_generation_kwh` | `expected - actual`, clipped to 0 |
| `lost_generation_pct_of_expected` | `lost / expected × 100` |
| `window_performance_ratio` | `actual / expected` for the whole window (e.g. 0.655 = 65.5% of expected) |

---

### Interval and day counts

| Field | How it's found |
|---|---|
| `daylight_interval_count` | Count of 15-min intervals where `expected_solar_kw ≥ 0.20` (filters nighttime) |
| `underperforming_interval_count` | Daylight intervals where `actual/expected < underperformance_ratio` AND `lost_kw ≥ 0.10 kW` |
| `underperforming_day_count` | Calendar days where daily `actual/expected < 0.75` AND `expected_kwh ≥ 1.0` |

---

### Financial metrics

| Field | How it's found |
|---|---|
| `credit_rate_usd_per_kwh` | From `credit_rate_usd_per_kwh` request field, or falls back to `plan.overage_rate` from billing JSON |
| `credit_rate_source` | `"request.credit_rate_usd_per_kwh"` if explicit, `"plan.overage_rate_proxy"` if defaulted |
| `estimated_lost_credit_value_usd` | `lost_kwh × credit_rate` |
| `projected_30_day_lost_generation_kwh` | `(lost_kwh / window_days) × 30` — assumes current rate continues |
| `rough_financial_impact_if_continues_30d_usd` | `projected_30d_kwh × credit_rate` |

---

### Baseline context

| Field | How it's found |
|---|---|
| `lookback_days` | From request (default 90) |
| `baseline_reference_source` | `"prior_lookback"` if 90-day window had ≥ 96 intervals, else `"all_other_history_fallback"` |
| `baseline_interval_count` | Number of historical rows used to build the baseline |
| `baseline_start` / `baseline_end` | Date range of the historical data used |
| `baseline_method` | Always: 3-tier slot-level baseline (same month+slot → same season+slot → same hour) |

**How the baseline works:** For each 15-min slot in the window, the agent looks at the same time-of-day slot in prior history and takes the average. Three tiers are tried in order, falling back to broader groupings if a slot has fewer than 8 historical samples:
1. Same month + same 15-min slot (most precise)
2. Same season + same 15-min slot
3. Same hour (broadest fallback)

---

### Weather adjustment

| Field | How it's found |
|---|---|
| `weather_context_used` | `true` if `weather_context` was passed in the request (or found in `context`) |
| `expected_generation_factor` | Scale applied to baseline: 0.65–1.0 based on adverse weather day ratio |
| `adverse_weather_ratio` | Fraction of days with cloudy/rainy/foggy/stormy WMO codes |
| `rationale` | Human-readable explanation of the factor chosen |

If `weather_context_used: false`, the baseline is used as-is. Pass the output of `weather_context_agent` to get a weather-corrected baseline that avoids false alarms on legitimately cloudy months.

---

### Feed performance

Per-feed breakdown (one entry per solar feed):

| Field | How it's found |
|---|---|
| `expected_kwh` | Baseline expected kWh for this feed alone (weather-adjusted) |
| `actual_kwh` | Actual kWh from this feed's column in the CSV |
| `performance_ratio` | `actual / expected` for this feed |
| `status` | `normal` (≥ 0.75), `low` (0.50–0.75), `dropped` (< 0.50), or `insufficient_expected_generation` |

If one feed is `dropped` while another is `normal`, `likely_cause_category` becomes `"possible partial inverter/feed issue"`.

---

### Worst days

Top 5 days by lost kWh. Only daylight intervals are counted.

| Field | How it's found |
|---|---|
| `expected_kwh` | Sum of slot-level expected kWh for this day's daylight intervals |
| `actual_kwh` | Sum of actual meter readings × 0.25h for this day |
| `estimated_lost_kwh` | `expected - actual` for the day |
| `performance_ratio` | `actual / expected` for the day |
| `underperforming_intervals` | Count of flagged 15-min slots on this day |
| `daylight_intervals` | Total daylight slots on this day (e.g. 43 = ~10.75 hours of expected sun) |

---

### Grid context

| Field | How it's found |
|---|---|
| `grid_data_available` | Whether the `grid` column exists and has non-null data in the CSV |
| `import_kwh` | Sum of positive `grid` values × 0.25h (drawing from utility) |
| `export_kwh` | Sum of negative `grid` values × 0.25h (selling back / net metering) |
| `export_interval_count` | Number of 15-min intervals where the customer was exporting |

---

## How to run locally

```bash
# From repo root
PYTHONPATH=. uvicorn src.agents.solar.solar_monitoring_service:app --host 0.0.0.0 --port 8010
```

---

## How to test (Postman)

`POST http://localhost:8010/api/solar_performance_credit_loss_agent`

**Basic:**
```json
{
  "query": "Check solar underperformance for customer CUST-1001 in October 2019."
}
```

**With weather context (prevents false alarms on cloudy months):**
```json
{
  "query": "Check solar underperformance for customer CUST-1001 in July 2019.",
  "weather_context": {
    "weather_condition_counts": {
      "overcast": 9,
      "light_drizzle": 9,
      "clear_sky": 1,
      "partly_cloudy": 3
    },
    "hot_days_count": 27
  }
}
```

---

## Data dependencies

| File | Purpose |
|---|---|
| `src/data/15minute_data_sample.csv` | 15-min meter readings — source of actual and baseline production data |
| `src/data/demo_billing_data.json` | Customer → dataid mapping and plan rate for credit calculations |

---

## Redeployment

```bash
az acr login --name uuoacrarya

docker buildx build \
  --platform linux/amd64 \
  -f src/agents/solar/Dockerfile \
  -t uuoacrarya.azurecr.io/solar-agent:latest \
  --push .

az containerapp update \
  --name solar-agent \
  --resource-group anomaly-agent-rg \
  --image uuoacrarya.azurecr.io/solar-agent:latest
```

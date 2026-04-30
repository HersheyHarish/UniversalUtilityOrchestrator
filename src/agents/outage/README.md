# Outage Detection Agent

Answers: *"Was there a power outage affecting this customer's area during this billing window?"*

Loads a static JSON file of known outage events and checks whether any overlap with the requested date range. 
---

## When it gets called

Ideally called **after** `anomaly_detection_agent` or `billing_agent` finds something suspicious. The orchestrator asks this agent to confirm or rule out a power outage as the cause before synthesizing an explanation.

Also feeds `billing_agent` via `billing_impact_hint` — if there was a significant outage, the billing agent can use that to evaluate whether a service credit applies.

---

## Endpoint

| | |
|---|---|
| **Local** | `POST http://localhost:8005/api/outage_detection_agent` |
| **Deployed** | `POST https://outage-agent.wonderfulrock-687dfc24.eastus2.azurecontainerapps.io/api/outage_detection_agent` |
| **Health** | `GET <base>/api/health` |

> **Use `https://` not `http://`** for the deployed endpoint — Azure Container Apps enforces HTTPS and POST requests will 405 on HTTP.

---

## Request payload

```json
{
  "query": "Was there an outage affecting customer CUST-1001 in July 2019?"
}
```

All fields except `query` are optional — customer ID and dates are parsed from the query automatically.

| Field | Type | Required | Description |
|---|---|---|---|
| `query` | string | yes | Natural-language question. Embed customer ID and month/date range. |
| `customer_id` | string | no | e.g. `CUST-1001`. Parsed from query if omitted. |
| `start_date` | string | no | ISO date or datetime. Parsed from query if omitted. |
| `end_date` | string | no | ISO date or datetime. Parsed from query if omitted. |
| `min_outage_minutes` | int | no | Minimum overlap to include an event. Default: 15. |

**Demo customers:** `CUST-1001` (Austin, TX · zip 78712) · `CUST-1002` (Portland, OR · zip 97201)

---

## Response

```json
{
  "agent": "outage_detection_agent",
  "status": "completed",
  "customer_id": "CUST-1001",
  "service_area": "78712",
  "city": "Austin",
  "state": "TX",
  "utility": "Austin Energy",
  "start_date": "2019-07-01T00:00:00",
  "end_date": "2019-07-31T23:59:59",
  "outage_detected": true,
  "outage_count": 2,
  "total_outage_minutes": 555.0,
  "longest_outage_minutes": 510.0,
  "severity": "high",
  "events": [
    {
      "outage_id": "OUT-78712-20190721",
      "event_start": "2019-07-21T14:00:00-05:00",
      "event_end": "2019-07-21T22:30:00-05:00",
      "duration_minutes": 510,
      "overlap_with_window_minutes": 510.0,
      "cause": "severe_weather",
      "scope": "regional",
      "estimated_customers_affected": 18500,
      "source": "synthetic_demo"
    }
  ],
  "summary": "Austin experienced 2 reported outage(s) during the requested window...",
  "billing_impact_hint": "Customer CUST-1001 was without utility power for ~555 min during this billing window."
}
```

### `severity` values

| Value | Condition |
|---|---|
| `critical` | ≥ 720 min (12 hours) total |
| `high` | ≥ 240 min (4 hours), or any regional-scope event |
| `medium` | ≥ 60 min |
| `low` | > 0 min |
| `none` | No overlapping outages found |

### `billing_impact_hint`

Set when total outage overlap ≥ 30 minutes. Designed to be passed directly to `billing_agent` to evaluate service credit eligibility. `null` if no significant outage.

---

## Demo outage data

All outages fall within the **May–October 2019** data window.

**CUST-1001 — Austin, TX (zip 78712)**

| Date | Cause | Duration | Scope | Customers Affected |
|---|---|---|---|---|
| Jul 21 | severe_weather | 510 min | regional | 18,500 |
| Jul 28 | scheduled_maintenance | 45 min | block | 220 |
| Oct 7 | equipment_failure | 285 min | neighborhood | 1,240 |

**CUST-1002 — Portland, OR (zip 97201)**

| Date | Cause | Duration | Scope | Customers Affected |
|---|---|---|---|---|
| Jun 12 | windstorm | 285 min | regional | 14,200 |
| Jul 11 | scheduled_maintenance | 30 min | block | 180 |
| Sep 18 | equipment_failure | 270 min | neighborhood | 870 |

---

## How to run locally

```bash
# From repo root
PYTHONPATH=. uvicorn src.agents.outage.outageDetectionAgent:app --host 0.0.0.0 --port 8005
```

---

## How to test (Postman)

`POST https://outage-agent.wonderfulrock-687dfc24.eastus2.azurecontainerapps.io/api/outage_detection_agent`

Body → raw → JSON:
```json
{
  "query": "Was there an outage affecting customer CUST-1001 in July 2019?"
}
```

Try CUST-1002 in June or September for Portland-specific outages.

---

## Data dependencies

| File | Purpose |
|---|---|
| `src/data/demo_outages.json` | Outage events and service area metadata |
| `src/data/demo_billing_data.json` | Customer → zip code mapping (single source of truth) |

Customer zip is read from `demo_billing_data.json → accounts → service_address → zip`. To add a new customer, update that file — no Python changes needed. To add new outage events, update `demo_outages.json → outages → <zip>`.

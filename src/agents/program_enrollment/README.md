# Program Enrollment Simulation Agent

Answers: *"What program would save this customer the most money, and by how much?"*

Simulates four utility enrollment programs against a customer's actual billing and 15-min meter data, ranks them by monthly impact, and returns a plain-English recommendation with per-program breakdowns. **Does not enroll the customer** — returns a comparison so the orchestrator can recommend the best option.

---

## When it gets called

- A customer asks why their bill is high and wants options to lower it
- The orchestrator finishes a `bill_shock_forecast_agent` run and wants to recommend relief programs
- A support agent is reviewing a high-bill complaint and needs program options to present

Composes naturally downstream of `bill_shock_forecast_agent`: pass `projected_bill_usd` and `projected_kwh` from the forecast response to simulate programs against a projected bill rather than a historical invoice.

---

## Endpoint

| | |
|---|---|
| **Local** | `POST http://localhost:8007/api/program_enrollment_simulation_agent` |
| **Deployed** | `POST https://program-enrollment-agent.wonderfulrock-687dfc24.eastus2.azurecontainerapps.io/api/program_enrollment_simulation_agent` |
| **Health** | `GET <base>/api/health` |

---

## Request payload

```json
{
  "query": "What programs could help CUST-1001 with their July 2019 bill?"
}
```

All fields except `query` are optional.

| Field | Type | Default | Description |
|---|---|---|---|
| `query` | string | required | Natural-language question. Embed customer ID and month/year. |
| `customer_id` | string | parsed from query | e.g. `CUST-1001` |
| `programs` | array of strings | all four | Subset to simulate: `level_pay`, `installment_plan`, `low_income_assistance`, `time_of_use` |
| `cycle_start` | string | parsed from query | ISO date `YYYY-MM-DD` |
| `cycle_end` | string | parsed from query | ISO date `YYYY-MM-DD` |
| `projected_bill_usd` | float | from invoice on file | Override bill amount — use the `projected_total_usd` from `bill_shock_forecast_agent` |
| `projected_kwh` | float | from invoice on file | Override kWh total — used by the low-income simulation |
| `installment_count` | int | 3 | Number of installments (2–12) |
| `low_income_discount_pct` | float | 0.25 | Fractional discount on energy charges, e.g. `0.25` = 25% |
| `tou_peak_rate` | float | 0.25 | Peak-hour $/kWh for TOU simulation (Mon–Fri 4–9pm) |
| `tou_off_peak_rate` | float | 0.08 | Off-peak $/kWh for TOU simulation |
| `assume_eligible` | bool | true | If false, skips low-income simulation entirely |
| `lookback_months` | int | 12 | How many prior invoices to use for the level-pay average |

**Demo customers:** `CUST-1001` (Austin, TX) · `CUST-1002` (Portland, OR)

---

## How the four programs are calculated

### Level Pay (Budget Billing)

Smooths the customer's bill by charging a fixed monthly average instead of the actual usage amount, with an annual true-up.

1. Load all invoices that **closed before** `cycle_start` (so future months never contaminate the lookback).
2. Take up to `lookback_months` of those invoices and compute the average total (`avg`).
3. `this_cycle_delta_usd = current_bill − avg` — positive means level pay would reduce this month's charge.
4. Eligible when ≥ 2 months of billing history exist.

**Example (CUST-1001, July 2019):** May and June invoices average to $114/month. Alice's July bill is $82, so level pay would actually *increase* her payment this month by $32 (she'd be smoothing a low month). Level pay is therefore not recommended, but TOU is.

---

### Installment Plan

Splits the current cycle's balance into equal payments over time. Cash-flow relief only — no net savings.

1. `per_installment_usd = current_bill / installment_count`
2. Always shown as an option in the summary; never auto-recommended because it produces zero savings.

**Example (CUST-1001, July 2019):** $82 bill ÷ 3 = $27.47/month.

---

### Low-Income Assistance

Applies a percentage discount to the customer's energy charges (base charge + overage).

1. Pull `base_charge` and `overage_rate` from the customer's plan.
2. Compute overage: `max(0, current_kwh − baseline_kwh) × overage_rate`
3. `energy_charge = base_charge + overage`
4. `discount = energy_charge × low_income_discount_pct`
5. `simulated_total = current_bill − discount`

Always shown as an option in the summary with a "call to verify" note; never auto-recommended because real enrollment requires income verification.

**Example (CUST-1001, July 2019):** Energy charges of ~$180 × 25% = ~$45 savings/month (~$540/year if eligible).

---

### Time-of-Use (TOU)

Reprices the customer's actual 15-min meter readings using peak and off-peak rates instead of their current flat rate. This is a **permanent rate plan switch**, not a one-time program.

1. Filter the `15minute_data_sample.csv` to the customer's `dataid` and the requested billing cycle.
2. Classify each interval: peak = Mon–Fri 16:00–21:00; all other times = off-peak.
3. `flat_cost = total_kwh × plan.overage_rate`
4. `tou_cost = peak_kwh × tou_peak_rate + off_peak_kwh × tou_off_peak_rate`
5. `monthly_savings_usd = flat_cost − tou_cost`
6. Eligible only when meter data exists for the cycle.

**Example (CUST-1001, July 2019):** Total usage ~307 kWh at flat $0.14 = $43. Under TOU: only 0% of usage falls in peak hours, so nearly all kWh price at $0.08 off-peak → TOU cost ~$25, saving ~$18.

---

## Recommendation logic

Only two programs compete for the auto-recommendation slot:

| Program | Ranking score | Why |
|---|---|---|
| `level_pay` | `this_cycle_delta_usd` (positive = saves money this cycle) | Only wins if current bill is above the historical average |
| `time_of_use` | `monthly_savings_usd` | Wins when off-peak usage outweighs peak exposure |
| `installment_plan` | never recommended | Cash-flow only — no savings |
| `low_income_assistance` | never recommended | Requires income verification — always shown separately |

The agent picks the program with the highest positive score. If no program produces a positive monthly impact, `recommendation` is `null` and the summary says so.

Installment plan and low-income assistance are always appended to the summary as options regardless of who wins the recommendation.

---

## Response

```json
{
  "agent": "program_enrollment_simulation_agent",
  "status": "completed",
  "customer_id": "CUST-1001",
  "plan_name": "Standard Residential",
  "context": {
    "current_bill_usd": 82.0,
    "current_kwh": 451.5,
    "bill_source": "from_invoice",
    "cycle_start": "2019-07-01T00:00:00",
    "cycle_end": "2019-07-31T23:59:59"
  },
  "programs": [
    {
      "name": "level_pay",
      "eligible": true,
      "level_pay_amount_usd": 114.0,
      "this_cycle_delta_usd": -32.0,
      "max_swing_avoided_usd": 36.0,
      "history_window_months": 2,
      "summary": "Level pay would charge ~$114/month, which would increase this cycle by $32..."
    },
    {
      "name": "installment_plan",
      "eligible": true,
      "installments": 3,
      "per_installment_usd": 27.47,
      "total_repayment_usd": 82.0,
      "monthly_savings_usd": 0.0,
      "summary": "Pay $27.47 per installment over 3 months."
    },
    {
      "name": "low_income_assistance",
      "eligible": true,
      "discount_pct": 0.25,
      "monthly_savings_usd": 45.0,
      "annualized_savings_usd": 540.0,
      "simulated_total_usd": 37.0,
      "summary": "If eligible, this customer would save ~$45 this cycle (~$540/year)."
    },
    {
      "name": "time_of_use",
      "eligible": true,
      "total_kwh": 307.5,
      "peak_kwh": 0.0,
      "off_peak_kwh": 307.5,
      "peak_share_pct": 0.0,
      "monthly_savings_usd": 18.0,
      "annualized_savings_usd": 216.0,
      "summary": "Currently paying a flat $0.14/kWh... switching to TOU would save ~$18."
    }
  ],
  "recommendation": "time_of_use",
  "summary": "For customer CUST-1001 (current cycle bill ~$82), the top recommendation is `time_of_use`... If you need to spread the payment, an installment plan of $27.47/month over 3 months is available. Additionally, low income assistance could save ~$45/month (~$540/year) if eligible — customer should call to verify qualification."
}
```

### Key response fields

| Field | How it's set |
|---|---|
| `bill_source` | `"from_invoice"` if pulled from billing data, `"from_request"` if `projected_bill_usd` was passed in |
| `history_window_months` | Number of historical invoices actually used (only those closed before `cycle_start`) |
| `recommendation` | Name of the winning program, or `null` if no program saves money |
| `summary` | One paragraph covering the top recommendation + installment and low-income options |

---

## How to run locally

```bash
# From repo root
PYTHONPATH=. uvicorn src.agents.program_enrollment.program_simulation_service:app --host 0.0.0.0 --port 8007
```

---

## How to test (Postman)

`POST https://program-enrollment-agent.wonderfulrock-687dfc24.eastus2.azurecontainerapps.io/api/program_enrollment_simulation_agent`

**Basic:**
```json
{
  "query": "What programs could help CUST-1001 with their July 2019 bill?"
}
```

**Downstream of bill_shock (pass the forecast output in):**
```json
{
  "query": "Simulate programs for CUST-1001 for July 2019",
  "projected_bill_usd": 95.00,
  "projected_kwh": 520.0
}
```

**Only simulate specific programs:**
```json
{
  "query": "Would TOU or level pay help CUST-1002 in August 2019?",
  "programs": ["level_pay", "time_of_use"]
}
```

> **Use `https://` not `http://`** — Azure Container Apps enforces HTTPS.

---

## Data dependencies

| File | Purpose |
|---|---|
| `src/data/demo_billing_data.json` | Customer accounts, plan rates, and invoice history |
| `src/data/15minute_data_sample.csv` | 15-min meter readings — required for TOU simulation |

---

## Redeployment

```bash
docker buildx build \
  --platform linux/amd64 \
  -f src/agents/program_enrollment/Dockerfile \
  -t uuoacrarya.azurecr.io/program-enrollment-agent:latest \
  --push .

az containerapp up \
  --name program-enrollment-agent \
  --resource-group anomaly-agent-rg \
  --location eastus2 \
  --image uuoacrarya.azurecr.io/program-enrollment-agent:latest \
  --ingress external \
  --target-port 8007
```

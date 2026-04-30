#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

BASE_DOMAIN="${BASE_DOMAIN:-wonderfulrock-687dfc24.eastus2.azurecontainerapps.io}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

pass_count=0
fail_count=0

run_check() {
    local name="$1"
    local cmd="$2"

    echo -e "${YELLOW}==>${NC} $name"
    if bash -lc "$cmd"; then
        echo -e "${GREEN}PASS${NC} $name"
        pass_count=$((pass_count + 1))
    else
        echo -e "${RED}FAIL${NC} $name"
        fail_count=$((fail_count + 1))
    fi
    echo
}

health_check() {
    local name="$1"
    local app="$2"
    run_check "$name health" "curl -fsS --retry 5 --retry-delay 2 \"https://${app}.${BASE_DOMAIN}/api/health\" > /dev/null"
}

post_check() {
    local name="$1"
    local app="$2"
    local path="$3"
    local payload="$4"
    local tmp_payload
    tmp_payload="$(mktemp)"
    printf '%s' "$payload" > "$tmp_payload"
    run_check "$name main endpoint" "curl -fsS --retry 5 --retry-delay 2 -X POST \"https://${app}.${BASE_DOMAIN}${path}\" -H 'Content-Type: application/json' --data-binary @$tmp_payload > /dev/null"
    rm -f "$tmp_payload"
}

health_check  "anomaly_detection_agent"             "anomaly-agent"
post_check    "anomaly_detection_agent"             "anomaly-agent"            "/api/anomaly_detection_agent"             '{"query":"Did customer CUST-1001 have a usage spike in July 2019?"}'

health_check  "customer_lookup_agent"               "customer-lookup-agent"
post_check    "customer_lookup_agent"               "customer-lookup-agent"    "/api/customer_lookup_agent"               '{"query":"Show me the account details for customer CUST-1001."}'

health_check  "weather_context_agent"               "weather-agent"
post_check    "weather_context_agent"               "weather-agent"            "/api/weather_context_agent"               '{"query":"Check whether weather may explain high usage for customer CUST-1001 in July 2019."}'

health_check  "outage_detection_agent"              "outage-agent"
post_check    "outage_detection_agent"              "outage-agent"             "/api/outage_detection_agent"              '{"query":"Was there an outage affecting customer CUST-1001 in July 2019?"}'

health_check  "bill_shock_forecast_agent"           "bill-shock-agent"
post_check    "bill_shock_forecast_agent"           "bill-shock-agent"         "/api/bill_shock_forecast_agent"           '{"query":"Will customer CUST-1001 have bill shock for July 2019 as of 2019-07-15?"}'

health_check  "program_enrollment_simulation_agent" "program-enrollment-agent"
post_check    "program_enrollment_simulation_agent" "program-enrollment-agent" "/api/program_enrollment_simulation_agent" '{"query":"Would level pay or budget billing help customer CUST-1001 for July 2019?"}'

health_check  "payment_risk_hardship_agent"         "payment-risk-agent"
post_check    "payment_risk_hardship_agent"         "payment-risk-agent"       "/api/payment_risk_hardship_agent"         '{"query":"Is customer CUST-1001 at risk of delinquency?"}'

health_check  "solar_performance_credit_loss_agent" "solar-agent"
post_check    "solar_performance_credit_loss_agent" "solar-agent"              "/api/solar_performance_credit_loss_agent" '{"query":"Check solar underperformance for customer CUST-1001 in July 2019."}'

echo "----------------------------------------"
echo "Smoke test complete: ${pass_count} passed, ${fail_count} failed"

if [[ $fail_count -gt 0 ]]; then
    exit 1
fi

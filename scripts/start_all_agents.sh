#!/usr/bin/env bash
# scripts/start_all_agents.sh

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$REPO_ROOT/scripts/stop_all.sh"

echo "Environment set, activating virtual environment..."
if [ -d "$REPO_ROOT/.venv" ]; then
    source "$REPO_ROOT/.venv/bin/activate"
elif [ -d "$REPO_ROOT/venv" ]; then
    source "$REPO_ROOT/venv/bin/activate"
fi

export PYTHONPATH="$REPO_ROOT:$PYTHONPATH"

# Ensure log directory exists
mkdir -p "$REPO_ROOT/scripts/logs"

echo "Starting Billing Agent (8001)..."
export PORT=8001
nohup uvicorn src.agents.billing.app:app --host 0.0.0.0 --port $PORT > "$REPO_ROOT/scripts/logs/billing_agent.log" 2>&1 &
echo $! > "$REPO_ROOT/scripts/logs/billing_agent.pid"

echo "Starting Anomaly Detection Agent (8000)..."
export PORT=8000
nohup uvicorn src.agents.anomaly.anomaly_service:app --host 0.0.0.0 --port $PORT > "$REPO_ROOT/scripts/logs/anomaly_agent.log" 2>&1 &
echo $! > "$REPO_ROOT/scripts/logs/anomaly_agent.pid"

echo "Starting Customer Lookup Agent (8002)..."
export PORT=8002
nohup uvicorn src.agents.supportAgents.customerLookupAgent:app --host 0.0.0.0 --port $PORT > "$REPO_ROOT/scripts/logs/customer_lookup.log" 2>&1 &
echo $! > "$REPO_ROOT/scripts/logs/customer_lookup.pid"

echo "Starting Conversation Summary Agent (8003)..."
export PORT=8003
nohup uvicorn src.agents.supportAgents.conversationSummaryAgent:app --host 0.0.0.0 --port $PORT > "$REPO_ROOT/scripts/logs/summary_agent.log" 2>&1 &
echo $! > "$REPO_ROOT/scripts/logs/summary_agent.pid"

echo "Starting Weather Context Agent (8004)..."
export PORT=8004
nohup uvicorn src.agents.weather.weatherContextAgent:app --host 0.0.0.0 --port $PORT > "$REPO_ROOT/scripts/logs/weather_context_agent.log" 2>&1 &
echo $! > "$REPO_ROOT/scripts/logs/weather_context_agent.pid"

echo "Starting Outage Detection Agent (8005)..."
export PORT=8005
nohup uvicorn src.agents.outage.outageDetectionAgent:app --host 0.0.0.0 --port $PORT > "$REPO_ROOT/scripts/logs/outage_detection_agent.log" 2>&1 &
echo $! > "$REPO_ROOT/scripts/logs/outage_detection_agent.pid"

echo "Starting Bill Shock Forecast Agent (8006)..."
export PORT=8006
nohup uvicorn src.agents.bill_shock.bill_shock_service:app --host 0.0.0.0 --port $PORT > "$REPO_ROOT/scripts/logs/bill_shock_forecast_agent.log" 2>&1 &
echo $! > "$REPO_ROOT/scripts/logs/bill_shock_forecast_agent.pid"

echo "Starting Program Enrollment Simulation Agent (8007)..."
export PORT=8007
nohup uvicorn src.agents.program_enrollment.program_simulation_service:app --host 0.0.0.0 --port $PORT > "$REPO_ROOT/scripts/logs/program_enrollment_simulation_agent.log" 2>&1 &
echo $! > "$REPO_ROOT/scripts/logs/program_enrollment_simulation_agent.pid"

echo "Starting Proactive Outreach Agent (8008)..."
export PORT=8008
nohup uvicorn src.agents.outreach.outreach_decision_service:app --host 0.0.0.0 --port $PORT > "$REPO_ROOT/scripts/logs/proactive_outreach_agent.log" 2>&1 &
echo $! > "$REPO_ROOT/scripts/logs/proactive_outreach_agent.pid"

echo "Starting Payment Risk & Hardship Agent (8009)..."
export PORT=8009
nohup uvicorn src.agents.payment_risk.payment_risk_service:app --host 0.0.0.0 --port $PORT > "$REPO_ROOT/scripts/logs/payment_risk_hardship_agent.log" 2>&1 &
echo $! > "$REPO_ROOT/scripts/logs/payment_risk_hardship_agent.pid"

echo "Starting Solar Performance & Credit Loss Agent (8010)..."
export PORT=8010
nohup uvicorn src.agents.solar.solar_monitoring_service:app --host 0.0.0.0 --port $PORT > "$REPO_ROOT/scripts/logs/solar_performance_credit_loss_agent.log" 2>&1 &
echo $! > "$REPO_ROOT/scripts/logs/solar_performance_credit_loss_agent.pid"

echo "All agents started successfully in the background!"
echo "Check scripts/logs/ for outputs."

#!/usr/bin/env bash
# scripts/stop_all.sh

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$REPO_ROOT/scripts/logs"

echo "Stopping any running agents..."

for pid_file in "$LOG_DIR"/*.pid; do
    if [ -f "$pid_file" ]; then
        PID=$(cat "$pid_file")
        if ps -p $PID > /dev/null 2>&1; then
            echo "Killing process $PID from $pid_file"
            kill -9 $PID
        fi
        rm -f "$pid_file"
    fi
done

# Fallback explicit cleanup matching older standard script naming conventions
pkill -f "src/agents/anomaly/api.py" || true
pkill -f "src.agents.anomaly.anomaly_service:app" || true
pkill -f "src.agents.billing.app:app" || true
pkill -f "src.agents.supportAgents.customerLookupAgent:app" || true
pkill -f "src.agents.supportAgents.conversationSummaryAgent:app" || true
pkill -f "src.agents.weather.weatherContextAgent:app" || true
pkill -f "src.agents.outage.outageDetectionAgent:app" || true
pkill -f "src/agents/supportAgents/customerLookupAgent.py" || true
pkill -f "src/agents/supportAgents/conversationSummaryAgent.py" || true
pkill -f "src/agents/weather/weatherContextAgent.py" || true
pkill -f "src/agents/outage/outageDetectionAgent.py" || true
pkill -f "src.agents.bill_shock.bill_shock_service:app" || true
pkill -f "src.agents.program_enrollment.program_simulation_service:app" || true
pkill -f "src.agents.outreach.outreach_decision_service:app" || true
pkill -f "src/agents/solar/api.py" || true
pkill -f "src.agents.solar.solar_monitoring_service:app" || true
pkill -f "src.agents.payment_risk.payment_risk_service:app" || true

echo "Agents stopped."

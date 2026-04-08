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
nohup uvicorn src.billing.app:app --host 0.0.0.0 --port $PORT > "$REPO_ROOT/scripts/logs/billing_agent.log" 2>&1 &
echo $! > "$REPO_ROOT/scripts/logs/billing_agent.pid"

echo "Starting Anomaly Detection Agent (8000)..."
export PORT=8000
nohup python "$REPO_ROOT/src/agents/anomalyAgent.py" > "$REPO_ROOT/scripts/logs/anomaly_agent.log" 2>&1 &
echo $! > "$REPO_ROOT/scripts/logs/anomaly_agent.pid"

echo "Starting Customer Lookup Agent (8002)..."
export PORT=8002
nohup python "$REPO_ROOT/src/agents/customerLookupAgent.py" > "$REPO_ROOT/scripts/logs/customer_lookup.log" 2>&1 &
echo $! > "$REPO_ROOT/scripts/logs/customer_lookup.pid"

echo "Starting Conversation Summary Agent (8003)..."
export PORT=8003
nohup python "$REPO_ROOT/src/agents/conversationSummaryAgent.py" > "$REPO_ROOT/scripts/logs/summary_agent.log" 2>&1 &
echo $! > "$REPO_ROOT/scripts/logs/summary_agent.pid"

echo "All agents started successfully in the background!"
echo "Check scripts/logs/ for outputs."

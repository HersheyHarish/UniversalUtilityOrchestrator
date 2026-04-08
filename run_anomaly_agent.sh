#!/bin/bash

# Local run script (Docker bypassed since Daemon is down)

# Find absolute path of the environment script
VENV_PATH="$(cd .. && pwd)/.venv/bin/activate"

if [ -f "$VENV_PATH" ]; then
    source "$VENV_PATH"
elif [ -d ".venv" ]; then
    source .venv/bin/activate
fi

if [ -f "anomaly_agent.pid" ]; then
    echo "Anomaly agent might already be running. Run ./stop_agents.sh first."
    exit 0
fi

echo "--- Starting anomaly agent on http://localhost:8000 ---"
export PORT=8000
nohup python -m src.agents.anomalyAgent > anomaly_agent.log 2>&1 &
echo $! > anomaly_agent.pid

echo "Anomaly agent started with PID $(cat anomaly_agent.pid). Test with:"
echo "curl -s -X POST http://localhost:8000/anomaly_detection_agent -H 'Content-Type: application/json' -d '{\"user_id\":4550,\"start_date\":\"2019-10-24T23:45:00-05:00\",\"end_date\":\"2019-10-31T23:45:00-05:00\"}'"

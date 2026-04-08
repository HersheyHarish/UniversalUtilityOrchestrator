#!/bin/bash

# Local run script (Docker bypassed since Daemon is down)

VENV_PATH="$(cd .. && pwd)/.venv/bin/activate"

if [ -f "$VENV_PATH" ]; then
    source "$VENV_PATH"
elif [ -d ".venv" ]; then
    source .venv/bin/activate
fi

if [ -f "billing_agent.pid" ]; then
    echo "Billing agent might already be running. Run ./stop_agents.sh first."
    exit 0
fi

echo "--- Starting billing agent on http://localhost:8001 ---"
export PORT=8001
nohup python -m src.agents.billingAgent > billing_agent.log 2>&1 &
echo $! > billing_agent.pid

echo "Billing agent started with PID $(cat billing_agent.pid). Test with:"
echo "curl -s http://localhost:8001/health"

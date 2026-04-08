#!/bin/bash

# Stops locally running native python agents

for agent in anomaly_agent billing_agent; do
    if [ -f "${agent}.pid" ]; then
        PID=$(cat "${agent}.pid")
        echo "--- Stopping ${agent} (PID: $PID) ---"
        kill -9 "$PID" 2>/dev/null || true
        rm "${agent}.pid"
    fi
done

# Failsafe port kill just in case PIDs were lost
lsof -ti:8000 | xargs kill -9 2>/dev/null || true
lsof -ti:8001 | xargs kill -9 2>/dev/null || true

echo "Agent processes stopped."

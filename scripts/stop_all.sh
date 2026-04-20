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
pkill -f "src/agents/anomalyAgent.py" || true
pkill -f "src.billing.app:app" || true
pkill -f "src/agents/customerLookupAgent.py" || true
pkill -f "src/agents/conversationSummaryAgent.py" || true

echo "Agents stopped."

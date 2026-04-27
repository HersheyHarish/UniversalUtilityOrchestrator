#!/usr/bin/env bash
# scripts/start_orchestrator.sh

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ -d "$REPO_ROOT/.venv" ]; then
    source "$REPO_ROOT/.venv/bin/activate"
elif [ -d "$REPO_ROOT/venv" ]; then
    source "$REPO_ROOT/venv/bin/activate"
fi

cd "$REPO_ROOT"
echo "Starting Azure Functions Orchestrator Host..."
func start --port 7071

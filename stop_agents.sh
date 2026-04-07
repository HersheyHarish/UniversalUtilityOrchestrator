#!/bin/bash

set -euo pipefail

for container in billing_agent_local anomaly_agent_local; do
    if [ "$(docker ps -aq -f name=^/${container}$)" ]; then
        echo "--- Stopping ${container} ---"
        docker rm -f "${container}" >/dev/null
    fi
done

echo "Agent containers stopped."

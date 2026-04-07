#!/bin/bash

set -euo pipefail

CONTAINER_NAME="billing_agent_local"
IMAGE_NAME="utility-agent-alpine"

if [ "$(docker ps -q -f name=^/${CONTAINER_NAME}$)" ]; then
    echo "Billing agent already running at http://localhost:8001"
    exit 0
fi

if [ ! "$(docker images -q ${IMAGE_NAME} 2>/dev/null)" ]; then
    echo "--- Building shared image ${IMAGE_NAME} ---"
    docker build -t "${IMAGE_NAME}" .
fi

if [ "$(docker ps -aq -f name=^/${CONTAINER_NAME}$)" ]; then
    echo "--- Removing stopped container ${CONTAINER_NAME} ---"
    docker rm -f "${CONTAINER_NAME}" >/dev/null
fi

echo "--- Starting billing agent on http://localhost:8001 ---"
docker run -d \
    --name "${CONTAINER_NAME}" \
    -p 8001:8001 \
    -v "$(pwd)":/app \
    "${IMAGE_NAME}" \
    python -m src.agents.billingAgent >/dev/null

echo "Billing agent started. Test with:"
echo "curl -s http://localhost:8001/health"

#!/bin/bash

set -euo pipefail

CONTAINER_NAME="anomaly_agent_local"
IMAGE_NAME="utility-agent-alpine"

if [ "$(docker ps -q -f name=^/${CONTAINER_NAME}$)" ]; then
    echo "Anomaly agent already running at http://localhost:8000"
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

echo "--- Starting anomaly agent on http://localhost:8000 ---"
docker run -d \
    --name "${CONTAINER_NAME}" \
    -p 8000:8000 \
    -v "$(pwd)":/app \
    "${IMAGE_NAME}" \
    python -m src.agents.anomalyAgent >/dev/null

echo "Anomaly agent started. Test with:"
echo "curl -s -X POST http://localhost:8000/anomaly_detection_agent -H 'Content-Type: application/json' -d '{\"user_id\":4550,\"start_date\":\"2019-10-24T23:45:00-05:00\",\"end_date\":\"2019-10-31T23:45:00-05:00\"}'"

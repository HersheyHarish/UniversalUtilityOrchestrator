#!/bin/bash

CONTAINER_NAME="utility_agent_dev"
IMAGE_NAME="utility-agent-alpine"

if [ "$(docker ps -q -f name=$CONTAINER_NAME)" ]; then
    echo "--- Container is already running. Entering terminal... ---"
    docker exec -it $CONTAINER_NAME /bin/sh
    exit 0
fi

if [ "$(docker ps -aq -f status=exited -f name=$CONTAINER_NAME)" ]; then
    echo "--- Starting existing stopped container... ---"
    docker start $CONTAINER_NAME
    docker exec -it $CONTAINER_NAME /bin/sh
    exit 0
fi

echo "--- Container not found. Building and starting fresh... ---"
docker build -t $IMAGE_NAME .
docker run -d \
    --name $CONTAINER_NAME \
    -v $(pwd):/app \
    $IMAGE_NAME

echo "--- Entering Interactive Terminal ---"
docker exec -it $CONTAINER_NAME /bin/sh
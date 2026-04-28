#!/bin/bash
set -e

echo "Building and running tests in Docker..."
docker-compose -f docker-compose.test.yml build
docker-compose -f docker-compose.test.yml run --rm test-runner

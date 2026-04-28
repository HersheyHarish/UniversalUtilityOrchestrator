# Tests

This directory contains fast, mocked unit tests for the Azure orchestrator and registry components.
These tests use `pytest`, `pytest-asyncio`, and `respx` to mock out all external network calls (such as Azure OpenAI, Cosmos DB, and remote agents).

## How to Run Locally (via Docker)

A standalone Docker Compose environment is provided to run these tests predictably across environments, mirroring the CI setup.

From the root `UniversalUtilityAgent` directory, run the test script:

```bash
./run_tests.sh
```

Alternatively, you can run the compose command directly:
```bash
docker-compose -f docker-compose.test.yml build
docker-compose -f docker-compose.test.yml run --rm test-runner
```

## How to Run without Docker

If you prefer to run tests directly on your host machine (assuming Python 3.11+):

1. Create a virtual environment and activate it.
2. Install the application requirements:
   ```bash
   pip install -r azure/orchestrator/requirements.txt
   pip install -r azure/registry/requirements.txt
   ```
3. Install the test requirements:
   ```bash
   pip install -r tests/requirements-test.txt
   ```
4. Run pytest for each app, setting the PYTHONPATH to its root:
   ```bash
   PYTHONPATH="azure/orchestrator" pytest tests/orchestrator/
   PYTHONPATH="azure/registry" pytest tests/registry/
   ```

The Universal Utility Orchestrator is an autonomous orchestration layer to sequence agents to achieve a goal. It is designed to be flexible and adaptable, allowing it to work with a wide range of agents and tasks.

## Orchestration Flow
The orchestrator now runs a full pipeline:
1. Input Guardrails: sanitizes user input and blocks risky prompt-injection patterns.
2. Planning Service: asks the LLM to create a structured multi-step JSON plan.
3. DAG Creator: validates dependencies and builds topological execution layers.
4. Agent Execution: selects agents by capability and calls their registered endpoints.
5. Final Synthesis: composes a user-facing answer from all step outputs.

## Agent Endpoint Contract
Each registered agent endpoint is called with:
```json
{
  "query": "user request",
  "step": {
    "id": "step_1",
    "objective": "step objective",
    "required_capabilities": ["..."],
    "dependencies": ["step_0"],
    "output_key": "..."
  },
  "context": {
    "dependency_outputs": {},
    "all_step_results": {}
  }
}
```

The orchestrator accepts either JSON or plain-text responses from agents.

## Run Locally
To run the Universal Utility Orchestrator locally, follow these steps:

1. Download Ollama Locally on your machine and pull the image:
```bash
ollama pull llama3.1:8b
```
2. Navigate to the project directory:
```bash
cd UniversalUtilityAgent
```
3. Run run_dev.sh:
```bash
chmod +x run_dev.sh
./run_dev.sh
```
4. Once in interactive mode within docker, cd into project directory and run orchestrator.py:
```bash
cd UniversalUtilityAgent/src/core
python3 orchestrator.py
```

## Run Agents Locally With Docker
The repo now includes small launcher scripts that reuse the existing Docker image and start the FastAPI agents directly.

Here's an example of starting the anomaly agent:

Start the anomaly agent:
```bash
bash run_anomaly_agent.sh
```

Anomaly agent test request:
```bash
curl -s -X POST http://localhost:8000/anomaly_detection_agent \
  -H "Content-Type: application/json" \
  -d '{"user_id":3488,"start_date":"2019-10-24T23:45:00-05:00","end_date":"2019-10-31T23:45:00-05:00"}'
```

Here's an example of starting the billing agent:


Start the billing agent:
```bash
bash run_billing_agent.sh
```

Billing agent test request:
```bash
curl -s -X POST http://localhost:8001/billing_agent \
  -H "Content-Type: application/json" \
  -d '{"query":"Why was customer CUST-1001 charged in July 2025?"}'
```

Stop both agent containers:
```bash
bash stop_agents.sh
```
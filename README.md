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

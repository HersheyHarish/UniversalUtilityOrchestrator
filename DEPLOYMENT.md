# Universal Utility Orchestrator: Deployment & Architecture Guide

Welcome to the comprehensive deployment and architecture documentation for the **Universal Utility Orchestrator**. This guide provides development and operations teams with everything required to deploy, run, and scale the multi-agent system.

---

## 1. System Architecture

The Orchestrator follows a **Hub and Spoke** event-driven pattern:
- **Hub (Orchestrator)**: An Azure Functions serverless API (`func host`) running on `localhost:7071`. It leverages `gpt-5.4-nano` (or equivalent Azure OpenAI model) through LangChain to act as the primary planner. It takes a raw natural language query, breaks it down into a Directed Acyclic Graph (DAG) Execution Plan, and sequentially or asynchronously dispatches HTTP payloads to specialized agents.
- **Spokes (Agents)**: A fleet of independent FastAPI microservices. These are registered dynamically into an `agents.json` registry. The orchestrator uses these to offload data retrieval, algorithmic execution (e.g. Scikit-learn), or secondary RAG pipelines.
- **Interface**: A Streamlit chat UI (`localhost:8501`) acts as the front-end, visually exposing the orchestrator's "Chain-of-Thought" plans to stakeholders.

![Architecture Layout](architecture_diagram_placeholder.png)

---

## 2. Environment & Requirements

### Prerequisites
- **Python**: `3.10+`
- **Docker**: (Optional) For running models or pre-containerized hubs.
- **Azure Functions Core Tools**: `v4.x` (For running the `func start` host locally).
- **Ollama**: Running locally with `llama3.1:8b` pulled for secondary local modeling.

### Core Environment Variables (`local.settings.json`)
```json
{
  "IsEncrypted": false,
  "Values": {
    "FUNCTIONS_WORKER_RUNTIME": "python",
    "AzureWebJobsStorage": "UseDevelopmentStorage=true",
    "AZURE_OPENAI_API_KEY": "<your-azure-key>",
    "AZURE_OPENAI_ENDPOINT": "<your-azure-endpoint>",
    "OLLAMA_BASE_URL": "http://localhost:11434"
  }
}
```

---

## 3. Deployment Scripts Quickstart

We have refactored all disparate run routines into three simple start scripts located under `scripts/`.

### Activating the Ecosystem

1. **Start the Fleet of Agents**:
   Spin up all microservices in the background. Logs are written to `scripts/logs/*.log`.
   ```bash
   ./scripts/start_all_agents.sh
   ```

2. **Start the Orchestrator Host**:
   Start the Azure Functions runtime for the main routing engine.
   ```bash
   ./scripts/start_orchestrator.sh
   ```

3. **Launch the Demo Interface**:
   Spin up the visual UI to test the workflows.
   ```bash
   ./scripts/start_ui.sh
   ```

### Stopping the Ecosystem
To cleanly kill all background agent PIDs:
```bash
./scripts/stop_all.sh
```

*(Note: Stop Azure Functions and Streamlit via `CTRL+C` in their respective terminals).*

---

## 4. Agent Registry & API Endpoints

The orchestrator dynamically routes payloads depending on the registered API schema and the agent capabilities defined in `src/core/agents.json`.

Below is the definitive reference for the currently deployed active agents:

### A. Billing Agent
- **Description**: Generates accurate billing reports and RAG-based explanations by citing policy markdowns.
- **Endpoint**: `POST http://localhost:8001/api/billing_agent`
- **Payload Schema**:
  ```json
  {
    "query": "Why was CUST-1001 charged $150 in July 2019?",
    "customer_id": "CUST-1001", 
    "start_date": "2019-07-01T00:00:00",
    "end_date": "2019-07-31T23:59:59"
  }
  ```

### B. Anomaly Detection Agent
- **Description**: Uses `IsolationForest` + `Z-Score` clustering on backend CSV datasets to spot electricity usage spikes in 15-minute intervals.
- **Endpoint**: `POST http://localhost:8000/api/anomaly_detection_agent`
- **Payload Schema**:
  ```json
  {
    "query": "Check usage spikes for CUST-1002 in July 2019",
    "customer_id": "CUST-1002",
    "start_date": "2019-07-01T00:00:00",
    "end_date": "2019-07-31T23:59:59",
    "user_id": 3488, 
    "max_results": 5
  }
  ```

### C. Customer Lookup Agent
- **Description**: Pure explicit data retrieval (no LLM overhead). Identifies core profile information, plan packages, and aggregates historic invoices.
- **Endpoint**: `POST http://localhost:8002/api/customer_lookup_agent`
- **Payload Schema**:
  ```json
  {
    "query": "Get info on CUST-1001",
    "customer_id": "CUST-1001"
  }
  ```

### D. Conversation Summary Agent
- **Description**: Compresses long conversation histories and dependency execution outputs into concise bullet-pointed executive summaries using `Ollama`.
- **Endpoint**: `POST http://localhost:8003/api/conversation_summary_agent`
- **Payload Schema**:
  ```json
  {
    "query": "Summarize what we discussed.",
    "context": {
      "all_step_results": {"step_1": "...", "step_2": "..."},
      "history": ["..."]
    }
  }
  ```

### Hot-Plugging New Agents (CLI)
Dev teams can hot-plug new agents directly into the running orchestrator without restarting it by using the CLI.
```bash
python src/core/add_agent.py add \
  --name "new_custom_agent" \
  --description "Description of what it does" \
  --capabilities "cap 1" "cap 2" \
  --endpoint "http://localhost:8004/api/new_custom_agent" \
  --timeout 30 \
  --input-schema '{"type":"object", "required":["query"], "properties": {"query": {"type":"string"}}}'
```

---

## 5. Trace Debugging & Persistent Memory

The orchestrator utilizes a dual memory strategy. In production, this can hook into `Azure CosmosDB`. Locally, it defaults to the `LocalFileMemoryStore`, actively caching all requests securely as JSON dumps inside `src/data/traces/<session_id>/`.

To debug backend logic instantly without parsing logs, developers can use the CLI:

1. **List Active Sessions:**
   ```bash
   python src/core/view_memory.py list
   ```
2. **View a Session's Trace:**
   ```bash
   python src/core/view_memory.py <session_id>
   ```

## 6. Advanced Testing

You can definitively prove that the LLM Orchestrator is utilizing proper "Routing Specialization" (minimizing unneeded parallel calls and executing purely required capabilities) by testing it directly via script using temperature `0.0` execution paths:
```bash
python test_routing.py
```

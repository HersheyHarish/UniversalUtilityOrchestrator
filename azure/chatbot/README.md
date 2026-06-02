# Utility Chatbot Frontend UI

This directory contains the React-based customer service chatbot interface for the Universal Utility Orchestrator, built using React 18, Vite, and Lucide React.

---

## Getting Started Locally

### 1. Prerequisite Installations
Ensure you have Node.js 18+ or 20+ installed on your host machine.

### 2. Run the Development Server
Install npm dependencies:
```bash
npm install
```

Start the Vite development server:
```bash
npm run dev
```
* The chatbot UI will run on `http://localhost:5174`.
* Incoming requests targeting `/api/*` are automatically proxied to the Orchestrator Function App (by default, `http://localhost:7071`) using Vite's server proxy.

### 3. Local Environment Variables
You can configure environment variables in a local `.env` file under this directory:
* `VITE_ORCHESTRATOR_URL`: The destination URL of the Orchestrator service (default: `http://localhost:7071`).
* `VITE_DEMO_STEPS`: Enable or disable the left-hand "Orchestrator Activity" step execution panel (default: `true`).
* `VITE_CHAT_STREAM`: Stream tokens token-by-token or render the completed block at once (default: `false` for stable demo).

---

## Running with Docker

You can build and run the chatbot UI inside a Docker container:

1. Build the Docker image:
   ```bash
   docker build -t utility-chatbot-ui .
   ```
2. Run the Docker container:
   ```bash
   docker run -d \
     -p 5174:3000 \
     -e VITE_ORCHESTRATOR_URL=http://host.docker.internal:7071 \
     utility-chatbot-ui
   ```

---

## Production & Cloud Deployment Settings

When deploying the frontend to a cloud environment separate from the local Docker compose stack, consider the following configuration patterns:

### Option A: Azure Static Web Apps (Recommended)
This project is configured out-of-the-box for Azure Static Web Apps (SWA). SWA serves the static bundles and integrates seamlessly with Azure Functions.

1. **Routing and SPA Support**:
   * The [staticwebapp.config.json](file:///Users/harishsundarakumar/Documents/UniversalUtilityOrchestrator/UniversalUtilityAgent/azure/chatbot/staticwebapp.config.json) handles client-side routing fallback (`/*` -> `index.html`) so that reloading the page on sub-routes does not cause 404 errors.
2. **Back-end Integration (Proxying `/api/*`)**:
   * SWA allows you to link your backend Azure Function App (the Orchestrator).
   * Once linked, SWA automatically proxies all traffic targeting `/api/*` to the function app. The browser makes requests using relative URLs, avoiding cross-origin issues and bypassing CORS rules.

### Option B: Hosting on CDN / Object Storage (AWS S3, Netlify, Azure Storage)
If you deploy the static assets to a simple CDN or storage bucket:

1. **Enable CORS on the Orchestrator**:
   * Because requests will cross domains (e.g. from `https://your-frontend.net` to `https://your-orchestrator.azurewebsites.net`), the Orchestrator must be configured to permit your frontend origin.
   * Add the frontend origin to the Function App CORS configuration or the `CORS_ALLOWED_ORIGINS` environment variable in the orchestrator environment settings.
2. **Configure API Endpoint Base URL**:
   * Modify the API client [client.js](file:///Users/harishsundarakumar/Documents/UniversalUtilityOrchestrator/UniversalUtilityAgent/azure/chatbot/src/api/client.js) (or inject values into `window.__UUA_RUNTIME_CONFIG__` via [runtime-config.js](file:///Users/harishsundarakumar/Documents/UniversalUtilityOrchestrator/UniversalUtilityAgent/azure/chatbot/public/runtime-config.js)) to target the absolute URL of the Cloud Function App rather than using a relative path.

---

## Summary of Orchestrator changes from `iac-final` branch

To assist with Infrastructure-as-Code (IaC) updates, the following core updates have been made to the Azure Orchestrator compared to the baseline `iac-final` branch:

1. **Shared Chat Pipeline (`chat_pipeline.py` & `sse_events.py` [NEW])**:
   * Extracted the monolithic execution block inside the HTTP endpoints into a shared async orchestration pipeline (`run_chat_pipeline`). This pipeline manages logging, trace writes, stage event SSE rendering, and synthesizes the outputs.
2. **Self-Correction & Synthesizer Evaluation (`evaluator.py` [NEW])**:
   * Integrated a response evaluation step (`evaluator.evaluate_response`) which runs after synthesis. If quality gates are not met, a self-correction repair synthesis is executed.
3. **Execution Graph Parallelism (`execution_graph.py` [NEW] & `executor.py` [MODIFIED])**:
   * Refactored execution from a linear sequence to a dependency graph. Step execution now utilizes parallel tasks (`asyncio.gather`) for independent agents and incorporates retry logic.
4. **Input Guardrails & Scenario Enforcement (`input_guard.py` [NEW])**:
   * Added character length limits, blocked patterns, and an async semantic checker (`is_query_related_to_scenario`) using Azure OpenAI.
   * If a user query is determined to be unrelated to the Austin utility support scenario (e.g., asking for skincare tips or coding advice), the pipeline exits early and returns: `"It isn't related to scenario and cannot answer this question."`
5. **Absolute Date Resolution (`planner.py` [MODIFIED])**:
   * Refined the planner system prompts to avoid relative step-reference queries. The planner is now instructed to generate tasks with absolute calendar ranges (e.g. `"July 2019"`), fixing the 400 bad request errors encountered by the anomaly detection agent.
6. **Agent Registry Constraints (`synthesizer.py` [MODIFIED])**:
   * Refined the synthesizer prompt to strictly suggest next steps grounded in registered active specialist agents.
7. **Simulated Outage & Email microservice endpoints (`function_app.py` [MODIFIED])**:
   * Added `POST /api/simulate-outage` route to trigger simulated outages for customer `CUST-1001` in Austin (`78712`).
   * Added `POST /api/email_agent` route acting as the Email Notification Agent microservice inside the orchestrator app for seamless zero-intrusion reactive email workflows.

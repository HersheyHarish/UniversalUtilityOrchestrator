# Universal Utility Agent

A production-grade, multi-agent orchestration platform for utility companies built on Microsoft Azure. The system enables natural-language customer interactions routed through a registry of specialised AI agents, with full observability, schema-driven invocation, proactive notification delivery, and a React admin interface.

> **CS Masters Capstone Project** — built incrementally with a focus on serverless architecture, zero-credential Managed Identity security, and LangSmith-style end-to-end traceability.

---

## Table of contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Features](#features)
- [Repository layout](#repository-layout)
- [Prerequisites](#prerequisites)
- [Quick start](#quick-start)
- [API reference](#api-reference)
- [Configuration](#configuration)
- [Development](#development)
- [Deployment](#deployment)
- [Security model](#security-model)

---

## Overview

The Universal Utility Agent replaces static IVR trees and rule-based chatbots with a dynamic multi-agent system. A customer sends a natural-language message; the orchestrator decomposes it into a directed acyclic graph (DAG) of specialist agent tasks, executes them, and synthesises a coherent response. Every request is traced end-to-end in Cosmos DB and is visible in the admin UI.

**Key design decisions:**

- **Serverless-first** — Azure Functions Consumption plan; costs are near zero at low volume and scale automatically under load.
- **Zero credentials in code** — all secrets live in Azure Key Vault; Function Apps access them via Managed Identity (no connection strings, no `.env` files in production).
- **Pydantic everywhere** — every API request and response is validated with Pydantic v2 models; validation errors return structured 400 responses.
- **Best-effort tracing** — trace writes never block the main execution path; a Cosmos failure degrades observability, not functionality.
- **Conversation memory** — every session retains the last 10 user/assistant turns; follow-up questions are resolved in context.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                        Customer Portal (external)                     │
│              POST /api/chat  ·  GET /api/sessions/{id}                │
└────────────────────────────┬─────────────────────────────────────────┘
                             │
                  ┌──────────▼──────────┐
                  │   Orchestrator      │  fn-orchestrator-ua001
                  │   Function App      │  Python 3.11 · Consumption
                  │                     │
                  │  planner.py         │  GPT-4o → execution DAG
                  │  executor.py        │  sequential step runner
                  │  synthesizer.py     │  GPT-4o → final response
                  │  memory.py          │  Cosmos read/write
                  │  trace_writer.py    │  async trace capture
                  │  schema_mapper.py   │  LLM-driven body construction
                  └──────┬──────┬───────┘
                         │      │
          ┌──────────────┘      └─────────────────┐
          │                                        │
┌─────────▼──────────┐                  ┌──────────▼──────────┐
│   Cosmos DB        │                  │  Azure OpenAI       │
│   (NoSQL,          │                  │  GPT-4o             │
│    serverless)     │                  │  gpt-4o deployment  │
│                    │                  └─────────────────────┘
│  agents            │
│  sessions          │
│  messages          │                  ┌─────────────────────┐
│  traces            │                  │  Azure Key Vault    │
│  admin_sessions    │                  │  RBAC-only access   │
└─────────▲──────────┘                  │  agent API keys     │
          │                             │  admin credentials  │
          │                             └─────────────────────┘
┌─────────┴──────────┐
│   Registry API     │  fn-registry-ua001
│   Function App     │  Python 3.11 · Consumption
│                    │
│  models.py         │  Pydantic request/response types
│  cosmos.py         │  data access layer
│  registry.py       │  business logic
│  auth.py           │  bcrypt + session tokens
│  observability.py  │  trace queries + metrics
│  function_app.py   │  HTTP routes
└─────────▲──────────┘
          │
┌─────────┴──────────┐
│   Registry UI      │  swa-registry-ua001
│   React 18 + Vite  │  Azure Static Web Apps (Free)
│                    │
│  AgentList         │  CRUD, import/export
│  AgentDetail       │  health, capabilities, invocation config
│  TraceExplorer     │  filterable trace list (reactive + proactive)
│  TraceDetail       │  DAG · timeline · step inspector · data flow
│  MetricsDashboard  │  success rate, latency p95, per-agent table
└────────────────────┘
```

### Cosmos DB containers

| Container | Partition key | TTL | Purpose |
|---|---|---|---|
| `agents` | `/partition_key` (fixed: `agents`) | none | Agent registry documents |
| `sessions` | `/partition_key` (= session ID) | 30 days | Conversation session metadata |
| `messages` | `/partition_key` (= session ID) | 30 days | All messages — reactive and proactive |
| `traces` | `/partition_key` (= session ID) | 30 days | Full execution traces with step data |
| `admin_sessions` | `/partition_key` | 8 h (auto-expire) | Admin UI session tokens |

---

## Features

### Orchestrator

- **LLM planning** — GPT-4o decomposes the user's request into a DAG of specialist agent tasks using a structured JSON system prompt; cycles are detected and rejected.
- **Sequential DAG execution** — steps execute in topological order; a failed step skips its dependants and records the reason.
- **Schema-driven body construction** — each agent defines typed field descriptions; the LLM constructs the request body at runtime from available context rather than using static templates.
- **Pluggable authentication** — per-agent auth supports `none`, `api_key`, `bearer_token`, `basic_auth`, `oauth2_client_credentials`, and `custom`; OAuth2 tokens are cached in memory.
- **Response synthesis** — GPT-4o combines all step outputs into a single coherent response; different system prompts for reactive (Q&A) and proactive (notification) modes.
- **Conversation history** — the last 10 turns are loaded from Cosmos before each call to planner and synthesizer so follow-up questions resolve correctly.
- **Proactive triggers** — remote agents `POST /api/proactive/trigger`; the orchestrator optionally runs an enrichment plan and saves `role="system"` messages into the customer's session.

### Registry API

- Full CRUD for agent documents with Pydantic validation and 409-on-duplicate.
- Partial update (PATCH), full replacement (PUT) and delete (DELETE).
- Health probing — single agent (`/ping`) and bulk (`/ping-all`), TCP and HTTP modes, configurable expected status code and timeout.
- Capability index — deduplicated capability manifest across all agents.
- JSON export / import — full registry backup as a downloadable file; import accepts single object, array, or `{ "agents": [...] }` envelope.
- Observability routes — `GET /api/traces`, `GET /api/traces/{id}`, `GET /api/observability/metrics`, `GET /api/observability/agents`, `GET /api/observability/timeseries`.
- Session-based admin auth with bcrypt password validation against Key Vault and 8-hour TTL Cosmos sessions.

### Admin UI

- **Agent management** — register, edit, view, deactivate, export, and import agents with full form validation and tooltips.
- **Invocation config** — three modes: Schema-driven (LLM constructs the body), Template ({token} placeholders), and Default.
- **Schema editor** — define typed fields (string/number/boolean/array/object) with descriptions, required toggles, defaults, optional JSON Schema validation, and nested object support.
- **Auth config** — configure per-agent authentication with type selector, credential fields, and Key Vault secret naming conventions.
- **Health monitor** — real-time health check results with latency, configurable HTTP/TCP probe settings.
- **Trace Explorer** — filterable list of all traces; filter by status, trigger type (Reactive / Proactive), time window, and agent name. Each row shows latency bar, agent count, and links to full detail.
- **Trace Detail** — four views: DAG (SVG with layered layout, latency badges, status colours), Timeline (Gantt-style), Data Flow (shows context fields passing between steps), Step Inspector (input/output JSON, schema mapping decisions, error details).
- **Metrics Dashboard** — system-wide stats with trend chart and per-agent performance table.

---

## Repository layout

```
utility-agent/
├── deploy.sh                        ← single-command deployment
├── .env.deploy                      ← auto-generated by deploy.sh (gitignored)
├── data/
│   ├── agent_billing.json
│   ├── agent_outage.json
│   └── agent_conservation.json
├── orchestrator-fn/
│   ├── function_app.py              ← HTTP routes: /chat, /proactive/trigger, /sessions, /health
│   ├── planner.py                   ← GPT-4o DAG generation, reactive + proactive system prompts
│   ├── executor.py                  ← sequential step runner, schema-driven / template / default body
│   ├── synthesizer.py               ← GPT-4o response synthesis, reactive + proactive prompts
│   ├── memory.py                    ← Cosmos sessions, messages, conversation history
│   ├── models.py                    ← Pydantic: SessionDoc, MessageDoc, ChatRequest/Response,
│   │                                   PlanStep, ExecutionPlan, ProactiveTriggerRequest/Response
│   ├── trace_writer.py              ← TraceContext: async best-effort trace capture
│   ├── schema_mapper.py             ← LLM-driven request body construction
│   ├── auth_injector.py             ← resolves auth config → injects headers/query params
│   ├── proactive_models.py          ← Severity, ProactiveTriggerRequest/Response
│   ├── host.json
│   └── requirements.txt
├── registry-fn-complete/
│   ├── function_app.py              ← all routes with _guard/_json/_err/_token_from pattern
│   ├── models.py                    ← AgentDoc, AgentCreate/Update/Replace, CapabilityAdd,
│   │                                   StatusPatch, LoginRequest/Response, RegistryStats, …
│   ├── cosmos.py                    ← data access layer (no business logic)
│   ├── registry.py                  ← all agent business logic, health probing
│   ├── auth.py                      ← bcrypt login, Cosmos session management
│   ├── observability.py             ← trace queries, metrics aggregation
│   ├── host.json
│   └── requirements.txt
├── registry-ui/
│   ├── src/
│   │   ├── api/client.js            ← req(), orchReq(), auth/agents/registry/traces/observability/proactive
│   │   ├── context/AuthContext.jsx
│   │   ├── styles/globals.css       ← full design system
│   │   ├── App.jsx                  ← route definitions
│   │   └── components/
│   │       ├── Layout.jsx
│   │       ├── LoginPage.jsx
│   │       ├── Dashboard.jsx
│   │       ├── AgentList.jsx        ← with Import button
│   │       ├── AgentDetail.jsx
│   │       ├── AgentForm.jsx        ← register + edit
│   │       ├── ImportAgentModal.jsx ← file picker + editable JSON + per-agent results
│   │       ├── HealthMonitor.jsx
│   │       ├── Icons.jsx
│   │       ├── Primitives.jsx
│   │       └── observability/
│   │           ├── TraceExplorer.jsx
│   │           ├── TraceDetail.jsx
│   │           ├── DAGVisualization.jsx
│   │           ├── TimelineView.jsx
│   │           ├── StepInspector.jsx
│   │           ├── DataFlowView.jsx
│   │           ├── SchemaMappingPanel.jsx
│   │           └── MetricsDashboard.jsx
│   ├── index.html
│   ├── vite.config.js
│   ├── package.json
│   └── staticwebapp.config.json
└── infra/
    ├── main.tf
    ├── variables.tf
    ├── outputs.tf
    ├── terraform.tfvars.example
    └── modules/
        ├── resource_group/main.tf
        ├── cosmos_db/main.tf
        ├── openai/main.tf
        ├── key_vault/main.tf
        └── function_app/main.tf
```

---

## Prerequisites

| Tool | Minimum version | Install |
|---|---|---|
| Azure CLI | 2.58+ | `brew install azure-cli` / [docs.microsoft.com](https://docs.microsoft.com/cli/azure/install-azure-cli) |
| Azure Functions Core Tools | 4.x | `npm install -g azure-functions-core-tools@4` |
| Terraform | 1.7+ | `brew install terraform` / [terraform.io](https://developer.hashicorp.com/terraform/install) |
| Python | 3.11 | `pyenv install 3.11` |
| Node.js | 18+ | `nvm install 18` |
| jq | any | `brew install jq` |

Azure resources required (provisioned by Terraform):

- Subscription with Contributor or Owner role
- Azure OpenAI access approved for your subscription region

---

## Quick start

```bash
# 1. Clone and enter the repo
git clone <your-repo-url> utility-agent
cd utility-agent

# 2. Log in to Azure
az login
az account set --subscription "<your-subscription-id>"

# 3. Copy and edit tfvars
cp infra/terraform.tfvars.example infra/terraform.tfvars
# Edit: suffix, location, openai_location, tags

# 4. Deploy everything in one command
bash deploy.sh --env dev --suffix ua001
# This provisions infra, deploys both function apps, builds and deploys the UI,
# seeds sample agents, runs smoke tests, and writes .env.deploy

# 5. Set admin credentials
source .env.deploy
python3 -c "import bcrypt; print(bcrypt.hashpw(b'yourpassword', bcrypt.gensalt()).decode())"
az keyvault secret set --vault-name "$KV_NAME" --name "admin-username" --value "admin"
az keyvault secret set --vault-name "$KV_NAME" --name "admin-password" --value '$2b$12$...'

# 6. Open the admin UI
echo "https://$SWA_URL"
```

---

## API reference

### Orchestrator

| Method | Route | Auth | Description |
|---|---|---|---|
| `GET` | `/api/health` | none | Liveness — surfaces import errors and missing env vars |
| `POST` | `/api/chat` | func key | Main orchestration: plan → execute → synthesise |
| `GET` | `/api/sessions/{id}` | func key | Full session with all messages (reactive + proactive) |
| `POST` | `/api/proactive/trigger` | func key | Agent-initiated proactive notification |

**`POST /api/chat` request:**
```json
{
  "message":     "Why is my bill so high this month?",
  "customer_id": "CUST-1001",
  "session_id":  "optional-existing-session-uuid"
}
```

**`POST /api/proactive/trigger` request:**
```json
{
  "agent_name":     "OutageAgent",
  "customer_id":    "CUST-1001",
  "event_type":     "service_outage",
  "severity":       "high",
  "message":        "A power outage has been detected in your area.",
  "context":        { "outage_id": "OUT-9982", "eta": "2h" },
  "run_enrichment": true,
  "session_id":     null
}
```

### Registry API

All routes except `/api/health` and `/api/agents/dashboard` require:
- Function-level key: `?code=<key>` query parameter
- Session token: `X-Session-Token: <token>` header (obtained from `POST /api/auth/login`)

| Method | Route | Description |
|---|---|---|
| `POST` | `/api/auth/login` | Validate credentials → return session token |
| `POST` | `/api/auth/logout` | Delete session immediately |
| `GET` | `/api/auth/verify` | Check if a token is still valid |
| `GET` | `/api/health` | Liveness probe |
| `GET` | `/api/agents/dashboard` | HTML browser dashboard |
| `POST` | `/api/agents` | Register new agent (409 on duplicate name) |
| `GET` | `/api/agents` | List — optional `?status` `?utility_type` `?tag` `?q` |
| `GET` | `/api/agents/stats` | Counts by status/type, tag list, last timestamps |
| `GET` | `/api/agents/capabilities` | Deduplicated capability index |
| `GET` | `/api/agents/export` | Full JSON export as file download |
| `POST` | `/api/agents/ping-all` | Health-check all agents regardless of status |
| `GET` | `/api/agents/{id}` | Get single agent |
| `PUT` | `/api/agents/{id}` | Full replacement |
| `PATCH` | `/api/agents/{id}` | Partial update |
| `DELETE` | `/api/agents/{id}` | Soft delete (`?hard=true` for physical) |
| `PATCH` | `/api/agents/{id}/status` | Set status + optional audit reason |
| `GET` | `/api/agents/{id}/ping` | Health-check single agent |
| `POST` | `/api/agents/{id}/capabilities` | Add capability |
| `DELETE` | `/api/agents/{id}/capabilities/{name}` | Remove capability |
| `GET` | `/api/traces` | List traces — `?status` `?agent` `?trigger_type` `?since_hours` |
| `GET` | `/api/traces/{id}` | Full trace with all step payloads |
| `GET` | `/api/observability/metrics` | System-wide metrics |
| `GET` | `/api/observability/agents` | Per-agent metrics |
| `GET` | `/api/observability/timeseries` | Request volume over time |

**Important — route ordering:** Fixed-path routes must be registered before parameterised routes in `function_app.py`. `agents/stats`, `agents/ping-all`, `agents/capabilities`, `agents/export`, `traces/proactive` all appear before `agents/{agent_id}` and `traces/{trace_id}` respectively to prevent the literal segment being captured as a path parameter.

---

## Configuration

### Orchestrator environment variables

| Variable | Required | Description |
|---|---|---|
| `COSMOS_ENDPOINT` | ✓ | Cosmos DB account endpoint URL |
| `COSMOS_DATABASE` | | Database name (default: `utility_agent_db`) |
| `AZURE_OPENAI_ENDPOINT` | ✓ | Azure OpenAI endpoint URL |
| `AZURE_OPENAI_DEPLOYMENT` | | GPT-4o deployment name (default: `gpt-4o`) |
| `KEY_VAULT_URL` | ✓ | Key Vault endpoint URL |
| `OPENAI_SECRET_NAME` | | KV secret holding the OpenAI API key (default: `openai-api-key`) |
| `AGENT_TIMEOUT_SECS` | | Global agent call timeout (default: `45`) |
| `AGENT_MAX_RETRIES` | | Global retry count (default: `2`) |

### Registry environment variables

| Variable | Required | Description |
|---|---|---|
| `COSMOS_ENDPOINT` | ✓ | Cosmos DB account endpoint URL |
| `COSMOS_DATABASE` | | Database name (default: `utility_agent_db`) |
| `KEY_VAULT_URL` | ✓ | Key Vault endpoint URL (for auth and agent API keys) |
| `SESSION_TTL_HOURS` | | Admin session lifetime (default: `8`) |

### UI environment variables (Vite)

| Variable | Description |
|---|---|
| `VITE_REGISTRY_URL` | Registry Function App base URL |
| `VITE_FUNC_CODE` | Registry function-level key |
| `VITE_ORCHESTRATOR_URL` | Orchestrator Function App base URL |
| `VITE_ORCHESTRATOR_CODE` | Orchestrator function-level key |

---

## Development

### Run the orchestrator locally

```bash
cd orchestrator-fn
pip install -r requirements.txt --break-system-packages

# Set env vars (source from .env.deploy or set manually)
export COSMOS_ENDPOINT="https://cosmos-ua001-dev.documents.azure.com:443/"
export AZURE_OPENAI_ENDPOINT="https://oai-ua-ua001.openai.azure.com/"
export KEY_VAULT_URL="https://kv-ua-ua001.vault.azure.net/"

func start
# Runs on http://localhost:7071
```

### Run the registry API locally

```bash
cd registry-fn-complete
pip install -r requirements.txt --break-system-packages

export COSMOS_ENDPOINT="..."
export KEY_VAULT_URL="..."

func start --port 7072
```

### Run the React UI locally

```bash
cd registry-ui

# Create local env file
cat > .env.local << EOF
VITE_REGISTRY_URL=https://fn-registry-ua001.azurewebsites.net
VITE_FUNC_CODE=<your-registry-key>
VITE_ORCHESTRATOR_URL=https://fn-orchestrator-ua001.azurewebsites.net
VITE_ORCHESTRATOR_CODE=<your-orchestrator-key>
EOF

npm install
npm run dev
# Hot-reload dev server at http://localhost:3000
```

### Adding a new agent

1. In the admin UI, click **Register agent**.
2. Fill in the name, description, and endpoint URL.
3. Under **Invocation**, choose **Schema-driven** and define the fields your agent expects.
4. Under **Auth**, select the authentication type and provide the credentials.
5. Click **Register**. The agent is immediately available to the planner.

Alternatively, via the API:

```bash
curl -s -X POST "$REGISTRY_URL/api/agents?code=$REGISTRY_KEY" \
  -H "Content-Type: application/json" \
  -H "X-Session-Token: $SESSION_TOKEN" \
  -d '{
    "name":         "BillingAgent",
    "description":  "Retrieves billing history and explains charges",
    "endpoint_url": "https://fn-billing.azurewebsites.net/api/invoke",
    "utility_types": ["electric", "gas"],
    "capabilities": [
      {
        "name":        "get_billing_history",
        "description": "Returns the last N billing cycles for a customer"
      }
    ],
    "invocation_config": {
      "request_schema": {
        "fields": [
          {
            "name":        "customer_id",
            "description": "The customer account number in format ACC-XXXXX",
            "required":    true,
            "field_type":  "string"
          }
        ]
      }
    }
  }' | jq '{id, name, status}'
```

---

## Deployment

### First deployment from scratch

```bash
# 1. Provision all infrastructure
cd utility-agent
bash deploy.sh --env dev --suffix ua001

# 2. Set admin password (after deploy.sh completes)
source .env.deploy
HASH=$(python3 -c "import bcrypt; print(bcrypt.hashpw(b'your-password', bcrypt.gensalt()).decode())")
az keyvault secret set --vault-name "$KV_NAME" --name "admin-username" --value "admin"
az keyvault secret set --vault-name "$KV_NAME" --name "admin-password" --value "$HASH"
```

### Redeploy code only (no infra changes)

```bash
# Orchestrator
cd orchestrator-fn
func azure functionapp publish "$FUNC_APP_NAME" --python --build remote

# Registry
cd registry-fn-complete
func azure functionapp publish "$REGISTRY_APP_NAME" --python --build remote

# UI
cd registry-ui
npm run build
swa deploy ./dist --deployment-token "$SWA_TOKEN" --env production
```

### Tear down

```bash
bash deploy.sh --destroy
# or: terraform -chdir=infra destroy
```

---

## Security model

**No secrets in code or environment variables in production.** All sensitive values — OpenAI API key, agent API keys, admin password hash — are stored in Azure Key Vault. Function Apps access Key Vault using their system-assigned Managed Identity; no connection strings are ever stored.

**RBAC principle of least privilege:**

| Identity | Role | Scope |
|---|---|---|
| Orchestrator MSI | Cosmos DB Built-in Data Contributor | Cosmos account |
| Orchestrator MSI | Key Vault Secrets User | Key Vault |
| Orchestrator MSI | Cognitive Services OpenAI User | OpenAI account |
| Registry MSI | Cosmos DB Built-in Data Contributor | Cosmos account |
| Registry MSI | Key Vault Secrets User | Key Vault |

**Admin authentication:** Passwords are bcrypt-hashed (cost factor 12) before storage in Key Vault. Session tokens are UUID v4 strings stored in Cosmos `admin_sessions` with server-side 8-hour TTL auto-expiry. Tokens are never stored in `localStorage` — `sessionStorage` is cleared when the browser tab closes.

**Function-level keys:** Every API endpoint on both function apps requires the Azure Functions function-level key (`?code=<key>`) at the HTTP layer. The registry additionally requires a valid session token (`X-Session-Token`) on all routes except `health`, `dashboard`, and `auth/*`.

**Proactive trigger security:** The `/api/proactive/trigger` endpoint requires the orchestrator function key. No additional per-agent credentials are needed; restrict access at the network level (VNet integration or API Management) if needed.
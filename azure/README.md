# Universal Utility Orchestrator (UUO)

The **Universal Utility Orchestrator (UUO)** is a serverless, multi-agent orchestration infrastructure built natively on Microsoft Azure. 

As enterprises rush to automate operations with specialized AI agents (e.g., billing analyzers, anomaly detectors, weather monitors), a critical failure point has emerged: these systems operate in isolated silos, relying on rigid, hardcoded developer workflows. If a smart-meter agent detects an anomaly, it cannot autonomously consult the billing agent to calculate the financial impact. 

UUO solves this by providing a **decoupled, plug-and-play orchestration layer**. It acts as a dynamic central controller that allows enterprises to register any HTTP-based agent, dynamically plan multi-step execution graphs using an LLM, and synthesize complex, multi-agent responses on the fly—without requiring manual workflow rewrites. 

> **CS Masters Capstone Project (Sponsored by Accenture)** — Built with a strict focus on enterprise requirements: serverless-first Azure Functions, zero-trust Managed Identity security, schema-driven LLM invocation, and LangSmith-style observability.

**Related docs:** [TECHNICAL_DOCUMENTATION.md](./TECHNICAL_DOCUMENTATION.md) (Deep implementation reference) · [local.md](./local.md) (Local Docker quick-start)

---

## Table of contents

1. [Project overview](#1-project-overview)
2. [Team members](#2-team-members)
3. [Features implemented](#3-features-implemented)
4. [Architecture](#4-architecture)
5. [Repository layout](#5-repository-layout)
6. [Prerequisites](#6-prerequisites)
7. [Setup instructions](#7-setup-instructions)
8. [How to run locally](#8-how-to-run-locally)
9. [Configuration reference (flags & settings)](#9-configuration-reference-flags--settings)
10. [API reference](#10-api-reference)
11. [Testing and verification](#11-testing-and-verification)
12. [Deployment (Azure)](#12-deployment-azure)
13. [Demo video](#13-demo-video)
14. [Known issues and future work](#14-known-issues-and-future-work)
15. [Security model](#15-security-model)

---

## 1. Project overview

### What is this?

UUO is the Azure-hosted **control plane** for enterprise multi-agent systems. It provides the core orchestration infrastructure: an agent registry, an autonomous planner, an executor, response synthesis, conversation memory, and compliance tracing. Downstream agents are simply **registered HTTP endpoints** (any service you operate). Because UUO is headless, it can deliver insights anywhere—powering everything from proactive SMS alerts to zero-click executive dashboards and reactive customer portals.

*(Note: This repository provides the core infrastructure and optional demo frontends to exercise the platform. It does not ship with production agent implementations).*

### What does it do?

| Flow | Description |
|------|-------------|
| **Reactive Orchestration** | A user submits a complex query → input guardrails validate the request → the LLM Planner builds a Directed Acyclic Graph (DAG) → the Executor calls registered remote agents sequentially or in parallel → the Synthesizer composes the final answer → session states and traces are committed to Cosmos DB. |
| **Proactive Execution** | A remote agent detects an event (e.g., localized outage) and sends `POST /api/proactive/trigger` → the Orchestrator optionally runs an enrichment plan across other agents → an actionable system message is pushed to the user's session without manual intervention. |
| **Agent Registry & Observability** | A dedicated admin backend to CRUD agents, configure pluggable authentication, monitor health probes, and explore deep-dive execution traces (DAG visualization, data flow, latency). |
| **Universal Delivery (Demos)** | Includes a reactive chatbot (`/demo` route) and a "zero-click" insight dashboard, demonstrating how the orchestrator can power varied interfaces. |

A **multi-agent orchestration platform** on Microsoft Azure: register HTTP agents, plan DAGs with an LLM, execute steps with schema-driven invocation, synthesize responses, and trace runs in Cosmos DB. Includes a registry admin UI and optional demo frontends (chatbot, dashboard) to exercise the platform—not part of the core orchestration infrastructure.

> **CS Masters Capstone Project** — serverless-first Azure Functions, Managed Identity for secrets in production, and LangSmith-style traceability in the registry UI.

**Related docs:** [TECHNICAL_DOCUMENTATION.md](./TECHNICAL_DOCUMENTATION.md) (deep implementation reference) · [local.md](./local.md) (short Docker quick reference)


---

### Who built it?

**CS Masters Capstone** — Built by MCS students at University of California, Irvine. [Team members](#2-team-members) section with your roster and roles before external handoff.
**Sponsored by Accenture** - Special Thanks to Shawna Tuli, Mo Nomeli, Vishrut Chokshi, Cheryl Linder

---

## 2. Team members

| Name | Role | Contact |
|------|------|---------|
| _Harish Sundarakumar_| Project lead / orchestrator / Customer UIs (chatbot, zero-clicks) / Admin UI (Registry) | _[sundarh1@uci.edu]_ |
| _Sanket Landge_ | infra (Terraform) / Admin UI (Registry) / Orchestrator / Testing | _[slandge@uci.edu]_ |
| _Arya Gupta_ | Demo agents / integrations (external) / Orchestrator / Research / cloud | _[aagupta1@uci.edu]_ |
| _Shaun Morata Lim_ | Orchstrator / Security / Research / Testing   | _[shaunl1@uci.edu]_ |

**Course / org:** CS Masters Capstone — set `Owner` and `CostCenter` in `infra/terraform.tfvars` (see `terraform.tfvars.example`).

---

## 3. Features implemented

### Orchestrator (`orchestrator/`)

- LLM planning (GPT-4o / configured deployment) → execution DAG with cycle detection.
- Topological execution with optional **parallel** steps (`ORCHESTRATOR_PARALLEL_EXEC`).
- **Schema-driven** request bodies via `schema_mapper.py` (LLM constructs JSON from field definitions).
- **Template** and **default** invocation fallbacks.
- **Auth injector** for outbound agent calls; secrets from Key Vault or local env.
- **Input guardrails** (length, blocked patterns, excessive code fences).
- **Scenario guard** (LLM classifies utility-related vs unrelated queries).
- **Reactive** and **proactive** synthesis prompts.
- **SSE streaming** (`POST /api/chat/stream`) with progress/demo events.
- **Traces** in Cosmos (`trace_writer.py`); demo events when demo/stream flags on.
- Routes: `health`, `chat`, `chat/stream`, `proactive/trigger`, `sessions/{id}`, `users/{id}/sessions`, `insights`, `copilot/context`, `alerts`, `agents`, `email_agent`, `simulate-outage`.

### Registry API (`registry/`)

- Session-based admin auth (bcrypt password in Key Vault; local default `admin` / `password`).
- Agent CRUD, PATCH/PUT, soft delete (`?hard=true` for physical delete).
- Health: HTTP/TCP/none per agent; `ping` and `ping-all`.
- Capabilities index, export, import via API/UI.
- Observability: `traces`, `observability/metrics`, `agent-metrics`, `timeseries`.
- Capability fetch helper: `POST /api/agents/capabilities/fetch`.
- HTML dashboard at `/api/agents/dashboard` (no session required).

### Registry UI (`registry-ui/`)

- Login, agent list/detail/form, import modal.
- Invocation config: schema-driven / template / default.
- Request schema editor, auth config, health monitor.
- Trace explorer, trace detail (DAG, timeline, data flow, step inspector, schema mapping panel).
- Metrics dashboard.

### Customer-facing UIs

| App | Port (Docker) | Purpose |
|-----|---------------|---------|
| **registry-ui** | 5173 | Admin / ops console |
| **chatbot** | 5174 | Chat + `/demo` layout with streaming |
| **zero-clicks-dashboard** | 5175 | Utility portal mock (bills, usage, proactive toasts, copilot) |

### Infrastructure (`infra/`)

- Terraform modules: resource group, Cosmos DB (serverless), OpenAI deployment, Key Vault (RBAC), two Function Apps, Static Web App.
- `deploy.sh`: provision, publish functions, build/deploy UI, store host keys in KV, smoke tests.

---

## 4. Architecture

### High-level diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Customer UIs: chatbot (5174) · zero-clicks-dashboard (5175)            │
│  Admin UI: registry-ui (5173)                                           │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │ HTTP / SSE
                ┌───────────────▼────────────────┐
                │  Orchestrator Function App    │  :7071  orchestrator/
                │  planner · executor · synth   │
                │  memory · trace_writer        │
                └───────┬───────────────┬───────┘
                        │               │
         ┌──────────────▼───┐    ┌──────▼──────────┐
         │  Cosmos DB        │    │  Azure OpenAI   │
         │  agents           │    │  (planner/synth) │
         │  sessions         │    └─────────────────┘
         │  messages         │
         │  traces           │    ┌─────────────────┐
         │  admin_sessions   │    │  Key Vault       │
         └──────────▲─────────┘    │  (prod secrets)  │
                    │              └─────────────────┘
         ┌──────────┴──────────┐
         │  Registry Function   │  :7072  registry/
         │  auth · registry ·    │
         │  observability       │
         └──────────▲────────────┘
                    │
         ┌──────────┴──────────┐
         │  Registered agents   │  (any HTTP services you register)
         └─────────────────────┘

Local-only: Azurite (blob/queue/table) · Cosmos DB Emulator
```

### Chat pipeline (reactive)

```
POST /api/chat
  → InputGuardrails.validate()
  → (optional) scenario relevance check
  → get/create session + load transcript
  → planner.build_plan()          [GPT, history + agent manifest]
  → executor.execute_plan()       [DAG, schema/template/default, auth]
  → synthesizer.synthesize()      [GPT]
  → (optional) evaluator          [ORCHESTRATOR_EVAL_ENABLED]
  → save assistant message + trace.finish()
```

### Cosmos containers (local init)

| Container | Partition key | TTL | Purpose |
|-----------|---------------|-----|---------|
| `agents` | `/partition_key` | — | Agent registry (`partition_key` = `"agents"`) |
| `sessions` | `/session_id` | optional | Session metadata |
| `messages` | `/session_id` | optional | Chat/proactive messages |
| `traces` | `/partition_key` | optional | Execution traces (`partition_key` = session id) |
| `admin_sessions` | `/partition_key` | enabled | Admin UI tokens |

Created by `registry/init_cosmos_emulator.py` (also run via `cosmos-init` in Docker Compose).

---

## 5. Repository layout

```
azure/
├── README.md                    ← this file (handoff front door)
├── TECHNICAL_DOCUMENTATION.md     ← deep architecture / models / patterns
├── local.md                       ← short Docker notes
├── docker-compose.yml             ← full local stack
├── .env.example                   ← compose-level hints
├── orchestrator/                  ← Azure Functions: chat, proactive, traces
│   ├── function_app.py
│   ├── planner.py, executor.py, synthesizer.py
│   ├── chat_pipeline.py, schema_mapper.py, auth_injector.py
│   ├── memory.py, trace_writer.py, input_guard.py
│   ├── runtime_contract.py        ← validates env on startup (strict/prod)
│   ├── .env.example → copy to .env
│   └── requirements.txt
├── registry/                      ← Azure Functions: agents + observability
│   ├── function_app.py, registry.py, cosmos.py, auth.py
│   ├── observability.py, models.py
│   ├── init_cosmos_emulator.py
│   └── import_agents.py          ← optional local utility (not used by compose)
├── registry-ui/                   ← Admin React app (Vite)
├── chatbot/                       ← Customer chat React app
├── zero-clicks-dashboard/         ← Utility portal demo React app
└── infra/
    ├── main.tf, variables.tf, outputs.tf
    ├── terraform.tfvars.example
    └── deploy.sh                  ← one-command Azure deploy
```

Demo agent services, if any, are maintained separately from this `azure/` tree.

---

## 6. Prerequisites

### Local (Docker — recommended)

| Tool | Version | Notes |
|------|---------|--------|
| Docker Desktop | Recent | Allocate ≥4 GB RAM for Cosmos emulator |
| Azure OpenAI | API access | Real key + endpoint in `orchestrator/.env` |

### Local (native — optional)

| Tool | Version |
|------|---------|
| Python | 3.11 |
| Node.js | 18+ |
| Azure Functions Core Tools | 4.x |
| jq | any |

### Azure deployment

| Tool | Version |
|------|---------|
| Azure CLI | 2.58+ (`az login`) |
| Terraform | ≥ 1.7 |
| Azure Functions Core Tools | 4.x |
| npm | Node 18+ |
| Static Web Apps CLI | `npm i -g @azure/static-web-apps-cli` |
| python3 + bcrypt | For admin password hashing in deploy |

Subscription needs **Azure OpenAI** access in your chosen region.

---

## 7. Setup instructions

### Step 1 — Clone the repository

```bash
git clone <your-repo-url>
cd UniversalUtilityAgent/azure
```

### Step 2 — Configure orchestrator secrets (required)

```bash
cp orchestrator/.env.example orchestrator/.env
```

Edit `orchestrator/.env` and set at minimum:

```bash
AZURE_OPENAI_API_KEY=<your-azure-openai-key>
AZURE_OPENAI_ENDPOINT=https://<your-resource>.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=gpt-4o
```

Never commit `orchestrator/.env` or real keys. Production uses Key Vault + Managed Identity instead of inline API keys.

### Step 3 — (Optional) Configure admin UI for non-Docker dev

```bash
cp registry-ui/.env.example registry-ui/.env.local
# Set VITE_REGISTRY_URL and VITE_FUNC_CODE when using FUNCTION auth level
```

### Step 4 — Install dependencies (only if running UIs outside Docker)

```bash
cd registry-ui && npm install
cd ../chatbot && npm install
cd ../zero-clicks-dashboard && npm install
```

### Step 5 — Boot local infrastructure

```bash
cd azure
docker compose up --build
```

First boot: Cosmos emulator may take **30–45 seconds**. The `cosmos-init` container retries until the database and containers exist — that is expected.

### Step 6 — Register demo agents (first time)

1. Open [http://localhost:5173](http://localhost:5173) → login `admin` / `password`.
2. **Register agent** or **Import** JSON you maintain locally (do not commit files with live production URLs).

Without at least one **active** agent with a reachable `endpoint_url`, the planner has an empty manifest and cannot execute steps.

---

## 8. How to run locally

### Docker Compose (all services)

```bash
cd azure
docker compose up --build
```

| Service | URL | Notes |
|---------|-----|--------|
| Registry UI | http://localhost:5173 | `admin` / `password` |
| Registry API | http://localhost:7072/api/health | ANONYMOUS auth locally |
| Orchestrator | http://localhost:7071/api/health | ANONYMOUS auth locally |
| Chatbot | http://localhost:5174 | Demo: http://localhost:5174/demo |
| Zero-clicks dashboard | http://localhost:5175 | Proactive + copilot widgets |

### Run orchestrator only (Functions Core Tools)

```bash
cd orchestrator
pip install -r requirements.txt
# Load orchestrator/.env (export vars or use local.settings.json)
export $(grep -v '^#' .env | xargs)   # Linux/macOS — review before running
func start
# http://localhost:7071
```

### Run registry only

```bash
cd registry
pip install -r requirements.txt
func start --port 7072
```

### Run registry UI (Vite dev server)

```bash
cd registry-ui
cp .env.example .env.local   # edit URLs/keys
npm install
npm run dev
# Default Vite port may differ; Docker maps 5173→3000
```

### Production-like behavior locally

From `local.md` — set on orchestrator/registry containers or your shell:

1. `APP_ENV=prod`
2. `USE_LOCAL_EMULATORS=false`
3. `REGISTRY_HTTP_AUTH_LEVEL=FUNCTION` and `ORCHESTRATOR_HTTP_AUTH_LEVEL=FUNCTION`
4. `REGISTRY_STRICT_MODE=true` and `ORCHESTRATOR_STRICT_MODE=true`
5. `BUILD_VERSION`, `BUILD_SHA`, `KEY_VAULT_URL`, and UI `VITE_FUNC_CODE`

Runtime contract validation is in `orchestrator/runtime_contract.py` and `registry/runtime_contract.py`.

---

## 9. Configuration reference (flags & settings)

### Global runtime modes

| Variable | Default (local Docker) | Description |
|----------|------------------------|-------------|
| `APP_ENV` | `local` | `local` \| `prod` / `production` — enables prod forbids (no emulators, no anonymous auth, no demo steps). |
| `USE_LOCAL_EMULATORS` | `true` | Cosmos emulator key, ANONYMOUS HTTP auth default, inline admin password, env-based OpenAI key. |
| `BUILD_VERSION` | `dev` | Shown on `/api/health`. **Required** when strict or prod. |
| `BUILD_SHA` | `local` | Git SHA on health endpoint. **Required** when strict or prod. |

### Orchestrator — security & contract

| Variable | Default | Description |
|----------|---------|-------------|
| `ORCHESTRATOR_HTTP_AUTH_LEVEL` | `ANONYMOUS` if emulators; else `FUNCTION` | `ANONYMOUS` \| `FUNCTION` \| `ADMIN`. Prod forbids `ANONYMOUS`. |
| `ORCHESTRATOR_STRICT_MODE` | `false` (local), `true` (prod) | When true, requires `KEY_VAULT_URL`, `OPENAI_SECRET_NAME`, build metadata. |
| `ORCHESTRATOR_DEMO_STEPS` | `true` in compose | Persists `demo_events` on traces; enables step UI in session payload. **Forbidden in prod.** |
| `ORCHESTRATOR_STREAM_PROGRESS` | `true` in compose | Stream progress events; with demo steps, persists trace events. |
| `ORCHESTRATOR_CHAT_STREAM_ENABLED` | `true` in compose | Gates `/api/chat/stream` route behavior. |
| `ORCHESTRATOR_PARALLEL_EXEC` | `true` | Execute independent DAG layers in parallel. |
| `ORCHESTRATOR_EVAL_ENABLED` | `false` | Post-synthesis LLM faithfulness check. |
| `ORCHESTRATOR_PLANNER_HISTORY_TURNS` | `6` | Prior turns fed to planner (see also transcript limits). |
| `ORCHESTRATOR_TRANSCRIPT_MAX_TURNS` | `20` | Max messages loaded for session transcript. |
| `ORCHESTRATOR_TRANSCRIPT_MAX_CHARS` | `12000` | Character cap on transcript payload. |

### Orchestrator — data & AI

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `COSMOS_ENDPOINT` | Yes | — | Cosmos account URL (emulator: `https://cosmos:8081/`). |
| `COSMOS_DATABASE` | No | `utility_agent_db` | Database name. |
| `AZURE_OPENAI_ENDPOINT` | Yes | — | Azure OpenAI or Foundry project URL. |
| `AZURE_OPENAI_DEPLOYMENT` | No | `gpt-4o-mini` | Default chat deployment/model id. |
| `AZURE_OPENAI_PLANNER_DEPLOYMENT` | No | same as above | Optional separate planner deployment. |
| `AZURE_OPENAI_API_VERSION` | No | `2024-10-21` | API version for classic Azure OpenAI client. |
| `AZURE_OPENAI_API_KEY` | Local | — | Direct key when `USE_LOCAL_EMULATORS=true`. |
| `OPENAI_SECRET_NAME` | Prod/strict | `openai-api-key` | Key Vault secret name for OpenAI key. |
| `KEY_VAULT_URL` | Prod/strict | — | Key Vault URI for Managed Identity access. |
| `AGENT_TIMEOUT_SECS` | No | `45` | Global HTTP timeout to agent endpoints. |
| `AGENT_MAX_RETRIES` | No | `2` | Retries on 5xx/network (not 4xx). |
| `OUTAGE_INPUT_FILE` | No | — | Path to JSON for `simulate-outage` demo route. |

### Orchestrator — CORS (Docker)

Set in `docker-compose.yml`:

- `CORS_ALLOWED_ORIGINS` — JSON array of allowed origins.
- `CORS_SUPPORT_CREDENTIALS` — `true` for credentialed browser calls.

### Registry — security & contract

| Variable | Default | Description |
|----------|---------|-------------|
| `REGISTRY_HTTP_AUTH_LEVEL` | `ANONYMOUS` if emulators | Same semantics as orchestrator. |
| `REGISTRY_STRICT_MODE` | `false` (local) | Requires `KEY_VAULT_URL`, build metadata when true. |
| `SESSION_TTL_HOURS` | `8` | Admin session Cosmos TTL (also Terraform `registry_session_ttl_hours`). |
| `KEY_VAULT_URL` | empty locally | Admin username/password secrets in prod. |
| `CONTAINER_NAME` | — | Docker-only label (`azure_registry`). |

### Registry UI (Vite — build time)

| Variable | Description |
|----------|-------------|
| `VITE_REGISTRY_URL` | Registry Function App base URL (no trailing slash). |
| `VITE_FUNC_CODE` | Function host key when `REGISTRY_HTTP_AUTH_LEVEL=FUNCTION`. |
| `VITE_ORCHESTRATOR_URL` | Optional direct orchestrator URL. |
| `VITE_ORCHESTRATOR_CODE` | Orchestrator function key if needed. |

### Chatbot (Vite)

| Variable | Docker default | Description |
|----------|----------------|-------------|
| `VITE_ORCHESTRATOR_URL` | `http://host.docker.internal:7071` | Proxy target for `/api/*`. |
| `VITE_FUNC_CODE` | empty | Function key when auth is FUNCTION. |
| `VITE_DEMO_STEPS` | `true` | Show demo step UI in chat. |
| `VITE_CHAT_STREAM` | `true` | Use SSE streaming endpoint. |

### Zero-clicks dashboard

| Variable | Description |
|----------|-------------|
| `VITE_ORCHESTRATOR_URL` | Orchestrator base URL (Docker: `host.docker.internal:7071`). |

### Docker Compose — Cosmos tuning

| Variable | Purpose |
|----------|---------|
| `COSMOS_IMAGE` | Emulator image override. |
| `COSMOS_PLATFORM` | e.g. `linux/amd64` on Apple Silicon. |
| `COSMOS_MEM_LIMIT` | Default `3g`. |
| `COSMOS_CPUS` | Default `2.0`. |
| `COSMOS_IP_OVERRIDE` | Emulator hostname override (default `cosmos`). |

### Terraform variables (`infra/terraform.tfvars`)

| Variable | Description |
|----------|-------------|
| `location` | Azure region (e.g. `westus2`). |
| `environment` | `dev` \| `staging` \| `prod`. |
| `suffix` | Short unique suffix for global names (≤8 chars, lowercase alphanumeric). |
| `model_name` / `model_version` / `model_capacity_tpm` | Azure OpenAI deployment. |
| `cosmos_database_name` | Default `utility_agent_db`. |
| `registry_session_ttl_hours` | Admin session hours (default 8). |
| `swa_location` | Static Web App region. |
| `build_version` / `build_sha` | Injected into Function App settings. |
| `tags` | Resource tags (`Owner`, `CostCenter`, etc.). |

### Per-agent settings (stored in Cosmos, not env)

Configured in registry UI or API on each `AgentDoc`:

- **Auth:** `auth_config.auth_type` — `none`, `api_key`, `bearer_token`, `basic_auth`, `oauth2`, `custom`.
- **Health:** `health_check_config` — `http` \| `tcp` \| `none`, URLs, expected status, timeouts.
- **Invocation:** `invocation_config` — `request_schema.fields`, `body_template`, `response_result_path`, per-agent `timeout_seconds`, `max_retries`.

See [TECHNICAL_DOCUMENTATION.md](./TECHNICAL_DOCUMENTATION.md) §5–6 for field-level detail.

---

## 10. API reference

### Orchestrator

Base: `http://localhost:7071` (local) or `https://fn-orchestrator-<suffix>.azurewebsites.net`

Append `?code=<function-key>` when `ORCHESTRATOR_HTTP_AUTH_LEVEL=FUNCTION`.

| Method | Route | Auth | Description |
|--------|-------|------|-------------|
| GET | `/api/health` | Anonymous | Liveness, version, import/runtime errors |
| POST | `/api/chat` | Function* | Plan → execute → synthesize |
| POST | `/api/chat/stream` | Function* | SSE stream (tokens + progress events) |
| POST | `/api/proactive/trigger` | Function* | Proactive notification pipeline |
| GET | `/api/sessions/{session_id}` | Function* | Session + messages (+ demo_events if enabled) |
| GET | `/api/users/{customer_id}/sessions` | Function* | List sessions for customer |
| GET | `/api/insights` | Function* | Dashboard insights payload |
| GET | `/api/copilot/context` | Function* | Copilot context for zero-clicks UI |
| GET | `/api/alerts` | Function* | Alerts list |
| POST | `/api/alerts/{alert_id}/ack` | Function* | Acknowledge alert |
| GET | `/api/agents` | Anonymous | Active agents for demo UIs |
| POST | `/api/email_agent` | Anonymous | Email-oriented agent helper |
| POST | `/api/simulate-outage` | Anonymous | Demo outage simulation |

\* Locally defaults to anonymous.

**Chat request body:**

```json
{
  "message": "Summarize my account status for the last billing period.",
  "customer_id": "customer-001",
  "session_id": "optional-existing-uuid"
}
```

**Proactive trigger body:**

```json
{
  "agent_name": "NotificationAgent",
  "customer_id": "customer-001",
  "event_type": "account_alert",
  "severity": "high",
  "message": "An important account event requires your attention.",
  "context": { "event_id": "EVT-001" },
  "run_enrichment": true,
  "session_id": null
}
```

### Registry

Base: `http://localhost:7072` (local) or `https://fn-registry-<suffix>.azurewebsites.net`

Protected routes need:

- `?code=<function-key>` when auth level is FUNCTION, and
- `X-Session-Token: <token>` from `POST /api/auth/login` (except health, dashboard, auth routes).

| Method | Route | Description |
|--------|-------|-------------|
| POST | `/api/auth/login` | Returns session token |
| POST | `/api/auth/logout` | Invalidates session |
| GET | `/api/auth/verify` | Token validity |
| GET | `/api/health` | Liveness |
| GET | `/api/agents/dashboard` | HTML dashboard |
| GET/POST | `/api/agents` | List / create agents |
| GET | `/api/agents/stats` | Registry statistics |
| GET | `/api/registry/stats` | Alias stats endpoint |
| GET | `/api/agents/capabilities` | Capability index |
| POST | `/api/agents/capabilities/fetch` | Fetch capabilities from remote URL |
| GET | `/api/agents/export` | JSON export download |
| POST | `/api/agents/ping-all` | Health-check all agents |
| GET/PUT/PATCH/DELETE | `/api/agents/{id}` | CRUD |
| PATCH | `/api/agents/{id}/status` | Status change |
| GET | `/api/agents/{id}/ping` | Single-agent health |
| POST/DELETE | `/api/agents/{id}/capabilities/...` | Capability management |
| GET | `/api/traces` | List traces (filters: status, agent, trigger_type, since_hours) |
| GET | `/api/traces/{session_id}` | Full trace |
| GET | `/api/observability/metrics` | System metrics |
| GET | `/api/observability/agent-metrics` | Per-agent metrics |
| GET | `/api/observability/timeseries` | Volume over time |

**Route ordering:** Fixed paths (`agents/stats`, `agents/ping-all`, etc.) must be registered before `agents/{agent_id}` in `function_app.py`.

---

## 11. Testing and verification

### Health checks

```bash
curl -s http://localhost:7071/api/health | jq .
curl -s http://localhost:7072/api/health | jq .
```

Expect `"status": "ok"` when runtime contract passes and imports succeed.

### Chat smoke test

```bash
curl -s -X POST http://localhost:7071/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"What is the status of customer-001?","customer_id":"customer-001"}' | jq .
```

Requires Azure OpenAI credentials and at least one **active** agent in the registry whose endpoint is reachable from the orchestrator container.

### Registry auth (local)

```bash
curl -s -X POST http://localhost:7072/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"password"}' | jq .
```

Use returned `token` as `X-Session-Token` on subsequent registry calls.

### Chatbot unit tests

```bash
cd chatbot
npm test
```

Vitest tests exist for `ChatArea` and `Sidebar` components.

### Azure deploy smoke tests

`infra/deploy.sh` runs health checks on both function apps after deploy (unless `--skip-smoke-tests`).

### Manual UI checklist

- [ ] Registry UI login and agent list
- [ ] Register or import demo agents (local JSON only)
- [ ] Health monitor ping-all
- [ ] Send chat from http://localhost:5174/demo
- [ ] Trace appears in Trace Explorer
- [ ] Zero-clicks proactive toast (http://localhost:5175)

---

## 12. Deployment (Azure)

**Status:** Fully supported via Terraform + `deploy.sh`. Local Docker stack does **not** require Azure resources except OpenAI.

### First-time deploy

```bash
cd azure/infra
cp terraform.tfvars.example terraform.tfvars
# Edit: location, suffix, model_version, tags

az login
az account set --subscription "<subscription-id>"

cd ..
bash infra/deploy.sh --env dev --suffix ua001
```

### Set admin password (production)

```bash
source .env.deploy   # written by deploy.sh at azure/ root
HASH=$(python3 -c "import bcrypt; print(bcrypt.hashpw(b'your-secure-password', bcrypt.gensalt()).decode())")
az keyvault secret set --vault-name "$KV_NAME" --name "admin-username" --value "admin"
az keyvault secret set --vault-name "$KV_NAME" --name "admin-password" --value "$HASH"
```

### Redeploy code only

```bash
cd orchestrator && func azure functionapp publish "$FUNC_APP_NAME" --python --build remote
cd ../registry && func azure functionapp publish "$REGISTRY_APP_NAME" --python --build remote
cd ../registry-ui && npm run build && swa deploy ./dist --deployment-token "$SWA_TOKEN" --env production
```

### deploy.sh flags

| Flag | Effect |
|------|--------|
| `--env dev\|staging\|prod` | Terraform environment |
| `--suffix ua001` | Resource name suffix |
| `--skip-infra` | Skip Terraform |
| `--skip-orchestrator` | Skip orchestrator publish |
| `--skip-registry` | Skip registry publish |
| `--skip-ui` | Skip React SWA deploy |
| `--skip-smoke-tests` | Skip post-deploy curls |
| `--destroy` | `terraform destroy` |

### Terraform outputs

After apply: orchestrator URL, registry URL, SWA URL, Key Vault name, Cosmos endpoint — see `infra/outputs.tf` and `shell_exports`.

### Tear down

```bash
bash infra/deploy.sh --destroy --env dev --suffix ua001
```

---

## 13. Demo video

| Item | Value |
|------|--------|
| **Link** | _[Add YouTube / SharePoint / course submission URL]_ |
| **Recorded** | _[Date]_ |
| **Covers** | Suggested: Docker startup → registry import → chat demo → trace explorer → proactive notification on zero-clicks dashboard |

---

## 14. Known issues and future work

### Known issues

1. **Cosmos emulator on ARM Macs** — Requires `platform: linux/amd64` and sufficient memory; first start is slow.
2. **Cosmos partition key mismatch** — Emulator init vs Terraform use different partition paths for `sessions` / `messages`.
3. **Hardcoded outage path fallback** — `simulate-outage` may reference a developer-specific absolute path if `OUTAGE_INPUT_FILE` is unset (see `function_app.py`).
4. **Cross-partition trace queries** — Observability lists use cross-partition queries (RU cost at scale).
5. **Empty function keys in local Vite** — UIs rely on ANONYMOUS auth; production must set `VITE_FUNC_CODE` at build time.
6. **registry-ui metrics path** — UI client may call `/api/observability/agents`; API route is `/api/observability/agent-metrics`.

### Future work

- [ ] Check in demo video URL and capstone team roster
- [ ] Align Cosmos container partition keys between Terraform and `init_cosmos_emulator.py`
- [ ] Enable optional `ORCHESTRATOR_EVAL_ENABLED` in staging
- [ ] Remote Terraform state backend for team deploys
- [ ] Integration tests for orchestrator pipeline (mock HTTP agents)
- [ ] API Management / VNet for proactive trigger hardening

---

## 15. Security model

### Production

- **No secrets in source control** — use Key Vault; Function Apps use **Managed Identity** (`DefaultAzureCredential`).
- **RBAC:** Orchestrator/registry → Cosmos Data Contributor, Key Vault Secrets User; orchestrator → Cognitive Services OpenAI User.
- **Admin passwords:** bcrypt (cost 12) stored in Key Vault; sessions in Cosmos with TTL.
- **Function keys:** Required at HTTP layer when auth level is FUNCTION.
- **Session tokens:** Stored in `sessionStorage` in registry UI (cleared when tab closes).

### Local emulators

- `USE_LOCAL_EMULATORS=true` enables ANONYMOUS function auth and default `admin`/`password`.
- `AZURE_OPENAI_API_KEY` in `.env` is acceptable locally only.
- Inline agent secrets (`inline:...` refs) are **forbidden** when `APP_ENV=prod`.

### Never commit

- `orchestrator/.env`, `.env.local`, `terraform.tfvars`, `.env.deploy`
- Real API keys, function host keys, SWA deployment tokens, or client secrets

---

## Quick links

| Resource | Path |
|----------|------|
| Implementation deep-dive | [TECHNICAL_DOCUMENTATION.md](./TECHNICAL_DOCUMENTATION.md) |
| Docker quick notes | [local.md](./local.md) |
| Orchestrator env template | [orchestrator/.env.example](./orchestrator/.env.example) |
| Deploy script | [infra/deploy.sh](./infra/deploy.sh) |

**Questions?** Start with health endpoints, then registry agent count, then OpenAI env vars — most local failures are missing `.env` OpenAI settings or an empty agent registry.

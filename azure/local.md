# Local Development Guide

This guide explains how to run the **entire Azure stack on your laptop** using Docker Compose, what emulators are involved, how configuration is layered, and every flag that affects local behavior.

For API routes, deployment, and repo-wide handoff, see [README.md](./README.md). For implementation internals, see [TECHNICAL_DOCUMENTATION.md](./TECHNICAL_DOCUMENTATION.md).

---

## Table of contents

1. [What you need vs. what you skip](#1-what-you-need-vs-what-you-skip)
2. [Docker Compose architecture](#2-docker-compose-architecture)
3. [Emulators and infrastructure services](#3-emulators-and-infrastructure-services)
4. [Application services (ports and URLs)](#4-application-services-ports-and-urls)
5. [Startup order and first-boot timing](#5-startup-order-and-first-boot-timing)
6. [Step-by-step: run locally](#6-step-by-step-run-locally)
7. [Configuration: how env vars are loaded](#7-configuration-how-env-vars-are-loaded)
8. [The `USE_LOCAL_EMULATORS` switch](#8-the-use_local_emulators-switch)
9. [Orchestrator flags and settings](#9-orchestrator-flags-and-settings)
10. [Registry flags and settings](#10-registry-flags-and-settings)
11. [Frontend (Vite) environment variables](#11-frontend-vite-environment-variables)
12. [Cosmos DB: database, containers, and partition keys](#12-cosmos-db-database-containers-and-partition-keys)
13. [Seeding agents (required for chat)](#13-seeding-agents-required-for-chat)
14. [Verification and smoke tests](#14-verification-and-smoke-tests)
15. [Running without Docker (optional)](#15-running-without-docker-optional)
16. [Production-like behavior on localhost](#16-production-like-behavior-on-localhost)
17. [Troubleshooting](#17-troubleshooting)

---

## 1. What you need vs. what you skip

### You **do** need

| Requirement | Why |
|-------------|-----|
| **Docker Desktop** (or compatible runtime) | Runs emulators + all app containers |
| **Azure OpenAI** credentials | Planner, synthesizer, schema mapper, and input scenario guard call the LLM |
| **`orchestrator/.env`** | Single file used by Compose for OpenAI + optional overrides (see below) |

Minimum `orchestrator/.env` content:

```bash
AZURE_OPENAI_API_KEY=<your-key>
AZURE_OPENAI_ENDPOINT=https://<your-resource>.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=gpt-4o
```

Copy from the template:

```bash
cp orchestrator/.env.example orchestrator/.env
# Edit orchestrator/.env — never commit it
```

### You **do not** need (for default local Docker flow)

| Usually skipped locally | Reason |
|-------------------------|--------|
| Azure subscription / `az login` | Cosmos and storage are emulated in Docker |
| Key Vault | Secrets read from env (`AZURE_OPENAI_API_KEY`) when `USE_LOCAL_EMULATORS=true` |
| Terraform / `deploy.sh` | Only for cloud deployment |
| Function host keys on APIs | HTTP auth defaults to `ANONYMOUS` for orchestrator and registry |
| Managed Identity | Cosmos uses the well-known emulator master key |

**Still required in the cloud:** Cosmos account, Key Vault, Function keys, SWA token, etc. See [README.md § Deployment](./README.md#12-deployment-azure).

---

## 2. Docker Compose architecture

File: [`docker-compose.yml`](./docker-compose.yml)

```
                    ┌─────────────────────────────────────────┐
                    │  Host machine (your laptop)              │
                    │                                          │
  Browser ──────────┼──► registry-ui      :5173 ──► registry :7072
                    │    chatbot          :5174 ──┐
                    │    zero-clicks        :5175 ──┼──► orchestrator :7071
                    │                              │         │
                    │                              │         ├──► Cosmos emulator :8081
                    │                              │         └──► Azurite :10000-10002
                    │                              │
                    │    cosmos-init (one-shot) ───┘ creates DB/containers
                    └─────────────────────────────────────────┘
```

**Design intent:** Backend state (Cosmos) is local; intelligence (Azure OpenAI) is real. **Registered agents** are arbitrary HTTP endpoints you configure for demos—they are not started by this Compose file.

---

## 3. Emulators and infrastructure services

### 3.1 Cosmos DB Emulator (`cosmos`)

| Property | Value |
|----------|--------|
| **Image** | `mcr.microsoft.com/cosmosdb/linux/azure-cosmos-emulator:latest` (override with `COSMOS_IMAGE`) |
| **Container name** | `cosmos_emulator` |
| **Platform** | `linux/amd64` by default (`COSMOS_PLATFORM`) — important on Apple Silicon |
| **Memory / CPU** | `COSMOS_MEM_LIMIT` default `3g`, `COSMOS_CPUS` default `2.0` |

**Published ports**

| Port | Purpose |
|------|---------|
| `8081` | HTTPS API (what apps use — `https://cosmos:8081/` inside Docker network) |
| `8080` | HTTP readiness / health |
| `1234` | Emulator gateway |
| `10251–10254` | Additional emulator services |

**Emulator environment (inside container)**

| Variable | Default | Meaning |
|----------|---------|---------|
| `AZURE_COSMOS_EMULATOR_PARTITION_COUNT` | `5` | Partition count for emulator |
| `AZURE_COSMOS_EMULATOR_ENABLE_DATA_EXPLORER` | `true` | Data Explorer UI support |
| `AZURE_COSMOS_EMULATOR_IP_ADDRESS_OVERRIDE` | `cosmos` | Hostname other containers use (`COSMOS_IP_OVERRIDE`) |

**Health check:** Compose waits until `http://localhost:8080/ready` or the emulator cert endpoint responds before starting `cosmos-init`.

**Well-known emulator key (used in code when `USE_LOCAL_EMULATORS=true`):**

The master key is the standard Microsoft emulator key (hardcoded in `registry/cosmos.py`, `registry/init_cosmos_emulator.py`, and trace/memory modules). TLS verification is disabled (`connection_verify=False`).

**From your host (optional debugging):**

- Data Explorer: often `https://localhost:8081/_explorer/index.html` (accept self-signed cert)
- Endpoint for tools on host: `https://localhost:8081/`

Inside Docker, apps use **`https://cosmos:8081/`** (service DNS name `cosmos`).

---

### 3.2 Azurite (`azurite`)

| Property | Value |
|----------|--------|
| **Image** | `mcr.microsoft.com/azure-storage/azurite` |
| **Container name** | `azurite` |

**Published ports**

| Port | Service |
|------|---------|
| `10000` | Blob |
| `10001` | Queue |
| `10002` | Table |

Azure Functions runtime expects a storage account for internal host state (queues, logs). Azurite satisfies that for local Functions containers. **Application code does not document direct Azurite usage** in business logic—the orchestrator/registry talk to Cosmos and HTTP agents, not blob storage.

---

### 3.3 Cosmos init (`cosmos-init`)

| Property | Value |
|----------|--------|
| **Type** | One-shot job (exits after success) |
| **Build** | Same image context as `registry/` |
| **Command** | `python init_cosmos_emulator.py` |
| **Depends on** | `cosmos` healthy |

**What it creates**

- Database: `utility_agent_db` (or `COSMOS_DATABASE`)
- Containers: `agents`, `admin_sessions`, `sessions`, `messages`, `traces` (see [§12](#12-cosmos-db-database-containers-and-partition-keys))

**Retry behavior:** Up to 10 attempts, 8 seconds apart, for both connection and per-container creation. If Compose logs show retries on first boot, that is normal while Cosmos warms up (often **30–45 seconds** total).

**Re-run manually:**

```bash
docker exec azure_registry python /home/site/wwwroot/init_cosmos_emulator.py
```

---

## 4. Application services (ports and URLs)

| Service | Container | Host URL | Role |
|---------|-----------|----------|------|
| **orchestrator** | `azure_orchestrator` | http://localhost:7071 | Chat, proactive, sessions, traces, demo routes |
| **registry** | `azure_registry` | http://localhost:7072 | Agent CRUD, auth, observability |
| **registry-ui** | `azure_registry_ui` | http://localhost:5173 | Admin console (Vite dev server) |
| **chatbot** | `utility_chatbot_ui` | http://localhost:5174 | Customer chat; demo at `/demo` |
| **zero-clicks-dashboard** | `zero_clicks_dashboard_ui` | http://localhost:5175 | Utility portal mock + copilot |

**Default admin login (registry UI):** `admin` / `password` (only when `USE_LOCAL_EMULATORS=true`; see [§8](#8-the-use_local_emulators-switch)).

**Hot reload:** `orchestrator`, `registry`, and all three UIs mount source volumes. Editing Python or React files reloads without rebuilding images (restart container if you change `requirements.txt` or root `package.json`).

---

## 5. Startup order and first-boot timing

```
1. azurite          (starts immediately)
2. cosmos           (healthcheck until ready — slowest step)
3. cosmos-init      (creates DB/containers, then exits)
4. orchestrator     (waits for cosmos-init completion in depends_on)
5. registry         (same)
6. registry-ui      (no hard dependency on backends)
7. chatbot          (depends_on orchestrator)
8. zero-clicks      (depends_on orchestrator)
```

**Typical first `docker compose up --build`:** allow **1–3 minutes** before all health checks and Function hosts are ready.

---

## 6. Step-by-step: run locally

### 6.1 Prerequisites

- Docker Desktop with **at least 4 GB RAM** allocated (Cosmos emulator is heavy)
- On **Apple Silicon:** keep `COSMOS_PLATFORM=linux/amd64` (default in compose)

### 6.2 Configure environment

```bash
cd azure
cp orchestrator/.env.example orchestrator/.env
```

Edit `orchestrator/.env` and set your Azure OpenAI values (see [§1](#1-what-you-need-vs-what-you-skip)).

Optional: create a root `.env` next to `docker-compose.yml` to override Cosmos Docker settings (see [§7](#7-configuration-how-env-vars-are-loaded)).

### 6.3 Start the stack

```bash
docker compose up --build
```

Detached mode:

```bash
docker compose up --build -d
docker compose logs -f orchestrator registry
```

### 6.4 Register demo agents (optional)

The planner reads **active agents** from Cosmos (`memory.get_active_agents()`). This repo does not commit registry export files (they often contain live URLs).

After registry is up:

1. Open http://localhost:5173 → login `admin` / `password`
2. **Register agent** with a name, `endpoint_url`, and invocation config, **or** use **Import** with JSON you keep outside git.

Import formats accepted by the UI: single agent object, array of agents, or `{ "agents": [ ... ] }`.

API alternative (no function key when auth is ANONYMOUS):

```bash
TOKEN=$(curl -s -X POST http://localhost:7072/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"password"}' | jq -r .token)

curl -s -X POST http://localhost:7072/api/agents \
  -H "Content-Type: application/json" \
  -H "X-Session-Token: $TOKEN" \
  -d '{
    "name": "echo-agent",
    "description": "Demo agent for local testing",
    "endpoint_url": "https://your-mock-agent.example/api/invoke",
    "status": "active",
    "capabilities": [],
    "invocation_config": { "http_method": "POST" },
    "auth_config": { "auth_type": "none" }
  }'
```

Replace `endpoint_url` with a mock or stub you control. The orchestrator must be able to reach it from the `orchestrator` container (use host networking or a public test URL).

### 6.5 Try the UIs

| URL | What to try |
|-----|-------------|
| http://localhost:5173 | Agent list, health ping, trace explorer |
| http://localhost:5174/demo | Streaming chat with demo steps |
| http://localhost:5175 | Dashboard + proactive notification controls |

---

## 7. Configuration: how env vars are loaded

### 7.1 Layers (highest wins last)

For **orchestrator** and **registry** containers:

1. **`orchestrator/.env`** — loaded via `env_file` in Compose (your OpenAI keys, optional overrides)
2. **`environment:` block in `docker-compose.yml`** — forces local emulator mode, CORS, feature flags, Cosmos endpoint
3. Shell interpolation from **project `.env`** (optional) — e.g. `${COSMOS_ENDPOINT:-https://cosmos:8081/}`

So: values in `docker-compose.yml` **override** the same keys in `orchestrator/.env` for orchestrator/registry.

Example: even if `.env` sets `ORCHESTRATOR_HTTP_AUTH_LEVEL=FUNCTION`, Compose sets `ANONYMOUS` unless you remove or change the compose `environment` section.

### 7.2 Files to know

| File | Committed? | Purpose |
|------|------------|---------|
| `orchestrator/.env.example` | Yes | Template — copy to `.env` |
| `orchestrator/.env` | **No** (gitignored) | Your secrets + local overrides |
| `azure/.env.example` | Yes | Optional Compose-level Cosmos tuning |
| `registry-ui/.env.example` | Yes | For non-Docker Vite dev only |
| `chatbot/.env.example` | Yes | For non-Docker Vite dev only |

### 7.3 Optional Compose-level overrides (host `.env`)

Create `azure/.env` (beside `docker-compose.yml`) to tune the emulator container:

```bash
COSMOS_PLATFORM=linux/amd64
COSMOS_MEM_LIMIT=4g
COSMOS_CPUS=2.0
COSMOS_ENDPOINT=https://cosmos:8081/
```

These affect the **cosmos** service image/platform/resources, not the Python apps, unless also referenced in compose interpolation.

---

## 8. The `USE_LOCAL_EMULATORS` switch

Set to **`true`** on orchestrator, registry, and `cosmos-init` in Docker Compose.

When enabled, the codebase changes behavior as follows:

### 8.1 Cosmos DB

- Connect with emulator **master key** (not Managed Identity)
- `connection_verify=False`, `enable_endpoint_discovery=False`
- Endpoint from `COSMOS_ENDPOINT` (default `https://cosmos:8081/`)

### 8.2 HTTP authentication (Function Apps)

- Default auth level: **`ANONYMOUS`** unless `ORCHESTRATOR_HTTP_AUTH_LEVEL` / `REGISTRY_HTTP_AUTH_LEVEL` is set
- UIs use **empty** `VITE_FUNC_CODE` — no `?code=` query param required

### 8.3 Admin login (registry)

- Username: **`admin`**
- Password: **`password`** (bcrypt hash embedded in `registry/auth.py` for local only)
- No Key Vault fetch for `admin-username` / `admin-password`

### 8.4 Secrets (OpenAI and agent credentials)

- **`secret_provider.get_secret()`** (orchestrator): reads `AZURE_OPENAI_API_KEY` from env when `local_env_fallback` is set; skips Key Vault if `KEY_VAULT_URL` is empty
- **Agent secrets:** registry can store **`inline:<base64>`** references (`registry/secret_refs.py`) instead of writing to Key Vault
- **`inline:` secrets are forbidden** when `APP_ENV=prod`

### 8.5 Runtime contract validation

- `APP_ENV=local`, `ORCHESTRATOR_STRICT_MODE=false`, `REGISTRY_STRICT_MODE=false`
- Does **not** require `KEY_VAULT_URL`, `BUILD_*` beyond what Compose sets
- **`APP_ENV=prod` + `USE_LOCAL_EMULATORS=true`** is explicitly rejected in code

---

## 9. Orchestrator flags and settings

### 9.1 Set by Docker Compose (`environment:`)

These are applied on top of `orchestrator/.env`:

| Variable | Compose value | Description |
|----------|---------------|-------------|
| `APP_ENV` | `local` | Non-production runtime |
| `USE_LOCAL_EMULATORS` | `true` | Emulator + local auth behavior ([§8](#8-the-use_local_emulators-switch)) |
| `ORCHESTRATOR_STRICT_MODE` | `false` | Relaxed startup validation |
| `ORCHESTRATOR_HTTP_AUTH_LEVEL` | `ANONYMOUS` | No function key on API calls |
| `COSMOS_ENDPOINT` | `https://cosmos:8081/` | Emulator inside Docker network |
| `COSMOS_DATABASE` | `utility_agent_db` | Database name |
| `ORCHESTRATOR_DEMO_STEPS` | `true` | Record `demo_events` on traces; expose in session GET |
| `ORCHESTRATOR_STREAM_PROGRESS` | `true` | SSE progress events; persists trace events when combined with demo |
| `ORCHESTRATOR_PARALLEL_EXEC` | `true` | Run independent DAG layers in parallel |
| `ORCHESTRATOR_CHAT_STREAM_ENABLED` | `true` | Enables streaming chat route behavior |
| `CORS_ALLOWED_ORIGINS` | JSON array of localhost URLs | Browser access from UIs on 5173/5174/3000 |
| `CORS_SUPPORT_CREDENTIALS` | `true` | Credentialed CORS |
| `BUILD_VERSION` | `dev` | Reported on `/api/health` |
| `BUILD_SHA` | `local` | Reported on `/api/health` |

### 9.2 Typically set in `orchestrator/.env` (your file)

| Variable | Required | Default / notes |
|----------|----------|-----------------|
| `AZURE_OPENAI_API_KEY` | **Yes** | Real key for planner/synthesizer/mapper |
| `AZURE_OPENAI_ENDPOINT` | **Yes** | Resource or Foundry project URL |
| `AZURE_OPENAI_DEPLOYMENT` | Yes | e.g. `gpt-4o` |
| `AZURE_OPENAI_PLANNER_DEPLOYMENT` | No | Falls back to `AZURE_OPENAI_DEPLOYMENT` |
| `AZURE_OPENAI_API_VERSION` | No | `2024-10-21` for classic Azure OpenAI client |
| `OPENAI_SECRET_NAME` | No | Used only when not in local emulator mode |
| `KEY_VAULT_URL` | No locally | Empty for Docker default |
| `AGENT_TIMEOUT_SECS` | No | `45` — HTTP timeout to downstream agents |
| `AGENT_MAX_RETRIES` | No | `2` — retries on 5xx/network, not 4xx |
| `ORCHESTRATOR_EVAL_ENABLED` | No | `false` — post-synthesis faithfulness LLM check |
| `ORCHESTRATOR_PLANNER_HISTORY_TURNS` | No | `6` — prior turns in planner prompt |
| `ORCHESTRATOR_TRANSCRIPT_MAX_TURNS` | No | `20` |
| `ORCHESTRATOR_TRANSCRIPT_MAX_CHARS` | No | `12000` |
| `OUTAGE_INPUT_FILE` | No | Path for `/api/simulate-outage` demo data |

### 9.3 Feature flag behavior (orchestrator code)

| Flag | When true |
|------|-----------|
| `ORCHESTRATOR_DEMO_STEPS` | `TraceContext` stores `demo_events`; `GET /api/sessions/{id}` may include them; chat UI can show step-by-step demo |
| `ORCHESTRATOR_STREAM_PROGRESS` | SSE emits progress; with demo steps, trace events are persisted |
| `ORCHESTRATOR_CHAT_STREAM_ENABLED` | Streaming endpoint active (see `function_app.py`) |
| `ORCHESTRATOR_PARALLEL_EXEC` | Executor runs steps in the same DAG layer concurrently |
| `ORCHESTRATOR_EVAL_ENABLED` | Extra LLM pass after synthesis to detect unsupported claims |

**Prod rule:** `runtime_contract.py` rejects `ORCHESTRATOR_DEMO_STEPS=true` when `APP_ENV=prod`.

### 9.4 Strict mode (`ORCHESTRATOR_STRICT_MODE`)

When `true` (production default), startup validation requires:

- `COSMOS_ENDPOINT`, `AZURE_OPENAI_ENDPOINT`
- `KEY_VAULT_URL`, `OPENAI_SECRET_NAME`, `BUILD_VERSION`, `BUILD_SHA`

Docker sets `false` so you can develop without Key Vault.

---

## 10. Registry flags and settings

### 10.1 Set by Docker Compose

| Variable | Compose value | Description |
|----------|---------------|-------------|
| `APP_ENV` | `local` | Non-production |
| `USE_LOCAL_EMULATORS` | `true` | [§8](#8-the-use_local_emulators-switch) |
| `REGISTRY_STRICT_MODE` | `false` | Relaxed validation |
| `REGISTRY_HTTP_AUTH_LEVEL` | `ANONYMOUS` | No function key |
| `COSMOS_ENDPOINT` | `https://cosmos:8081/` | Same emulator as orchestrator |
| `COSMOS_DATABASE` | `utility_agent_db` | Shared database |
| `CONTAINER_NAME` | `azure_registry` | Label only (logging/debug) |
| `CORS_ALLOWED_ORIGINS` | localhost:5173, 3000 | Admin UI origins |
| `CORS_SUPPORT_CREDENTIALS` | `true` | |
| `BUILD_VERSION` / `BUILD_SHA` | `dev` / `local` | Health endpoint |

Registry also loads **`orchestrator/.env`** via `env_file` (same OpenAI vars are harmless; registry does not call OpenAI for core CRUD).

### 10.2 Optional in `.env` (not overridden by compose)

| Variable | Default | Description |
|----------|---------|-------------|
| `SESSION_TTL_HOURS` | `8` | Admin session lifetime in Cosmos (`admin_sessions` TTL) |

### 10.3 Strict mode (`REGISTRY_STRICT_MODE`)

When `true`, requires `COSMOS_ENDPOINT` and, in strict/prod, `KEY_VAULT_URL`, `BUILD_VERSION`, `BUILD_SHA`.

---

## 11. Frontend (Vite) environment variables

Frontends run **Vite dev servers** inside Docker with source mounts. `VITE_*` variables are read at dev-server startup; restart the container after changing them.

### 11.1 registry-ui

| Variable | Docker value | Meaning |
|----------|--------------|---------|
| `VITE_REGISTRY_URL` | `http://localhost:7072` | Browser calls registry on host port |
| `VITE_FUNC_CODE` | *(empty)* | No key when registry auth is ANONYMOUS |

Login stores session token in **`sessionStorage`** (`X-Session-Token` on API calls).

### 11.2 chatbot

| Variable | Docker value | Meaning |
|----------|--------------|---------|
| `VITE_ORCHESTRATOR_URL` | `http://host.docker.internal:7071` | Vite proxy target — avoids Docker DNS issues for service name `orchestrator` |
| `VITE_FUNC_CODE` | *(empty)* | |
| `VITE_DEMO_STEPS` | `true` | UI shows orchestration demo steps |
| `VITE_CHAT_STREAM` | `true` | Use SSE `/api/chat/stream` |

`extra_hosts: host.docker.internal:host-gateway` maps the host loopback so the proxy reaches published port **7071**.

### 11.3 zero-clicks-dashboard

| Variable | Docker value |
|----------|--------------|
| `VITE_ORCHESTRATOR_URL` | `http://host.docker.internal:7071` |

Same host-gateway pattern as chatbot for copilot, alerts, and proactive triggers.

### 11.4 Running a UI on the host (without Docker UI container)

```bash
cd registry-ui
cp .env.example .env.local
# VITE_REGISTRY_URL=http://localhost:7072
npm install && npm run dev
```

Use the same pattern for `chatbot/` and `zero-clicks-dashboard/` with their `.env.example` files.

---

## 12. Cosmos DB: database, containers, and partition keys

| Container | Partition key path | TTL | Used for |
|-----------|-------------------|-----|----------|
| `agents` | `/partition_key` | — | Agent registry documents (`partition_key` = `"agents"`) |
| `admin_sessions` | `/partition_key` | Enabled (`default_ttl = -1` per-doc) | Admin UI session tokens |
| `sessions` | `/session_id` | — | Chat session metadata |
| `messages` | `/session_id` | — | User/assistant/system messages |
| `traces` | `/partition_key` | Enabled | Execution traces (partition = session id) |

Orchestrator and registry **share one database** (`utility_agent_db`) on the same emulator instance.

---

## 13. Registering agents for chat demos

Compose does **not** auto-register agents. Without rows in `agents`:

- `/api/chat` may produce an empty plan or fail at execution
- Health monitor shows an empty list

Register at least one **active** agent whose `endpoint_url` is reachable from the **orchestrator container** (not only from your browser). For local experiments, use a mock HTTP server or a stub you deploy separately.

**Do not commit** registry export JSON with production endpoints. Use **Export** in the admin UI to download your own copy locally, or maintain seed files outside the repository.

---

## 14. Verification and smoke tests

### Health

```bash
curl -s http://localhost:7071/api/health | jq .
curl -s http://localhost:7072/api/health | jq .
```

Expect `"status": "ok"` and no `runtime_errors` once imports succeed.

### Admin auth

```bash
curl -s -X POST http://localhost:7072/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"password"}' | jq .
```

### Chat (after agents imported + OpenAI configured)

```bash
curl -s -X POST http://localhost:7071/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"What is the status of customer-001?","customer_id":"customer-001"}' | jq .
```

### List agents (registry)

```bash
curl -s http://localhost:7072/api/agents \
  -H "X-Session-Token: <token-from-login>" | jq '.agents | length'
```

### Chatbot tests

```bash
cd chatbot && npm test
```

---

## 15. Running without Docker (optional)

You can run pieces natively for debugging:

| Component | Command | Port |
|-----------|---------|------|
| Cosmos | Use emulator on host or point `COSMOS_ENDPOINT` to cloud | 8081 |
| Orchestrator | `cd orchestrator && pip install -r requirements.txt && func start` | 7071 |
| Registry | `cd registry && func start --port 7072` | 7072 |
| registry-ui | `npm run dev` | Vite default |

You must still set `USE_LOCAL_EMULATORS=true` and emulator endpoint/key behavior, or configure cloud Cosmos + Key Vault for a hybrid setup.

**Easiest path remains:** `docker compose up --build`.

---

## 16. Production-like behavior on localhost

To exercise function keys, Key Vault, and strict validation **without** emulators:

1. Set in orchestrator/registry environment (or `.env`, and **remove** compose overrides):
   - `APP_ENV=prod` *(or use `staging` patterns with strict flags)*
   - `USE_LOCAL_EMULATORS=false`
   - `ORCHESTRATOR_HTTP_AUTH_LEVEL=FUNCTION`
   - `REGISTRY_HTTP_AUTH_LEVEL=FUNCTION`
   - `ORCHESTRATOR_STRICT_MODE=true`
   - `REGISTRY_STRICT_MODE=true`
2. Provide cloud resources:
   - `COSMOS_ENDPOINT` → real Azure Cosmos account
   - `KEY_VAULT_URL` → vault with `openai-api-key`, admin secrets, agent secrets
   - Managed Identity or Azure CLI credential for `DefaultAzureCredential`
3. Set `BUILD_VERSION` and `BUILD_SHA`
4. Build UIs with `VITE_FUNC_CODE=<registry-host-key>` and correct `VITE_REGISTRY_URL`

Validation errors appear on `/api/health` via `runtime_contract.py` in each Function App.

**Note:** `APP_ENV=prod` with `USE_LOCAL_EMULATORS=true` **fails by design**.

---

## 17. Troubleshooting

| Symptom | Likely cause | What to do |
|---------|--------------|------------|
| `cosmos-init` keeps retrying | Emulator still starting | Wait 1–2 min; increase Docker RAM; check `docker compose logs cosmos` |
| Orchestrator health 503 / import error | Missing Python dep or bad env | Read `/api/health` JSON `import_error` field |
| Chat returns generic error | Missing `AZURE_OPENAI_*` in `orchestrator/.env` | Fill `.env`; restart orchestrator container |
| Planner finds no agents | Empty `agents` container | Register agents via UI or API |
| Agent step timeouts | Registered `endpoint_url` unreachable from orchestrator container | Curl URL from inside `azure_orchestrator`; fix network/DNS |
| CORS errors in browser | Origin not in list | Add your origin to `CORS_ALLOWED_ORIGINS` on orchestrator/registry |
| registry-ui cannot login | Wrong password or prod mode | Use `admin`/`password` only with local emulators |
| Chatbot cannot reach API | Proxy target wrong | Confirm orchestrator on 7071; chatbot uses `host.docker.internal:7071` |
| Apple Silicon slow crash | Cosmos emulator x86 | Keep `COSMOS_PLATFORM=linux/amd64`, allocate ≥4 GB RAM |

**Reset local Cosmos data:**

```bash
docker compose down -v   # removes volumes if defined; emulator data may persist in container layer
docker compose up --build
# Re-run import of agents
```

**View logs:**

```bash
docker compose logs -f orchestrator
docker compose logs -f registry
docker compose logs cosmos-init
```

---

## Quick reference card

```bash
# Setup once
cp orchestrator/.env.example orchestrator/.env   # add AZURE_OPENAI_*

# Every session
cd azure && docker compose up --build

# URLs
# Admin:     http://localhost:5173  (admin / password)
# Registry:  http://localhost:7072/api/health
# Orchestra: http://localhost:7071/api/health
# Chat demo: http://localhost:5174/demo
# Dashboard: http://localhost:5175
```

For the full variable catalog and Azure deployment, see [README.md § Configuration](./README.md#9-configuration-reference-flags--settings).

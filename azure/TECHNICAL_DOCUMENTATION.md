# Technical Documentation

## Universal Utility Agent — Architecture and Implementation Reference

This document describes the **`azure/`** multi-agent orchestration platform: orchestrator, registry, admin UI, optional demo frontends, and infrastructure. **Registered agents** are external HTTP services; this tree implements planning, execution, synthesis, registry, and observability—not specific downstream agent business logic.

**Operational guides:** [README.md](./README.md) · [local.md](./local.md)

---

## Contents

1. [System design principles](#1-system-design-principles)
2. [Repository map](#2-repository-map)
3. [Data models](#3-data-models)
4. [Orchestrator internals](#4-orchestrator-internals)
5. [Registry API internals](#5-registry-api-internals)
6. [Schema-driven invocation](#6-schema-driven-invocation)
7. [Authentication and authorisation](#7-authentication-and-authorisation)
8. [Observability system](#8-observability-system)
9. [Proactive execution](#9-proactive-execution)
10. [Conversation memory](#10-conversation-memory)
11. [React admin UI](#11-react-admin-ui)
12. [Infrastructure as code](#12-infrastructure-as-code)
13. [Known patterns and conventions](#13-known-patterns-and-conventions)

---

## 1. System design principles

### 1.1 Serverless-first

Both function apps target Azure Functions on Linux, Python 3.11 (`infra/modules/function_app`). Locally they run in Docker images based on `mcr.microsoft.com/azure-functions/python:4-python3.11`. Cold starts are acceptable for human-driven chat.

### 1.2 Managed Identity in production

When `USE_LOCAL_EMULATORS` is not set:

- Orchestrator MSI: Cosmos DB Built-in Data Contributor, Key Vault Secrets User, Cognitive Services OpenAI User.
- Registry MSI: Cosmos DB Built-in Data Contributor, Key Vault Secrets User.

`DefaultAzureCredential()` is used for Cosmos and Key Vault. OpenAI API keys are loaded from Key Vault via `secret_provider.get_secret()` using `OPENAI_SECRET_NAME` (Terraform sets `openai-key`).

### 1.3 Local emulator mode

When `USE_LOCAL_EMULATORS=true`:

- Cosmos uses the emulator well-known master key and `connection_verify=False`.
- HTTP auth defaults to `ANONYMOUS` unless overridden.
- Admin credentials are fixed local defaults (`admin` / `password` hash in `registry/auth.py`).
- OpenAI key may be read from `AZURE_OPENAI_API_KEY` in `orchestrator/.env`.
- Agent credentials may use `inline:` secret references (`registry/secret_refs.py`) instead of Key Vault.

`APP_ENV=prod` combined with `USE_LOCAL_EMULATORS=true` is rejected at runtime.

### 1.4 Pydantic validation boundary

HTTP bodies and Cosmos documents used as API responses are validated with Pydantic v2. Validation errors return structured JSON errors from `_err()` helpers in `function_app.py`.

### 1.5 Best-effort ancillary writes

Trace upserts, some message writes, and session updates are wrapped so failures log warnings but do not block the primary chat response when possible. Trace writes use `asyncio.wait_for(..., 10.0)` in `trace_writer.py`.

### 1.6 Route ordering is load-bearing

Azure Functions v2 matches routes in registration order. Fixed paths must appear before parameterized routes in `registry/function_app.py`, for example:

- `agents/stats`, `agents/ping-all`, `agents/capabilities`, `agents/export`, `agents/capabilities/fetch`
- before `agents/{agent_id}`
- `observability/metrics`, `observability/agent-metrics`, `observability/timeseries`, `traces`
- before `traces/{session_id}`

---

## 2. Repository map

```
azure/
├── orchestrator/          # Function app: chat, stream, proactive, memory, traces
│   ├── function_app.py
│   ├── chat_pipeline.py   # Shared pipeline for /chat and /chat/stream
│   ├── planner.py, executor.py, synthesizer.py
│   ├── schema_mapper.py, auth_injector.py
│   ├── memory.py, trace_writer.py
│   ├── input_guard.py, evaluator.py (optional)
│   ├── openai_client.py, secret_provider.py
│   ├── runtime_contract.py
│   └── models.py
├── registry/              # Function app: agents CRUD, auth, observability
│   ├── function_app.py, registry.py, cosmos.py, auth.py
│   ├── observability.py, models.py
│   ├── init_cosmos_emulator.py
│   ├── secret_refs.py, auth_config_manager.py
│   └── runtime_contract.py
├── registry-ui/           # Admin SPA (Vite → registry API only)
├── chatbot/               # Demo customer chat (Vite → orchestrator via proxy)
├── zero-clicks-dashboard/ # Demo portal (Vite → orchestrator)
├── docker-compose.yml
└── infra/                 # Terraform + deploy.sh
```

---

## 3. Data models

### 3.1 AgentDoc (registry)

Stored in container `agents`, logical partition value `"agents"` (partition path `/partition_key` in Terraform; same field used in emulator init).

Key fields: `name`, `description`, `endpoint_url`, `status`, `capabilities`, `auth_config`, `invocation_config`, `health_check_config`, health probe timestamps.

See `registry/models.py` for `AgentCreate`, `AgentUpdate`, `AgentReplace`, `HealthCheckConfig`, `InvocationConfig`, `RequestSchemaField`.

### 3.2 SessionDoc (orchestrator)

```python
class SessionDoc(BaseModel):
    id: str
    partition_key: str      # mirror of id (legacy)
    session_id: str         # Cosmos partition key value for sessions container (local init)
    user_message: str
    customer_id: str | None
    status: SessionStatus    # planning | executing | synthesizing | complete | failed
    plan: dict | None
    final_response: str | None
    created_at: str
    updated_at: str
```

Container **`sessions`**: partition path `/session_id` in `init_cosmos_emulator.py`. Terraform currently defines **`/partition_key`** for all containers—see [§12.3](#123-cosmos-db-partition-keys).

### 3.3 MessageDoc (orchestrator)

```python
class MessageDoc(BaseModel):
    id: str
    partition_key: str      # = session_id
    session_id: str
    type: MessageType       # user_input | final_response | plan | step_* | proactive_trigger
    step_id: int | None
    agent_name: str | None
    content: str
    metadata: dict
    created_at: str
```

Transcript for the LLM uses `type` in (`user_input`, `final_response`) via `memory.get_session_transcript()`.

### 3.4 TraceDoc (orchestrator writes, registry reads)

One document per session in container `traces`, `partition_key` = `session_id`:

- `trigger_type`: `reactive` | `proactive`
- `proactive_meta`: optional dict when proactive
- `plan`, `steps[]` (per-step payloads, `schema_mode`, `mapping_result`, redacted `input_payload`)
- `demo_events[]`: optional stage events when demo/stream flags enabled
- `status`, `total_latency_ms`, `final_response`, `error`
- `ttl`: 2592000 seconds (30 days) set in code

---

## 4. Orchestrator internals

### 4.1 Entry points (`orchestrator/function_app.py`)

| Route | Purpose |
|-------|---------|
| `GET /api/health` | Liveness, `BUILD_VERSION`, `BUILD_SHA`, runtime contract errors |
| `POST /api/chat` | Synchronous chat via `chat_pipeline.run_chat_pipeline()` |
| `POST /api/chat/stream` | SSE via same pipeline + `sse_events.format_sse()` |
| `POST /api/proactive/trigger` | Proactive pipeline (`trigger_type="proactive"`) |
| `GET /api/sessions/{session_id}` | Session, messages, transcript; optional `demo_events` |
| `GET /api/users/{customer_id}/sessions` | List sessions |
| `GET /api/insights`, `/api/copilot/context`, `/api/alerts`, … | Dashboard contracts |
| `GET /api/agents` | Active agent list for demo UIs |
| `POST /api/simulate-outage`, `/api/email_agent` | Demo helpers |

Auth level: `ORCHESTRATOR_HTTP_AUTH_LEVEL` (default `ANONYMOUS` when `USE_LOCAL_EMULATORS=true`).

### 4.2 Chat pipeline (`chat_pipeline.py`)

```
POST /api/chat or /api/chat/stream
  → Parse ChatRequest or ProactiveTriggerRequest
  → get_or_create session (SessionDoc)
  → get_session_transcript(session_id)
  → save user or proactive message
  → TraceContext (optional)
  → [reactive only] input_guard.validate()
  → [reactive only] is_query_related_to_scenario() — may short-circuit
  → planner.build_plan(..., transcript=..., trigger_type=...)
  → memory.save_plan()
  → trace.record_plan()
  → executor.execute_plan(..., ORCHESTRATOR_PARALLEL_EXEC)
  → synthesizer.synthesize(..., stream_tokens optional)
  → [optional] evaluator.evaluate_response() if ORCHESTRATOR_EVAL_ENABLED
  → memory.save_final_response()
  → trace.finish()
  → return PipelineResult / SSE events
```

Stage and step events are emitted to SSE clients; when `ORCHESTRATOR_DEMO_STEPS` or `ORCHESTRATOR_STREAM_PROGRESS` is true, events are also persisted on the trace as `demo_events`.

### 4.3 Planner (`planner.py`)

- Loads manifest from `memory.get_active_agents()` (Cosmos `agents` container).
- Uses `openai_client.get_chat_client()` and deployment from `AZURE_OPENAI_DEPLOYMENT` / `AZURE_OPENAI_PLANNER_DEPLOYMENT`.
- Reactive vs proactive system prompts.
- Injects `transcript` from `get_session_transcript` (not the legacy `get_conversation_history` limit alone).
- `ORCHESTRATOR_PLANNER_HISTORY_TURNS` env (default 6) affects planner-specific history slicing where used.
- Validates DAG: unknown agents skipped, cycles rejected, empty plan raises.

### 4.4 Executor (`executor.py`)

- Topological execution; **`ORCHESTRATOR_PARALLEL_EXEC`** (default true) runs ready steps in parallel within a layer.
- Body modes: schema-driven (`schema_mapper.build`), template (`body_template`), or default `AgentRequest`.
- **`auth_injector.resolve()`** adds headers/query params; secrets via `secret_provider` / inline refs.
- Retries: `AGENT_MAX_RETRIES`, timeout `AGENT_TIMEOUT_SECS` (global or per-agent overrides).
- Persists step progress via `memory.save_step_*`.
- Sends `X-Trigger-Type` header to downstream agents.

### 4.5 Synthesizer (`synthesizer.py`)

Combines step outputs with `synthesis_instruction`; reactive vs proactive prompts; optional token streaming callback for SSE.

### 4.6 TraceContext (`trace_writer.py`)

| Method | Cosmos write? |
|--------|----------------|
| `record_plan()` | Yes |
| `record_step_start()` | No — updates in-memory `steps[]` only |
| `record_step_result()` / `record_step_error()` | Yes (upsert full doc) |
| `record_event()` | Yes — appends to `demo_events` |
| `finish()` | Yes |

Payload sanitization redacts keys matching `key`, `token`, `secret`, `auth`, `password`.

### 4.7 Runtime contract (`orchestrator/runtime_contract.py`)

Validates forbidden combinations (`prod` + emulators, `prod` + `ANONYMOUS`, `prod` + demo steps) and required env vars when `APP_ENV` is prod or `ORCHESTRATOR_STRICT_MODE` is true.

---

## 5. Registry API internals

### 5.1 Module graph

```
function_app.py
├── auth.py
├── cosmos.py
├── registry.py
├── observability.py
├── models.py
├── capability_fetcher.py
└── auth_config_manager.py
```

### 5.2 Auth routes

`POST /api/auth/login`, `logout`, `GET /api/auth/verify` — session token in `admin_sessions` container with TTL from `SESSION_TTL_HOURS`.

### 5.3 Agent routes

CRUD, `PATCH .../status`, capabilities add/remove, `GET .../ping`, `POST /api/agents/ping-all`, `GET /api/agents/export` (download; filename `agent-registry-export.json` in response header only).

`POST /api/agents/capabilities/fetch` — discovery probe using plain secrets in request body (not persisted).

### 5.4 Observability routes

| Route | Handler |
|-------|---------|
| `GET /api/traces` | `observability.list_traces` — query params: status, agent, trigger_type, since_hours |
| `GET /api/traces/{session_id}` | Full trace document |
| `GET /api/observability/metrics` | System metrics |
| `GET /api/observability/agent-metrics` | Per-agent metrics |
| `GET /api/observability/timeseries` | Volume buckets |

There is **no** `GET /api/observability/proactive/metrics` route in the current codebase.

### 5.5 Health probing (`registry.py`)

`HealthCheckConfig.check_type`: `http`, `tcp`, or `none`. Updates `last_health_*` on the agent document after each probe.

---

## 6. Schema-driven invocation

Documented in `schema_mapper.py` and `registry/models.py` (`InvocationConfig.request_schema`).

Pipeline: runtime context + field definitions → LLM JSON (`temperature=0`) → `_validate_and_clean()` → HTTP body.

Executor precedence:

1. Non-empty `request_schema.fields` → schema-driven  
2. Else non-empty `body_template` → template tokens `{task}`, `{session_id}`, `{customer_id}`, `{context}`, `{step_N}`  
3. Else default legacy body  

`MappingResult` is stored on trace steps for the admin **SchemaMappingPanel**.

---

## 7. Authentication and authorisation

### 7.1 Admin UI

Production: bcrypt hash in Key Vault (`admin-username`, `admin-password`). Local emulators: embedded hash for password `password`.

Sessions: UUID token, `X-Session-Token` header, stored in Cosmos `admin_sessions`.

### 7.2 Function-level HTTP auth

`REGISTRY_HTTP_AUTH_LEVEL` / `ORCHESTRATOR_HTTP_AUTH_LEVEL`: `ANONYMOUS`, `FUNCTION`, or `ADMIN` (validated in runtime contracts).

### 7.3 Downstream agent auth (`auth_injector.py`)

| `auth_type` | Behaviour |
|-------------|-----------|
| `none` | No auth headers |
| `api_key` | Header or query |
| `bearer_token` | `Authorization: Bearer` |
| `basic_auth` | Basic header |
| `oauth2` | Client credentials; token cached in `_oauth2_token_cache` |
| `custom` | Custom header/query entries |

Secrets resolved through `secret_provider.get_secret()` (Key Vault or local env / `inline:` refs). Production forbids `inline:` references.

---

## 8. Observability system

### 8.1 Write path

Orchestrator `TraceContext` upserts into Cosmos `traces`. Registry `observability.py` reads with cross-partition queries where needed.

### 8.2 Admin UI

`registry-ui` components under `src/components/` and `observability/`:

- **TraceExplorer** — filters passed as query params to `GET /api/traces`
- **TraceDetail** — DAG, timeline, data flow, step inspector
- **MetricsDashboard** — calls `observability/metrics` (verify client path matches `agent-metrics` route)

API client: `registry-ui/src/api/client.js` — **registry base URL only** (no orchestrator client in admin UI).

---

## 9. Proactive execution

`POST /api/proactive/trigger` validates `ProactiveTriggerRequest` (`models.py`: `agent_name`, `customer_id`, `event_type`, `severity`, `message`, `context`, `run_enrichment`).

Uses the same `chat_pipeline.run_chat_pipeline(..., trigger_type="proactive")`:

- Saves proactive message via `memory.save_proactive_message`
- Optional enrichment plan when `run_enrichment` and severity warrant it
- Trace `trigger_type=proactive` and `proactive_meta` on trace document

Downstream UIs (e.g. zero-clicks-dashboard) call the orchestrator directly for triggers; they are not part of the registry service.

---

## 10. Conversation memory

### 10.1 Transcript source

`memory.get_session_transcript(session_id)`:

- Queries `messages` where `type` is `user_input` or `final_response`
- Orders by `created_at`
- Truncates to `ORCHESTRATOR_TRANSCRIPT_MAX_TURNS` (default 20) and `ORCHESTRATOR_TRANSCRIPT_MAX_CHARS` per turn (default 12000)

Used by `chat_pipeline` and passed to `planner.build_plan` / synthesizer.

### 10.2 Wrapper

`get_conversation_history(session_id, limit=8)` delegates to `get_session_transcript` with a smaller turn limit for backward compatibility.

### 10.3 Agent manifest

`get_active_agents()` returns registry documents with `status = active` for planner manifest construction.

---

## 11. React admin UI

### 11.1 Stack

- React 18, Vite 5, React Router 6
- `registry-ui/vite.config.js`: dev server port **3000** inside container (Compose maps host **5173→3000**)
- Proxy: `/api` → `VITE_REGISTRY_URL` (registry function app)
- `staticwebapp.config.json` for Azure Static Web Apps SPA fallback

### 11.2 API client (`src/api/client.js`)

Exports: `auth`, `agents`, `registry`, `traces`, `observability`.

- Session token from `sessionStorage` key `session_token`
- Optional `?code=` from `VITE_FUNC_CODE`
- **Export** downloads via `GET /api/agents/export` (client sets download filename locally; do not commit exported files with live URLs)

### 11.3 Import modal

`ImportAgentsModal.jsx` + `utils/agentImport.js` — normalizes payloads and POSTs per agent. Supports envelope `{ "agents": [...] }`.

### 11.4 Demo frontends (outside registry-ui)

| App | Talks to |
|-----|----------|
| `chatbot/` | Orchestrator (`VITE_ORCHESTRATOR_URL`, SSE stream) |
| `zero-clicks-dashboard/` | Orchestrator (insights, copilot, proactive) |

These exist to **demo** the orchestration platform; they are not required for registry or infra operation.

---

## 12. Infrastructure as code

### 12.1 Layout

```
infra/
├── main.tf
├── variables.tf
├── outputs.tf
├── terraform.tfvars.example
├── deploy.sh
└── modules/
    ├── resource_group/
    ├── cosmos_db/
    ├── openai/
    ├── key_vault/
    ├── function_app/      # orchestrator + registry instances
    └── static_web_app/    # registry-ui hosting
```

### 12.2 Orchestrator app settings (Terraform)

`COSMOS_ENDPOINT`, `COSMOS_DATABASE`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT`, `KEY_VAULT_URL`, `OPENAI_SECRET_NAME` (`openai-key`), `APP_ENV=prod`, `AGENT_TIMEOUT_SECS`, `AGENT_MAX_RETRIES`, `BUILD_VERSION`, `BUILD_SHA`.

### 12.3 Cosmos DB partition keys

| Source | `sessions` / `messages` partition path | Other containers |
|--------|----------------------------------------|------------------|
| `init_cosmos_emulator.py` (local) | `/session_id` | `/partition_key` |
| `infra/modules/cosmos_db/main.tf` (Azure) | `/partition_key` | `/partition_key` |

**Implication:** Documents written locally with `session_id` as partition value may not match cloud container definitions until paths are aligned. Application code uses `session_id` as the partition key **value** for reads/writes in `memory.py`.

Local init containers: `agents`, `admin_sessions`, `sessions`, `messages`, `traces`.

Terraform creates the same five container names with uniform `/partition_key` path.

### 12.4 deploy.sh

Location: `infra/deploy.sh` (run from `azure/` per README).

| Flag | Effect |
|------|--------|
| `--env` | `dev` \| `staging` \| `prod` |
| `--suffix` | Resource name suffix |
| `--skip-infra` | Skip Terraform |
| `--skip-orchestrator` | Skip orchestrator publish |
| `--skip-registry` | Skip registry publish |
| `--skip-ui` | Skip SWA deploy |
| `--skip-smoke-tests` | Skip health curls |
| `--destroy` | Terraform destroy |

`--skip-seed` appears in the script header but **no seeding step is implemented**—register agents via admin UI or API after deploy.

Steps: Terraform apply → optional admin password in Key Vault → `func azure functionapp publish` (orchestrator, registry) → store host keys in KV → `npm run build` + `swa deploy` for registry-ui → smoke tests → write `azure/.env.deploy`.

---

## 13. Known patterns and conventions

### Pydantic helpers

`_now()` and `_uuid()` as `Field(default_factory=...)` in models.

### Responses

Use `.model_dump()` (Pydantic v2), serialized with `json.dumps(default=str)` in HTTP helpers.

### Secret caching

- `registry/auth.py`: `_secret_cache` for Key Vault admin secrets  
- `orchestrator/secret_provider.py`: `_secret_cache` for OpenAI and agent secrets  

### Idempotent Cosmos writes

Prefer `upsert_item` over `create_item` for retries and redeployments.

### JavaScript (no TypeScript)

Admin and demo UIs use plain JS + Vite.

### OpenAI clients

`openai_client.py` supports classic Azure OpenAI (`AsyncAzureOpenAI`) and Foundry-style base URLs containing `/openai/v1` (`AsyncOpenAI` with `base_url`).

---

## Document history

This file is aligned to the `azure/orchestrator`, `azure/registry`, `azure/registry-ui`, `docker-compose.yml`, and `azure/infra` tree as of the capstone handoff revision. If code diverges, prefer the source files over this document.

# Technical Documentation

## Universal Utility Agent — Architecture and Implementation Reference

---

## Contents

1. [System design principles](#1-system-design-principles)
2. [Data models](#2-data-models)
3. [Orchestrator internals](#3-orchestrator-internals)
4. [Registry API internals](#4-registry-api-internals)
5. [Schema-driven invocation](#5-schema-driven-invocation)
6. [Authentication and authorisation](#6-authentication-and-authorisation)
7. [Observability system](#7-observability-system)
8. [Proactive execution](#8-proactive-execution)
9. [Conversation history](#9-conversation-history)
10. [React admin UI](#10-react-admin-ui)
11. [Infrastructure as code](#11-infrastructure-as-code)
12. [Known patterns and conventions](#12-known-patterns-and-conventions)

---

## 1. System design principles

### 1.1 Serverless-first

Both function apps run on Azure Functions Consumption plan. Cold-start latency is acceptable because the primary use case is human-initiated chat (not sub-100ms SLA). Consumption plan means there are no always-on costs; the platform scales to zero and bills only for actual invocations.

### 1.2 Managed Identity everywhere

Neither function app stores a connection string or API key as an environment variable. Identity is established at the Azure control-plane level:

- The orchestrator's system-assigned Managed Identity is granted `Cosmos DB Built-in Data Contributor`, `Key Vault Secrets User`, and `Cognitive Services OpenAI User`.
- The registry's system-assigned Managed Identity is granted `Cosmos DB Built-in Data Contributor` and `Key Vault Secrets User`.

`DefaultAzureCredential()` from the Azure SDK handles the token exchange transparently.

### 1.3 Pydantic validation boundary

Every external input — HTTP request bodies, Cosmos document reads used as API responses — is validated through Pydantic v2 models. Validation errors produce structured 400 responses with the field path and error message. This creates a hard boundary between untrusted external data and internal Python objects.

### 1.4 Best-effort writes

Trace writes, step-level memory saves, and session status updates are wrapped in `try/except` and never re-raise. A failure in observability infrastructure degrades monitoring, not functionality. The main chat response is always returned even if every ancillary write fails.

### 1.5 Route ordering is load-bearing

Azure Functions v2 registers HTTP routes in the order they appear in the source file and matches them in that order. A fixed-path route (e.g. `agents/stats`) must appear before a parameterised route (e.g. `agents/{agent_id}`) or the literal segment will be captured as a path parameter value. This constraint affects `agents/stats`, `agents/ping-all`, `agents/capabilities`, `agents/export`, and `traces/proactive`.

---

## 2. Data models

### 2.1 AgentDoc (registry)

Stored in the `agents` container, partition key fixed to the string `"agents"` so all agent documents are co-located on a single logical partition.

```python
class AgentDoc(BaseModel):
    id:                   str                # UUID
    partition_key:        str = "agents"
    name:                 str                # unique within registry
    description:          str
    endpoint_url:         str                # validated as URL
    api_key_secret_name:  str | None         # KV secret name for legacy key injection
    status:               AgentStatus        # active | inactive | degraded
    version:              str = "1.0.0"
    utility_types:        list[UtilityType]  # electric | gas | water | multi
    tags:                 list[str]
    capabilities:         list[Capability]
    metadata:             dict[str, Any]
    auth_config:          dict | None        # pluggable auth configuration
    invocation_config:    dict | None        # HTTP method, schema, body template, timeouts
    health_check_config:  dict | None        # http | tcp | none
    last_health_check_at: str | None
    last_health_status:   str | None
    last_health_ms:       int | None
    created_at:           str               # ISO 8601 UTC
    updated_at:           str
```

`AgentCreate` is AgentDoc without `id`, `partition_key`, `created_at`, `updated_at`, and health fields. `AgentUpdate` makes all fields optional for PATCH semantics. `AgentReplace` requires all non-computed fields for PUT semantics.

### 2.2 SessionDoc (orchestrator)

```python
{
    "id":            "<uuid>",
    "partition_key": "<id>",        # same as id; single-partition access
    "customer_id":   "CUST-1001",
    "status":        "active | executing | completed",
    "created_at":    "<iso>",
    "updated_at":    "<iso>",
    "ttl":           2592000        # 30 days
}
```

`user_message`, `plan`, and `final_response` are intentionally excluded. These values are passed between functions as arguments; reading them from Cosmos is never needed and would waste RUs.

### 2.3 MessageDoc (orchestrator)

```python
{
    "id":           "<uuid>",
    "partition_key":"<session_id>",
    "session_id":   "<session_id>",
    "customer_id":  "CUST-1001",
    "role":         "user | assistant | system",
    "content":      "...",
    "message_type": "reactive | proactive_trigger",
    "metadata":     {},             # populated for proactive_trigger messages
    "created_at":   "<iso>",
    "ttl":          2592000
}
```

The `role` field is the customer portal's rendering signal:
- `"user"` → render as customer message (right-aligned)
- `"assistant"` → render as AI response (left-aligned)
- `"system"` → render as proactive notification card

For `message_type="proactive_trigger"`, `metadata` contains: `source_agent`, `event_type`, `severity`, `context`, `original_message` (if enriched), `enriched` (bool), `customer_id`, `session_id`.

### 2.4 TraceDoc (orchestrator → read by registry)

Written by `trace_writer.py`; read by `observability.py` in the registry.

```python
{
    "id":               "<session_id>",   # 1:1 with session
    "partition_key":    "<session_id>",
    "session_id":       "<session_id>",
    "user_message":     "Why is my bill high?",
    "customer_id":      "CUST-1001",
    "trigger_type":     "reactive | proactive",
    "proactive_meta":   None | {
        "agent_name":       "OutageAgent",
        "event_type":       "service_outage",
        "severity":         "high",
        "original_message": "...",
        "enriched":         true
    },
    "status":           "running | completed | failed",
    "started_at":       "<iso>",
    "completed_at":     "<iso>",
    "total_latency_ms": 1823,
    "agents_invoked":   2,
    "plan": {
        "plan_id":               "<uuid>",
        "user_intent":           "Explain the billing increase",
        "synthesis_instruction": "...",
        "step_count":            2
    },
    "steps": [
        {
            "step_id":        1,
            "agent_name":     "BillingAgent",
            "agent_url":      "https://...",
            "task":           "Retrieve billing history for CUST-1001",
            "depends_on":     [],
            "input_payload":  { ... },   # sanitised — secrets redacted
            "output_raw":     "...",
            "result":         "...",
            "started_at":     "<iso>",
            "completed_at":   "<iso>",
            "latency_ms":     456,
            "status":         "completed | failed | skipped",
            "error":          null,
            "auth_type":      "api_key",
            "schema_mode":    "schema_driven | template | default",
            "mapping_result": null | { ... }
        }
    ],
    "final_response":   "...",
    "error":            null,
    "ttl":              2592000
}
```

Trace documents are partitioned by session_id. Observability queries use `enable_cross_partition_query=True`. The 30-day TTL means traces auto-expire with no manual cleanup.

---

## 3. Orchestrator internals

### 3.1 Request pipeline

```
POST /api/chat
     │
     ├─ Parse + validate body (ChatRequest)
     ├─ get_or_create_session()
     ├─ get_conversation_history(session_id, limit=10)
     ├─ save_message(role="user", message_type="reactive")
     ├─ TraceContext(session_id, user_message, customer_id)
     │
     ├─ planner.build_plan(user_message, customer_id, chat_history)
     │       └─ GPT-4o with reactive system prompt
     │          Inputs: user message + history + agent manifest
     │          Output: { user_intent, steps[], synthesis_instruction }
     │
     ├─ trace.record_plan(plan)        → upsert trace doc (status=running)
     │
     ├─ executor.execute_plan(plan, session_id, customer_id, trace)
     │       └─ For each step in topological order:
     │            ├─ Skip if dependencies failed
     │            ├─ Build request body (schema / template / default)
     │            ├─ Inject auth
     │            ├─ HTTP call with retry
     │            ├─ Extract result via response_result_path
     │            └─ record_step_result() or record_step_error()
     │
     ├─ synthesizer.synthesize(user_message, plan, results, chat_history)
     │       └─ GPT-4o with reactive system prompt
     │          Inputs: question + history + step outputs + synthesis hint
     │
     ├─ save_message(role="assistant", message_type="reactive")
     ├─ update_session(status="completed")
     ├─ trace.finish(final_response)
     │
     └─ return { session_id, response, agents_invoked, trigger_type }
```

### 3.2 Planner

`planner.build_plan()` calls GPT-4o with `temperature=0.1` and `response_format={"type": "json_object"}`. The response is a JSON object with `user_intent`, `steps[]`, and `synthesis_instruction`.

Two system prompts:
- **Reactive** — instructs the LLM to decompose the user's question into agent tasks and produce a synthesis instruction for a direct customer answer.
- **Proactive** — instructs the LLM to plan data-enrichment tasks for a notification event, with a synthesis instruction tuned for ≤150-word notifications.

When `chat_history` is provided, prior turns are injected as alternating `user`/`assistant` messages before the current request. The agent manifest is only appended to the final user turn to avoid token repetition.

The planner validates the returned plan:
- Unknown agent names are skipped with a warning.
- Cycles are detected using Kahn's topological sort; a cyclic plan raises `RuntimeError`.
- An empty steps list raises `RuntimeError`.

### 3.3 Executor

`executor.execute_plan()` iterates steps in topological order. For each step:

1. **Dependency check** — if any `depends_on` step ID is in the failed set, the current step is skipped and added to failed.
2. **Body construction** — selects schema-driven, template, or default mode based on `invocation_config`.
3. **Auth injection** — `auth_injector.resolve()` returns an `InjectedAuth` object with an `apply_to_kwargs()` method that adds headers or query parameters without exposing the secret value.
4. **HTTP call** — `httpx.AsyncClient` with per-step timeout and retry. 4xx errors do not retry; 5xx and network errors retry with exponential back-off.
5. **Result extraction** — `response_result_path` is a dot-notation path into the response JSON. If absent, common keys (`result`, `output`, `response`, `text`, `content`, `message`) are tried in order.

`trigger_type` is threaded through as a string and added to the `X-Trigger-Type` header on every outgoing agent call so remote agents can adjust behaviour.

### 3.4 Synthesizer

`synthesizer.synthesize()` calls GPT-4o with `temperature=0.3`. Step outputs are formatted as `[AgentName]: <result>` lines. The synthesis instruction from the plan is appended as additional guidance.

Falls back to concatenating step results if the LLM call fails.

### 3.5 TraceContext

`TraceContext` maintains an in-memory dict that is upserted to Cosmos after each significant event:

1. `record_plan()` → first write; creates the document in `running` state.
2. `record_step_start()` → synchronous (no `await`); appends a step sub-document. No Cosmos write here — reduces write count.
3. `record_step_result()` or `record_step_error()` → async; updates the step and upserts.
4. `finish()` → sets `status`, `total_latency_ms`, `final_response`, `completed_at`; final upsert.

All Cosmos writes are wrapped in `asyncio.wait_for(..., timeout=10.0)` and catch all exceptions — a slow or unavailable Cosmos never blocks the response.

Input payloads are sanitised before storage: any key containing `key`, `token`, `secret`, `auth`, or `password` is replaced with `"***redacted***"`.

---

## 4. Registry API internals

### 4.1 Module dependency graph

```
function_app.py
├── auth.py          session creation/validation, bcrypt password check
├── cosmos.py        raw Cosmos operations (no business logic)
├── registry.py      agent business logic, health probing
├── models.py        Pydantic validation types
└── observability.py trace queries and metrics aggregation
```

No module imports from `function_app.py`. The dependency arrow is always downward.

### 4.2 Route handler pattern

Every route in `function_app.py` follows this exact template:

```python
@app.route(route="agents/{agent_id}", methods=["GET"])
async def get_agent(req: func.HttpRequest) -> func.HttpResponse:
    err = await _guard(req)         # 1. Auth check
    if err:
        return err                  #    Bail on 401

    try:                            # 2. Input validation
        agent_id = req.route_params["agent_id"]
    except Exception as exc:
        return _err(f"Validation error: {exc}")

    try:                            # 3. Business logic
        result = await registry.get_agent(agent_id)
        if not result:
            return _err("Agent not found", 404)
        return _json(result.model_dump())
    except Exception as exc:
        log.exception("get_agent failed")
        return _err(str(exc), 500)
```

Helper functions:
- `_json(body, status=200)` — serialises with `json.dumps(default=str)` (handles datetime).
- `_err(msg, status=400, detail=None)` — returns `{"error": msg}` JSON.
- `_html(body, status=200)` — returns `text/html` response.
- `_token_from(req)` — reads `X-Session-Token` header or `?session_token=` query param.
- `_guard(req)` — calls `auth.validate_session(token)`, returns `None` if valid or a 401 response.

### 4.3 `_IMPORT_ERROR` pattern

At the top of `function_app.py`:

```python
_IMPORT_ERROR: str | None = None
try:
    import auth, cosmos, registry
    from models import (AgentCreate, AgentUpdate, ...)
except Exception as _exc:
    _IMPORT_ERROR = f"{type(_exc).__name__}: {_exc}\n{traceback.format_exc()}"
    log.critical("Startup import failed:\n%s", _IMPORT_ERROR)
```

Every route handler begins with:

```python
if _IMPORT_ERROR:
    return _err(f"Worker startup failed: {_IMPORT_ERROR}", 503)
```

This surfaces import errors (missing dependencies, syntax errors, misconfigured env vars) as 503 responses with the full traceback, rather than silent 500s.

### 4.4 Health probing

`registry.ping_agent(agent)` supports two check types:

**HTTP** — `GET` (or configured method) to the health URL; compares response status to `expected_http_status` (default 200). Stores latency in milliseconds.

**TCP** — `socket.create_connection((host, port), timeout=N)`. Used for agents that don't expose an HTTP health endpoint.

`ping_all()` calls `cosmos.agent_list()` with no status filter (all agents regardless of status) and runs `ping_agent()` for each concurrently using `asyncio.gather()`. Each agent's `last_health_check_at`, `last_health_status`, and `last_health_ms` fields are updated in Cosmos regardless of result.

---

## 5. Schema-driven invocation

### 5.1 Overview

Agents define their expected request body as a list of `RequestSchemaField` objects stored in `invocation_config.request_schema.fields`. At execution time, `schema_mapper.build()` uses GPT-4o to construct the actual request body from the available runtime context.

### 5.2 Field definition

```python
class RequestSchemaField(BaseModel):
    name:          str           # exact JSON key
    description:   str           # natural-language hint for the LLM
    required:      bool = True
    field_type:    FieldType     # string | number | boolean | array | object
    default:       Any | None    # last-resort for required fields
    nested_fields: list[RequestSchemaField]  # for object types
```

### 5.3 Mapping pipeline

```
Runtime context
  { task, session_id, customer_id, step_N_output, planner_note }
         +
Field definitions
         ↓
GPT-4o (temperature=0, response_format=json_object)
  System: strict rules — no nulls, no extras, no hallucinations
  User:   field definitions + available context
         ↓
Raw JSON output
         ↓
_validate_and_clean()
  1. Strip null / empty-string / empty-array values
  2. Strip extra fields if strict=True
  3. Apply defaults for any missing required fields
  4. Run JSON Schema validation if provided
         ↓
Missing required fields with no default → SchemaMapError
         ↓
Constructed body dict
```

On JSON parse failure, one retry with `_STRICT_RETRY_SUFFIX` appended to the prompt. After two failures, `raw_body={}` and validation handles the empty body.

### 5.4 Observability integration

`MappingResult` is returned by `schema_mapper.build()` and captured by `TraceContext.record_step_start()`. The trace step document gains:

```json
{
  "schema_mode": "schema_driven",
  "mapping_result": {
    "fields_included": ["customer_id", "message"],
    "fields_skipped":  ["optional_extra"],
    "llm_tokens_used":   47,
    "mapping_latency_ms": 312,
    "retry_count":         0,
    "warnings":           [],
    "decisions": [
      { "field_name": "customer_id", "included": true,  "confidence": 1.0, "inferred": false },
      { "field_name": "optional_extra", "included": false, "reason": "no relevant context" }
    ]
  }
}
```

The `SchemaMappingPanel` component in the admin UI renders this per-field decision table in the Step Inspector.

### 5.5 Backward compatibility

The executor checks `invocation_config.request_schema.fields` first:
- Non-empty → schema-driven mode.
- Empty + `body_template` non-empty → legacy template renderer with `{token}` substitution.
- Both empty → default body `{task, session_id, customer_id, context}`.

Existing agents with body templates continue to work without modification.

---

## 6. Authentication and authorisation

### 6.1 Admin UI auth flow

```
Browser                Registry Function App         Key Vault        Cosmos
   │                          │                          │               │
   │── POST /auth/login ──────▶│                          │               │
   │   {username, password}   │── GET admin-username ───▶│               │
   │                          │◀─ "admin" ───────────────│               │
   │                          │── GET admin-password ───▶│               │
   │                          │◀─ "$2b$12$..." ──────────│               │
   │                          │                          │               │
   │                          │  bcrypt.checkpw()        │               │
   │                          │                          │               │
   │                          │── upsert session doc ────────────────────▶│
   │◀─ { token, expires_at } ─│                          │               │
   │                          │                          │               │
   │── GET /api/agents ───────▶│                          │               │
   │   X-Session-Token: <tok> │── read session doc ──────────────────────▶│
   │                          │◀─ { valid: true } ───────────────────────│
   │◀─ { agents: [...] } ─────│                          │               │
```

Session documents live in `admin_sessions` with TTL = `SESSION_TTL_HOURS * 3600`. Cosmos auto-deletes expired documents. Each login creates a new session; logout deletes it immediately.

### 6.2 Pluggable agent auth

`auth_injector.resolve()` reads `auth_config` from the agent document and returns an `InjectedAuth` object. Auth types:

| Type | Mechanism |
|---|---|
| `none` | No-op; headers unchanged |
| `api_key` | Adds `X-Api-Key` header or `Authorization: ApiKey <value>` |
| `bearer_token` | Adds `Authorization: Bearer <token>` |
| `basic_auth` | Adds `Authorization: Basic <base64(user:pass)>` |
| `oauth2_client_credentials` | Fetches token from `token_endpoint`, caches in memory until `expires_in - 60s` |
| `custom` | Injects arbitrary headers defined in `auth_config.custom_headers` |

Secret values are fetched from Key Vault using the agent's Managed Identity. The KV secret name follows a deterministic convention: `agent-{slug}-apikey`, `agent-{slug}-clientsecret`, etc., where `slug` is the agent name lowercased and non-alphanumerics replaced with hyphens (max 24 chars).

`InjectedAuth.apply_to_kwargs()` modifies the `httpx.AsyncClient.request()` kwargs dict. Secret values never appear in trace documents or logs.

---

## 7. Observability system

### 7.1 Data flow

```
Orchestrator                    Cosmos DB               Registry API
function_app.py                 traces container        observability.py
      │                               │                       │
      │── TraceContext(session) ──────▶│ (running)             │
      │── record_plan(plan) ──────────▶│ (running + plan)      │
      │── record_step_start(step) ────▶│ (in-memory only)      │
      │── record_step_result(result) ─▶│ (step completed)      │
      │── finish(response) ───────────▶│ (completed)           │
                                       │                       │
                                       │◀── list_traces() ─────│
                                       │◀── get_trace(id) ──────│
                                       │◀── get_metrics() ──────│
                                       │◀── get_agent_metrics() │
                                       │◀── get_time_series() ──│
```

### 7.2 Trace queries

All queries use `enable_cross_partition_query=True` since traces are partitioned by session_id (unknown at query time). The `started_at` field is indexed and used in the `WHERE` clause time filter.

`list_traces()` returns lightweight summary rows (no step payloads) suitable for the explorer list view. `get_trace(id)` does a single-partition point-read for the full document including all step data.

### 7.3 UI components

**TraceExplorer** — filterable list. Filters are applied server-side (passed as query params to `GET /api/traces`). The `trigger_type` filter sends `reactive` or `proactive` to the backend's `WHERE c.trigger_type = @trigger_type` clause.

**TraceDetail** — three visualisation modes:

*DAG* — layered layout algorithm assigns each step a layer equal to `max(dependency layers) + 1`. Steps at the same layer are stacked vertically. Edges are cubic bezier curves. Node size is fixed; latency is shown as a badge inside the node.

*Timeline* — Gantt chart where each bar's `x` is `(step.started_at - trace.started_at) * scale` and width is `step.latency_ms * scale`. The scale is computed as `chartWidth / trace.total_latency_ms`.

*Data Flow* — steps stacked vertically in step_id order. Context flow connectors appear between steps where `step.depends_on` lists the source step. The connector shows the number of fields passed in `step.input_payload.context`.

**StepInspector** — rendered in a sticky right-panel. Shows `input_payload` and `output_raw` as collapsible dark-mode `<pre>` blocks. The `SchemaMappingPanel` sub-component renders below for schema-driven steps.

---

## 8. Proactive execution

### 8.1 Trigger flow

```
Remote agent
POST /api/proactive/trigger
    ↓
Parse + validate ProactiveTriggerRequest
    ↓
Resolve session (use supplied session_id, or find latest for customer, or create new)
    ↓
Determine enrichment:
  severity="low" or run_enrichment=False → skip to save
  otherwise → run enrichment pipeline
    ↓
Enrichment pipeline:
  Build enrichment prompt (structured text with agent/event/customer/context)
  TraceContext(trigger_type="proactive", proactive_meta={...})
  planner.build_plan(enrichment_prompt, trigger_type="proactive")
      └─ Proactive system prompt: plan data-enrichment tasks
  executor.execute_plan(trigger_type="proactive")
  synthesizer.synthesize(trigger_type="proactive")
      └─ Proactive system prompt: ≤150-word notification, urgency-matched tone
  trace.finish(final_response)
    ↓
memory.save_message(
    role="system",
    message_type="proactive_trigger",
    metadata={ source_agent, event_type, severity, context,
               original_message, enriched, customer_id, session_id }
)
    ↓
Return ProactiveTriggerResponse
```

### 8.2 Trace document for proactive

Proactive traces are identical in structure to reactive traces with two additions:

- `"trigger_type": "proactive"` — enables `WHERE c.trigger_type = 'proactive'` queries.
- `"proactive_meta": { agent_name, event_type, severity, original_message, enriched }` — supports `WHERE c.proactive_meta.severity = 'high'` filters.

### 8.3 Admin UI visibility

**Trace Explorer** — the Type filter chip `⚡ Proactive` sends `trigger_type=proactive` to `GET /api/traces` and filters to proactive traces. Clicking any row opens the full TraceDetail view with DAG and step inspector.

`GET /api/observability/proactive/metrics` aggregates: total, completed, failed, enriched count, enrichment_rate, by_severity, by_event_type, by_agent, avg_latency_ms.

---

## 9. Conversation history

### 9.1 Problem

Without history, every orchestrator call was stateless from the LLM's perspective. A follow-up like *"What about last month?"* had no referent — the planner had no knowledge of what had been discussed.

### 9.2 Implementation

`memory.get_conversation_history(session_id, limit=10)` queries the `messages` container for the last `limit` messages where:
- `role IN ('user', 'assistant')`
- `message_type = 'reactive'`

Internal messages (`role="system"`, step tracking, proactive triggers) are excluded. Results are reversed to chronological order.

History is loaded **before** saving the new user message to avoid double-inclusion.

### 9.3 LLM injection — planner

Prior turns are injected as alternating `user`/`assistant` messages in the OpenAI `messages` array:

```python
messages = [
    {"role": "system", "content": REACTIVE_SYSTEM_PROMPT},
    {"role": "user",   "content": prior_turn_1},
    {"role": "assistant", "content": prior_response_1},
    {"role": "user",   "content": prior_turn_2},
    {"role": "assistant", "content": prior_response_2},
    # ... up to limit turns
    {"role": "user",   "content": f"{customer_id_prefix}{current_message}\n\n{agent_manifest}"},
]
```

The agent manifest is only appended to the final user turn. This avoids repeating ~2000 tokens of manifest for every prior turn.

### 9.4 LLM injection — synthesizer

The same prior turns are injected before the final synthesis request. This allows the synthesizer to reference earlier answers: *"As I mentioned above, your bill increased due to..."*

### 9.5 Limit

`limit=10` (5 exchanges) keeps token consumption bounded. At typical message lengths (~100 tokens each), 10 turns add ~1000 tokens — well within GPT-4o's context window. Adjust in the `chat()` handler if sessions tend to be longer.

---

## 10. React admin UI

### 10.1 Tech stack

- React 18 with functional components and hooks throughout.
- Vite for bundling; `vite.config.js` sets `base: "/"` and dev proxy to the registry function.
- React Router v6 for client-side routing; `staticwebapp.config.json` rewrites all paths to `index.html` for SPA navigation.
- No UI component library — all components built from the design system in `globals.css` (CSS variables, `.card`, `.btn`, `.form-group`, `.modal`, `.table-wrap`, `.filter-chips`, `.chip`, `.badge`).
- No state management library — `AuthContext` provides session state; local `useState` is used within components; no Redux or Zustand.

### 10.2 API client

`src/api/client.js` defines two request helpers:

```js
async function req(method, path, { body, params } = {})      // → registry function app
async function orchReq(method, path, { body, params } = {})  // → orchestrator function app
```

Both attach `X-Session-Token` from `sessionStorage`. `req()` redirects to `/login` on 401 (stale session); `orchReq()` throws — a 401 from the orchestrator means a wrong function key, not an expired session.

Exported namespaces: `auth`, `agents`, `registry`, `traces`, `observability`, `proactive`.

### 10.3 Import agent feature

`ImportAgentModal.jsx` accepts three input formats:
- Single agent object: `{ "name": "...", "endpoint_url": "..." }`
- Array: `[{ ... }, { ... }]`
- Export envelope: `{ "agents": [{ ... }] }`

`toAgentCreate()` filters to `AGENT_CREATE_FIELDS` (name, description, endpoint_url, api_key_secret_name, status, version, utility_types, tags, capabilities, metadata, invocation_config, auth_config, health_check_config) and strips Cosmos-internal fields (id, partition_key, _rid, _etag, _ts, created_at, updated_at, last_health_*).

Import is per-agent: each document is sent to `POST /api/agents` independently. Results are shown per-agent so partial success is visible.

---

## 11. Infrastructure as code

### 11.1 Module structure

```
infra/
├── main.tf             root: wires modules, outputs, RBAC assignments
├── variables.tf        all tunable inputs (suffix, location, tags, SKUs)
├── outputs.tf          URLs, resource names, env-export block
├── terraform.tfvars.example
└── modules/
    ├── resource_group/ azurerm_resource_group
    ├── cosmos_db/      account (serverless) + database + 5 containers
    ├── openai/         cognitive services account + gpt-4o deployment
    ├── key_vault/      vault (RBAC mode) + time_sleep for propagation
    └── function_app/   storage + consumption plan + linux function app
                        (instantiated twice: orchestrator + registry)
```

### 11.2 RBAC assignments

All role assignments are in `main.tf` (not in modules) because they create cross-resource dependencies that Terraform's dependency graph handles better at the root level.

```hcl
# Orchestrator → Cosmos
resource "azurerm_cosmosdb_sql_role_assignment" "orch_cosmos" {
  role_definition_id = "00000000-0000-0000-0000-000000000002"  # Data Contributor
  principal_id       = module.orchestrator.principal_id
  scope              = module.cosmos_db.account_id
}

# Orchestrator → Key Vault
resource "azurerm_role_assignment" "orch_kv" {
  role_definition_name = "Key Vault Secrets User"
  principal_id         = module.orchestrator.principal_id
  scope                = module.key_vault.vault_id
}
```

### 11.3 deploy.sh

The script wraps the full deployment workflow:

| Step | What happens |
|---|---|
| Prerequisite check | Verifies az, terraform, func, python3, jq; checks az login |
| Terraform init/plan/apply | Provisions all resources; writes plan file |
| Read outputs | Captures resource names from Terraform into shell variables |
| func publish (orchestrator) | Remote build and deploy |
| func publish (registry) | Remote build and deploy |
| Store host keys | Retrieves function keys, writes to Key Vault |
| npm run build | Builds React app with production env vars |
| swa deploy | Deploys dist/ to Static Web App |
| Seed agents | Upserts data/agent_*.json via REST API |
| Smoke test | Hits /api/health on both apps; sends a test chat message |
| Write .env.deploy | All variables for future `source` |

Flags: `--skip-infra`, `--skip-code`, `--skip-seed`, `--skip-ui`, `--destroy`.

---

## 12. Known patterns and conventions

### Pydantic `_now()` / `_uuid()`

All models that auto-populate timestamps or IDs use module-level helper functions:

```python
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _uuid() -> str:
    return str(uuid.uuid4())
```

Fields use these as default factories: `created_at: str = Field(default_factory=_now)`.

### `model_dump()` for responses

All Pydantic models use `.model_dump()` (not `.dict()`, which is deprecated in v2) before passing to `_json()`.

### Cosmos partition key naming

Every document has an explicit `partition_key` field. This is set in code at document creation time, not derived from another field, so the partition key is always readable from the document itself without knowing the container's partition key path.

### Secret caching

`auth.py`, `planner.py`, and `synthesizer.py` all maintain a `_secret_cache: dict[str, str]` at module level. Key Vault fetches happen once per cold-start per secret name. This avoids redundant KV calls per request without complicating the code with TTL invalidation (secrets rotate infrequently; cold starts naturally invalidate the cache).

### Idempotent upsert

All Cosmos writes use `ctr.upsert_item()` rather than `create_item()`. This makes redeployments and retries safe — a duplicate write updates the existing document rather than raising a conflict error.

### TypeScript-free

The UI is deliberately plain JavaScript. The project timeline and the solo-developer constraint made TypeScript's overhead (tsconfig, type declarations, compilation errors) outweigh the benefits. JSDoc comments are used where type information aids readability.


## Agent Registry — Plug-and-Play Schema

### What was done

#### 1. `agents.json` — enriched plug-and-play schema

Every agent entry now has these fields on top of the original `name / description / capabilities / endpoint`:

| New field | Purpose |
|---|---|
| `version` | Semantic version; lets you track compatibility as agents evolve |
| `status` | `active / inactive / maintenance` — only `active` agents are routed to |
| `tags` | Short keywords for grouping and future filtering UIs |
| `health_check` | URL the orchestrator (or a health-check job) can GET to confirm the agent is alive |
| `timeout_seconds` | Per-agent override so a slow ML agent can have 60 s while billing gets 30 s |
| `input_schema` | JSON Schema inline — documents exactly what the agent expects |
| `output_schema` | JSON Schema inline — documents what the agent returns |
| `metadata` | Free-form object (`author`, `created_at`, `updated_at`, etc.) |

The two existing agents are also split onto separate ports (`8001` / `8002`) to reinforce the microservice model.

---

#### 2. `agents.schema.json` — formal JSON Schema (draft-07)

A new file that formally declares the shape of `agents.json`. It:
- marks required fields with `"required"` and uses `"additionalProperties": false` to catch typos
- enforces the `snake_case` name pattern via a `"pattern"` rule
- gives each field a `"description"` so any IDE with JSON Schema support shows inline docs when editing `agents.json`

---

#### 3. `orchestrator.py` — updated `AgentDefinition` + `AgentRegistry`

**`AgentDefinition`**:
- Added all new fields as typed dataclass attributes with sensible defaults
- Added `to_dict()` so the object can be serialised back to JSON cleanly

**`AgentRegistry`** — three new methods:

- `add_agent(agent_dict, persist=True)` — validates the dict, checks for duplicates, stamps `created_at` / `updated_at`, appends to the in-memory list, and optionally writes back to disk immediately
- `remove_agent(name, persist=True)` — removes by name and optionally persists
- `save()` — writes the full registry to JSON, preserving the `$schema` reference
- `list_active()` — returns only `status == "active"` agents
- `list_brief()` now includes `tags` and `status` and only lists active agents

`AgentInvoker.invoke()` now uses `agent.timeout_seconds` as a per-agent override when set.

---

#### 4. `add_agent.py` — CLI plug-and-play script

Developers can register a new agent in three ways:

```bash
# Interactive wizard (no args needed)
python src/core/add_agent.py

# One-liner
python src/core/add_agent.py add \
  --name document_parser_agent \
  --description "Parses PDFs and extracts structured data." \
  --capabilities "Parse PDF invoices" "Extract tables from images" \
  --endpoint http://localhost:8003/document_parser_agent \
  --tags documents parsing ocr \
  --health-check http://localhost:8003/health

# Remove an agent
python src/core/add_agent.py remove --name document_parser_agent

# List all registered agents
python src/core/add_agent.py list
```

---

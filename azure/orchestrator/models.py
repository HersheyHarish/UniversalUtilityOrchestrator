from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid() -> str:
    return str(uuid.uuid4())


# ── Enumerations ──────────────────────────────────────────────────────────────


class SessionStatus(str, Enum):
    PLANNING = "planning"
    EXECUTING = "executing"
    SYNTHESIZING = "synthesizing"
    COMPLETE = "complete"
    FAILED = "failed"


class MessageType(str, Enum):
    PROACTIVE    = "proactive_trigger"
    USER_INPUT   = "user_input"
    PLAN         = "plan"
    EXEC_START   = "exec_start"
    EXEC_RESULT  = "exec_result"
    EXEC_ERROR   = "exec_error"
    FINAL        = "final_response"

class MessageRole(str, Enum):
    USER    = "user"
    ORCHESTRATOR = "orchestrator"
    AGENT   = "agent"
    SYSTEM  = "system"
    SYSTEM_TRIGGER = "system_trigger"

class FieldType(str, Enum):
    STRING  = "string"
    NUMBER  = "number"
    BOOLEAN = "boolean"
    ARRAY   = "array"
    OBJECT  = "object"

class Severity(str, Enum):
    LOW    = "low"
    MEDIUM = "medium"
    HIGH   = "high"


# ── Execution plan ─────────────────────────────────────────────────────────────


class PlanStep(BaseModel):
    step_id:             int
    agent_name:          str
    agent_url:           str
    task:                str             = Field(..., description="Exact task description sent to the agent")
    depends_on:          list[int]       = Field(default_factory=list, description="step_ids this step must wait for")
    context_note:        str             = ""
    auth_config:         dict[str, Any]  = Field(default_factory=dict)
    api_key_secret_name: str | None      = None
    invocation_config:   dict[str, Any]  = Field(default_factory=dict)
    health_check_config: dict[str, Any]  = Field(default_factory=dict)



class ExecutionPlan(BaseModel):
    plan_id:               str       = Field(default_factory=_uuid)
    user_intent:           str       = Field(..., description="One-sentence summary of what the user wants")
    steps:                 list[PlanStep]
    synthesis_instruction: str       = Field(..., description="How the synthesizer should combine all outputs")
    created_at:            str       = Field(default_factory=_now)

# ── Agent invocation contract ─────────────────────────────────────────────────

class FieldDecision(BaseModel):
    field_name:  str
    included:    bool
    value:       Any              = None
    reason:      str              = ""
    confidence:  float            = 1.0
    inferred:    bool             = False

class MappingResult(BaseModel):
    body:              dict[str, Any]
    decisions:         list[FieldDecision]  = Field(default_factory=list)
    warnings:          list[str]            = Field(default_factory=list)
    errors:            list[str]            = Field(default_factory=list)
    llm_tokens_used:   int                  = 0
    mapping_latency_ms:int                  = 0
    retry_count:       int                  = 0
    fields_included:   list[str]            = Field(default_factory=list)
    fields_skipped:    list[str]            = Field(default_factory=list)

class RequestSchemaField(BaseModel):
    name:          str
    description:   str
    required:      bool        = True
    field_type:    FieldType   = FieldType.STRING
    default:       Any | None  = None
    nested_fields: list["RequestSchemaField"] = Field(default_factory=list)

class AgentResponse(BaseModel):
    agent_name:    str
    result:        str
    actions_taken: list[dict[str, Any]] = Field(default_factory=list)
    suggestions:   list[str] = Field(default_factory=list)
    metadata:      dict[str, Any] = Field(default_factory=dict)

# ── Cosmos DB documents ───────────────────────────────────────────────────────

class SessionDoc(BaseModel):
    id:            str = Field(default_factory=_uuid)
    partition_key: str = ""          # set to id after creation
    customer_id:   str | None = None
    status:        SessionStatus = SessionStatus.PLANNING
    created_at:    str = Field(default_factory=_now)
    updated_at:    str = Field(default_factory=_now)

    def model_post_init(self, __context: Any) -> None:
        if not self.partition_key:
            self.partition_key = self.id


class MessageDoc(BaseModel):
    id:          str = Field(default_factory=_uuid)
    partition_key: str           # = session_id
    session_id:  str
    role:        MessageRole
    type:        MessageType
    content:     str
    metadata:    dict[str, Any] = Field(default_factory=dict)
    created_at:  str = Field(default_factory=_now)

# ── HTTP API models ───────────────────────────────────────────────────────────


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None  # omit to start a new session
    customer_id: str | None = None

class ProactiveTriggerRequest(BaseModel):
    message:        str
    customer_id:    str
    agent_name:     str
    event_type:     str
    severity:       Severity       = Severity.MEDIUM
    context:        dict[str, Any] = Field(default_factory=dict)
    run_enrichment: bool           = True

class StandardResponse(BaseModel):
    session_id:      str
    response:        str
    plan_id:         str | None = None
    agents_used:     list[str] = Field(default_factory=list)
    steps_completed: int = 0



# ── Zero-click dashboard contracts ────────────────────────────────────────────


class InsightCTA(BaseModel):
    label: str
    action: str
    payload: dict[str, Any] = Field(default_factory=dict)


class InsightItem(BaseModel):
    id: str
    type: str
    severity: str
    title: str
    summary: str
    evidence: list[str] = Field(default_factory=list)
    cta: InsightCTA | None = None
    session_id: str
    created_at: str


class CopilotContext(BaseModel):
    target: str
    explanation: str
    confidence: float
    drivers: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    related_programs: list[str] = Field(default_factory=list)


class AlertAction(BaseModel):
    label: str
    action: str


class AlertItem(BaseModel):
    id: str
    channel: str
    title: str
    body: str
    severity: str
    status: str
    actions: list[AlertAction] = Field(default_factory=list)
    triggered_at: str
    session_id: str

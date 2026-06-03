"""
models.py — Shared data models for the orchestrator function.
All Cosmos DB documents and inter-module contracts are typed here.
"""

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
    PROACTIVE = "proactive_trigger"
    USER_INPUT = "user_input"
    PLAN = "plan"
    STEP_START = "step_start"
    STEP_RESULT = "step_result"
    STEP_ERROR = "step_error"
    FINAL = "final_response"


# ── Execution plan ─────────────────────────────────────────────────────────────


class PlanStep(BaseModel):
    """One agent call in the execution plan."""

    step_id: int
    agent_name: str
    agent_url: str
    auth_config: dict[str, Any] = Field(default_factory=dict)
    api_key_secret_name: str | None = None  # Key Vault secret name
    task: str = Field(..., description="Exact task description sent to the agent")
    depends_on: list[int] = Field(default_factory=list, description="step_ids this step must wait for")
    context_note: str = ""  # extra context the planner wants injected


class ExecutionPlan(BaseModel):
    """Structured output returned by the planner LLM."""

    plan_id: str = Field(default_factory=_uuid)
    user_intent: str = Field(..., description="One-sentence summary of what the user wants")
    steps: list[PlanStep]
    synthesis_instruction: str = Field(..., description="How the synthesizer should combine all outputs")
    created_at: str = Field(default_factory=_now)


# ── Agent invocation contract ─────────────────────────────────────────────────


class AgentRequest(BaseModel):
    """Payload sent to every remote agent endpoint."""

    task: str
    session_id: str
    customer_id: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    conversation_history: list[dict[str, str]] = Field(default_factory=list)


class AgentResponse(BaseModel):
    """Expected response shape from every remote agent."""

    agent_name: str
    result: str
    actions_taken: list[dict[str, Any]] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Cosmos DB documents ───────────────────────────────────────────────────────


class SessionDoc(BaseModel):
    """
    Stored in the `sessions` container.

    init_cosmos_emulator.py defines this container with partition key path
    /session_id — Cosmos requires that property on every document (not /partition_key).
    """

    id: str = Field(default_factory=_uuid)
    partition_key: str = ""  # legacy mirror of id; kept for older docs / queries
    session_id: str = ""  # must match id; used as the Cosmos partition key value
    user_message: str
    customer_id: str | None = None
    status: SessionStatus = SessionStatus.PLANNING
    plan: dict[str, Any] | None = None
    final_response: str | None = None
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)

    def model_post_init(self, __context: Any) -> None:
        if not self.session_id:
            self.session_id = self.id
        if not self.partition_key:
            self.partition_key = self.id


class MessageDoc(BaseModel):
    """
    Stored in the `messages` container.
    partition_key = session_id  (stored in the partition_key field)
    """

    id: str = Field(default_factory=_uuid)
    partition_key: str  # = session_id
    session_id: str
    type: MessageType
    step_id: int | None = None
    agent_name: str | None = None
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=_now)


# ── HTTP API models ───────────────────────────────────────────────────────────


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None  # omit to start a new session
    customer_id: str | None = None


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ProactiveTriggerRequest(BaseModel):
    message: str
    customer_id: str
    agent_name: str
    event_type: str
    severity: Severity = Severity.MEDIUM
    context: dict[str, Any] = Field(default_factory=dict)
    run_enrichment: bool = True


class ChatResponse(BaseModel):
    session_id: str
    response: str
    plan_id: str | None = None
    agents_used: list[str] = Field(default_factory=list)
    steps_completed: int = 0
    content_segments: list[dict[str, Any]] = Field(default_factory=list)


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

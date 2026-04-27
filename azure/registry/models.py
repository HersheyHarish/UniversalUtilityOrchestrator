"""
models.py — Pydantic models for the Agent Registry API.

New in this version:
  HealthCheckConfig
    - check_type: http | tcp | none
    - health_check_url: optional custom URL (derived from endpoint_url when blank)
    - expected_http_status: default 200
    - http_timeout_seconds: default 10
    - tcp_port: derived from endpoint_url when blank
    - tcp_timeout_seconds: default 5

  InvocationConfig
    - http_method: default POST
    - content_type: default application/json
    - body_template: dict[str, str|dict] — maps field names to template expressions
        Supported template tokens: {task}, {session_id}, {customer_id}, {context}
        Example: {"message": "{task}", "user": "{customer_id}"}
        When empty the orchestrator uses the legacy AgentRequest schema.
    - response_result_path: dot-notation path into the JSON response
        Example: "result" → resp["result"]
                 "data.output.text" → resp["data"]["output"]["text"]
        When empty the orchestrator falls back to resp["result"].
    - extra_static_headers: non-auth headers always sent (e.g. Accept, X-Api-Version)
    - timeout_seconds: per-agent override (0 = use global default)
    - max_retries: per-agent override (-1 = use global default)

  AgentDoc gains health_check_config and invocation_config fields.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid() -> str:
    return str(uuid.uuid4())


# =============================================================================
# Auth enumerations (unchanged)
# =============================================================================


class AuthType(str, Enum):
    NONE = "none"
    API_KEY = "api_key"
    BEARER_TOKEN = "bearer_token"
    BASIC_AUTH = "basic_auth"
    OAUTH2 = "oauth2"
    CUSTOM = "custom"


class ApiKeyLocation(str, Enum):
    HEADER = "header"
    QUERY_PARAM = "query_param"


class CustomAuthInjectAs(str, Enum):
    HEADER = "header"
    QUERY_PARAM = "query_param"


# =============================================================================
# Health check configuration
# =============================================================================


class HealthCheckType(str, Enum):
    HTTP = "http"  # GET request, check status code
    TCP = "tcp"  # TCP socket connect, no HTTP
    NONE = "none"  # always treated as healthy — for agents without health endpoints


class HealthCheckConfig(BaseModel):
    """
    Configures how the registry and orchestrator determine whether an agent is alive.

    If health_check_url is blank:
      - For HTTP checks: derived as <endpoint_url base>/api/health
      - For TCP checks: host and port are parsed from endpoint_url

    Leave check_type as "http" for Azure Functions, FastAPI, and similar.
    Use "tcp" for raw TCP services (gRPC, sockets) with no HTTP interface.
    Use "none" for agents that don't expose any reachability signal.
    """

    check_type: HealthCheckType = HealthCheckType.HTTP

    # Optional: explicit health check URL.
    # Blank → auto-derived from endpoint_url by the registry probe logic.
    health_check_url: str | None = None

    # HTTP check settings
    expected_http_status: int = 200
    http_timeout_seconds: int = 10

    # TCP check settings (port derived from endpoint_url when 0)
    tcp_port: int = 0
    tcp_timeout_seconds: int = 5


# =============================================================================
# Invocation configuration
# =============================================================================


class InvocationConfig(BaseModel):
    """
    Configures how the orchestrator invokes this agent.

    body_template
    ─────────────
    A dict mapping request body field names to template strings.
    Supported tokens (replaced at invocation time):
        {task}        — the agent's task string from the plan
        {session_id}  — the current orchestrator session ID
        {customer_id} — the customer ID (may be empty string)
        {context}     — JSON-encoded dict of prior step outputs
        {step_N}      — output of plan step N (e.g. {step_1})

    Examples:
        LangChain agent:  {"input": "{task}"}
        OpenAI-style:     {"messages": [{"role": "user", "content": "{task}"}]}
        Legacy default:   {"task": "{task}", "session_id": "{session_id}", ...}

    Nested values and lists are supported — the template is rendered by
    _render_body() in executor.py which recurses into dicts and lists.

    When body_template is empty ({}) the orchestrator uses the legacy
    AgentRequest Pydantic model (task, session_id, customer_id, context).

    response_result_path
    ────────────────────
    Dot-notation path used to extract the agent's result string from the JSON
    response. Examples:
        "result"            → resp["result"]
        "data.text"         → resp["data"]["text"]
        "choices.0.message.content"  → resp["choices"][0]["message"]["content"]

    When empty, the executor falls back to resp.get("result", str(resp)).

    extra_static_headers
    ────────────────────
    Non-auth headers always added to every request to this agent.
    Examples: {"Accept": "application/json", "X-Api-Version": "2"}
    Auth headers come from auth_injector — do NOT duplicate them here.
    """

    http_method: str = "POST"
    content_type: str = "application/json"

    # Field mapping: leave empty to use the legacy AgentRequest schema
    body_template: dict[str, Any] = Field(default_factory=dict)

    # Dot-notation extraction path for the result: leave empty for resp["result"]
    response_result_path: str = ""

    # Non-auth static headers (e.g. Accept, X-Api-Version)
    extra_static_headers: dict[str, str] = Field(default_factory=dict)

    # Per-agent overrides: 0 / -1 = use orchestrator global defaults
    timeout_seconds: int = 0
    max_retries: int = -1


# =============================================================================
# Auth sub-models (unchanged from auth-v2)
# =============================================================================


class CustomAuthEntry(BaseModel):
    key: str
    inject_as: CustomAuthInjectAs = CustomAuthInjectAs.HEADER
    value: str | None = None
    secret_name: str | None = None


class AuthConfig(BaseModel):
    auth_type: AuthType = AuthType.NONE

    api_key_location: ApiKeyLocation | None = None
    api_key_name: str | None = None
    api_key_secret_name: str | None = None

    bearer_token_secret_name: str | None = None

    basic_auth_username: str | None = None
    basic_auth_password_secret_name: str | None = None

    oauth2_token_url: str | None = None
    oauth2_client_id: str | None = None
    oauth2_client_secret_name: str | None = None
    oauth2_scopes: str | None = None
    oauth2_token_ttl_seconds: int = 3600

    custom_entries: list[CustomAuthEntry] = Field(default_factory=list)


class AuthSecrets(BaseModel):
    api_key_value: str | None = None
    bearer_token_value: str | None = None
    basic_auth_password_value: str | None = None
    oauth2_client_secret_value: str | None = None
    custom_secret_values: list[str | None] = Field(default_factory=list)


# =============================================================================
# Agent status & utility enumerations
# =============================================================================


class AgentStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    DEGRADED = "degraded"


class UtilityType(str, Enum):
    ELECTRIC = "electric"
    GAS = "gas"
    WATER = "water"
    MULTI = "multi"


class Capability(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Core document
# =============================================================================


class AgentDoc(BaseModel):
    id: str = Field(default_factory=_uuid)
    partition_key: str = "agents"
    name: str
    description: str
    endpoint_url: str
    status: AgentStatus = AgentStatus.ACTIVE
    version: str = "1.0.0"
    utility_types: list[UtilityType] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    capabilities: list[Capability] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    # Auth
    auth_config: AuthConfig = Field(default_factory=AuthConfig)
    api_key_secret_name: str | None = None  # legacy

    # NEW: Health check and invocation configs
    health_check_config: HealthCheckConfig = Field(default_factory=HealthCheckConfig)
    invocation_config: InvocationConfig = Field(default_factory=InvocationConfig)

    # Health tracking (populated by ping operations)
    last_health_check_at: str | None = None
    last_health_status: str | None = None
    last_health_ms: int | None = None

    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be empty")
        return v

    @field_validator("endpoint_url")
    @classmethod
    def endpoint_must_be_http(cls, v: str) -> str:
        if not v.startswith(("https://", "http://")):
            raise ValueError("endpoint_url must start with https:// or http://")
        return v.rstrip("/")


# =============================================================================
# Request bodies
# =============================================================================


class AgentCreate(BaseModel):
    name: str
    description: str
    endpoint_url: str
    version: str = "1.0.0"
    utility_types: list[UtilityType] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    capabilities: list[Capability] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    auth_config: AuthConfig = Field(default_factory=AuthConfig)
    auth_secrets: AuthSecrets | None = None
    api_key_secret_name: str | None = None  # legacy
    health_check_config: HealthCheckConfig = Field(default_factory=HealthCheckConfig)
    invocation_config: InvocationConfig = Field(default_factory=InvocationConfig)

    @field_validator("endpoint_url")
    @classmethod
    def endpoint_must_be_http(cls, v: str) -> str:
        if not v.startswith(("https://", "http://")):
            raise ValueError("endpoint_url must start with https:// or http://")
        return v.rstrip("/")


class AgentUpdate(BaseModel):
    """PATCH — all fields optional."""

    description: str | None = None
    endpoint_url: str | None = None
    version: str | None = None
    utility_types: list[UtilityType] | None = None
    tags: list[str] | None = None
    capabilities: list[Capability] | None = None
    metadata: dict[str, Any] | None = None
    auth_config: AuthConfig | None = None
    auth_secrets: AuthSecrets | None = None
    api_key_secret_name: str | None = None
    health_check_config: HealthCheckConfig | None = None
    invocation_config: InvocationConfig | None = None


class AgentReplace(BaseModel):
    """PUT — full replacement."""

    name: str
    description: str
    endpoint_url: str
    version: str = "1.0.0"
    utility_types: list[UtilityType] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    capabilities: list[Capability] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    auth_config: AuthConfig = Field(default_factory=AuthConfig)
    auth_secrets: AuthSecrets | None = None
    api_key_secret_name: str | None = None
    health_check_config: HealthCheckConfig = Field(default_factory=HealthCheckConfig)
    invocation_config: InvocationConfig = Field(default_factory=InvocationConfig)


class StatusPatch(BaseModel):
    status: AgentStatus
    reason: str | None = None


class CapabilityAdd(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Admin UI auth models
# =============================================================================


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    expires_at: str
    username: str


class VerifyResponse(BaseModel):
    valid: bool
    username: str | None = None


# =============================================================================
# Response models
# =============================================================================


class HealthCheckResult(BaseModel):
    agent_id: str
    agent_name: str
    endpoint: str
    status: str  # healthy | unhealthy | unreachable
    check_type: str = "http"
    http_code: int | None = None
    response_ms: int | None = None
    checked_at: str = Field(default_factory=_now)
    error: str | None = None


class PingAllResponse(BaseModel):
    checked: int
    healthy: int
    degraded: int
    results: list[HealthCheckResult]


class RegistryStats(BaseModel):
    total: int
    by_status: dict[str, int]
    by_utility_type: dict[str, int]
    by_auth_type: dict[str, int]
    by_health_check_type: dict[str, int]
    total_capabilities: int
    unique_tags: list[str]
    last_registered_at: str | None
    last_health_check_at: str | None


class CapabilityIndex(BaseModel):
    capability_name: str
    description: str
    agent_count: int
    agent_names: list[str]

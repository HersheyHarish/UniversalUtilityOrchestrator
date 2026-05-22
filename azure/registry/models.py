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
# Field type enum
# =============================================================================

class FieldType(str, Enum):
    STRING  = "string"
    NUMBER  = "number"
    BOOLEAN = "boolean"
    ARRAY   = "array"
    OBJECT  = "object"

# =============================================================================
# RequestSchemaField
# =============================================================================

class RequestSchemaField(BaseModel):
    name:          str
    description:   str
    required:      bool        = True
    field_type:    FieldType   = FieldType.STRING
    default:       Any | None  = None
    nested_fields: list["RequestSchemaField"] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def name_valid(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("field name must not be empty")
        return v

    @field_validator("description")
    @classmethod
    def desc_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("field description must not be empty")
        return v


# Rebuild for forward ref
RequestSchemaField.model_rebuild()

# =============================================================================
# RequestSchema  (container stored in InvocationConfig)
# =============================================================================

class RequestSchema(BaseModel):
    fields:      list[RequestSchemaField] = Field(default_factory=list)
    strict:      bool                     = True
    json_schema: dict[str, Any] | None    = None

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
    check_type: HealthCheckType = HealthCheckType.HTTP

    health_check_url: str | None = None

    expected_http_status: int = 200
    http_timeout_seconds: int = 10

    tcp_port: int = 0
    tcp_timeout_seconds: int = 5


# =============================================================================
# Invocation configuration
# =============================================================================


class InvocationConfig(BaseModel):
    # ── Schema-driven (new) ───────────────────────────────────────────────────
    request_schema:        RequestSchema       = Field(default_factory=RequestSchema)

    # ── Template (legacy fallback — do NOT remove) ────────────────────────────
    body_template:         dict[str, Any]      = Field(default_factory=dict)

    # ── Unchanged transport settings ──────────────────────────────────────────
    http_method:           str                 = "POST"
    content_type:          str                 = "application/json"
    response_result_path:  str                 = ""
    extra_static_headers:  dict[str, str]      = Field(default_factory=dict)
    timeout_seconds:       int                 = 0
    max_retries:           int                 = -1

    def uses_schema(self) -> bool:
        """True when schema-driven mode is active."""
        return bool(self.request_schema.fields)


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

    auth_config: AuthConfig = Field(default_factory=AuthConfig)
    api_key_secret_name: str | None = None  # legacy

    health_check_config: HealthCheckConfig = Field(default_factory=HealthCheckConfig)
    invocation_config: InvocationConfig = Field(default_factory=InvocationConfig)

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
    status: str
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

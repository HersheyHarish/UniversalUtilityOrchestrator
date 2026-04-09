"""
models.py — Pydantic models for the Agent Registry API.

Key additions in this version:
  - AuthType.OAUTH2 (client_credentials grant)
  - OAuth2Config fields in AuthConfig
  - AuthSecrets — carries the ACTUAL secret values from the UI
    (registry stores them in Key Vault, saves only the secret name in Cosmos)
  - AgentCreate / AgentUpdate / AgentReplace gain auth_secrets: AuthSecrets | None
"""
from __future__ import annotations
from datetime import datetime, timezone
from enum import Enum
from typing import Any
import uuid

from pydantic import BaseModel, Field, field_validator


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _uuid() -> str:
    return str(uuid.uuid4())


# ── Auth enumerations ─────────────────────────────────────────────────────────

class AuthType(str, Enum):
    NONE         = "none"
    API_KEY      = "api_key"
    BEARER_TOKEN = "bearer_token"
    BASIC_AUTH   = "basic_auth"
    OAUTH2       = "oauth2"
    CUSTOM       = "custom"


class ApiKeyLocation(str, Enum):
    HEADER      = "header"
    QUERY_PARAM = "query_param"


class CustomAuthInjectAs(str, Enum):
    HEADER      = "header"
    QUERY_PARAM = "query_param"


# ── Auth sub-models ────────────────────────────────────────────────────────────

class CustomAuthEntry(BaseModel):
    """
    One injection rule for custom auth.
    secret_name references Key Vault; value is plain text for non-sensitive data.
    Exactly one of value or secret_name should be set.
    """
    key:         str
    inject_as:   CustomAuthInjectAs = CustomAuthInjectAs.HEADER
    value:       str | None = None        # plain — for non-sensitive values
    secret_name: str | None = None        # KV ref — for sensitive values


class AuthConfig(BaseModel):
    """
    Auth configuration stored in Cosmos DB.
    Contains type, names, locations, and KV secret-name REFERENCES.
    Actual secret values are NEVER stored here — they live in Key Vault.
    """
    auth_type: AuthType = AuthType.NONE

    # ── API Key ───────────────────────────────────────────────────────────────
    api_key_location:    ApiKeyLocation | None = None
    api_key_name:        str | None = None         # header/param name
    api_key_secret_name: str | None = None         # KV secret name

    # ── Bearer Token ──────────────────────────────────────────────────────────
    bearer_token_secret_name: str | None = None    # KV secret name

    # ── Basic Auth ────────────────────────────────────────────────────────────
    basic_auth_username:             str | None = None   # plain — not sensitive
    basic_auth_password_secret_name: str | None = None   # KV secret name

    # ── OAuth2 (Client Credentials) ───────────────────────────────────────────
    oauth2_token_url:           str | None = None   # token endpoint URL
    oauth2_client_id:           str | None = None   # client ID (not sensitive)
    oauth2_client_secret_name:  str | None = None   # KV secret name for client secret
    oauth2_scopes:              str | None = None   # space-separated scopes, optional
    oauth2_token_ttl_seconds:   int        = 3600   # cache TTL (default 1 hour)

    # ── Custom ────────────────────────────────────────────────────────────────
    custom_entries: list[CustomAuthEntry] = Field(default_factory=list)


class AuthSecrets(BaseModel):
    """
    Carries actual SECRET VALUES from the UI to the registry backend.
    The registry writes each non-empty value into Key Vault under a
    deterministic name (e.g. agent-<slug>-apikey), then stores only
    that name in auth_config inside Cosmos.

    UI sends this alongside AgentCreate / AgentUpdate.
    This model is NEVER stored in Cosmos — it is ephemeral.
    """
    api_key_value:             str | None = None
    bearer_token_value:        str | None = None
    basic_auth_password_value: str | None = None
    oauth2_client_secret_value: str | None = None
    # For custom entries: list of values in the same order as custom_entries.
    # Index alignment: custom_secret_values[0] → custom_entries[0], etc.
    custom_secret_values:      list[str | None] = Field(default_factory=list)


# ── Agent status & utility ────────────────────────────────────────────────────

class AgentStatus(str, Enum):
    ACTIVE   = "active"
    INACTIVE = "inactive"
    DEGRADED = "degraded"

class UtilityType(str, Enum):
    ELECTRIC = "electric"
    GAS      = "gas"
    WATER    = "water"
    MULTI    = "multi"


# ── Capability sub-model ──────────────────────────────────────────────────────

class Capability(BaseModel):
    name:          str
    description:   str
    input_schema:  dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)


# ── Core document ─────────────────────────────────────────────────────────────

class AgentDoc(BaseModel):
    id:            str              = Field(default_factory=_uuid)
    partition_key: str              = "agents"
    name:          str
    description:   str
    endpoint_url:  str
    status:        AgentStatus      = AgentStatus.ACTIVE
    version:       str              = "1.0.0"
    utility_types: list[UtilityType] = Field(default_factory=list)
    tags:          list[str]        = Field(default_factory=list)
    capabilities:  list[Capability] = Field(default_factory=list)
    metadata:      dict[str, Any]   = Field(default_factory=dict)
    auth_config:   AuthConfig       = Field(default_factory=AuthConfig)
    # Legacy field — kept for backward compat
    api_key_secret_name: str | None = None
    # Health tracking
    last_health_check_at: str | None = None
    last_health_status:   str | None = None
    last_health_ms:       int | None = None
    created_at:           str        = Field(default_factory=_now)
    updated_at:           str        = Field(default_factory=_now)

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


# ── Request bodies ────────────────────────────────────────────────────────────

class AgentCreate(BaseModel):
    name:          str
    description:   str
    endpoint_url:  str
    version:       str                  = "1.0.0"
    utility_types: list[UtilityType]    = Field(default_factory=list)
    tags:          list[str]            = Field(default_factory=list)
    capabilities:  list[Capability]     = Field(default_factory=list)
    metadata:      dict[str, Any]       = Field(default_factory=dict)
    auth_config:   AuthConfig           = Field(default_factory=AuthConfig)
    # auth_secrets carries plain values — processed then discarded by registry.py
    auth_secrets:  AuthSecrets | None   = None
    # Legacy
    api_key_secret_name: str | None     = None

    @field_validator("endpoint_url")
    @classmethod
    def endpoint_must_be_http(cls, v: str) -> str:
        if not v.startswith(("https://", "http://")):
            raise ValueError("endpoint_url must start with https:// or http://")
        return v.rstrip("/")


class AgentUpdate(BaseModel):
    """PATCH — all fields optional."""
    description:   str | None              = None
    endpoint_url:  str | None              = None
    version:       str | None              = None
    utility_types: list[UtilityType] | None = None
    tags:          list[str] | None         = None
    capabilities:  list[Capability] | None  = None
    metadata:      dict[str, Any] | None    = None
    auth_config:   AuthConfig | None        = None
    auth_secrets:  AuthSecrets | None       = None
    api_key_secret_name: str | None         = None


class AgentReplace(BaseModel):
    """PUT — full replacement."""
    name:          str
    description:   str
    endpoint_url:  str
    version:       str                  = "1.0.0"
    utility_types: list[UtilityType]    = Field(default_factory=list)
    tags:          list[str]            = Field(default_factory=list)
    capabilities:  list[Capability]     = Field(default_factory=list)
    metadata:      dict[str, Any]       = Field(default_factory=dict)
    auth_config:   AuthConfig           = Field(default_factory=AuthConfig)
    auth_secrets:  AuthSecrets | None   = None
    api_key_secret_name: str | None     = None


class StatusPatch(BaseModel):
    status: AgentStatus
    reason: str | None = None


class CapabilityAdd(BaseModel):
    name:          str
    description:   str
    input_schema:  dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)


# ── Auth models (admin UI login) ──────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str

class LoginResponse(BaseModel):
    token:      str
    expires_at: str
    username:   str

class VerifyResponse(BaseModel):
    valid:    bool
    username: str | None = None


# ── Response models ───────────────────────────────────────────────────────────

class HealthCheckResult(BaseModel):
    agent_id:    str
    agent_name:  str
    endpoint:    str
    status:      str
    http_code:   int | None  = None
    response_ms: int | None  = None
    checked_at:  str         = Field(default_factory=_now)
    error:       str | None  = None


class PingAllResponse(BaseModel):
    checked:  int
    healthy:  int
    degraded: int
    results:  list[HealthCheckResult]


class RegistryStats(BaseModel):
    total:                int
    by_status:            dict[str, int]
    by_utility_type:      dict[str, int]
    by_auth_type:         dict[str, int]
    total_capabilities:   int
    unique_tags:          list[str]
    last_registered_at:   str | None
    last_health_check_at: str | None


class CapabilityIndex(BaseModel):
    capability_name: str
    description:     str
    agent_count:     int
    agent_names:     list[str]

"""
auth_config_manager.py — Stores agent auth secrets in Key Vault (cloud) or
inline references (local emulator mode).

Called by registry.py when an agent is created or updated with auth_secrets.

Responsibilities:
  1. Accept the agent name + auth_config + auth_secrets from the request.
  2. For each non-empty secret value in auth_secrets, generate a deterministic
     Key Vault secret name and write the value to Key Vault via MSI.
  3. Return an updated AuthConfig with the secret_name references filled in.
     The caller then stores this updated config in Cosmos (never the values).

Secret naming convention:
  agent-{slug}-apikey           API key
  agent-{slug}-bearertoken      Bearer token
  agent-{slug}-basicpassword    Basic auth password
  agent-{slug}-oauth2secret     OAuth2 client secret
  agent-{slug}-custom-{index}   Custom entry at index N

{slug} = lowercase, non-alphanumeric chars replaced with hyphens, max 24 chars.
This is deterministic: re-saving an agent overwrites the same secret (idempotent).

Key Vault limits: secret names 1-127 chars, alphanumeric and hyphens only.
"""

from __future__ import annotations

import logging
import os
import re

from azure.identity.aio import DefaultAzureCredential
from azure.keyvault.secrets.aio import SecretClient
from models import AuthConfig, AuthSecrets, AuthType
from secret_refs import is_local_mode, is_prod_env, to_inline_secret_ref

log = logging.getLogger(__name__)

_KV_URL = os.environ.get("KEY_VAULT_URL", "")
_CREDENTIAL: DefaultAzureCredential | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────


def _slug(name: str) -> str:
    """Convert an agent name to a safe KV secret name segment (max 24 chars)."""
    s = name.lower()
    s = re.sub(r"[^a-z0-9]", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:24]


async def _set_secret(secret_name: str, value: str) -> str:
    """
    Persist a secret and return the reference that should be saved.

    Cloud mode:
      Stores in Key Vault, returns the Key Vault secret name.
    Local mode:
      Stores an inline reference, returns inline:<base64>.
    """
    if is_local_mode():
        if is_prod_env():
            raise RuntimeError("inline secret references are forbidden when APP_ENV=prod")
        return to_inline_secret_ref(value)

    if not _KV_URL:
        raise RuntimeError("KEY_VAULT_URL is not configured — cannot store auth secrets.")
    global _CREDENTIAL
    if _CREDENTIAL is None:
        _CREDENTIAL = DefaultAzureCredential()
    async with SecretClient(_KV_URL, _CREDENTIAL) as kv:
        await kv.set_secret(secret_name, value)
    log.info("Stored secret in Key Vault: %s", secret_name)
    return secret_name


# ── Public API ────────────────────────────────────────────────────────────────


async def process_and_store(
    agent_name: str,
    auth_config: AuthConfig,
    auth_secrets: AuthSecrets | None,
) -> AuthConfig:
    """
    Write any provided secret values into Key Vault and return an updated
    AuthConfig with the corresponding secret_name fields populated.

    If auth_secrets is None or all values are empty, the original auth_config
    is returned unchanged (idempotent — existing KV references are preserved).
    """
    if not auth_secrets:
        return auth_config

    slug = _slug(agent_name)
    updated_cfg = auth_config.model_copy(deep=True)
    auth_type = auth_config.auth_type

    # ── API Key ────────────────────────────────────────────────────────────────
    if auth_type == AuthType.API_KEY and auth_secrets.api_key_value:
        secret_name = f"agent-{slug}-apikey"
        updated_cfg.api_key_secret_name = await _set_secret(secret_name, auth_secrets.api_key_value)

    # ── Bearer Token ──────────────────────────────────────────────────────────
    elif auth_type == AuthType.BEARER_TOKEN and auth_secrets.bearer_token_value:
        secret_name = f"agent-{slug}-bearertoken"
        updated_cfg.bearer_token_secret_name = await _set_secret(secret_name, auth_secrets.bearer_token_value)

    # ── Basic Auth ────────────────────────────────────────────────────────────
    elif auth_type == AuthType.BASIC_AUTH and auth_secrets.basic_auth_password_value:
        secret_name = f"agent-{slug}-basicpassword"
        updated_cfg.basic_auth_password_secret_name = await _set_secret(
            secret_name, auth_secrets.basic_auth_password_value
        )

    # ── OAuth2 ────────────────────────────────────────────────────────────────
    elif auth_type == AuthType.OAUTH2 and auth_secrets.oauth2_client_secret_value:
        secret_name = f"agent-{slug}-oauth2secret"
        updated_cfg.oauth2_client_secret_name = await _set_secret(secret_name, auth_secrets.oauth2_client_secret_value)

    # ── Custom ────────────────────────────────────────────────────────────────
    elif auth_type == AuthType.CUSTOM:
        custom_vals = auth_secrets.custom_secret_values or []
        updated_entries = list(updated_cfg.custom_entries)

        for i, entry in enumerate(updated_entries):
            if i < len(custom_vals) and custom_vals[i]:
                secret_name = f"agent-{slug}-custom-{i}"
                stored_ref = await _set_secret(secret_name, custom_vals[i])
                # Mark this entry as KV-backed, clear any plain value
                updated_entries[i] = entry.model_copy(
                    update={
                        "secret_name": stored_ref,
                        "value": None,
                    }
                )

        updated_cfg.custom_entries = updated_entries

    return updated_cfg

from __future__ import annotations
import logging
import os
import re

from azure.identity.aio import DefaultAzureCredential
from azure.keyvault.secrets.aio import SecretClient

from models import AuthConfig, AuthSecrets, AuthType

log = logging.getLogger(__name__)

_KV_URL     = os.environ.get("KEY_VAULT_URL", "")
_CREDENTIAL = DefaultAzureCredential()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _slug(name: str) -> str:
    """Convert an agent name to a safe KV secret name segment (max 24 chars)."""
    s = name.lower()
    s = re.sub(r"[^a-z0-9]", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:24]


async def _set_secret(secret_name: str, value: str) -> None:
    """Write a secret to Key Vault. Overwrites if it already exists."""
    if not _KV_URL:
        raise RuntimeError(
            "KEY_VAULT_URL is not configured — cannot store auth secrets."
        )
    async with SecretClient(_KV_URL, _CREDENTIAL) as kv:
        await kv.set_secret(secret_name, value)
    log.info("Stored secret in Key Vault: %s", secret_name)


# ── Public API ────────────────────────────────────────────────────────────────

async def process_and_store(
    agent_name:  str,
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

    slug         = _slug(agent_name)
    updated_cfg  = auth_config.model_copy(deep=True)
    auth_type    = auth_config.auth_type

    # ── API Key ────────────────────────────────────────────────────────────────
    if auth_type == AuthType.API_KEY and auth_secrets.api_key_value:
        secret_name = f"agent-{slug}-apikey"
        await _set_secret(secret_name, auth_secrets.api_key_value)
        updated_cfg.api_key_secret_name = secret_name

    # ── Bearer Token ──────────────────────────────────────────────────────────
    elif auth_type == AuthType.BEARER_TOKEN and auth_secrets.bearer_token_value:
        secret_name = f"agent-{slug}-bearertoken"
        await _set_secret(secret_name, auth_secrets.bearer_token_value)
        updated_cfg.bearer_token_secret_name = secret_name

    # ── Basic Auth ────────────────────────────────────────────────────────────
    elif auth_type == AuthType.BASIC_AUTH and auth_secrets.basic_auth_password_value:
        secret_name = f"agent-{slug}-basicpassword"
        await _set_secret(secret_name, auth_secrets.basic_auth_password_value)
        updated_cfg.basic_auth_password_secret_name = secret_name

    # ── OAuth2 ────────────────────────────────────────────────────────────────
    elif auth_type == AuthType.OAUTH2 and auth_secrets.oauth2_client_secret_value:
        secret_name = f"agent-{slug}-oauth2secret"
        await _set_secret(secret_name, auth_secrets.oauth2_client_secret_value)
        updated_cfg.oauth2_client_secret_name = secret_name

    # ── Custom ────────────────────────────────────────────────────────────────
    elif auth_type == AuthType.CUSTOM:
        custom_vals = auth_secrets.custom_secret_values or []
        updated_entries = list(updated_cfg.custom_entries)

        for i, entry in enumerate(updated_entries):
            if i < len(custom_vals) and custom_vals[i]:
                secret_name = f"agent-{slug}-custom-{i}"
                await _set_secret(secret_name, custom_vals[i])
                # Mark this entry as KV-backed, clear any plain value
                updated_entries[i] = entry.model_copy(update={
                    "secret_name": secret_name,
                    "value":       None,
                })

        updated_cfg.custom_entries = updated_entries

    return updated_cfg

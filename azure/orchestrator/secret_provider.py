"""
secret_provider.py — central secret resolution for orchestrator local + cloud modes.

Resolution order:
  1) Inline secret reference (inline:<base64>)
  2) Local emulator mode env vars
  3) Azure Key Vault secret lookup
"""
from __future__ import annotations

import base64
import logging
import os

from azure.identity.aio import DefaultAzureCredential
from azure.keyvault.secrets.aio import SecretClient

log = logging.getLogger(__name__)

_INLINE_PREFIX = "inline:"
_KV_URL = os.environ.get("KEY_VAULT_URL", "")
_APP_ENV = os.environ.get("APP_ENV", "local").strip().lower()
_IS_PROD = _APP_ENV in {"prod", "production"}
_LOCAL_MODE = os.environ.get("USE_LOCAL_EMULATORS", "").lower() == "true"

_secret_cache: dict[str, str] = {}
_kv_credential: DefaultAzureCredential | None = None


def _decode_inline(secret_ref: str) -> str | None:
    if not secret_ref or not secret_ref.startswith(_INLINE_PREFIX):
        return None
    raw = secret_ref[len(_INLINE_PREFIX):]
    try:
        padding = "=" * (-len(raw) % 4)
        return base64.urlsafe_b64decode((raw + padding).encode("ascii")).decode("utf-8")
    except Exception:
        log.warning("Invalid inline secret reference encountered")
        return None


async def get_secret(secret_name: str, local_env_fallback: str | None = None) -> str:
    """
    Resolve a secret value from inline refs, env (local), or Key Vault (cloud).

    local_env_fallback:
      Optional env var name to prefer in local mode before falling back to
      secret_name-as-env-var behavior.
    """
    if not secret_name:
        return ""

    inline = _decode_inline(secret_name)
    if inline is not None:
        if _IS_PROD:
            raise RuntimeError("inline secret references are forbidden when APP_ENV=prod")
        return inline

    if _IS_PROD and _LOCAL_MODE:
        raise RuntimeError("USE_LOCAL_EMULATORS=true is forbidden when APP_ENV=prod")

    if _LOCAL_MODE:
        if local_env_fallback:
            preferred = os.environ.get(local_env_fallback)
            if preferred:
                return preferred
        return os.environ.get(secret_name, "")

    if not _KV_URL:
        raise RuntimeError("KEY_VAULT_URL is not set — cannot fetch secrets.")

    if secret_name in _secret_cache:
        return _secret_cache[secret_name]

    global _kv_credential
    if _kv_credential is None:
        _kv_credential = DefaultAzureCredential()

    async with SecretClient(_KV_URL, _kv_credential) as kv:
        _secret_cache[secret_name] = (await kv.get_secret(secret_name)).value

    return _secret_cache[secret_name]

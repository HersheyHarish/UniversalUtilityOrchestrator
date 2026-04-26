"""
auth_injector.py — Pluggable authentication injection for outgoing agent calls.

New in this version:
  - OAuth2 Client Credentials grant flow
    - Fetches token from oauth2_token_url using client_id + client_secret
    - Caches access tokens per agent (keyed by token_url + client_id) until expiry
    - Injects Authorization: Bearer <access_token>
  - All existing auth types (none, api_key, bearer_token, basic_auth, custom) unchanged

Security:
  - Secret values are resolved via secret_provider:
      * inline refs (local mode),
      * environment variables (local mode),
      * Key Vault via MSI (cloud mode).
  - OAuth2 access tokens are cached with their expiry time; a 60-second buffer
    ensures tokens are refreshed before they actually expire.
  - Nothing is logged at INFO level — only secret names, never values.
"""
from __future__ import annotations
import base64
import logging
import time
from typing import Any

import httpx

from secret_provider import get_secret

log = logging.getLogger(__name__)

# ── In-memory caches (per cold-start) ─────────────────────────────────────────

# OAuth2 access tokens: { cache_key: (access_token, expires_at_epoch) }
_oauth2_token_cache: dict[str, tuple[str, float]] = {}

_OAUTH2_TOKEN_BUFFER_SECONDS = 60  # refresh token this many seconds before it expires


# ── OAuth2 token fetch ────────────────────────────────────────────────────────

async def _get_oauth2_token(
    token_url:     str,
    client_id:     str,
    client_secret: str,
    scopes:        str | None,
) -> str:
    """
    Fetch an OAuth2 access token using the client_credentials grant.
    Caches the token until expiry - buffer seconds.
    """
    cache_key = f"{token_url}::{client_id}"
    cached    = _oauth2_token_cache.get(cache_key)

    if cached:
        token, expires_at = cached
        if time.monotonic() < expires_at - _OAUTH2_TOKEN_BUFFER_SECONDS:
            log.debug("Using cached OAuth2 token for client_id=%s", client_id)
            return token

    log.info("Fetching new OAuth2 token from %s (client_id=%s)", token_url, client_id)

    data: dict[str, str] = {
        "grant_type":    "client_credentials",
        "client_id":     client_id,
        "client_secret": client_secret,
    }
    if scopes:
        data["scope"] = scopes

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            token_url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    if resp.status_code != 200:
        raise RuntimeError(
            f"OAuth2 token request to {token_url} failed with HTTP {resp.status_code}: "
            f"{resp.text[:200]}"
        )

    body        = resp.json()
    token       = body.get("access_token")
    expires_in  = int(body.get("expires_in", 3600))

    if not token:
        raise RuntimeError(
            f"OAuth2 response from {token_url} missing access_token field"
        )

    _oauth2_token_cache[cache_key] = (token, time.monotonic() + expires_in)
    log.info("OAuth2 token obtained, expires_in=%ds", expires_in)
    return token


# ── Public interface ──────────────────────────────────────────────────────────

class InjectedAuth:
    """Resolved authentication ready to merge into an httpx request."""
    __slots__ = ("headers", "params")

    def __init__(self):
        self.headers: dict[str, str] = {}
        self.params:  dict[str, str] = {}

    def apply_to_kwargs(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        if self.headers:
            kwargs["headers"] = {**kwargs.get("headers", {}), **self.headers}
        if self.params:
            kwargs["params"]  = {**kwargs.get("params", {}), **self.params}
        return kwargs


async def resolve(
    auth_config:         dict[str, Any],
    legacy_secret_name:  str | None = None,
) -> InjectedAuth:
    """
    Resolve auth_config into concrete headers / params.

    auth_config   — the auth_config dict from the agent's Cosmos document.
    legacy_secret_name — old api_key_secret_name field for backward compat.
    """
    result    = InjectedAuth()
    auth_type = (auth_config or {}).get("auth_type", "none")

    # ── Backward compat: legacy api_key_secret_name ───────────────────────────
    if auth_type == "none" and legacy_secret_name:
        try:
            key_value = await get_secret(legacy_secret_name)
            result.headers["x-functions-key"] = key_value
        except Exception as exc:
            log.warning("Legacy secret fetch failed (non-fatal): %s", exc)
        return result

    if auth_type == "none" or not auth_config:
        return result

    # ── API Key ────────────────────────────────────────────────────────────────
    if auth_type == "api_key":
        secret_name = auth_config.get("api_key_secret_name")
        key_name    = auth_config.get("api_key_name") or "x-api-key"
        location    = auth_config.get("api_key_location") or "header"

        if not secret_name:
            log.warning("auth_type=api_key but api_key_secret_name not set — skipping")
            return result

        key_value = await get_secret(secret_name)
        if location == "header":
            result.headers[key_name] = key_value
        else:
            result.params[key_name] = key_value

    # ── Bearer Token ──────────────────────────────────────────────────────────
    elif auth_type == "bearer_token":
        secret_name = auth_config.get("bearer_token_secret_name")
        if not secret_name:
            log.warning("auth_type=bearer_token but bearer_token_secret_name not set")
            return result
        token = await get_secret(secret_name)
        result.headers["Authorization"] = f"Bearer {token}"

    # ── Basic Auth ────────────────────────────────────────────────────────────
    elif auth_type == "basic_auth":
        username    = auth_config.get("basic_auth_username") or ""
        secret_name = auth_config.get("basic_auth_password_secret_name")
        if not secret_name:
            log.warning("auth_type=basic_auth but basic_auth_password_secret_name not set")
            return result
        password    = await get_secret(secret_name)
        credentials = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
        result.headers["Authorization"] = f"Basic {credentials}"

    # ── OAuth2 (Client Credentials) ───────────────────────────────────────────
    elif auth_type == "oauth2":
        token_url   = auth_config.get("oauth2_token_url")
        client_id   = auth_config.get("oauth2_client_id")
        secret_name = auth_config.get("oauth2_client_secret_name")
        scopes      = auth_config.get("oauth2_scopes")

        if not token_url or not client_id or not secret_name:
            log.warning(
                "auth_type=oauth2 requires oauth2_token_url, oauth2_client_id, "
                "and oauth2_client_secret_name — skipping"
            )
            return result

        client_secret = await get_secret(secret_name)
        access_token  = await _get_oauth2_token(
            token_url=token_url,
            client_id=client_id,
            client_secret=client_secret,
            scopes=scopes,
        )
        result.headers["Authorization"] = f"Bearer {access_token}"

    # ── Custom ────────────────────────────────────────────────────────────────
    elif auth_type == "custom":
        for entry in (auth_config.get("custom_entries") or []):
            key       = entry.get("key", "")
            inject_as = entry.get("inject_as", "header")
            plain_val = entry.get("value")
            secret_nm = entry.get("secret_name")

            if not key:
                continue

            if secret_nm:
                try:
                    value = await get_secret(secret_nm)
                except Exception as exc:
                    log.error("Custom entry '%s' KV fetch failed: %s", key, exc)
                    continue
            elif plain_val is not None:
                value = plain_val
            else:
                log.warning("Custom entry '%s' has no value or secret_name", key)
                continue

            if inject_as == "header":
                result.headers[key] = value
            else:
                result.params[key] = value

    else:
        log.warning("Unknown auth_type '%s' — no auth injected", auth_type)

    return result

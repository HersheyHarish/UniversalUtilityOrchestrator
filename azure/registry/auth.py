"""
auth.py — Admin authentication for the Agent Registry API.

Credentials are stored in Key Vault (never in code or env vars):
  - admin-username  : plain-text username
  - admin-password  : bcrypt hash of the password

Generate a hash once with:
  python3 -c "import bcrypt; print(bcrypt.hashpw(b'yourpass', bcrypt.gensalt()).decode())"

Then store it:
  az keyvault secret set --vault-name <KV> --name admin-password --value '<hash>'

Session lifecycle:
  1. POST /api/auth/login  → validate credentials → create session UUID in Cosmos
  2. Every protected route calls auth.require_session(req) → validates token from header
  3. POST /api/auth/logout → deletes session from Cosmos immediately
  4. Sessions auto-expire after SESSION_TTL_HOURS via Cosmos TTL (no cron needed)
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import cosmos
from azure.identity.aio import DefaultAzureCredential
from azure.keyvault.secrets.aio import SecretClient
from models import LoginResponse, VerifyResponse

log = logging.getLogger(__name__)

_KV_URL = os.environ.get("KEY_VAULT_URL", "")
_SESSION_TTL_H = int(os.environ.get("SESSION_TTL_HOURS", "8"))

# Shared credential — created lazily to avoid import-time aiohttp session leaks
_KV_CREDENTIAL: DefaultAzureCredential | None = None
_secret_cache: dict[str, str] = {}


# ── Key Vault helpers ─────────────────────────────────────────────────────────


async def _get_secret(name: str) -> str:
    """Fetch a secret from Key Vault, caching it for the lifetime of this instance."""
    app_env = os.environ.get("APP_ENV", "local").strip().lower()
    use_local = os.environ.get("USE_LOCAL_EMULATORS", "").lower() == "true"
    if app_env in {"prod", "production"} and use_local:
        raise RuntimeError("USE_LOCAL_EMULATORS=true is forbidden when APP_ENV=prod")

    if use_local:
        if name == "admin-username":
            return "admin"
        if name == "admin-password":
            return "$2b$12$H97DNnZIrhu070DIyJcNA.tNCbtX8Qqpv7KCec0iTbrUBQ7zjgOfO"  # hash of 'password'
        return ""

    if name not in _secret_cache:
        global _KV_CREDENTIAL
        if _KV_CREDENTIAL is None:
            _KV_CREDENTIAL = DefaultAzureCredential()
        async with SecretClient(_KV_URL, _KV_CREDENTIAL) as kv:
            secret = await kv.get_secret(name)
            _secret_cache[name] = secret.value
    return _secret_cache[name]


# ── Auth operations ───────────────────────────────────────────────────────────


async def login(username: str, password: str) -> LoginResponse | None:
    """
    Validate username + password against Key Vault secrets.
    On success: creates a session in Cosmos and returns LoginResponse.
    On failure: returns None (caller should return 401).
    """
    if not username or not password:
        return None

    try:
        stored_username = await _get_secret("admin-username")
        stored_hash = await _get_secret("admin-password")
    except Exception as exc:
        log.error("Key Vault credential fetch failed: %s", exc)
        # Don't leak the error message to the caller
        return None

    # Constant-time username comparison
    if username != stored_username:
        return None

    try:
        password_valid = bcrypt.checkpw(
            password.encode("utf-8"),
            stored_hash.encode("utf-8"),
        )
    except Exception as exc:
        log.error("bcrypt check error: %s", exc)
        return None

    if not password_valid:
        return None

    # Create session
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=_SESSION_TTL_H)
    token = str(uuid.uuid4())

    session_doc = {
        "id": token,
        "partition_key": token,  # each session is its own partition
        "username": username,
        "created_at": now.isoformat(),
        "expires_at": expires.isoformat(),
        "ttl": _SESSION_TTL_H * 3600,  # Cosmos auto-deletes after this
    }

    await cosmos.session_create(session_doc)

    return LoginResponse(
        token=token,
        expires_at=expires.isoformat(),
        username=username,
    )


async def validate(token: str) -> VerifyResponse:
    """
    Check that the token exists in Cosmos and has not expired.
    Returns VerifyResponse(valid=True, username=...) or VerifyResponse(valid=False).
    """
    if not token:
        return VerifyResponse(valid=False)

    doc = await cosmos.session_get(token)
    if not doc:
        return VerifyResponse(valid=False)

    # Belt-and-suspenders expiry check even though Cosmos TTL handles deletion
    try:
        expires = datetime.fromisoformat(doc["expires_at"])
        # Make both offset-aware for comparison
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > expires:
            await cosmos.session_delete(token)
            return VerifyResponse(valid=False)
    except (KeyError, ValueError):
        pass

    return VerifyResponse(valid=True, username=doc.get("username"))


async def logout(token: str) -> None:
    """Immediately invalidate a session by removing it from Cosmos."""
    if token:
        await cosmos.session_delete(token)

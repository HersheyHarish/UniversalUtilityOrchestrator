"""
secret_refs.py — helpers for local inline secret references.

In local emulator mode, secret values are encoded into an inline reference:
  inline:<urlsafe_base64_value>

This avoids hard dependency on Key Vault while keeping plaintext values out of
regular config fields during local development.
"""
from __future__ import annotations

import base64
import os

_INLINE_PREFIX = "inline:"


def is_local_mode() -> bool:
    return os.environ.get("USE_LOCAL_EMULATORS", "").lower() == "true"

def is_prod_env() -> bool:
    return os.environ.get("APP_ENV", "local").strip().lower() in {"prod", "production"}


def to_inline_secret_ref(value: str) -> str:
    encoded = base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")
    return f"{_INLINE_PREFIX}{encoded}"

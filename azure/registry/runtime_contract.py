"""
runtime_contract.py — runtime mode validation for registry service.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

PROD_ENV_NAMES = {"prod", "production"}


def _is_true(value: str | None) -> bool:
    return (value or "").strip().lower() == "true"


def validate_runtime_contract(env: Mapping[str, str] | None = None) -> list[str]:
    values = env if env is not None else os.environ

    app_env = (values.get("APP_ENV") or "local").strip().lower()
    is_prod = app_env in PROD_ENV_NAMES
    use_local = _is_true(values.get("USE_LOCAL_EMULATORS"))

    default_auth = "ANONYMOUS" if use_local else "FUNCTION"
    auth_level = (values.get("REGISTRY_HTTP_AUTH_LEVEL") or default_auth).strip().upper()

    strict_default = "true" if is_prod else "false"
    strict_mode = _is_true(values.get("REGISTRY_STRICT_MODE") or strict_default)

    errors: list[str] = []

    if is_prod and use_local:
        errors.append("APP_ENV=prod forbids USE_LOCAL_EMULATORS=true")

    if is_prod and auth_level == "ANONYMOUS":
        errors.append("APP_ENV=prod forbids REGISTRY_HTTP_AUTH_LEVEL=ANONYMOUS")

    if auth_level not in {"ANONYMOUS", "FUNCTION", "ADMIN"}:
        errors.append(f"Invalid REGISTRY_HTTP_AUTH_LEVEL '{auth_level}'")

    required = ["COSMOS_ENDPOINT"]
    if is_prod or strict_mode:
        required.extend(["KEY_VAULT_URL", "BUILD_VERSION", "BUILD_SHA"])

    missing = [name for name in required if not (values.get(name) or "").strip()]
    if missing:
        errors.append("Missing required settings: " + ", ".join(sorted(set(missing))))

    return errors

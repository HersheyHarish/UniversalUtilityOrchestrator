from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2] / "azure" / "registry"))

from runtime_contract import validate_runtime_contract


def test_registry_prod_rejects_local_mode() -> None:
    errors = validate_runtime_contract(
        {
            "APP_ENV": "production",
            "USE_LOCAL_EMULATORS": "true",
            "REGISTRY_HTTP_AUTH_LEVEL": "ANONYMOUS",
            "COSMOS_ENDPOINT": "https://example",
            "KEY_VAULT_URL": "https://kv",
            "BUILD_VERSION": "1.0.0",
            "BUILD_SHA": "abc123",
        }
    )

    assert any("forbids USE_LOCAL_EMULATORS=true" in e for e in errors)
    assert any("forbids REGISTRY_HTTP_AUTH_LEVEL=ANONYMOUS" in e for e in errors)

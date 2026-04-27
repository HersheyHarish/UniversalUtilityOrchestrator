from __future__ import annotations

from azure.orchestrator.runtime_contract import validate_runtime_contract


def test_prod_rejects_local_mode() -> None:
    errors = validate_runtime_contract(
        {
            "APP_ENV": "prod",
            "USE_LOCAL_EMULATORS": "true",
            "ORCHESTRATOR_HTTP_AUTH_LEVEL": "ANONYMOUS",
            "COSMOS_ENDPOINT": "https://example",
            "AZURE_OPENAI_ENDPOINT": "https://example",
            "KEY_VAULT_URL": "https://kv",
            "OPENAI_SECRET_NAME": "openai-key",
            "BUILD_VERSION": "1.0.0",
            "BUILD_SHA": "abc123",
        }
    )

    assert any("forbids USE_LOCAL_EMULATORS=true" in e for e in errors)
    assert any("forbids ORCHESTRATOR_HTTP_AUTH_LEVEL=ANONYMOUS" in e for e in errors)


def test_prod_requires_build_metadata() -> None:
    errors = validate_runtime_contract(
        {
            "APP_ENV": "prod",
            "USE_LOCAL_EMULATORS": "false",
            "ORCHESTRATOR_HTTP_AUTH_LEVEL": "FUNCTION",
            "COSMOS_ENDPOINT": "https://example",
            "AZURE_OPENAI_ENDPOINT": "https://example",
            "KEY_VAULT_URL": "https://kv",
            "OPENAI_SECRET_NAME": "openai-key",
        }
    )

    assert any("BUILD_VERSION" in e for e in errors)
    assert any("BUILD_SHA" in e for e in errors)

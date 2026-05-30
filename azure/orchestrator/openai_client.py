"""
Shared Azure OpenAI / OpenAI-compatible client factory.

Supports:
  - Classic Azure OpenAI (resource.openai.azure.com)
  - Azure AI Foundry project URLs (.../openai/v1 or .../openai/v1/responses)
"""

from __future__ import annotations

import logging
import os
from typing import Any

from openai import AsyncAzureOpenAI, AsyncOpenAI

from secret_provider import get_secret

log = logging.getLogger(__name__)

_OAI_ENDPOINT_RAW = (os.environ.get("AZURE_OPENAI_ENDPOINT") or "").strip()
_OAI_DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
_OAI_PLANNER_DEPLOYMENT = os.environ.get("AZURE_OPENAI_PLANNER_DEPLOYMENT") or _OAI_DEPLOYMENT
_OAI_API_VER = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21")
_OPENAI_SECRET = os.environ.get("OPENAI_SECRET_NAME", "openai-api-key")

_clients: dict[str, Any] = {}


def _foundry_chat_base_url(raw: str) -> str | None:
    """
  Normalize Foundry / project OpenAI-compatible base URL for chat.completions.

  Examples:
    .../openai/v1/responses  -> .../openai/v1
    .../openai/v1/           -> .../openai/v1
    """
    url = raw.strip().rstrip("/")
    if "/openai/v1" not in url:
        return None
    idx = url.index("/openai/v1")
    return url[: idx + len("/openai/v1")]


def _classic_azure_host(raw: str) -> str:
    """Host for AsyncAzureOpenAI (classic Azure OpenAI resource)."""
    return raw.split("/openai")[0].split("/api/")[0].rstrip("/")


_FOUNDRY_BASE = _foundry_chat_base_url(_OAI_ENDPOINT_RAW) if _OAI_ENDPOINT_RAW else None
_AZURE_HOST = _classic_azure_host(_OAI_ENDPOINT_RAW) if _OAI_ENDPOINT_RAW and not _FOUNDRY_BASE else ""


async def _api_key() -> str:
    return await get_secret(_OPENAI_SECRET, local_env_fallback="AZURE_OPENAI_API_KEY")


def is_foundry_endpoint() -> bool:
    return _FOUNDRY_BASE is not None


async def get_chat_client(role: str = "default") -> AsyncAzureOpenAI | AsyncOpenAI:
    """Return a cached async client. role: default | planner | synthesizer."""
    if role in _clients:
        return _clients[role]

    api_key = await _api_key()
    if _FOUNDRY_BASE:
        log.info("OpenAI client: Foundry base_url=%s", _FOUNDRY_BASE)
        client: Any = AsyncOpenAI(api_key=api_key, base_url=_FOUNDRY_BASE)
    else:
        host = _AZURE_HOST or _OAI_ENDPOINT_RAW
        log.info("OpenAI client: Azure host=%s", host)
        client = AsyncAzureOpenAI(
            azure_endpoint=host,
            api_key=api_key,
            api_version=_OAI_API_VER,
        )
    _clients[role] = client
    return client


def deployment_for_role(role: str = "default") -> str:
    if role == "planner":
        return _OAI_PLANNER_DEPLOYMENT
    return _OAI_DEPLOYMENT


def model_name_for_role(role: str = "default") -> str:
    """Model/deployment id passed to chat.completions.create."""
    return deployment_for_role(role)

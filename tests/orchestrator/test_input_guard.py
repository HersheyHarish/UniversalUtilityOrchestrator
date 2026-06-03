import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ORCH = Path(__file__).resolve().parents[2] / "azure" / "orchestrator"
sys.path.insert(0, str(ORCH))

from input_guard import is_query_related_to_scenario  # noqa: E402


@pytest.mark.asyncio
async def test_is_query_related_to_scenario_related():
    mock_choice = MagicMock()
    mock_choice.message.content = "RELATED"

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    mock_client = AsyncMock()
    mock_client.chat.completions.create.return_value = mock_response

    with patch("openai_client.get_chat_client", return_value=mock_client), \
         patch("openai_client.model_name_for_role", return_value="gpt-4o-mini"):
        result = await is_query_related_to_scenario("explain my bill")
        assert result is True


@pytest.mark.asyncio
async def test_is_query_related_to_scenario_unrelated():
    mock_choice = MagicMock()
    mock_choice.message.content = "UNRELATED"

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    mock_client = AsyncMock()
    mock_client.chat.completions.create.return_value = mock_response

    with patch("openai_client.get_chat_client", return_value=mock_client), \
         patch("openai_client.model_name_for_role", return_value="gpt-4o-mini"):
        result = await is_query_related_to_scenario("skincare routine")
        assert result is False


@pytest.mark.asyncio
async def test_is_query_related_to_scenario_failure_fallback():
    # Test that if OpenAI throws an exception, it fails safe to True
    mock_client = AsyncMock()
    mock_client.chat.completions.create.side_effect = Exception("API error")

    with patch("openai_client.get_chat_client", return_value=mock_client):
        result = await is_query_related_to_scenario("anything")
        assert result is True

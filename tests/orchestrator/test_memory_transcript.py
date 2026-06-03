import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

ORCH = Path(__file__).resolve().parents[2] / "azure" / "orchestrator"
sys.path.insert(0, str(ORCH))

from memory import MessageType, get_session_transcript  # noqa: E402


@pytest.mark.asyncio
async def test_transcript_maps_roles_and_truncates_turns():
    rows = [
        {"type": MessageType.USER_INPUT, "content": "hello", "created_at": "t1"},
        {"type": MessageType.FINAL, "content": "hi there", "created_at": "t2"},
        {"type": MessageType.USER_INPUT, "content": "follow up", "created_at": "t3"},
    ]

    with patch("memory._query", new_callable=AsyncMock) as mock_query:
        mock_query.return_value = rows
        transcript = await get_session_transcript("sess-1", max_turns=2, max_chars_per_turn=100)

    assert len(transcript) == 2
    assert transcript[0]["role"] == "assistant"
    assert transcript[0]["content"] == "hi there"
    assert transcript[-1]["role"] == "user"
    assert transcript[-1]["content"] == "follow up"


@pytest.mark.asyncio
async def test_exclude_current_user():
    rows = [
        {"type": MessageType.USER_INPUT, "content": "new question", "created_at": "t3"},
    ]
    with patch("memory._query", new_callable=AsyncMock) as mock_query:
        mock_query.return_value = rows
        transcript = await get_session_transcript("sess-1", exclude_current_user=True)

    assert transcript == []

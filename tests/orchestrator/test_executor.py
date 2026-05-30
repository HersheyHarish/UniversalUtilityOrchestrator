import sys
from pathlib import Path

import httpx
import pytest
import respx

ORCH = Path(__file__).resolve().parents[2] / "azure" / "orchestrator"
sys.path.insert(0, str(ORCH))

from executor import _build_body, _call_agent, _extract_result  # noqa: E402


class MockStep:
    def __init__(
        self, step_id, agent_name, agent_url, task, invocation_config=None, auth_config=None, api_key_secret_name=None
    ):
        self.step_id = step_id
        self.agent_name = agent_name
        self.agent_url = agent_url
        self.task = task
        self.invocation_config = invocation_config or {}
        self.auth_config = auth_config or {}
        self.api_key_secret_name = api_key_secret_name
        self.context_note = ""


@pytest.mark.asyncio
async def test_build_body_legacy():
    body = await _build_body({}, "test_task", "sess_1", "cust_1", {1: "out_1"}, "note")
    assert body["task"] == "test_task"
    assert body["session_id"] == "sess_1"
    assert body["customer_id"] == "cust_1"
    assert body["context"]["step_1_output"] == "out_1"
    assert body["context"]["planner_note"] == "note"
    assert body["conversation_history"] == []


@pytest.mark.asyncio
<<<<<<< HEAD
async def test_build_body_includes_conversation_history():
    transcript = [{"role": "user", "content": "prior"}]
    body = await _build_body(
        {}, "test_task", "sess_1", "cust_1", {}, "", transcript=transcript
    )
    assert body["conversation_history"] == transcript


@pytest.mark.asyncio
=======
>>>>>>> 5efa666 (feat(orchestrator): v1.2 streaming, parallel execution, and Foundry OpenAI fix)
async def test_build_body_template():
    inv_config = {"body_template": {"query": "{task}", "user": "{customer_id}", "previous": "{step_1}"}}
    body = await _build_body(inv_config, "my_task", "sess_1", "cust_1", {1: "out_1"}, "")
    assert body == {"query": "my_task", "user": "cust_1", "previous": "out_1"}


def test_extract_result():
    resp = {"data": {"nested": {"value": "hello"}}}
    assert _extract_result(resp, "data.nested.value") == "hello"

    resp_default = {"result": "world"}
    assert _extract_result(resp_default, "") == "world"

    assert _extract_result(resp_default, "invalid.path") == '{"result": "world"}'


@pytest.mark.asyncio
@respx.mock
async def test_call_agent_success():
    step = MockStep(1, "TestAgent", "https://test.com/api", "Do it")

    class MockInjectedAuth:
        def apply_to_kwargs(self, kwargs):
            kwargs["headers"]["Authorization"] = "Bearer token"
            return kwargs

    respx.post("https://test.com/api").mock(
        return_value=httpx.Response(200, json={"result": "Agent output", "actions_taken": ["act1"]})
    )

    from unittest.mock import patch

    async with httpx.AsyncClient() as client:
        with patch("auth_injector.resolve", return_value=MockInjectedAuth()):
            result = await _call_agent(step, "sess_1", "cust_1", {}, client)

    assert result["result"] == "Agent output"
    assert result["actions_taken"] == ["act1"]


@pytest.mark.asyncio
@respx.mock
async def test_call_agent_http_error():
    step = MockStep(1, "TestAgent", "https://test.com/api", "Do it", {"max_retries": 0})

    respx.post("https://test.com/api").mock(return_value=httpx.Response(500, json={"error": "Server error"}))

    class MockInjectedAuth:
        def apply_to_kwargs(self, kwargs):
            return kwargs

    from unittest.mock import patch

    async with httpx.AsyncClient() as client:
        with patch("auth_injector.resolve", return_value=MockInjectedAuth()):
            with pytest.raises(RuntimeError, match="TestAgent failed"):
                await _call_agent(step, "sess_1", "cust_1", {}, client)

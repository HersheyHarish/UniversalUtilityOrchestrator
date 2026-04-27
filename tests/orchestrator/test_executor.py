import pytest
import respx
import httpx
from executor import _build_body, _extract_result, _call_agent

class MockStep:
    def __init__(self, step_id, agent_name, agent_url, task, invocation_config=None, auth_config=None, api_key_secret_name=None):
        self.step_id = step_id
        self.agent_name = agent_name
        self.agent_url = agent_url
        self.task = task
        self.invocation_config = invocation_config or {}
        self.auth_config = auth_config or {}
        self.api_key_secret_name = api_key_secret_name
        self.context_note = ""

def test_build_body_legacy():
    body = _build_body({}, "test_task", "sess_1", "cust_1", {1: "out_1"}, "note")
    assert body["task"] == "test_task"
    assert body["session_id"] == "sess_1"
    assert body["customer_id"] == "cust_1"
    assert body["context"]["step_1_output"] == "out_1"
    assert body["context"]["planner_note"] == "note"

def test_build_body_template():
    inv_config = {
        "body_template": {
            "query": "{task}",
            "user": "{customer_id}",
            "previous": "{step_1}"
        }
    }
    body = _build_body(inv_config, "my_task", "sess_1", "cust_1", {1: "out_1"}, "")
    assert body == {
        "query": "my_task",
        "user": "cust_1",
        "previous": "out_1"
    }

def test_extract_result():
    resp = {"data": {"nested": {"value": "hello"}}}
    assert _extract_result(resp, "data.nested.value") == "hello"
    
    # Fallback to default
    resp_default = {"result": "world"}
    assert _extract_result(resp_default, "") == "world"
    
    # Invalid path fallback
    assert _extract_result(resp_default, "invalid.path") == '{"result": "world"}'

@pytest.mark.asyncio
@respx.mock
async def test_call_agent_success():
    step = MockStep(1, "TestAgent", "https://test.com/api", "Do it")
    
    # Mock auth resolution
    import sys
    
    # Mock the auth_injector which _call_agent uses
    class MockInjectedAuth:
        def apply_to_kwargs(self, kwargs):
            kwargs["headers"]["Authorization"] = "Bearer token"
            return kwargs
            
    # respx mock
    respx.post("https://test.com/api").mock(
        return_value=httpx.Response(200, json={"result": "Agent output", "actions_taken": ["act1"]})
    )
    
    # We must patch auth_injector.resolve since it interacts with Key Vault
    from unittest.mock import patch
    with patch('auth_injector.resolve', return_value=MockInjectedAuth()):
        result = await _call_agent(step, "sess_1", "cust_1", {})
        
    assert result["result"] == "Agent output"
    assert result["actions_taken"] == ["act1"]

@pytest.mark.asyncio
@respx.mock
async def test_call_agent_http_error():
    step = MockStep(1, "TestAgent", "https://test.com/api", "Do it", {"max_retries": 0})
    
    respx.post("https://test.com/api").mock(
        return_value=httpx.Response(500, json={"error": "Server error"})
    )
    
    class MockInjectedAuth:
        def apply_to_kwargs(self, kwargs): return kwargs
        
    from unittest.mock import patch
    with patch('auth_injector.resolve', return_value=MockInjectedAuth()):
        with pytest.raises(RuntimeError, match="TestAgent failed"):
            await _call_agent(step, "sess_1", "cust_1", {})

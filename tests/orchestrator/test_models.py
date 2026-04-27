import pytest
from pydantic import ValidationError
from models import PlanStep, ExecutionPlan, AgentRequest, AgentResponse

def test_plan_step_valid():
    step = PlanStep(
        step_id=1,
        agent_name="TestAgent",
        agent_url="https://test.com/api",
        task="Do something",
        depends_on=[0]
    )
    assert step.step_id == 1
    assert step.agent_name == "TestAgent"
    assert step.task == "Do something"
    assert step.depends_on == [0]

def test_plan_step_missing_required():
    with pytest.raises(ValidationError):
        PlanStep(step_id=1, agent_name="TestAgent", agent_url="https://test.com/api") # missing task

def test_execution_plan_valid():
    step = PlanStep(step_id=1, agent_name="Agent1", agent_url="http://agent1", task="Task 1")
    plan = ExecutionPlan(
        user_intent="Test intent",
        steps=[step],
        synthesis_instruction="Combine results."
    )
    assert plan.user_intent == "Test intent"
    assert len(plan.steps) == 1
    assert plan.plan_id is not None
    assert plan.created_at is not None

def test_agent_request_valid():
    req = AgentRequest(
        task="Test task",
        session_id="12345",
        context={"key": "value"},
    )
    assert req.task == "Test task"
    assert req.session_id == "12345"
    assert req.context == {"key": "value"}

def test_agent_response_valid():
    resp = AgentResponse(
        agent_name="Agent1",
        result="Success!"
    )
    assert resp.agent_name == "Agent1"
    assert resp.result == "Success!"
    assert resp.actions_taken == []

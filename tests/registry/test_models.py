import pytest
from pydantic import ValidationError
from models import AgentDoc, Capability, AuthConfig, HealthCheckConfig, InvocationConfig

def test_agent_doc_valid():
    doc = AgentDoc(
        name="BillingAgent",
        description="Handles billing",
        endpoint_url="https://billing.local",
    )
    assert doc.name == "BillingAgent"
    assert doc.endpoint_url == "https://billing.local"
    assert doc.status == "active"
    assert doc.auth_config is not None
    assert doc.health_check_config is not None
    assert doc.invocation_config is not None

def test_agent_doc_invalid_url():
    with pytest.raises(ValidationError, match="endpoint_url must start with"):
        AgentDoc(
            name="BillingAgent",
            description="Handles billing",
            endpoint_url="ftp://billing.local", # Invalid
        )

def test_agent_doc_empty_name():
    with pytest.raises(ValidationError, match="name must not be empty"):
        AgentDoc(
            name="   ", # Invalid
            description="Handles billing",
            endpoint_url="https://billing.local",
        )

def test_capability_schema():
    cap = Capability(
        name="get_balance",
        description="Gets balance",
        input_schema={"type": "object"},
        output_schema={"type": "number"}
    )
    assert cap.name == "get_balance"
    assert cap.input_schema == {"type": "object"}

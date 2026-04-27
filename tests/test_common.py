# File: tests/test_common.py
# Purpose: Unit tests for common enums and helpers.

from pathlib import Path
import pytest
from aegis.schemas import AgentID, TierName, stream_name, tenant_path

def test_agent_id_enum_contains_all_agents():
    """Verify AgentID has all 7 council agents + observer."""
    expected_agents = {
        "ORCHESTRATOR", "FORGE", "ORACLE", "WARDEN",
        "LEXICON", "JANUS", "IDENTITY", "OBSERVER"
    }
    assert set(AgentID.__members__.keys()) == expected_agents

@pytest.mark.parametrize("agent_id, expected_stream", [
    (AgentID.WARDEN, "aegis:stream:warden"),
    (AgentID.ORCHESTRATOR, "aegis:stream:t_orchestrator"),
    ("forge", "aegis:stream:forge"), # Also test with raw string
])
def test_stream_name_helper(agent_id, expected_stream):
    """Test the stream name generation helper function."""
    assert stream_name(agent_id) == expected_stream

def test_tier_name_enum_has_correct_values():
    """Verify TierName values match the spec."""
    assert TierName.L0.value == "l0_identity.yaml"
    assert TierName.L1.value == "l1_context"

def test_tenant_path_helper():
    """Test the tenant path generation helper."""
    base_dir = "/tmp/aegis_test"
    tenant = "tenant-xyz"
    user = "user-789"

    expected = Path(f"{base_dir}/{tenant}/{user}")

    assert tenant_path(base_dir, tenant, user) == expected
    assert tenant_path(Path(base_dir), tenant, user) == expected

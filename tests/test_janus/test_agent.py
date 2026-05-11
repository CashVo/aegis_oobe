# tests/test_janus/test_agent.py
"""
Unit tests for the Janus Agent — integration of engine + storage + protocol.
"""

import pytest
import asyncio
from pathlib import Path

from aegis.agents.janus.agent import JanusAgent
from aegis.schemas.message import AegisMessage, MessageType, Priority


@pytest.fixture
def agent(tmp_path):
    """Create a JanusAgent with temporary storage."""
    a = JanusAgent(data_dir=tmp_path)
    asyncio.get_event_loop().run_until_complete(a.startup())
    yield a
    asyncio.get_event_loop().run_until_complete(a.shutdown())


def _make_message(action: str, payload: dict, tenant_id: str = "test-tenant") -> AegisMessage:
    """Helper to construct test messages."""
    return AegisMessage(
        source_agent="warden",
        target_agent="janus",
        message_type=MessageType.REQUEST,
        tenant_id=tenant_id,
        user_id="test-user",
        action=action,
        payload=payload,
    )


class TestJanusAgentStartup:
    """Test agent initialization and default policy seeding."""

    def test_startup_seeds_defaults(self, agent):
        """On first startup with empty store, default policies should be seeded."""
        assert agent._initialized is True
        assert agent._store.count_policies() > 0

    def test_default_policies_present(self, agent):
        """Verify specific default policies exist."""
        policy = agent._store.get_policy("SYS-SEC-001")
        assert policy is not None
        assert policy.name == "Shell Command Allowlist Enforcement"

        policy_ac = agent._store.get_policy("SYS-AC-001")
        assert policy_ac is not None
        assert policy_ac.name == "Deny Cross-Tenant Access"


class TestJanusEvaluatePolicy:
    """Test policy evaluation through the agent."""

    @pytest.mark.asyncio
    async def test_evaluate_deny_cross_tenant(self, agent):
        """SYS-AC-001 should deny cross-tenant access."""
        msg = _make_message(
            action="janus.evaluate_policy",
            payload={
                "context": {
                    "cross_tenant": "true",
                    "action": "lexicon.search_memory",
                    "resource": "memory",
                },
            },
        )
        response = await agent.handle_message(msg)
        assert response is not None
        assert response.payload["success"] is True
        assert response.payload["verdict"] == "deny"
        assert "SYS-AC-001" in response.payload["matched_policies"]

    @pytest.mark.asyncio
    async def test_evaluate_no_match_allows(self, agent):
        """When no policies match, verdict should be 'allow'."""
        msg = _make_message(
            action="janus.evaluate_policy",
            payload={
                "context": {
                    "action": "oracle.query",
                    "resource": "llm",
                    "role": "member",
                },
            },
        )
        response = await agent.handle_message(msg)
        assert response is not None
        assert response.payload["verdict"] == "allow"

    @pytest.mark.asyncio
    async def test_evaluate_shell_escalate(self, agent):
        """SYS-SEC-001 should escalate shell command execution."""
        msg = _make_message(
            action="janus.evaluate_policy",
            payload={
                "context": {
                    "action": "forge.execute_tool",
                    "resource": "tool:execute_shell_command",
                    "role": "member",
                },
            },
        )
        response = await agent.handle_message(msg)
        assert response is not None
        # SYS-SEC-001 triggers escalate for shell commands
        assert response.payload["verdict"] in ("escalate", "deny")

    @pytest.mark.asyncio
    async def test_evaluate_l0_protection(self, agent):
        """SYS-MEM-001 should deny agent-initiated L0 writes."""
        msg = _make_message(
            action="janus.evaluate_policy",
            payload={
                "context": {
                    "action": "lexicon.store_memory",
                    "target_tier": "L0",
                    "user_initiated": "false",
                },
            },
        )
        response = await agent.handle_message(msg)
        assert response is not None
        assert response.payload["verdict"] == "deny"
        assert "SYS-MEM-001" in response.payload["matched_policies"]


class TestJanusCRUDActions:
    """Test CRUD operations through the agent message protocol."""

    @pytest.mark.asyncio
    async def test_add_policy(self, agent):
        """Add a custom policy via agent message."""
        msg = _make_message(
            action="janus.add_policy",
            payload={
                "payload": {
                    "rule_id": "CUSTOM-001",
                    "name": "Custom Rule",
                    "description": "Test custom policy",
                    "condition": 'action == "custom.action"',
                    "action_on_match": "warn",
                    "priority": 300,
                    "tags": ["custom"],
                },
            },
        )
        response = await agent.handle_message(msg)
        assert response.payload["success"] is True
        assert response.payload["data"]["rule_id"] == "CUSTOM-001"

    @pytest.mark.asyncio
    async def test_list_policies(self, agent):
        """List policies via agent message."""
        msg = _make_message(
            action="janus.list_policies",
            payload={"payload": {"active_only": True}},
        )
        response = await agent.handle_message(msg)
        assert response.payload["success"] is True
        assert response.payload["data"]["count"] > 0

    @pytest.mark.asyncio
    async def test_get_policy(self, agent):
        """Get a single policy via agent message."""
        msg = _make_message(
            action="janus.get_policy",
            payload={"payload": {"rule_id": "SYS-SEC-001"}},
        )
        response = await agent.handle_message(msg)
        assert response.payload["success"] is True
        assert response.payload["data"]["policy"]["name"] == "Shell Command Allowlist Enforcement"

    @pytest.mark.asyncio
    async def test_delete_policy(self, agent):
        """Delete a policy via agent message."""
        # First add one
        add_msg = _make_message(
            action="janus.add_policy",
            payload={
                "payload": {
                    "rule_id": "TO-DELETE",
                    "name": "Delete Me",
                    "description": "",
                    "condition": 'x == "y"',
                    "action_on_match": "log",
                },
            },
        )
        await agent.handle_message(add_msg)

        # Now delete it
        del_msg = _make_message(
            action="janus.delete_policy",
            payload={"payload": {"rule_id": "TO-DELETE"}},
        )
        response = await agent.handle_message(del_msg)
        assert response.payload["success"] is True
        assert response.payload["data"]["deleted"] is True


class TestJanusErrorHandling:
    """Test error conditions."""

    @pytest.mark.asyncio
    async def test_invalid_action(self, agent):
        """Invalid action should return error."""
        msg = _make_message(
            action="janus.nonexistent_action",
            payload={},
        )
        response = await agent.handle_message(msg)
        assert response.message_type == MessageType.ERROR

    @pytest.mark.asyncio
    async def test_add_duplicate_fails(self, agent):
        """Adding a policy with existing ID should fail gracefully."""
        policy_payload = {
            "payload": {
                "rule_id": "DUP-001",
                "name": "Duplicate",
                "description": "",
                "condition": 'a == "b"',
                "action_on_match": "log",
            },
        }
        msg = _make_message(action="janus.add_policy", payload=policy_payload)
        await agent.handle_message(msg)

        # Try again
        response = await agent.handle_message(msg)
        assert response.payload["success"] is False
        assert "already exists" in response.payload["error"]

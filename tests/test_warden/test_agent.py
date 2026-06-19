# tests/test_warden/test_agent.py
"""
Unit tests for the Warden Agent.
Tests: Agent initialization, message handling, startup/shutdown.
"""

import pytest
from aegis.agents.warden import WardenAgent
from aegis.schemas.message import AegisMessage, MessageType
from aegis.schemas.warden import WardenVerdict
from aegis.warden.permission_model import PermissionModel

def make_warden_message(action: str, payload: dict = None) -> AegisMessage:
    """Helper to create messages targeting the Warden."""
    return AegisMessage(
        source_agent="torchestrator",
        target_agent="warden",
        message_type=MessageType.REQUEST,
        tenant_id="test-tenant",
        user_id="test-user",
        action=f"warden.{action}",
        payload=payload or {},
    )


@pytest.fixture
def agent():
    """Create a WardenAgent with test configuration."""
    # Create an instance of the real permission model
    perm_model = PermissionModel()

    def resolver(tenant_id, user_id):
        # Dynamically get permissions from the model, not hardcoded values
        if user_id == "root-user":
            return perm_model.get_role_permissions("root")
        elif user_id == "member-user":
            return perm_model.get_role_permissions("member")
        return set()

    return WardenAgent(
        config={"bypass": {"max_ttl_seconds": 60}},
        user_permission_resolver=resolver,
    )


class TestAgentInit:
    """Test agent initialization."""

    def test_agent_id(self, agent):
        assert agent.agent_id == "warden"

    def test_subscriptions(self, agent):
        assert "aegis:stream:warden" in agent.subscriptions

    def test_subsystems_initialized(self, agent):
        assert agent.permission_model is not None
        assert agent.allowlist_engine is not None
        assert agent.bypass_manager is not None
        assert agent.interceptor is not None


class TestSynchronousAuthorize:
    """Test the synchronous authorize() method."""

    def test_authorize_root(self, agent):
        msg = AegisMessage(
            source_agent="forge",
            target_agent="oracle",
            message_type=MessageType.REQUEST,
            tenant_id="t1",
            user_id="root-user",
            action="oracle.query",
            payload={},
        )
        response = agent.authorize(msg)
        assert response.verdict == WardenVerdict.ALLOW

    def test_authorize_member_tool(self, agent):
        msg = AegisMessage(
            source_agent="torchestrator",
            target_agent="forge",
            message_type=MessageType.REQUEST,
            tenant_id="t1",
            user_id="member-user",
            action="forge.execute_tool",
            payload={"tool_or_skill_name": "file_read"},
        )
        response = agent.authorize(msg)
        assert response.verdict == WardenVerdict.ALLOW


class TestMessageHandling:
    """Test async message handling."""

    @pytest.mark.asyncio
    async def test_handle_get_status(self, agent):
        msg = make_warden_message("get_status")
        response = await agent.handle_message(msg)
        assert response is not None
        assert response.message_type == MessageType.RESPONSE
        assert response.payload["verdict"] == "allow"

    @pytest.mark.asyncio
    async def test_handle_check_permission(self, agent):
        msg = make_warden_message(
            "check_permission",
            payload={
                "user_permissions": ["tool.execute", "file.read"],
                "required_permission": "tool.execute",
            },
        )
        response = await agent.handle_message(msg)
        assert response.payload["verdict"] == "allow"

    @pytest.mark.asyncio
    async def test_handle_enable_bypass_non_root(self, agent):
        msg = make_warden_message(
            "enable_bypass",
            payload={"is_root": False, "reason": "test"},
        )
        response = await agent.handle_message(msg)
        assert response.payload["verdict"] == "deny"

    @pytest.mark.asyncio
    async def test_handle_enable_bypass_root(self, agent):
        msg = AegisMessage(
            source_agent="torchestrator",
            target_agent="warden",
            message_type=MessageType.REQUEST,
            tenant_id="test-tenant",
            user_id="root-user",
            action="warden.enable_bypass",
            payload={"is_root": True, "reason": "emergency"},
        )
        response = await agent.handle_message(msg)
        assert response.payload["verdict"] == "allow"
        assert agent.bypass_manager.is_active is True

    @pytest.mark.asyncio
    async def test_handle_unknown_action(self, agent):
        msg = make_warden_message("nonexistent_action")
        response = await agent.handle_message(msg)
        assert response.payload["verdict"] == "deny"


class TestLifecycle:
    """Test agent startup and shutdown."""

    @pytest.mark.asyncio
    async def test_startup(self, agent):
        await agent.startup()
        # Should not raise

    @pytest.mark.asyncio
    async def test_shutdown_deactivates_bypass(self, agent):
        agent.bypass_manager.activate(user_id="root", is_root=True)
        assert agent.bypass_manager.is_active is True
        await agent.shutdown()
        assert agent.bypass_manager.is_active is False

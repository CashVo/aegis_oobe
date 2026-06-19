# tests/test_forge/test_agent.py
# Unit tests for the Forge Agent
"""
Tests for aegis.forge.agent — ForgeAgent message handling.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from aegis.schemas.message import AegisMessage, MessageType, Priority
from aegis.schemas.forge import ForgeAction, ForgeRequest, ForgeResponse
from aegis.forge.agent import ForgeAgent


@pytest.fixture
def forge_agent():
    """Create a ForgeAgent instance with mocked bus."""
    bus = MagicMock()
    bus.subscribe = AsyncMock()
    bus.unsubscribe = AsyncMock()
    agent = ForgeAgent(bus=bus)
    return agent


@pytest.fixture
def sample_message():
    """Create a sample AegisMessage targeting forge."""
    return AegisMessage(
        message_id=str(uuid4()),
        correlation_id=str(uuid4()),
        source_agent="torchestrator",
        target_agent="forge",
        message_type=MessageType.REQUEST,
        tenant_id="test-tenant",
        user_id="test-user",
        action="forge.execute_tool",
        payload={
            "action": "execute_tool",
            "tool_or_skill_name": "json_parse",
            "parameters": {"data": "{\"key\": \"value\"}"},
        },
        priority=Priority.NORMAL,
        metadata={"session_id": "test-session"},
    )


class TestForgeAgent:
    """Tests for ForgeAgent."""

    @pytest.mark.asyncio
    async def test_startup(self, forge_agent):
        await forge_agent.startup()
        assert forge_agent._running is True
        # Should have discovered tools and skills
        assert forge_agent.tool_registry.tool_count > 0

    @pytest.mark.asyncio
    async def test_shutdown(self, forge_agent):
        await forge_agent.startup()
        await forge_agent.shutdown()
        assert forge_agent._running is False

    @pytest.mark.asyncio
    async def test_handle_execute_tool(self, forge_agent, sample_message):
        await forge_agent.startup()
        response = await forge_agent.handle_message(sample_message)
        assert response is not None
        assert response.message_type == MessageType.RESPONSE
        payload = response.payload
        assert payload["success"] is True
        assert payload["action"] == ForgeAction.EXECUTE_TOOL

    @pytest.mark.asyncio
    async def test_handle_list_tools(self, forge_agent):
        await forge_agent.startup()
        msg = AegisMessage(
            source_agent="torchestrator",
            target_agent="forge",
            message_type=MessageType.REQUEST,
            tenant_id="test-tenant",
            user_id="test-user",
            action="forge.list_tools",
            payload={"action": "list_tools"},
        )
        response = await forge_agent.handle_message(msg)
        assert response is not None
        payload = response.payload
        assert payload["success"] is True
        assert isinstance(payload["result"], list)
        assert len(payload["result"]) > 0

    @pytest.mark.asyncio
    async def test_handle_nonexistent_tool(self, forge_agent):
        await forge_agent.startup()
        msg = AegisMessage(
            source_agent="torchestrator",
            target_agent="forge",
            message_type=MessageType.REQUEST,
            tenant_id="test-tenant",
            user_id="test-user",
            action="forge.execute_tool",
            payload={
                "action": "execute_tool",
                "tool_or_skill_name": "nonexistent_tool",
                "parameters": {},
            },
        )
        response = await forge_agent.handle_message(msg)
        payload = response.payload
        assert payload["success"] is False
        assert "not found" in payload["error"].lower()

    @pytest.mark.asyncio
    async def test_handle_invalid_payload(self, forge_agent):
        await forge_agent.startup()
        msg = AegisMessage(
            source_agent="torchestrator",
            target_agent="forge",
            message_type=MessageType.REQUEST,
            tenant_id="test-tenant",
            user_id="test-user",
            action="forge.execute_tool",
            payload={"invalid": "data"},
        )
        response = await forge_agent.handle_message(msg)
        payload = response.payload
        assert payload["success"] is False

    @pytest.mark.asyncio
    async def test_handle_list_skills(self, forge_agent):
        await forge_agent.startup()
        msg = AegisMessage(
            source_agent="torchestrator",
            target_agent="forge",
            message_type=MessageType.REQUEST,
            tenant_id="test-tenant",
            user_id="test-user",
            action="forge.list_skills",
            payload={"action": "list_skills"},
        )
        response = await forge_agent.handle_message(msg)
        payload = response.payload
        assert payload["success"] is True
        assert isinstance(payload["result"], list)

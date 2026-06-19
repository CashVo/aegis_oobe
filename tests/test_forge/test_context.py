# tests/test_forge/test_context.py
# Unit tests for ForgeContext
"""
Tests for aegis.forge.context — ForgeContext tool/oracle invocation.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock
from types import ModuleType

from aegis.forge.context import ForgeContext
from aegis.forge.registry import ToolRegistry
from aegis.forge.tools.base import ToolManifest, ToolResult


@pytest.fixture
def mock_tool_registry():
    """Create a registry with a mock tool."""
    registry = ToolRegistry()
    mod = ModuleType("aegis.forge.tools.mock")
    mod.manifest = ToolManifest(
        name="mock_tool",
        description="A mock tool",
        version="1.0.0",
    )
    mod.execute = AsyncMock(return_value=ToolResult(success=True, data={"result": "ok"}))
    registry.register(mod)
    return registry


@pytest.fixture
def forge_context(mock_tool_registry):
    """Create a ForgeContext with mocked dependencies."""
    return ForgeContext(
        tenant_id="test-tenant",
        user_id="test-user",
        session_id="test-session",
        tool_registry=mock_tool_registry,
        bus_publisher=None,
        correlation_id="test-correlation",
    )


class TestForgeContext:
    """Tests for ForgeContext."""

    @pytest.mark.asyncio
    async def test_invoke_tool_success(self, forge_context):
        result = await forge_context.invoke_tool("mock_tool", {"key": "value"})
        assert result.success is True
        assert result.data == {"result": "ok"}
        assert "tool:mock_tool" in forge_context.steps_executed

    @pytest.mark.asyncio
    async def test_invoke_tool_not_found(self, forge_context):
        result = await forge_context.invoke_tool("nonexistent", {})
        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_invoke_oracle_no_bus(self, forge_context):
        result = await forge_context.invoke_oracle({"action": "query", "prompt": "test"})
        assert result["success"] is False
        assert "not available" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_get_context_no_bus(self, forge_context):
        result = await forge_context.get_context("test query")
        assert "error" in result
        assert "not available" in result["error"].lower()

    def test_steps_tracking(self, forge_context):
        assert forge_context.steps_executed == []

    @pytest.mark.asyncio
    async def test_invoke_tool_no_registry(self):
        ctx = ForgeContext(
            tenant_id="t",
            user_id="u",
            session_id="s",
            tool_registry=None,
        )
        result = await ctx.invoke_tool("any_tool", {})
        assert result.success is False
        assert "not available" in result.error.lower()

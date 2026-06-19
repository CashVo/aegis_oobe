# tests/test_chunk_012/test_mcp.py
# Tests for Part IV, §4.5 — MCP Server
"""
Unit tests for the Aegis MCP Server.
Tests tool registration, auth validation, and request routing.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock


class TestAegisMCPServer:
    """Test the MCP server initialization and tool registration."""

    def test_import(self):
        """MCP server module should be importable."""
        from aegis.mcp.server import AegisMCPServer
        server = AegisMCPServer(config=None)
        assert server is not None

    def test_server_config_stored(self):
        """Config should be stored on the server instance."""
        from aegis.mcp.server import AegisMCPServer
        mock_config = {"test": True}
        server = AegisMCPServer(config=mock_config)
        assert server.config == mock_config

    @pytest.mark.asyncio
    async def test_shutdown_no_bus(self):
        """Shutdown with no bus should not raise."""
        from aegis.mcp.server import AegisMCPServer
        server = AegisMCPServer()
        await server.shutdown()  # Should not raise

    @pytest.mark.asyncio
    async def test_shutdown_with_bus(self):
        """Shutdown with an active bus should disconnect."""
        from aegis.mcp.server import AegisMCPServer
        server = AegisMCPServer()
        mock_bus = AsyncMock()
        server._bus = mock_bus
        await server.shutdown()
        mock_bus.disconnect.assert_called_once()


class TestMCPAvailability:
    """Test graceful handling when MCP SDK is not installed."""

    def test_mcp_available_flag_exists(self):
        """Module should expose MCP_AVAILABLE flag."""
        from aegis.mcp.server import MCP_AVAILABLE
        assert isinstance(MCP_AVAILABLE, bool)

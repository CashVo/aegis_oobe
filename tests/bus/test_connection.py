# tests/bus/test_connection.py
# Unit tests for aegis.bus.connection.RedisConnectionManager
"""
Tests for the Redis Connection Manager.

These tests use unittest.mock to patch the redis.asyncio client,
allowing them to run without a live Redis instance.
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from aegis.bus.connection import RedisConnectionManager


@pytest.fixture
def manager():
    """Create a fresh RedisConnectionManager instance."""
    return RedisConnectionManager(
        host="127.0.0.1",
        port=6379,
        db=0,
    )


class TestRedisConnectionManager:
    """Tests for RedisConnectionManager."""

    def test_initial_state(self, manager):
        """Manager starts in disconnected state."""
        assert manager.is_connected is False
        assert manager._client is None
        assert manager._pool is None

    def test_client_raises_before_connect(self, manager):
        """Accessing client before connect() raises RuntimeError."""
        with pytest.raises(RuntimeError, match=r"Call connect\(\) first"):
            _ = manager.client

    @pytest.mark.asyncio
    @patch("aegis.bus.connection.Redis")
    @patch("aegis.bus.connection.ConnectionPool")
    async def test_connect_success(self, mock_pool_cls, mock_redis_cls, manager):
        """Successful connection sets state correctly."""
        mock_client = AsyncMock()
        mock_client.ping = AsyncMock(return_value=True)
        mock_redis_cls.return_value = mock_client
        mock_pool_cls.return_value = MagicMock()

        await manager.connect()

        assert manager.is_connected is True
        assert manager.client is mock_client

    @pytest.mark.asyncio
    @patch("aegis.bus.connection.Redis")
    @patch("aegis.bus.connection.ConnectionPool")
    async def test_connect_failure(self, mock_pool_cls, mock_redis_cls, manager):
        """Failed health check during connect raises ConnectionError."""
        mock_client = AsyncMock()
        mock_client.ping = AsyncMock(return_value=False)
        mock_client.aclose = AsyncMock()
        mock_redis_cls.return_value = mock_client

        mock_pool = MagicMock()
        mock_pool.disconnect = AsyncMock()
        mock_pool_cls.return_value = mock_pool

        from redis.exceptions import ConnectionError as RedisConnectionError
        with pytest.raises(RedisConnectionError):
            await manager.connect()

        assert manager.is_connected is False

    @pytest.mark.asyncio
    @patch("aegis.bus.connection.Redis")
    @patch("aegis.bus.connection.ConnectionPool")
    async def test_health_check_success(self, mock_pool_cls, mock_redis_cls, manager):
        """health_check returns True when PING succeeds."""
        mock_client = AsyncMock()
        mock_client.ping = AsyncMock(return_value=True)
        mock_redis_cls.return_value = mock_client
        mock_pool_cls.return_value = MagicMock()

        await manager.connect()
        result = await manager.health_check()

        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_no_client(self, manager):
        """health_check returns False when client is None."""
        result = await manager.health_check()
        assert result is False

    @pytest.mark.asyncio
    @patch("aegis.bus.connection.Redis")
    @patch("aegis.bus.connection.ConnectionPool")
    async def test_close(self, mock_pool_cls, mock_redis_cls, manager):
        """close() shuts down client and pool cleanly."""
        mock_client = AsyncMock()
        mock_client.ping = AsyncMock(return_value=True)
        mock_client.aclose = AsyncMock()
        mock_redis_cls.return_value = mock_client

        mock_pool = MagicMock()
        mock_pool.disconnect = AsyncMock()
        mock_pool_cls.return_value = mock_pool

        await manager.connect()
        await manager.close()

        assert manager.is_connected is False
        assert manager._client is None
        assert manager._pool is None
        mock_client.aclose.assert_called_once()
        mock_pool.disconnect.assert_called_once()

    def test_repr(self, manager):
        """repr shows connection status."""
        repr_str = repr(manager)
        assert "disconnected" in repr_str
        assert "127.0.0.1" in repr_str

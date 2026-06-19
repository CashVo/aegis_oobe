# tests/bus/test_publisher.py
# Unit tests for aegis.bus.publisher.MessagePublisher
"""
Tests for the Message Publisher.
"""

import pytest
from unittest.mock import AsyncMock, patch

from aegis.bus.publisher import MessagePublisher
from aegis.schemas.message import AegisMessage, MessageType, Priority


@pytest.fixture
def mock_redis():
    """Create a mock Redis client."""
    client = AsyncMock()
    client.xadd = AsyncMock(return_value="1620000000000-0")
    return client


@pytest.fixture
def publisher(mock_redis):
    """Create a MessagePublisher with mock Redis."""
    return MessagePublisher(redis_client=mock_redis, max_stream_length=1000)


@pytest.fixture
def sample_message():
    """Create a sample AegisMessage for testing."""
    return AegisMessage(
        source_agent="torchestrator",
        target_agent="forge",
        message_type=MessageType.REQUEST,
        tenant_id="tenant-001",
        user_id="user-001",
        action="forge.execute_tool",
        payload={"tool_name": "file_read", "path": "/tmp/test.txt"},
        priority=Priority.NORMAL,
    )


class TestMessagePublisher:
    """Tests for MessagePublisher."""

    @pytest.mark.asyncio
    async def test_publish_success(self, publisher, mock_redis, sample_message):
        """publish() calls XADD on the correct stream."""
        result = await publisher.publish(sample_message)

        assert result == "1620000000000-0"
        mock_redis.xadd.assert_called_once()

        call_kwargs = mock_redis.xadd.call_args
        assert call_kwargs.kwargs["name"] == "aegis:stream:forge"
        assert "data" in call_kwargs.kwargs["fields"]

    @pytest.mark.asyncio
    async def test_publish_empty_target_raises(self, publisher):
        """publish() raises ValueError when target_agent is empty."""
        msg = AegisMessage(
            source_agent="torchestrator",
            target_agent="",
            message_type=MessageType.REQUEST,
            tenant_id="t1",
            user_id="u1",
            action="test",
        )
        with pytest.raises(ValueError, match="target_agent is empty"):
            await publisher.publish(msg)

    @pytest.mark.asyncio
    async def test_broadcast_success(self, publisher, mock_redis, sample_message):
        """broadcast() publishes to the broadcast stream."""
        result = await publisher.broadcast(sample_message)

        assert result == "1620000000000-0"
        call_kwargs = mock_redis.xadd.call_args
        assert call_kwargs.kwargs["name"] == "aegis:stream:broadcast"

    @pytest.mark.asyncio
    async def test_publish_connection_error(self, publisher, mock_redis, sample_message):
        """publish() returns None on Redis connection errors."""
        from redis.exceptions import ConnectionError as RedisConnectionError
        mock_redis.xadd = AsyncMock(side_effect=RedisConnectionError("Connection lost"))

        result = await publisher.publish(sample_message)
        assert result is None

    @pytest.mark.asyncio
    async def test_serialization_format(self, publisher, mock_redis, sample_message):
        """Messages are serialized with a 'data' key containing JSON."""
        await publisher.publish(sample_message)

        call_kwargs = mock_redis.xadd.call_args
        fields = call_kwargs.kwargs["fields"]
        assert "data" in fields

        import json
        data = json.loads(fields["data"])
        assert data["source_agent"] == "torchestrator"
        assert data["target_agent"] == "forge"
        assert data["action"] == "forge.execute_tool"

    @pytest.mark.asyncio
    async def test_max_stream_length_passed(self, mock_redis, sample_message):
        """max_stream_length is passed to XADD as maxlen."""
        pub = MessagePublisher(redis_client=mock_redis, max_stream_length=5000)
        await pub.publish(sample_message)

        call_kwargs = mock_redis.xadd.call_args
        assert call_kwargs.kwargs["maxlen"] == 5000
        assert call_kwargs.kwargs["approximate"] is True

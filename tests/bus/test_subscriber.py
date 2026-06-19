# tests/bus/test_subscriber.py
# Unit tests for aegis.bus.subscriber.MessageSubscriber
"""
Tests for the Message Subscriber.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from aegis.utils.time import utcnow, timedelta

from aegis.bus.subscriber import MessageSubscriber
from aegis.schemas.message import AegisMessage, MessageType, Priority


@pytest.fixture
def mock_redis():
    """Create a mock Redis client."""
    client = AsyncMock()
    client.xgroup_create = AsyncMock()
    client.xreadgroup = AsyncMock(return_value=[])
    client.xack = AsyncMock()
    client.xautoclaim = AsyncMock(return_value=["0-0", [], []])
    return client


@pytest.fixture
def mock_handler():
    """Create a mock message handler."""
    return AsyncMock()


@pytest.fixture
def subscriber(mock_redis, mock_handler):
    """Create a MessageSubscriber with mocks."""
    return MessageSubscriber(
        redis_client=mock_redis,
        agent_id="test_agent",
        handler=mock_handler,
        subscribe_to_broadcast=False,  # Simplify tests
    )


@pytest.fixture
def sample_message_json():
    """Create a sample AegisMessage serialized to JSON."""
    msg = AegisMessage(
        source_agent="oracle",
        target_agent="test_agent",
        message_type=MessageType.RESPONSE,
        tenant_id="t1",
        user_id="u1",
        action="oracle.query",
        payload={"content": "Paris is the capital of France."},
    )
    return msg.model_dump_json()


class TestMessageSubscriber:
    """Tests for MessageSubscriber."""

    def test_initial_state(self, subscriber):
        """Subscriber starts in non-running state."""
        assert subscriber.is_running is False
        assert subscriber._stream == "aegis:stream:test_agent"
        assert subscriber._group == "aegis:group:test_agent"

    @pytest.mark.asyncio
    async def test_ensure_consumer_group_creates(self, subscriber, mock_redis):
        """Consumer group is created on first call."""
        await subscriber._ensure_consumer_group(
            "aegis:stream:test_agent", "aegis:group:test_agent"
        )
        mock_redis.xgroup_create.assert_called_once_with(
            name="aegis:stream:test_agent",
            groupname="aegis:group:test_agent",
            id="0",
            mkstream=True,
        )

    @pytest.mark.asyncio
    async def test_ensure_consumer_group_idempotent(self, subscriber, mock_redis):
        """BUSYGROUP error is handled gracefully (group already exists)."""
        from redis.exceptions import ResponseError
        mock_redis.xgroup_create = AsyncMock(
            side_effect=ResponseError("BUSYGROUP Consumer Group name already exists")
        )
        # Should not raise
        await subscriber._ensure_consumer_group(
            "aegis:stream:test_agent", "aegis:group:test_agent"
        )

    @pytest.mark.asyncio
    async def test_deserialize_valid_entry(self, subscriber, sample_message_json):
        """Valid stream entries deserialize to AegisMessage."""
        msg = subscriber._deserialize_entry(
            "1620000000000-0",
            {"data": sample_message_json},
        )
        assert msg is not None
        assert msg.source_agent == "oracle"
        assert msg.target_agent == "test_agent"

    @pytest.mark.asyncio
    async def test_deserialize_missing_data_field(self, subscriber):
        """Entries without 'data' field return None."""
        msg = subscriber._deserialize_entry(
            "1620000000000-0",
            {"other_field": "value"},
        )
        assert msg is None

    @pytest.mark.asyncio
    async def test_deserialize_invalid_json(self, subscriber):
        """Entries with invalid JSON return None."""
        msg = subscriber._deserialize_entry(
            "1620000000000-0",
            {"data": "not valid json {{{"},
        )
        assert msg is None

    def test_is_expired_no_ttl(self, subscriber):
        """Messages with no TTL never expire."""
        msg = AegisMessage(
            source_agent="a",
            target_agent="b",
            message_type=MessageType.EVENT,
            tenant_id="t",
            user_id="u",
            action="test",
            ttl_seconds=None,
        )
        assert subscriber._is_expired(msg) is False

    def test_is_expired_within_ttl(self, subscriber):
        """Messages within TTL are not expired."""
        msg = AegisMessage(
            source_agent="a",
            target_agent="b",
            message_type=MessageType.EVENT,
            tenant_id="t",
            user_id="u",
            action="test",
            ttl_seconds=300,
            timestamp=utcnow(),
        )
        assert subscriber._is_expired(msg) is False

    def test_is_expired_past_ttl(self, subscriber):
        """Messages past TTL are expired."""
        msg = AegisMessage(
            source_agent="a",
            target_agent="b",
            message_type=MessageType.EVENT,
            tenant_id="t",
            user_id="u",
            action="test",
            ttl_seconds=60,
            timestamp=utcnow() - timedelta(seconds=120),
        )
        assert subscriber._is_expired(msg) is True

    @pytest.mark.asyncio
    async def test_start_creates_group_and_tasks(self, subscriber, mock_redis):
        """start() creates consumer group and launches read tasks."""
        # Make xreadgroup return empty so loop doesn't block forever
        mock_redis.xreadgroup = AsyncMock(return_value=[])

        await subscriber.start()

        assert subscriber.is_running is True
        assert len(subscriber._tasks) == 1  # No broadcast subscription

        # Cleanup
        await subscriber.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_tasks(self, subscriber, mock_redis):
        """stop() cancels all running tasks."""
        mock_redis.xreadgroup = AsyncMock(return_value=[])

        await subscriber.start()
        await subscriber.stop()

        assert subscriber.is_running is False
        assert len(subscriber._tasks) == 0

    @pytest.mark.asyncio
    async def test_acknowledge(self, subscriber, mock_redis):
        """_acknowledge calls XACK with correct args."""
        await subscriber._acknowledge(
            "aegis:stream:test_agent",
            "aegis:group:test_agent",
            "1620000000000-0",
        )
        mock_redis.xack.assert_called_once_with(
            "aegis:stream:test_agent",
            "aegis:group:test_agent",
            "1620000000000-0",
        )

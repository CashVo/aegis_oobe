# aegis/bus/publisher.py
# Implements: Part III, §3.1 — Stream publisher for durable message delivery.
"""
Message Publisher for the Aegis Redis Message Bus.

Publishes AegisMessage instances to agent-specific Redis Streams
and the broadcast stream using XADD.
"""

import json
import logging
from typing import Optional

from redis.asyncio import Redis
from redis.exceptions import (
    ConnectionError as RedisConnectionError,
    TimeoutError as RedisTimeoutError,
)

from aegis.schemas.message import AegisMessage
from aegis.bus.constants import agent_stream, BROADCAST_STREAM

logger = logging.getLogger(__name__)


class MessagePublisher:
    """
    Publishes AegisMessage instances to Redis Streams.

    Messages are serialized to JSON and published via XADD to:
    - The target agent's dedicated stream (for direct messages)
    - The broadcast stream (for system-wide events)

    The publisher supports optional max stream length trimming to prevent
    unbounded memory growth.

    Usage:
        publisher = MessagePublisher(redis_client)
        stream_id = await publisher.publish(message)
        stream_id = await publisher.broadcast(message)
    """

    def __init__(
        self,
        redis_client: Redis,
        max_stream_length: Optional[int] = 10000,
    ) -> None:
        """
        Initialize the message publisher.

        Args:
            redis_client: An active redis.asyncio.Redis client instance.
            max_stream_length: Maximum approximate stream length before
                trimming. Set to None for unbounded streams.
        """
        self._redis = redis_client
        self._max_stream_length = max_stream_length

    def _serialize_message(self, message: AegisMessage) -> dict[str, str]:
        """
        Serialize an AegisMessage into a flat dict suitable for XADD.

        Redis Streams store field-value pairs where both must be strings.
        We serialize the entire message as a single JSON string under the
        'data' field for simplicity and schema flexibility.

        Args:
            message: The AegisMessage to serialize.

        Returns:
            A dict with a single 'data' key containing the JSON payload.
        """
        return {"data": message.model_dump_json()}

    async def publish(self, message: AegisMessage) -> Optional[str]:
        """
        Publish a message to the target agent's dedicated stream.

        The target stream is derived from message.target_agent.

        Args:
            message: The AegisMessage to publish.

        Returns:
            The Redis stream entry ID (e.g., '1620000000000-0') on success,
            or None on failure.

        Raises:
            ValueError: If message.target_agent is empty.
        """
        if not message.target_agent:
            raise ValueError("Cannot publish: message.target_agent is empty.")

        stream_key = agent_stream(message.target_agent)
        return await self._xadd(stream_key, message)

    async def broadcast(self, message: AegisMessage) -> Optional[str]:
        """
        Publish a message to the system-wide broadcast stream.

        All agents subscribing to the broadcast stream will receive this message.

        Args:
            message: The AegisMessage to broadcast.

        Returns:
            The Redis stream entry ID on success, or None on failure.
        """
        return await self._xadd(BROADCAST_STREAM, message)

    async def _xadd(self, stream_key: str, message: AegisMessage) -> Optional[str]:
        """
        Internal method to execute XADD on a given stream.

        Args:
            stream_key: The Redis stream key to publish to.
            message: The AegisMessage to serialize and publish.

        Returns:
            The stream entry ID on success, or None on failure.
        """
        serialized = self._serialize_message(message)

        try:
            entry_id = await self._redis.xadd(
                name=stream_key,
                fields=serialized,
                maxlen=self._max_stream_length,
                approximate=True,  # Use ~ for efficient trimming
            )
            logger.debug(
                f"Published message {message.message_id} to "
                f"stream '{stream_key}' (entry_id={entry_id})"
            )
            return entry_id
        except (RedisConnectionError, RedisTimeoutError) as e:
            logger.error(
                f"Failed to publish message {message.message_id} "
                f"to stream '{stream_key}': {e}"
            )
            return None
        except Exception as e:
            logger.error(
                f"Unexpected error publishing to '{stream_key}': {e}",
                exc_info=True,
            )
            return None

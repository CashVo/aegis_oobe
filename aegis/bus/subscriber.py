# aegis/bus/subscriber.py
# Implements: Part III, §3.1 — Stream subscriber with consumer groups,
# acknowledgment (XACK), and pending message redelivery.
"""
Message Subscriber for the Aegis Redis Message Bus.

Provides durable, ordered message consumption using Redis Streams
consumer groups. Supports:
- Consumer group creation with MKSTREAM
- Blocking reads (XREADGROUP)
- Message acknowledgment (XACK)
- Pending message claiming (XAUTOCLAIM) for redelivery
- Graceful shutdown
"""

import asyncio
import json
import logging
from typing import Any, Callable, Awaitable, Optional

from redis.asyncio import Redis
from redis.exceptions import (
    ConnectionError as RedisConnectionError,
    TimeoutError as RedisTimeoutError,
    ResponseError as RedisResponseError,
)

from aegis.schemas.message import AegisMessage
from aegis.bus.constants import (
    agent_stream,
    agent_consumer_group,
    broadcast_consumer_group,
    BROADCAST_STREAM,
    DEFAULT_BLOCK_MS,
    DEFAULT_READ_COUNT,
    DEFAULT_CLAIM_MIN_IDLE_MS,
    DEFAULT_MAX_RETRIES,
)

logger = logging.getLogger(__name__)

# Type alias for the message handler callback
MessageHandler = Callable[[AegisMessage], Awaitable[None]]


class MessageSubscriber:
    """
    Subscribes to Redis Streams using consumer groups for durable message delivery.

    Each subscriber represents a single agent's consumption loop. It:
    1. Creates the consumer group on the target stream (idempotent).
    2. Claims and redelivers pending (unacknowledged) messages on startup.
    3. Reads new messages via XREADGROUP with blocking.
    4. Deserializes messages and invokes the handler callback.
    5. Acknowledges processed messages via XACK.

    Usage:
        subscriber = MessageSubscriber(
            redis_client=redis,
            agent_id="warden",
            handler=my_handler_func,
        )
        await subscriber.start()  # Runs until stop() is called
        await subscriber.stop()
    """

    def __init__(
        self,
        redis_client: Redis,
        agent_id: str,
        handler: MessageHandler,
        subscribe_to_broadcast: bool = True,
        block_ms: int = DEFAULT_BLOCK_MS,
        read_count: int = DEFAULT_READ_COUNT,
        claim_min_idle_ms: int = DEFAULT_CLAIM_MIN_IDLE_MS,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        """
        Initialize the message subscriber.

        Args:
            redis_client: An active redis.asyncio.Redis client.
            agent_id: The unique identifier for this agent/subscriber.
            handler: Async callback invoked for each deserialized AegisMessage.
            subscribe_to_broadcast: Whether to also consume from the broadcast stream.
            block_ms: Milliseconds to block on XREADGROUP when no messages.
            read_count: Maximum messages to read per poll cycle.
            claim_min_idle_ms: Minimum idle time (ms) before claiming pending messages.
            max_retries: Maximum redelivery attempts before dropping a message.
        """
        self._redis = redis_client
        self._agent_id = agent_id
        self._handler = handler
        self._subscribe_to_broadcast = subscribe_to_broadcast
        self._block_ms = block_ms
        self._read_count = read_count
        self._claim_min_idle_ms = claim_min_idle_ms
        self._max_retries = max_retries

        # Derived names
        self._stream = agent_stream(agent_id)
        self._group = agent_consumer_group(agent_id)
        self._consumer = f"{agent_id}-consumer-1"

        self._broadcast_group = broadcast_consumer_group(agent_id)
        self._broadcast_consumer = f"{agent_id}-broadcast-consumer-1"

        # Control
        self._running: bool = False
        self._tasks: list[asyncio.Task] = []

    @property
    def is_running(self) -> bool:
        """Whether the subscriber read loop is active."""
        return self._running

    async def _ensure_consumer_group(
        self, stream: str, group: str
    ) -> None:
        """
        Create a consumer group on a stream, idempotently.

        Uses XGROUP CREATE with MKSTREAM to create the stream if it
        doesn't exist. Ignores BUSYGROUP errors (group already exists).

        Args:
            stream: The Redis stream key.
            group: The consumer group name.
        """
        try:
            await self._redis.xgroup_create(
                name=stream,
                groupname=group,
                id="0",  # Start reading from the beginning for new groups
                mkstream=True,
            )
            logger.info(
                f"Created consumer group '{group}' on stream '{stream}'."
            )
        except RedisResponseError as e:
            if "BUSYGROUP" in str(e):
                logger.debug(
                    f"Consumer group '{group}' already exists on '{stream}'."
                )
            else:
                raise

    async def _claim_pending_messages(
        self, stream: str, group: str, consumer: str
    ) -> list[AegisMessage]:
        """
        Claim and return pending messages that have exceeded the idle threshold.

        Uses XAUTOCLAIM to atomically transfer ownership of idle pending
        messages to this consumer for redelivery.

        Args:
            stream: The Redis stream key.
            group: The consumer group name.
            consumer: The consumer name to claim messages for.

        Returns:
            A list of deserialized AegisMessage objects from claimed entries.
        """
        claimed_messages: list[AegisMessage] = []

        try:
            # XAUTOCLAIM returns: [next_start_id, [[id, fields], ...], [deleted_ids]]
            result = await self._redis.xautoclaim(
                name=stream,
                groupname=group,
                consumername=consumer,
                min_idle_time=self._claim_min_idle_ms,
                start_id="0-0",
                count=self._read_count,
            )

            if result and len(result) >= 2:
                entries = result[1]  # List of [id, fields] pairs
                for entry_id, fields in entries:
                    msg = self._deserialize_entry(entry_id, fields)
                    if msg is not None:
                        claimed_messages.append(msg)

            if claimed_messages:
                logger.info(
                    f"Claimed {len(claimed_messages)} pending messages "
                    f"on '{stream}' for consumer '{consumer}'."
                )

        except (RedisConnectionError, RedisTimeoutError) as e:
            logger.warning(f"Failed to claim pending messages on '{stream}': {e}")
        except Exception as e:
            logger.error(
                f"Unexpected error during XAUTOCLAIM on '{stream}': {e}",
                exc_info=True,
            )

        return claimed_messages

    def _deserialize_entry(
        self, entry_id: str, fields: dict[str, Any]
    ) -> Optional[AegisMessage]:
        """
        Deserialize a Redis stream entry into an AegisMessage.

        Args:
            entry_id: The Redis stream entry ID.
            fields: The field-value dict from the stream entry.

        Returns:
            An AegisMessage instance, or None if deserialization fails.
        """
        try:
            data = fields.get("data")
            if data is None:
                logger.warning(
                    f"Stream entry {entry_id} missing 'data' field. Skipping."
                )
                return None

            # data is a JSON string (already decoded since decode_responses=True)
            message = AegisMessage.model_validate_json(data)
            return message

        except (json.JSONDecodeError, ValueError) as e:
            logger.error(
                f"Failed to deserialize stream entry {entry_id}: {e}"
            )
            return None

    async def _acknowledge(
        self, stream: str, group: str, entry_id: str
    ) -> None:
        """
        Acknowledge a message as processed via XACK.

        Args:
            stream: The Redis stream key.
            group: The consumer group name.
            entry_id: The stream entry ID to acknowledge.
        """
        try:
            await self._redis.xack(stream, group, entry_id)
            logger.debug(f"Acknowledged entry {entry_id} on '{stream}/{group}'.")
        except (RedisConnectionError, RedisTimeoutError) as e:
            logger.warning(
                f"Failed to acknowledge entry {entry_id} on '{stream}': {e}"
            )

    async def _read_loop(
        self, stream: str, group: str, consumer: str
    ) -> None:
        """
        The main read loop for a single stream.

        Continuously reads new messages via XREADGROUP, deserializes them,
        invokes the handler, and acknowledges on success.

        Args:
            stream: The Redis stream key to read from.
            group: The consumer group name.
            consumer: The consumer name.
        """
        logger.info(
            f"Starting read loop: stream='{stream}', "
            f"group='{group}', consumer='{consumer}'"
        )

        # First, process any pending (previously claimed) messages
        pending = await self._claim_pending_messages(stream, group, consumer)
        for msg in pending:
            try:
                await self._handler(msg)
            except Exception as e:
                logger.error(
                    f"Handler error processing pending message "
                    f"{msg.message_id}: {e}",
                    exc_info=True,
                )

        # Main read loop
        while self._running:
            try:
                # XREADGROUP: read new messages (id=">")
                responses = await self._redis.xreadgroup(
                    groupname=group,
                    consumername=consumer,
                    streams={stream: ">"},
                    count=self._read_count,
                    block=self._block_ms,
                )

                if not responses:
                    # No new messages within block timeout — loop again
                    continue

                # responses format: [[stream_name, [(entry_id, fields), ...]]]
                for stream_name, entries in responses:
                    for entry_id, fields in entries:
                        message = self._deserialize_entry(entry_id, fields)

                        if message is None:
                            # Undeserializable — acknowledge to prevent redelivery
                            await self._acknowledge(stream, group, entry_id)
                            continue

                        # Check TTL expiration
                        if self._is_expired(message):
                            logger.warning(
                                f"Message {message.message_id} expired "
                                f"(ttl={message.ttl_seconds}s). Dropping."
                            )
                            await self._acknowledge(stream, group, entry_id)
                            continue

                        # Invoke handler
                        try:
                            await self._handler(message)
                            await self._acknowledge(stream, group, entry_id)
                        except Exception as e:
                            logger.error(
                                f"Handler error for message "
                                f"{message.message_id}: {e}",
                                exc_info=True,
                            )
                            # Do NOT acknowledge — message stays pending
                            # for redelivery via XAUTOCLAIM on next cycle

            except (RedisConnectionError, RedisTimeoutError) as e:
                if self._running:
                    logger.error(
                        f"Redis connection issue in read loop for "
                        f"'{stream}': {e}. Retrying in 2s..."
                    )
                    await asyncio.sleep(2)
            except asyncio.CancelledError:
                logger.info(f"Read loop cancelled for '{stream}'.")
                break
            except Exception as e:
                if self._running:
                    logger.error(
                        f"Unexpected error in read loop for '{stream}': {e}",
                        exc_info=True,
                    )
                    await asyncio.sleep(1)

        logger.info(f"Read loop stopped for stream '{stream}'.")

    def _is_expired(self, message: AegisMessage) -> bool:
        """
        Check if a message has exceeded its TTL.

        Args:
            message: The AegisMessage to check.

        Returns:
            True if the message is expired, False otherwise.
        """
        if message.ttl_seconds is None:
            return False

        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        # message.timestamp may be naive (utcnow) — treat as UTC
        msg_time = message.timestamp.replace(tzinfo=timezone.utc) if message.timestamp.tzinfo is None else message.timestamp
        elapsed = (now - msg_time).total_seconds()
        return elapsed > message.ttl_seconds

    async def start(self) -> None:
        """
        Start the subscriber read loops.

        Creates consumer groups and launches async tasks for:
        - The agent's dedicated stream
        - The broadcast stream (if subscribe_to_broadcast is True)
        """
        if self._running:
            logger.warning(f"Subscriber '{self._agent_id}' already running.")
            return

        self._running = True

        # Ensure consumer groups exist
        await self._ensure_consumer_group(self._stream, self._group)

        # Launch dedicated stream read loop
        task = asyncio.create_task(
            self._read_loop(self._stream, self._group, self._consumer),
            name=f"subscriber-{self._agent_id}-dedicated",
        )
        self._tasks.append(task)

        # Launch broadcast stream read loop
        if self._subscribe_to_broadcast:
            await self._ensure_consumer_group(
                BROADCAST_STREAM, self._broadcast_group
            )
            broadcast_task = asyncio.create_task(
                self._read_loop(
                    BROADCAST_STREAM,
                    self._broadcast_group,
                    self._broadcast_consumer,
                ),
                name=f"subscriber-{self._agent_id}-broadcast",
            )
            self._tasks.append(broadcast_task)

        logger.info(
            f"Subscriber '{self._agent_id}' started "
            f"({len(self._tasks)} read loop(s))."
        )

    async def stop(self) -> None:
        """
        Gracefully stop all read loops and cancel tasks.
        """
        logger.info(f"Stopping subscriber '{self._agent_id}'...")
        self._running = False

        for task in self._tasks:
            task.cancel()

        # Wait for tasks to finish cancellation
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

        self._tasks.clear()
        logger.info(f"Subscriber '{self._agent_id}' stopped.")

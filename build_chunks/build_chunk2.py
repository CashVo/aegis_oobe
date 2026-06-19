# build_chunk_002.py
#
# Project Aegis — AMCP Assembly Script
# CHUNK-002: Redis Message Bus
#
# Implements: Part III, §3.1 — Redis Message Bus
# Dependencies: CHUNK-001 (Base Layout & Schemas)
#
# Run from the project root: python build_chunk_002.py

import os
import textwrap


CHUNK_002_FILES = {

    # ═══════════════════════════════════════════════════════════
    # aegis/bus/constants.py
    # ═══════════════════════════════════════════════════════════
    "aegis/bus/constants.py": '''
        # aegis/bus/constants.py
        # Implements: Part III, §3.1 — Redis Stream naming conventions and constants.
        """
        Constants and naming conventions for the Aegis Redis Message Bus.

        All stream and consumer group names are derived from these constants
        to ensure consistency across the system.
        """

        # --- Stream Naming ---
        STREAM_PREFIX: str = "aegis:stream:"
        BROADCAST_STREAM: str = "aegis:stream:broadcast"

        # --- Consumer Group Naming ---
        CONSUMER_GROUP_PREFIX: str = "aegis:group:"

        # --- Default Configuration ---
        DEFAULT_REDIS_HOST: str = "127.0.0.1"
        DEFAULT_REDIS_PORT: int = 6379
        DEFAULT_REDIS_DB: int = 0
        DEFAULT_BLOCK_MS: int = 5000  # Block for 5s when reading streams
        DEFAULT_READ_COUNT: int = 10  # Read up to 10 messages per poll cycle
        DEFAULT_CLAIM_MIN_IDLE_MS: int = 30000  # Claim pending messages idle > 30s
        DEFAULT_MAX_RETRIES: int = 3  # Max redelivery attempts before dead-lettering


        def agent_stream(agent_id: str) -> str:
            """
            Derive the dedicated stream name for a given agent.

            Args:
                agent_id: The unique identifier of the agent.

            Returns:
                The fully qualified Redis stream key (e.g., 'aegis:stream:warden').
            """
            return f"{STREAM_PREFIX}{agent_id}"


        def agent_consumer_group(agent_id: str) -> str:
            """
            Derive the consumer group name for a given agent's stream.

            Each agent has a single consumer group on its own stream to enable
            acknowledgment and pending message tracking.

            Args:
                agent_id: The unique identifier of the agent.

            Returns:
                The consumer group name (e.g., 'aegis:group:warden').
            """
            return f"{CONSUMER_GROUP_PREFIX}{agent_id}"


        def broadcast_consumer_group(agent_id: str) -> str:
            """
            Derive the consumer group name for an agent subscribing to the broadcast stream.

            Each agent that subscribes to broadcast gets its own consumer group
            so all agents receive all broadcast messages independently.

            Args:
                agent_id: The unique identifier of the subscribing agent.

            Returns:
                The consumer group name for broadcast (e.g., 'aegis:group:broadcast:observer').
            """
            return f"{CONSUMER_GROUP_PREFIX}broadcast:{agent_id}"
    ''',

    # ═══════════════════════════════════════════════════════════
    # aegis/bus/connection.py
    # ═══════════════════════════════════════════════════════════
    "aegis/bus/connection.py": '''
        # aegis/bus/connection.py
        # Implements: Part III, §3.1 — Redis connection manager with health check.
        """
        Redis Connection Manager for the Aegis Message Bus.

        Provides a singleton-style async connection pool manager with:
        - Lazy connection initialization
        - Health check (PING)
        - Graceful shutdown
        - Configuration from aegis_config.yaml
        """

        import logging
        from typing import Optional

        import redis.asyncio as aioredis
        from redis.asyncio import ConnectionPool, Redis
        from redis.exceptions import (
            ConnectionError as RedisConnectionError,
            TimeoutError as RedisTimeoutError,
        )

        from aegis.bus.constants import (
            DEFAULT_REDIS_HOST,
            DEFAULT_REDIS_PORT,
            DEFAULT_REDIS_DB,
        )

        logger = logging.getLogger(__name__)


        class RedisConnectionManager:
            """
            Manages the async Redis connection pool for the Aegis message bus.

            This class provides a centralized connection manager that:
            - Creates and manages a shared connection pool
            - Verifies connectivity via health_check()
            - Supports graceful shutdown of all connections

            Usage:
                manager = RedisConnectionManager(host="127.0.0.1", port=6379)
                await manager.connect()
                redis = manager.client
                await manager.health_check()
                await manager.close()
            """

            def __init__(
                self,
                host: str = DEFAULT_REDIS_HOST,
                port: int = DEFAULT_REDIS_PORT,
                db: int = DEFAULT_REDIS_DB,
                password: Optional[str] = None,
                max_connections: int = 20,
                socket_timeout: float = 5.0,
                socket_connect_timeout: float = 5.0,
                retry_on_timeout: bool = True,
                decode_responses: bool = True,
            ) -> None:
                """
                Initialize the Redis connection manager.

                Args:
                    host: Redis server hostname.
                    port: Redis server port.
                    db: Redis database number.
                    password: Optional Redis password.
                    max_connections: Maximum pool connections.
                    socket_timeout: Timeout for socket operations (seconds).
                    socket_connect_timeout: Timeout for socket connect (seconds).
                    retry_on_timeout: Whether to retry on timeout errors.
                    decode_responses: Whether to decode byte responses to strings.
                """
                self._host = host
                self._port = port
                self._db = db
                self._password = password
                self._max_connections = max_connections
                self._socket_timeout = socket_timeout
                self._socket_connect_timeout = socket_connect_timeout
                self._retry_on_timeout = retry_on_timeout
                self._decode_responses = decode_responses

                self._pool: Optional[ConnectionPool] = None
                self._client: Optional[Redis] = None
                self._connected: bool = False

            @property
            def client(self) -> Redis:
                """
                Get the active Redis client instance.

                Returns:
                    The redis.asyncio.Redis client.

                Raises:
                    RuntimeError: If connect() has not been called.
                """
                if self._client is None:
                    raise RuntimeError(
                        "Redis client not initialized. Call connect() first."
                    )
                return self._client

            @property
            def is_connected(self) -> bool:
                """Whether the connection manager has an active connection."""
                return self._connected

            async def connect(self) -> None:
                """
                Initialize the connection pool and create the Redis client.

                This must be called before any operations on the bus.

                Raises:
                    RedisConnectionError: If Redis is unreachable.
                """
                if self._connected:
                    logger.warning("RedisConnectionManager.connect() called but already connected.")
                    return

                logger.info(
                    f"Connecting to Redis at {self._host}:{self._port}/{self._db} "
                    f"(max_connections={self._max_connections})"
                )

                self._pool = ConnectionPool(
                    host=self._host,
                    port=self._port,
                    db=self._db,
                    password=self._password,
                    max_connections=self._max_connections,
                    socket_timeout=self._socket_timeout,
                    socket_connect_timeout=self._socket_connect_timeout,
                    retry_on_timeout=self._retry_on_timeout,
                    decode_responses=self._decode_responses,
                )

                self._client = Redis(connection_pool=self._pool)

                # Verify connectivity immediately
                if not await self.health_check():
                    await self.close()
                    raise RedisConnectionError(
                        f"Failed to connect to Redis at {self._host}:{self._port}"
                    )

                self._connected = True
                logger.info("Redis connection established successfully.")

            async def health_check(self) -> bool:
                """
                Verify Redis connectivity via PING.

                Returns:
                    True if Redis responds to PING, False otherwise.
                """
                if self._client is None:
                    return False

                try:
                    response = await self._client.ping()
                    return response is True
                except (RedisConnectionError, RedisTimeoutError, OSError) as e:
                    logger.error(f"Redis health check failed: {e}")
                    self._connected = False
                    return False

            async def close(self) -> None:
                """
                Gracefully close the Redis connection and drain the pool.
                """
                logger.info("Closing Redis connection...")
                if self._client is not None:
                    await self._client.aclose()
                    self._client = None
                if self._pool is not None:
                    await self._pool.disconnect()
                    self._pool = None
                self._connected = False
                logger.info("Redis connection closed.")

            def __repr__(self) -> str:
                status = "connected" if self._connected else "disconnected"
                return (
                    f"<RedisConnectionManager "
                    f"host={self._host} port={self._port} "
                    f"db={self._db} status={status}>"
                )
    ''',

    # ═══════════════════════════════════════════════════════════
    # aegis/bus/publisher.py
    # ═══════════════════════════════════════════════════════════
    "aegis/bus/publisher.py": '''
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
    ''',

    # ═══════════════════════════════════════════════════════════
    # aegis/bus/subscriber.py
    # ═══════════════════════════════════════════════════════════
    "aegis/bus/subscriber.py": '''
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
    ''',

    # ═══════════════════════════════════════════════════════════
    # aegis/bus/__init__.py
    # ═══════════════════════════════════════════════════════════
    "aegis/bus/__init__.py": '''
        # aegis/bus/__init__.py
        # Implements: Part III, §3.1 — Message Bus package exports.
        """
        Aegis Message Bus — Redis Streams-based inter-agent communication.

        This package provides the core messaging infrastructure for all
        inter-agent communication in Project Aegis.

        Components:
            - RedisConnectionManager: Connection pool and lifecycle management.
            - MessagePublisher: Publish AegisMessage to agent streams.
            - MessageSubscriber: Consume messages with consumer groups and XACK.

        Constants:
            - agent_stream(): Derive stream name for an agent.
            - agent_consumer_group(): Derive consumer group for an agent.
            - broadcast_consumer_group(): Derive broadcast group for an agent.
            - BROADCAST_STREAM: The system-wide broadcast stream key.
        """

        from aegis.bus.connection import RedisConnectionManager
        from aegis.bus.publisher import MessagePublisher
        from aegis.bus.subscriber import MessageSubscriber
        from aegis.bus.constants import (
            agent_stream,
            agent_consumer_group,
            broadcast_consumer_group,
            BROADCAST_STREAM,
            STREAM_PREFIX,
        )

        __all__ = [
            "RedisConnectionManager",
            "MessagePublisher",
            "MessageSubscriber",
            "agent_stream",
            "agent_consumer_group",
            "broadcast_consumer_group",
            "BROADCAST_STREAM",
            "STREAM_PREFIX",
        ]
    ''',

    # ═══════════════════════════════════════════════════════════
    # tests/__init__.py
    # ═══════════════════════════════════════════════════════════
    "tests/__init__.py": '''
        # tests/__init__.py
    ''',

    # ═══════════════════════════════════════════════════════════
    # tests/bus/__init__.py
    # ═══════════════════════════════════════════════════════════
    "tests/bus/__init__.py": '''
        # tests/bus/__init__.py
    ''',

    # ═══════════════════════════════════════════════════════════
    # tests/bus/test_connection.py
    # ═══════════════════════════════════════════════════════════
    "tests/bus/test_connection.py": '''
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
                with pytest.raises(RuntimeError, match="Call connect\\(\\) first"):
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
    ''',

    # ═══════════════════════════════════════════════════════════
    # tests/bus/test_publisher.py
    # ═══════════════════════════════════════════════════════════
    "tests/bus/test_publisher.py": '''
        # tests/bus/test_publisher.py
        # Unit tests for aegis.bus.publisher.MessagePublisher
        """
        Tests for the Message Publisher.
        """

        import pytest
        from unittest.mock import AsyncMock, patch
        from datetime import datetime

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
    ''',

    # ═══════════════════════════════════════════════════════════
    # tests/bus/test_subscriber.py
    # ═══════════════════════════════════════════════════════════
    "tests/bus/test_subscriber.py": '''
        # tests/bus/test_subscriber.py
        # Unit tests for aegis.bus.subscriber.MessageSubscriber
        """
        Tests for the Message Subscriber.
        """

        import pytest
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch
        from datetime import datetime, timezone, timedelta

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
                    timestamp=datetime.now(timezone.utc),
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
                    timestamp=datetime.now(timezone.utc) - timedelta(seconds=120),
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
    ''',

    # ═══════════════════════════════════════════════════════════
    # tests/bus/test_constants.py
    # ═══════════════════════════════════════════════════════════
    "tests/bus/test_constants.py": '''
        # tests/bus/test_constants.py
        # Unit tests for aegis.bus.constants
        """
        Tests for bus naming conventions and constants.
        """

        from aegis.bus.constants import (
            agent_stream,
            agent_consumer_group,
            broadcast_consumer_group,
            STREAM_PREFIX,
            BROADCAST_STREAM,
        )


        class TestConstants:
            """Tests for stream/group naming functions."""

            def test_agent_stream(self):
                """agent_stream produces correct stream key."""
                assert agent_stream("warden") == "aegis:stream:warden"
                assert agent_stream("torchestrator") == "aegis:stream:torchestrator"

            def test_agent_consumer_group(self):
                """agent_consumer_group produces correct group name."""
                assert agent_consumer_group("forge") == "aegis:group:forge"

            def test_broadcast_consumer_group(self):
                """broadcast_consumer_group includes agent id."""
                result = broadcast_consumer_group("observer")
                assert result == "aegis:group:broadcast:observer"

            def test_stream_prefix(self):
                """STREAM_PREFIX is correct."""
                assert STREAM_PREFIX == "aegis:stream:"

            def test_broadcast_stream(self):
                """BROADCAST_STREAM is correct."""
                assert BROADCAST_STREAM == "aegis:stream:broadcast"
    ''',

}


def create_package_init_files(path: str) -> None:
    """Create __init__.py files in parent directories if they don't exist."""
    dir_name = os.path.dirname(path)
    if dir_name and (dir_name.startswith("aegis/") or dir_name.startswith("tests/")):
        parts = dir_name.split("/")
        for i in range(1, len(parts) + 1):
            pkg_path = "/".join(parts[:i])
            init_file = os.path.join(pkg_path, "__init__.py")
            if not os.path.exists(init_file) and pkg_path not in ("aegis/bus", "tests/bus", "tests"):
                # Only create if not already in our file manifest
                if init_file not in CHUNK_002_FILES:
                    os.makedirs(pkg_path, exist_ok=True)
                    if not os.path.exists(init_file):
                        print(f"  [Created] {init_file} (package marker)")
                        with open(init_file, "w") as f:
                            pass


def main() -> None:
    """Assemble CHUNK-002: Redis Message Bus."""
    print("=" * 60)
    print("  CHUNK-002: Redis Message Bus — Assembly")
    print("  Implements: Part III, §3.1")
    print("=" * 60)
    print()

    files_written = 0

    for path, content in CHUNK_002_FILES.items():
        # Ensure directory exists
        dir_name = os.path.dirname(path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)

        # Create package init files for parent packages
        create_package_init_files(path)

        # Write the file
        clean_content = textwrap.dedent(content).strip() + "\n"
        print(f"  [Writing] {path}")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(clean_content)
        files_written += 1

    print()
    print("-" * 60)
    print(f"  Assembly Complete: {files_written} files written.")
    print()
    print("  New dependency required in pyproject.toml / requirements.txt:")
    print('    redis[hiredis] >= 5.0.0')
    print()
    print("  Verify with:")
    print("    pytest tests/bus/ -v")
    print("=" * 60)


if __name__ == "__main__":
    main()

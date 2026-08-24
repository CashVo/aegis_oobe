"""
aegis/bus/redis_bus.py
High-level message bus facade composing Redis connection, pub, and sub primitives.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Awaitable, Optional

from aegis.bus.connection import RedisConnectionManager
from aegis.bus.publisher import MessagePublisher
from aegis.bus.subscriber import MessageSubscriber
from aegis.bus.constants import agent_stream, BROADCAST_STREAM
from aegis.schemas.message import AegisMessage

logger = logging.getLogger(__name__)

class RedisBus:
    """
    Unified Redis-backed message bus for inter-agent communication.

    Wraps RedisConnectionManager, MessagePublisher, and MessageSubscriber
    into a single lifecycle-managed object. Also exposes lower-level
    stream operations (consume, consumer groups) for web/CLI consumers.
    """

    def __init__(self, config: Any) -> None:
        redis_cfg = config.redis

        self._conn = RedisConnectionManager(
            host=redis_cfg.host,
            port=redis_cfg.port,
            db=redis_cfg.db,
            password=getattr(redis_cfg, "password", None),
        )
        self._publisher: MessagePublisher | None = None
        self._subscriber: MessageSubscriber | None = None

    # Lifecycle
    async def connect(self) -> None:
        await self._conn.connect()
        client = self._conn.client
        self._publisher = MessagePublisher(client)
        self._subscriber = None  # Lazy — created on subscribe()
        logger.info("RedisBus connected")

    async def disconnect(self) -> None:
        if self._subscriber:
            await self._subscriber.stop()
        await self._conn.close()
        logger.info("RedisBus disconnected")

    # Health
    async def ping(self) -> bool:
        try:
            if not self._conn._connected:
                await self.connect()
            return await self._conn.health_check()
        except Exception:
            logger.exception("RedisBus ping failed")
            return False

    @property
    def connected(self) -> bool:
        return self._conn._connected

    @property
    def is_connected(self) -> bool:
        return self._conn._connected
    
    @property
    def client(self):
        return self._conn.client

    # Publishing — does XADD directly (bypasses MessagePublisher for flexibility)
    async def publish(
        self,
        stream: str,
        message: AegisMessage | dict[str, Any],
        *,
        maxlen: int | None = 10000,
    ) -> str | None:
        if not self._conn._connected:
            raise RuntimeError("RedisBus not connected. Call connect() first.")

        client = self._conn.client

        if isinstance(message, AegisMessage):
            fields = {"data": message.model_dump_json()}
        elif isinstance(message, dict):
            fields = {"data": json.dumps(message, default=str)}
        else:
            fields = {"data": str(message)}

        try:
            entry_id = await client.xadd(
                name=stream,
                fields=fields,
                maxlen=maxlen,
                approximate=True,
            )
            logger.debug(f"Published to '{stream}' (entry_id={entry_id})")
            return entry_id
        except Exception as e:
            logger.error(f"Failed to publish to '{stream}': {e}")
            return None

    async def broadcast(self, message: AegisMessage | dict[str, Any]) -> str | None:
        return await self.publish(BROADCAST_STREAM, message)

    async def send_to_agent(self, agent_id: str, message: AegisMessage | dict[str, Any]) -> str | None:
        return await self.publish(agent_stream(agent_id), message)

    # Consumer Groups
    async def create_consumer_group(self, stream: str, group: str, start_id: str = "0") -> None:
        if not self._conn._connected:
            raise RuntimeError("RedisBus not connected. Call connect() first.")

        client = self._conn.client
        try:
            await client.xgroup_create(name=stream, groupname=group, id=start_id, mkstream=True)
        except Exception as e:
            if "BUSYGROUP" in str(e):
                pass
            else:
                raise

    # Consuming (for web/CLI request-response patterns)
    async def consume(
        self,
        stream: str,
        group: str,
        consumer: str,
        *,
        count: int = 1,
        block_ms: int = 1000,
    ) -> list[tuple[str, dict[str, Any]]]:
        if not self._conn._connected:
            raise RuntimeError("RedisBus not connected. Call connect() first.")

        client = self._conn.client
        try:
            responses = await client.xreadgroup(
                groupname=group,
                consumername=consumer,
                streams={stream: ">"},
                count=count,
                block=block_ms,
            )
            if not responses:
                return []

            results = []
            for stream_name, entries in responses:
                for entry_id, fields in entries:
                    raw_data = fields.get("data")
                    if raw_data is None:
                        await client.xack(stream, group, entry_id)
                        continue
                    try:
                        data = json.loads(raw_data)
                    except (json.JSONDecodeError, TypeError):
                        data = {"raw": raw_data}
                    await client.xack(stream, group, entry_id)
                    results.append((entry_id, data))
            return results
        except Exception as e:
            logger.error(f"Error consuming from '{stream}': {e}")
            return []

    # Subscribing (for agents with persistent read loops)
    async def subscribe(
        self,
        stream: str,
        handler: Callable[[dict[str, Any]], Awaitable[None]],
        *,
        group: str | None = None,
        consumer: str | None = None,
        agent_id: str = "web",
    ) -> None:
        if not self._conn._connected:
            raise RuntimeError("RedisBus not connected. Call connect() first.")
        if self._subscriber is None:
            self._subscriber = MessageSubscriber(
                redis_client=self._conn.client,
                agent_id=agent_id,
                handler=handler,
                subscribe_to_broadcast=False,
            )
        await self._subscriber.start()

    # Context manager
    async def __aenter__(self) -> "RedisBus":
        await self.connect()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.disconnect()
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

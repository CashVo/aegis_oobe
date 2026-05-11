# aegis/agents/oracle/cache.py
# Implements: Part II §2.1 — Response caching for Oracle
"""
Response Cache — SQLite-backed cache for LLM responses. Reduces redundant
inference calls by caching responses keyed on a hash of the request parameters.

Features:
- SHA-256 hash keys from (prompt + model + temperature + max_tokens)
- TTL-based expiration
- Hit count tracking
- Periodic cleanup of expired entries
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

import aiosqlite
import structlog

from aegis.schemas.oracle import OracleRequest, OracleResponse

logger = structlog.get_logger(__name__)

DEFAULT_CACHE_DB = "aegis_data/oracle_cache.db"
DEFAULT_TTL_SECONDS = 3600  # 1 hour
DEFAULT_MAX_ENTRIES = 10000


class ResponseCache:
    """
    SQLite-backed response cache for Oracle LLM responses.

    Cache keys are SHA-256 hashes of the canonical request parameters.
    Entries expire based on configurable TTL. Expired entries are cleaned
    up periodically.
    """

    def __init__(self, config: dict | None = None) -> None:
        """
        Initialize the cache.

        Args:
            config: Cache configuration from aegis_config.yaml.
        """
        config = config or {}
        self.enabled: bool = config.get("enabled", True)
        self._db_path: str = config.get("db_path", DEFAULT_CACHE_DB)
        self._ttl_seconds: int = config.get("ttl_seconds", DEFAULT_TTL_SECONDS)
        self._max_entries: int = config.get("max_entries", DEFAULT_MAX_ENTRIES)
        self._db: Optional[aiosqlite.Connection] = None
        self._initialized = False

    async def initialize(self) -> None:
        """Create the cache database and table if they don't exist."""
        if not self.enabled:
            logger.info("oracle_cache.disabled")
            return

        # Ensure directory exists
        db_dir = Path(self._db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS oracle_cache (
                cache_key TEXT PRIMARY KEY,
                response_json TEXT NOT NULL,
                llm_used TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                hit_count INTEGER DEFAULT 0
            )
        """)
        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_cache_expires
            ON oracle_cache(expires_at)
        """)
        await self._db.commit()
        self._initialized = True

        # Cleanup expired entries on startup
        await self._cleanup_expired()

        logger.info(
            "oracle_cache.initialized",
            db_path=self._db_path,
            ttl_seconds=self._ttl_seconds,
        )

    def compute_key(
        self, request: OracleRequest, llm_id: str
    ) -> str:
        """
        Compute a deterministic cache key from request parameters.

        The key is a SHA-256 hash of the canonical JSON representation
        of the cache-relevant fields.

        Args:
            request: The Oracle request.
            llm_id: The resolved model identifier.

        Returns:
            Hex-encoded SHA-256 hash string.
        """
        key_data = {
            "action": request.action.value,
            "prompt": request.prompt,
            "system_prompt": request.system_prompt or "",
            "llm_id": llm_id,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "response_format": request.response_format or "",
        }
        canonical = json.dumps(key_data, sort_keys=True, ensure_ascii=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    async def get(self, cache_key: str) -> dict | None:
        """
        Retrieve a cached response by key.

        Returns None if cache is disabled, key not found, or entry expired.

        Args:
            cache_key: The SHA-256 hash key.

        Returns:
            Dict with "content", "llm_used", "tokens_used" or None.
        """
        if not self.enabled or not self._initialized or self._db is None:
            return None

        now = datetime.now(timezone.utc).isoformat()

        async with self._db.execute(
            """
            SELECT response_json, llm_used, hit_count
            FROM oracle_cache
            WHERE cache_key = ? AND expires_at > ?
            """,
            (cache_key, now),
        ) as cursor:
            row = await cursor.fetchone()

        if row is None:
            return None

        # Increment hit count
        await self._db.execute(
            "UPDATE oracle_cache SET hit_count = ? WHERE cache_key = ?",
            (row[2] + 1, cache_key),
        )
        await self._db.commit()

        try:
            response_data = json.loads(row[0])
        except json.JSONDecodeError:
            logger.warning("oracle_cache.corrupt_entry", key=cache_key[:16])
            return None

        logger.debug("oracle_cache.hit", key=cache_key[:16])
        return response_data

    async def store(
        self, cache_key: str, response: OracleResponse
    ) -> None:
        """
        Store a response in the cache.

        Args:
            cache_key: The SHA-256 hash key.
            response: The OracleResponse to cache.
        """
        if not self.enabled or not self._initialized or self._db is None:
            return

        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=self._ttl_seconds)

        response_data = {
            "content": response.content,
            "llm_used": response.llm_used,
            "tokens_used": response.tokens_used,
        }

        await self._db.execute(
            """
            INSERT OR REPLACE INTO oracle_cache
            (cache_key, response_json, llm_used, created_at, expires_at, hit_count)
            VALUES (?, ?, ?, ?, ?, 0)
            """,
            (
                cache_key,
                json.dumps(response_data, default=str),
                response.llm_used,
                now.isoformat(),
                expires.isoformat(),
            ),
        )
        await self._db.commit()

        logger.debug("oracle_cache.stored", key=cache_key[:16])

    async def flush(self) -> None:
        """Flush all cache entries and close the database connection."""
        if self._db is not None:
            await self._db.execute("DELETE FROM oracle_cache")
            await self._db.commit()
            await self._db.close()
            self._db = None
            self._initialized = False
            logger.info("oracle_cache.flushed")

    async def invalidate(self, cache_key: str) -> None:
        """
        Remove a specific entry from the cache.

        Args:
            cache_key: The entry to invalidate.
        """
        if not self._initialized or self._db is None:
            return

        await self._db.execute(
            "DELETE FROM oracle_cache WHERE cache_key = ?", (cache_key,)
        )
        await self._db.commit()

    async def _cleanup_expired(self) -> None:
        """Remove all expired entries from the cache."""
        if not self._initialized or self._db is None:
            return

        now = datetime.now(timezone.utc).isoformat()
        cursor = await self._db.execute(
            "DELETE FROM oracle_cache WHERE expires_at <= ?", (now,)
        )
        deleted = cursor.rowcount
        await self._db.commit()

        if deleted and deleted > 0:
            logger.info("oracle_cache.cleanup", deleted=deleted)

    async def stats(self) -> dict[str, Any]:
        """
        Return cache statistics.

        Returns:
            Dict with total_entries, total_hits, oldest_entry, etc.
        """
        if not self._initialized or self._db is None:
            return {"enabled": self.enabled, "initialized": False}

        async with self._db.execute(
            "SELECT COUNT(*), COALESCE(SUM(hit_count), 0) FROM oracle_cache"
        ) as cursor:
            row = await cursor.fetchone()

        return {
            "enabled": self.enabled,
            "initialized": True,
            "total_entries": row[0] if row else 0,
            "total_hits": row[1] if row else 0,
            "ttl_seconds": self._ttl_seconds,
            "db_path": self._db_path,
        }

# aegis/agents/lexicon/tiers/l5_scratchpad.py
# Implements: Part IV §4.2 — L5 Session Scratchpad Tier
"""
L5 Session Scratchpad Tier.
Volatile, per-session working memory. Redis-backed for persistence across
agent restarts within a session. Expires at session end (default) or configurable TTL.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Default TTL for session data (4 hours — generous session window)
DEFAULT_SESSION_TTL = 14400


class L5ScratchpadTier:
    """
    Manages L5 Session Scratchpad memory.

    Properties:
        - Format: In-memory dict, Redis-backed for persistence across agent restarts
        - Mutability: Freely mutable
        - TTL: Expires at session end (default) or configurable TTL
    """

    def __init__(
        self,
        tenant_id: str,
        user_id: str,
        session_id: str,
        redis_client: Optional[Any] = None,
        ttl_seconds: int = DEFAULT_SESSION_TTL,
    ):
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.session_id = session_id
        self._redis = redis_client
        self._ttl = ttl_seconds
        self._local_cache: Dict[str, Any] = {}
        self._key_prefix = f"aegis:l5:{tenant_id}:{user_id}:{session_id}"

    def _make_key(self, key: str) -> str:
        """Generate the full Redis key for a scratchpad entry."""
        return f"{self._key_prefix}:{key}"

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """
        Store a value in the scratchpad.

        Args:
            key: The scratchpad key.
            value: Any JSON-serializable value.
            ttl: Optional TTL override for this specific entry.
        """
        self._local_cache[key] = value
        effective_ttl = ttl if ttl is not None else self._ttl

        if self._redis:
            try:
                redis_key = self._make_key(key)
                serialized = json.dumps(value)
                await self._redis.set(redis_key, serialized, ex=effective_ttl)
            except Exception as e:
                logger.warning(f"L5 Redis write failed (using local cache): {e}")

    async def get(self, key: str, default: Any = None) -> Any:
        """
        Retrieve a value from the scratchpad.

        Args:
            key: The scratchpad key.
            default: Default value if key not found.

        Returns:
            The stored value, or default.
        """
        # Check local cache first
        if key in self._local_cache:
            return self._local_cache[key]

        # Try Redis
        if self._redis:
            try:
                redis_key = self._make_key(key)
                raw = await self._redis.get(redis_key)
                if raw is not None:
                    value = json.loads(raw)
                    self._local_cache[key] = value
                    return value
            except Exception as e:
                logger.warning(f"L5 Redis read failed: {e}")

        return default

    async def delete(self, key: str) -> bool:
        """
        Delete a key from the scratchpad.

        Args:
            key: The key to delete.

        Returns:
            True if key existed and was deleted.
        """
        existed = key in self._local_cache
        self._local_cache.pop(key, None)

        if self._redis:
            try:
                redis_key = self._make_key(key)
                await self._redis.delete(redis_key)
            except Exception as e:
                logger.warning(f"L5 Redis delete failed: {e}")

        return existed

    async def get_all(self) -> Dict[str, Any]:
        """
        Retrieve all scratchpad entries for this session.

        Returns:
            Dictionary of all key-value pairs in the scratchpad.
        """
        # If we have Redis, scan for all session keys
        if self._redis:
            try:
                pattern = f"{self._key_prefix}:*"
                all_data = {}
                async for redis_key in self._redis.scan_iter(match=pattern):
                    key_name = redis_key.decode() if isinstance(redis_key, bytes) else redis_key
                    short_key = key_name.replace(f"{self._key_prefix}:", "", 1)
                    raw = await self._redis.get(redis_key)
                    if raw:
                        all_data[short_key] = json.loads(raw)
                # Merge with local cache (local takes precedence)
                all_data.update(self._local_cache)
                return all_data
            except Exception as e:
                logger.warning(f"L5 Redis scan failed, returning local cache: {e}")

        return dict(self._local_cache)

    async def get_context_fragments(self, query: str) -> List[Dict[str, Any]]:
        """
        Retrieve L5 content as context fragments for the Context Router.
        Returns all scratchpad content (it's session-scoped and small).

        Args:
            query: The search query (used for metadata; all L5 content is returned).

        Returns:
            List of context fragments from L5.
        """
        all_data = await self.get_all()
        if not all_data:
            return []

        # Serialize scratchpad as a single context fragment
        content_parts = []
        for key, value in all_data.items():
            if isinstance(value, str):
                content_parts.append(f"  {key}: {value}")
            else:
                content_parts.append(f"  {key}: {json.dumps(value)}")

        content = "Session Scratchpad:\n" + "\n".join(content_parts)

        return [{
            "tier": "L5",
            "content": content,
            "relevance": 0.9,  # Session context is highly relevant
            "metadata": {
                "session_id": self.session_id,
                "entry_count": len(all_data),
            },
        }]

    async def clear(self) -> int:
        """
        Clear all scratchpad entries for this session.
        Called at session end.

        Returns:
            Number of entries cleared.
        """
        count = len(self._local_cache)
        self._local_cache.clear()

        if self._redis:
            try:
                pattern = f"{self._key_prefix}:*"
                keys = []
                async for key in self._redis.scan_iter(match=pattern):
                    keys.append(key)
                if keys:
                    await self._redis.delete(*keys)
                    count = max(count, len(keys))
            except Exception as e:
                logger.warning(f"L5 Redis clear failed: {e}")

        logger.debug(f"L5 scratchpad cleared: {count} entries (session={self.session_id})")
        return count

    async def snapshot(self) -> Dict[str, Any]:
        """
        Create a snapshot of the current scratchpad state for persistence.
        Used for L5→L3 promotion review at session end.

        Returns:
            Snapshot dict with all entries and metadata.
        """
        all_data = await self.get_all()
        return {
            "session_id": self.session_id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "entries": all_data,
            "entry_count": len(all_data),
        }

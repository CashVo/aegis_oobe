# aegis/agents/oracle/rate_limiter.py
# Implements: Part II §2.1 — Rate limiting for Oracle requests
"""
Rate Limiter — Sliding-window rate limiter for Oracle LLM requests.
Prevents abuse and manages provider load by limiting requests per
tenant/user within configurable time windows.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

DEFAULT_MAX_REQUESTS_PER_MINUTE = 30
DEFAULT_MAX_REQUESTS_PER_HOUR = 500


class RateLimitExceededError(Exception):
    """Raised when a tenant/user exceeds their rate limit."""
    pass


class RateLimiter:
    """
    Sliding-window rate limiter for Oracle requests.

    Tracks request timestamps per (tenant_id, user_id) and enforces
    configurable per-minute and per-hour limits.
    """

    def __init__(self, config: dict | None = None) -> None:
        """
        Initialize the rate limiter.

        Args:
            config: Rate limit configuration.
        """
        config = config or {}
        self._rpm: int = config.get(
            "max_requests_per_minute", DEFAULT_MAX_REQUESTS_PER_MINUTE
        )
        self._rph: int = config.get(
            "max_requests_per_hour", DEFAULT_MAX_REQUESTS_PER_HOUR
        )
        self._enabled: bool = config.get("enabled", True)

        # Sliding window: {(tenant, user): deque of timestamps}
        self._windows: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def acquire(self, tenant_id: str, user_id: str) -> None:
        """
        Acquire a rate limit permit. Blocks if limit is reached (with timeout).

        Args:
            tenant_id: The tenant identifier.
            user_id: The user identifier.

        Raises:
            RateLimitExceededError: If the rate limit is exceeded.
        """
        if not self._enabled:
            return

        async with self._lock:
            key = (tenant_id, user_id)
            now = time.monotonic()
            window = self._windows[key]

            # Purge timestamps older than 1 hour
            cutoff_hour = now - 3600
            while window and window[0] < cutoff_hour:
                window.popleft()

            # Check per-hour limit
            if len(window) >= self._rph:
                logger.warning(
                    "rate_limiter.hourly_exceeded",
                    tenant_id=tenant_id,
                    user_id=user_id,
                    limit=self._rph,
                )
                raise RateLimitExceededError(
                    f"Hourly rate limit exceeded ({self._rph} requests/hour)"
                )

            # Check per-minute limit
            cutoff_minute = now - 60
            recent = sum(1 for ts in window if ts >= cutoff_minute)
            if recent >= self._rpm:
                logger.warning(
                    "rate_limiter.minute_exceeded",
                    tenant_id=tenant_id,
                    user_id=user_id,
                    limit=self._rpm,
                )
                raise RateLimitExceededError(
                    f"Per-minute rate limit exceeded ({self._rpm} requests/minute)"
                )

            # Record this request
            window.append(now)

    def get_remaining(self, tenant_id: str, user_id: str) -> dict[str, int]:
        """
        Check remaining request allowance for a tenant/user.

        Args:
            tenant_id: The tenant identifier.
            user_id: The user identifier.

        Returns:
            Dict with "remaining_per_minute" and "remaining_per_hour".
        """
        key = (tenant_id, user_id)
        now = time.monotonic()
        window = self._windows.get(key, deque())

        cutoff_minute = now - 60
        cutoff_hour = now - 3600

        recent_minute = sum(1 for ts in window if ts >= cutoff_minute)
        recent_hour = sum(1 for ts in window if ts >= cutoff_hour)

        return {
            "remaining_per_minute": max(0, self._rpm - recent_minute),
            "remaining_per_hour": max(0, self._rph - recent_hour),
        }

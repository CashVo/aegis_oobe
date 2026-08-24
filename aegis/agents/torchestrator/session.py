# aegis/agents/torchestrator/session.py
# Implements: Part II §2.1 — Multi-turn Session Management
# Implements: Part X §10.2 — Session persistence for CLI and Web chat
#
# Sessions are stored in-memory with Redis-backed persistence for durability.
# Each session maintains conversation history and contextual state.

import json
import logging
from aegis.utils import time
from typing import Dict, List, Optional

from aegis.schemas.torchestrator import (
    ConversationTurn,
    Session,
    SessionState,
)

logger = logging.getLogger(__name__)


class SessionManager:
    """
    Manages multi-turn conversation sessions.

    Provides:
    - Session creation and retrieval
    - Conversation history management
    - Session persistence via Redis (L5 scratchpad pattern)
    - Token budget tracking for context windows
    - Session lifecycle (active → paused → closed)
    """

    # Redis key prefix for session storage
    REDIS_PREFIX = "aegis:session:"
    # Maximum sessions kept in memory per user
    MAX_MEMORY_SESSIONS = 10
    # Default session TTL in seconds (24 hours)
    DEFAULT_TTL = 86400

    def __init__(self, redis_client=None):
        """
        Initialize SessionManager.

        Args:
            redis_client: An async Redis client for session persistence.
                         If None, sessions are in-memory only.
        """
        self.client = redis_client
        self._sessions: Dict[str, Session] = {}  # In-memory cache
        logger.info("SessionManager initialized (redis=%s)", "connected" if redis_client else "none")

    async def create_session(self, tenant_id: str, user_id: str, metadata: Optional[Dict] = None) -> Session:
        """
        Create a new conversation session.

        Args:
            tenant_id: The tenant this session belongs to.
            user_id: The user who owns this session.
            metadata: Optional metadata to attach to the session.

        Returns:
            A new Session instance.
        """
        session = Session(
            tenant_id=tenant_id,
            user_id=user_id,
            metadata=metadata or {}
        )
        self._sessions[session.session_id] = session

        # Persist to Redis if available
        await self._persist_session(session)

        logger.info(
            "Created session %s for user %s (tenant: %s)",
            session.session_id, user_id, tenant_id
        )
        return session

    async def get_session(self, session_id: str) -> Optional[Session]:
        """
        Retrieve a session by ID.

        Checks in-memory cache first, then Redis.

        Args:
            session_id: The session ID to look up.

        Returns:
            The Session if found, None otherwise.
        """
        # Check in-memory cache
        if session_id in self._sessions:
            return self._sessions[session_id]

        # Try Redis
        session = await self._load_session(session_id)
        if session:
            self._sessions[session_id] = session
            return session

        logger.warning("Session %s not found.", session_id)
        return None

    async def add_turn(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict] = None
    ) -> Optional[ConversationTurn]:
        """
        Add a conversation turn to a session.

        Args:
            session_id: Target session ID.
            role: "user" or "assistant"
            content: The message content.
            metadata: Optional metadata (tools_used, latency_ms, etc.)

        Returns:
            The created ConversationTurn, or None if session not found.
        """
        session = await self.get_session(session_id)
        if not session:
            logger.error("Cannot add turn: session %s not found.", session_id)
            return None

        if session.state == SessionState.CLOSED:
            logger.warning("Cannot add turn: session %s is closed.", session_id)
            return None

        turn = session.add_turn(role, content, metadata)

        # Persist updated session
        await self._persist_session(session)

        logger.debug(
            "Added %s turn to session %s (total turns: %d)",
            role, session_id, len(session.history)
        )
        return turn

    async def get_context_for_oracle(
        self,
        session_id: str,
        max_turns: int = 20,
        max_tokens: int = 4000
    ) -> str:
        """
        Build a conversation context string for Oracle prompts.

        Returns the recent conversation history formatted for LLM consumption.
        Respects token budget (approximate — uses character count heuristic).

        Args:
            session_id: The session to extract context from.
            max_turns: Maximum number of recent turns to include.
            max_tokens: Approximate token budget (1 token ≈ 4 chars).

        Returns:
            Formatted conversation history string.
        """
        session = await self.get_session(session_id)
        if not session:
            return ""

        recent = session.get_recent_history(max_turns)
        if not recent:
            return ""

        # Build context string, respecting approximate token budget
        max_chars = max_tokens * 4  # Rough token-to-char approximation
        context_parts: List[str] = []
        char_count = 0

        # Work backwards from most recent to prioritize recent context
        for turn in reversed(recent):
            entry = f"{turn.role.capitalize()}: {turn.content}"
            entry_len = len(entry)
            if char_count + entry_len > max_chars:
                break
            context_parts.insert(0, entry)
            char_count += entry_len

        return "\n".join(context_parts)

    async def list_sessions(
        self,
        tenant_id: str,
        user_id: str,
        state: Optional[SessionState] = None,
        limit: int = 20
    ) -> List[Session]:
        """
        List sessions for a user.

        Args:
            tenant_id: Filter by tenant.
            user_id: Filter by user.
            state: Optional filter by session state.
            limit: Maximum number of sessions to return.

        Returns:
            List of matching sessions, sorted by last_activity (newest first).
        """
        # Check in-memory sessions
        matching = [
            s for s in self._sessions.values()
            if s.tenant_id == tenant_id and s.user_id == user_id
            and (state is None or s.state == state)
        ]

        # If Redis is available and we have fewer than limit, check Redis
        if self.client and len(matching) < limit:
            pattern = f"{self.REDIS_PREFIX}{tenant_id}:{user_id}:*"
            try:
                keys = []
                async for key in self.client.scan_iter(match=pattern, count=100):
                    keys.append(key)
                    if len(keys) >= limit * 2:  # Fetch extra for filtering
                        break

                for key in keys:
                    key_str = key.decode() if isinstance(key, bytes) else key
                    session_id = key_str.split(":")[-1]
                    if session_id not in self._sessions:
                        session = await self._load_session(session_id)
                        if session and (state is None or session.state == state):
                            matching.append(session)
                            self._sessions[session_id] = session
            except Exception as e:
                logger.warning("Failed to list sessions from Redis: %s", e)

        # Sort by last activity, newest first
        matching.sort(key=lambda s: s.last_activity, reverse=True)
        return matching[:limit]

    async def close_session(self, session_id: str) -> bool:
        """
        Close a session (marks it as closed, persists final state).

        Args:
            session_id: The session to close.

        Returns:
            True if successfully closed, False if session not found.
        """
        session = await self.get_session(session_id)
        if not session:
            return False

        session.state = SessionState.CLOSED
        await self._persist_session(session)
        logger.info("Closed session %s", session_id)
        return True

    async def pause_session(self, session_id: str) -> bool:
        """Pause a session (can be resumed later)."""
        session = await self.get_session(session_id)
        if not session:
            return False

        session.state = SessionState.PAUSED
        await self._persist_session(session)
        logger.info("Paused session %s", session_id)
        return True

    async def resume_session(self, session_id: str) -> Optional[Session]:
        """Resume a paused session."""
        session = await self.get_session(session_id)
        if not session:
            return None

        if session.state == SessionState.CLOSED:
            logger.warning("Cannot resume closed session %s", session_id)
            return None

        session.state = SessionState.ACTIVE
        session.last_activity = time.utcnow()
        await self._persist_session(session)
        logger.info("Resumed session %s", session_id)
        return session

    # ─── Persistence Layer ───────────────────────────────────────────

    async def _persist_session(self, session: Session) -> None:
        """Persist session to Redis."""
        if not self.client:
            return

        key = f"{self.REDIS_PREFIX}{session.tenant_id}:{session.user_id}:{session.session_id}"
        try:
            data = session.model_dump_json()
            await self.client.set(key, data, ex=self.DEFAULT_TTL)
        except Exception as e:
            logger.error("Failed to persist session %s: %s", session.session_id, e)

    async def _load_session(self, session_id: str) -> Optional[Session]:
        """Load session from Redis by scanning for matching key."""
        if not self.client:
            return None

        try:
            # We need to scan for the session since we don't know tenant/user
            pattern = f"{self.REDIS_PREFIX}*:{session_id}"
            async for key in self.client.scan_iter(match=pattern, count=100):
                data = await self.client.get(key)
                if data:
                    data_str = data.decode() if isinstance(data, bytes) else data
                    return Session.model_validate_json(data_str)
        except Exception as e:
            logger.warning("Failed to load session %s from Redis: %s", session_id, e)

        return None

    async def cleanup_expired(self) -> int:
        """Remove expired/closed sessions from in-memory cache."""
        to_remove = [
            sid for sid, s in self._sessions.items()
            if s.state == SessionState.CLOSED
        ]
        for sid in to_remove:
            del self._sessions[sid]
        if to_remove:
            logger.info("Cleaned up %d closed sessions from memory.", len(to_remove))
        return len(to_remove)

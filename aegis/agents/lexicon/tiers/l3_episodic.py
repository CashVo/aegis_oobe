# aegis/agents/lexicon/tiers/l3_episodic.py
# Implements: Part IV §4.2 — L3 Episodic Memory Tier
"""
L3 Episodic Memory Tier.
Timestamped, append-only log of events, conversations, decisions, and outcomes.
Features FTS5 full-text search. Configurable retention (default: 365 days).
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

import aiosqlite

from aegis.agents.lexicon.storage import get_memory_db_path

logger = logging.getLogger(__name__)


class L3EpisodicTier:
    """
    Manages L3 Episodic Memory.

    Properties:
        - Format: SQLite table (l3_episodic) with FTS5 index
        - Mutability: Append-only
        - TTL: Configurable retention (default 365 days)
    """

    def __init__(
        self,
        tenant_id: str,
        user_id: str,
        base_dir: Optional[str] = None,
        retention_days: int = 365,
    ):
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.retention_days = retention_days
        self._db_path = str(get_memory_db_path(tenant_id, user_id, base_dir))

    async def append(
        self,
        content: str,
        event_type: str = "general",
        tags: Optional[List[str]] = None,
        source: Optional[str] = None,
        session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Append a new episodic memory entry (append-only — no updates).

        Args:
            content: The episodic content (event description, conversation snippet, etc.).
            event_type: Type categorization ('decision', 'conversation', 'outcome', 'event').
            tags: Optional tags for categorization.
            source: Origin of this memory.
            session_id: The session this memory belongs to (for L5→L3 promotion).
            metadata: Additional metadata.

        Returns:
            The entry_id of the appended entry.
        """
        entry_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()

        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO l3_episodic
                    (entry_id, content, event_type, tags, source, session_id, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry_id,
                    content,
                    event_type,
                    json.dumps(tags or []),
                    source,
                    session_id,
                    json.dumps(metadata or {}),
                    now,
                ),
            )
            await db.commit()

        logger.debug(f"L3 episodic entry appended: {entry_id} (type={event_type})")
        return entry_id

    async def search_fts(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Full-text search using FTS5 index.

        Args:
            query: Search query (supports FTS5 syntax: AND, OR, NOT, phrases).
            limit: Maximum results.

        Returns:
            List of matching episodic entries ordered by relevance.
        """
        results = []
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            try:
                async with db.execute(
                    """
                    SELECT e.*, rank
                    FROM l3_episodic e
                    JOIN l3_episodic_fts fts ON e.rowid = fts.rowid
                    WHERE l3_episodic_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (query, limit),
                ) as cursor:
                    rows = await cursor.fetchall()

                for row in rows:
                    # FTS5 rank is negative (closer to 0 = more relevant)
                    raw_rank = abs(row["rank"]) if row["rank"] else 1.0
                    relevance = 1.0 / (1.0 + raw_rank)

                    results.append({
                        "entry_id": row["entry_id"],
                        "content": row["content"],
                        "event_type": row["event_type"],
                        "tags": json.loads(row["tags"]),
                        "source": row["source"],
                        "session_id": row["session_id"],
                        "created_at": row["created_at"],
                        "relevance": relevance,
                    })
            except Exception as e:
                # Fallback to basic search if FTS query syntax is invalid
                logger.warning(f"FTS5 search failed, falling back to LIKE: {e}")
                results = await self._search_fallback(query, limit)

        return results

    async def _search_fallback(self, query: str, limit: int) -> List[Dict[str, Any]]:
        """Fallback keyword search when FTS5 query fails."""
        results = []
        query_lower = query.lower()
        query_terms = query_lower.split()

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM l3_episodic ORDER BY created_at DESC LIMIT ?",
                (limit * 5,),
            ) as cursor:
                rows = await cursor.fetchall()

            for row in rows:
                content_lower = row["content"].lower()
                score = sum(
                    1.0 / len(query_terms)
                    for term in query_terms
                    if term in content_lower
                )
                if score > 0:
                    results.append({
                        "entry_id": row["entry_id"],
                        "content": row["content"],
                        "event_type": row["event_type"],
                        "tags": json.loads(row["tags"]),
                        "source": row["source"],
                        "session_id": row["session_id"],
                        "created_at": row["created_at"],
                        "relevance": min(score, 1.0),
                    })

        results.sort(key=lambda x: x["relevance"], reverse=True)
        return results[:limit]

    async def search_by_recency(
        self,
        limit: int = 20,
        event_type: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve most recent episodic entries.

        Args:
            limit: Maximum entries to return.
            event_type: Optional filter by event type.
            session_id: Optional filter by session.

        Returns:
            List of recent entries ordered by creation time (newest first).
        """
        results = []
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row

            sql = "SELECT * FROM l3_episodic WHERE 1=1"
            params: List[Any] = []

            if event_type:
                sql += " AND event_type = ?"
                params.append(event_type)
            if session_id:
                sql += " AND session_id = ?"
                params.append(session_id)

            sql += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)

            async with db.execute(sql, params) as cursor:
                rows = await cursor.fetchall()

            for row in rows:
                results.append({
                    "entry_id": row["entry_id"],
                    "content": row["content"],
                    "event_type": row["event_type"],
                    "tags": json.loads(row["tags"]),
                    "source": row["source"],
                    "session_id": row["session_id"],
                    "created_at": row["created_at"],
                    "relevance": 0.8,  # Recency-based default relevance
                })

        return results

    async def get_context_fragments(
        self, query: str, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Retrieve L3 content as context fragments for the Context Router."""
        # Use FTS for semantic relevance
        results = await self.search_fts(query, limit=limit)
        return [
            {
                "tier": "L3",
                "content": r["content"],
                "relevance": r["relevance"],
                "metadata": {
                    "entry_id": r["entry_id"],
                    "event_type": r["event_type"],
                    "created_at": r["created_at"],
                    "tags": r["tags"],
                },
            }
            for r in results
        ]

    async def evict_expired(self) -> int:
        """
        Remove entries older than the retention period.
        Called by the Memory Governor during eviction runs.

        Returns:
            Number of entries evicted.
        """
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=self.retention_days)
        ).isoformat()

        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "DELETE FROM l3_episodic WHERE created_at < ?",
                (cutoff,),
            )
            evicted = cursor.rowcount
            await db.commit()

        if evicted > 0:
            logger.info(f"L3 eviction: removed {evicted} entries older than {self.retention_days} days")
        return evicted

    async def count(self) -> int:
        """Return the total number of L3 entries."""
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM l3_episodic") as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

    async def get_by_id(self, entry_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a specific L3 entry by ID."""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM l3_episodic WHERE entry_id = ?", (entry_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return {
                        "entry_id": row["entry_id"],
                        "content": row["content"],
                        "event_type": row["event_type"],
                        "tags": json.loads(row["tags"]),
                        "source": row["source"],
                        "session_id": row["session_id"],
                        "metadata": json.loads(row["metadata"]),
                        "created_at": row["created_at"],
                    }
        return None

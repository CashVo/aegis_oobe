# aegis/agents/lexicon/tiers/l1_domain.py
# Implements: Part IV §4.2 — L1 Domain Knowledge Tier
"""
L1 Domain Knowledge Tier.
Factual knowledge for specific domains, stored in SQLite.
Agent-writable via the promotion pipeline. Permanent retention.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

import aiosqlite

from aegis.agents.lexicon.storage import get_memory_db_path

logger = logging.getLogger(__name__)


class L1DomainTier:
    """
    Manages L1 Domain Knowledge memory.

    Properties:
        - Format: SQLite table (l1_domain)
        - Mutability: Agent-writable via promotion pipeline
        - TTL: Permanent
    """

    def __init__(self, tenant_id: str, user_id: str, base_dir: Optional[str] = None):
        self.tenant_id = tenant_id
        self.user_id = user_id
        self._db_path = str(get_memory_db_path(tenant_id, user_id, base_dir))

    async def store(
        self,
        content: str,
        category: str = "general",
        tags: Optional[List[str]] = None,
        source: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Store a new domain knowledge entry.

        Args:
            content: The knowledge content.
            category: Knowledge category (e.g., 'python', 'devops').
            tags: Optional tags for categorization.
            source: Origin of this knowledge.
            metadata: Additional metadata.

        Returns:
            The entry_id of the stored entry.
        """
        entry_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()

        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO l1_domain (entry_id, content, category, tags, source, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry_id,
                    content,
                    category,
                    json.dumps(tags or []),
                    source,
                    json.dumps(metadata or {}),
                    now,
                ),
            )
            await db.commit()

        logger.debug(f"L1 entry stored: {entry_id} (category={category})")
        return entry_id

    async def search(
        self,
        query: str,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Search L1 domain knowledge using keyword matching.

        Args:
            query: Search query string.
            category: Optional category filter.
            tags: Optional tag filter (entries must have ALL specified tags).
            limit: Maximum results to return.

        Returns:
            List of matching entries with relevance scoring.
        """
        results = []
        query_lower = query.lower()
        query_terms = query_lower.split()

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row

            sql = "SELECT * FROM l1_domain WHERE 1=1"
            params: List[Any] = []

            if category:
                sql += " AND category = ?"
                params.append(category)

            sql += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit * 3)  # Over-fetch for relevance filtering

            async with db.execute(sql, params) as cursor:
                rows = await cursor.fetchall()

            for row in rows:
                content_lower = row["content"].lower()
                row_tags = json.loads(row["tags"])

                # Tag filter
                if tags and not all(t in row_tags for t in tags):
                    continue

                # Simple relevance scoring based on term matches
                score = 0.0
                for term in query_terms:
                    if term in content_lower:
                        score += 1.0 / len(query_terms)
                    if term in " ".join(row_tags).lower():
                        score += 0.3 / len(query_terms)

                if score > 0:
                    results.append({
                        "entry_id": row["entry_id"],
                        "content": row["content"],
                        "category": row["category"],
                        "tags": row_tags,
                        "source": row["source"],
                        "metadata": json.loads(row["metadata"]),
                        "created_at": row["created_at"],
                        "relevance": min(score, 1.0),
                    })

        # Sort by relevance descending
        results.sort(key=lambda x: x["relevance"], reverse=True)
        return results[:limit]

    async def get_context_fragments(
        self, query: str, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Retrieve L1 content as context fragments for the Context Router.

        Args:
            query: The search query for relevance ranking.
            limit: Max fragments to return.

        Returns:
            List of context fragment dicts.
        """
        results = await self.search(query, limit=limit)
        return [
            {
                "tier": "L1",
                "content": r["content"],
                "relevance": r["relevance"],
                "metadata": {
                    "entry_id": r["entry_id"],
                    "category": r["category"],
                    "tags": r["tags"],
                },
            }
            for r in results
        ]

    async def count(self) -> int:
        """Return the total number of L1 entries."""
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM l1_domain") as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

    async def get_by_id(self, entry_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a specific L1 entry by ID."""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM l1_domain WHERE entry_id = ?", (entry_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return {
                        "entry_id": row["entry_id"],
                        "content": row["content"],
                        "category": row["category"],
                        "tags": json.loads(row["tags"]),
                        "source": row["source"],
                        "metadata": json.loads(row["metadata"]),
                        "created_at": row["created_at"],
                        "updated_at": row["updated_at"],
                    }
        return None

    async def deprecate(self, entry_id: str) -> bool:
        """
        Mark an entry as deprecated (soft delete — never auto-deleted per spec).

        Args:
            entry_id: The entry to deprecate.

        Returns:
            True if entry was found and updated, False otherwise.
        """
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                """
                UPDATE l1_domain
                SET metadata = json_set(COALESCE(metadata, '{}'), '$.deprecated', true),
                    updated_at = ?
                WHERE entry_id = ?
                """,
                (now, entry_id),
            )
            await db.commit()
            return cursor.rowcount > 0

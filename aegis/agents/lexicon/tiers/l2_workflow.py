# aegis/agents/lexicon/tiers/l2_workflow.py
# Implements: Part IV §4.2 — L2 Workflow Calibration Tier
"""
L2 Workflow Calibration Tier.
Procedural memory about how the user works — preferred formats, tools,
conventions, and recurring patterns. Stored in SQLite.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

import aiosqlite

from aegis.agents.lexicon.storage import get_memory_db_path

logger = logging.getLogger(__name__)


class L2WorkflowTier:
    """
    Manages L2 Workflow Calibration memory.

    Properties:
        - Format: SQLite table (l2_workflow)
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
        pattern_type: str = "general",
        tags: Optional[List[str]] = None,
        source: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        confidence: float = 0.5,
    ) -> str:
        """
        Store a new workflow pattern.

        Args:
            content: Description of the workflow pattern.
            pattern_type: Type of pattern (e.g., 'format_preference', 'tool_usage', 'convention').
            tags: Optional categorization tags.
            source: Where this pattern was observed.
            metadata: Additional metadata.
            confidence: Initial confidence score (0.0–1.0).

        Returns:
            The entry_id of the stored pattern.
        """
        entry_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()

        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO l2_workflow
                    (entry_id, content, pattern_type, tags, source, metadata, confidence, occurrence_count, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry_id,
                    content,
                    pattern_type,
                    json.dumps(tags or []),
                    source,
                    json.dumps(metadata or {}),
                    confidence,
                    1,
                    now,
                ),
            )
            await db.commit()

        logger.debug(f"L2 pattern stored: {entry_id} (type={pattern_type})")
        return entry_id

    async def reinforce(self, entry_id: str, confidence_boost: float = 0.1) -> bool:
        """
        Reinforce an existing pattern (increase confidence and occurrence count).
        Called when the same pattern is observed again.

        Args:
            entry_id: The pattern entry to reinforce.
            confidence_boost: Amount to increase confidence (capped at 1.0).

        Returns:
            True if pattern was found and updated.
        """
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                """
                UPDATE l2_workflow
                SET confidence = MIN(confidence + ?, 1.0),
                    occurrence_count = occurrence_count + 1,
                    updated_at = ?
                WHERE entry_id = ?
                """,
                (confidence_boost, now, entry_id),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def search(
        self,
        query: str,
        pattern_type: Optional[str] = None,
        min_confidence: float = 0.0,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Search L2 workflow patterns.

        Args:
            query: Search query string.
            pattern_type: Optional filter by pattern type.
            min_confidence: Minimum confidence threshold.
            limit: Maximum results.

        Returns:
            List of matching workflow patterns with relevance scores.
        """
        results = []
        query_lower = query.lower()
        query_terms = query_lower.split()

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row

            sql = "SELECT * FROM l2_workflow WHERE confidence >= ?"
            params: List[Any] = [min_confidence]

            if pattern_type:
                sql += " AND pattern_type = ?"
                params.append(pattern_type)

            sql += " ORDER BY confidence DESC, occurrence_count DESC LIMIT ?"
            params.append(limit * 3)

            async with db.execute(sql, params) as cursor:
                rows = await cursor.fetchall()

            for row in rows:
                content_lower = row["content"].lower()

                # Relevance scoring
                score = 0.0
                for term in query_terms:
                    if term in content_lower:
                        score += 1.0 / len(query_terms)

                # Boost by confidence
                score *= (0.5 + 0.5 * row["confidence"])

                if score > 0:
                    results.append({
                        "entry_id": row["entry_id"],
                        "content": row["content"],
                        "pattern_type": row["pattern_type"],
                        "tags": json.loads(row["tags"]),
                        "confidence": row["confidence"],
                        "occurrence_count": row["occurrence_count"],
                        "source": row["source"],
                        "created_at": row["created_at"],
                        "relevance": min(score, 1.0),
                    })

        results.sort(key=lambda x: x["relevance"], reverse=True)
        return results[:limit]

    async def get_context_fragments(
        self, query: str, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Retrieve L2 content as context fragments for the Context Router."""
        results = await self.search(query, limit=limit)
        return [
            {
                "tier": "L2",
                "content": r["content"],
                "relevance": r["relevance"],
                "metadata": {
                    "entry_id": r["entry_id"],
                    "pattern_type": r["pattern_type"],
                    "confidence": r["confidence"],
                    "occurrence_count": r["occurrence_count"],
                },
            }
            for r in results
        ]

    async def count(self) -> int:
        """Return the total number of L2 entries."""
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM l2_workflow") as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

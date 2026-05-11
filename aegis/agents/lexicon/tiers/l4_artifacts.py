# aegis/agents/lexicon/tiers/l4_artifacts.py
# Implements: Part IV §4.2 — L4 Artifact Index Tier
"""
L4 Artifact Index Tier.
Metadata index of user-referenced files, documents, URLs, and external resources.
Stores pointers, not content. Permanent retention for metadata.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

import aiosqlite

from aegis.agents.lexicon.storage import get_memory_db_path

logger = logging.getLogger(__name__)


class L4ArtifactTier:
    """
    Manages L4 Artifact Index memory.

    Properties:
        - Format: SQLite table (l4_artifacts)
        - Mutability: Agent-writable
        - TTL: Permanent (metadata); content freshness validated on access
    """

    def __init__(self, tenant_id: str, user_id: str, base_dir: Optional[str] = None):
        self.tenant_id = tenant_id
        self.user_id = user_id
        self._db_path = str(get_memory_db_path(tenant_id, user_id, base_dir))

    async def store(
        self,
        name: str,
        artifact_type: str,
        path_or_uri: str,
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Store a new artifact reference.

        Args:
            name: Human-readable name of the artifact.
            artifact_type: Type ('file', 'url', 'document', 'image').
            path_or_uri: The path or URI pointing to the artifact.
            description: Optional description.
            tags: Optional tags.
            metadata: Additional metadata.

        Returns:
            The entry_id of the stored artifact reference.
        """
        entry_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()

        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO l4_artifacts
                    (entry_id, name, artifact_type, path_or_uri, description, tags, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry_id,
                    name,
                    artifact_type,
                    path_or_uri,
                    description,
                    json.dumps(tags or []),
                    json.dumps(metadata or {}),
                    now,
                ),
            )
            await db.commit()

        logger.debug(f"L4 artifact stored: {entry_id} ({artifact_type}: {name})")
        return entry_id

    async def search(
        self,
        query: str,
        artifact_type: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Search artifact index.

        Args:
            query: Search query matching name, description, or path.
            artifact_type: Optional type filter.
            tags: Optional tag filter.
            limit: Maximum results.

        Returns:
            List of matching artifacts with relevance scores.
        """
        results = []
        query_lower = query.lower()
        query_terms = query_lower.split()

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row

            sql = "SELECT * FROM l4_artifacts WHERE 1=1"
            params: List[Any] = []

            if artifact_type:
                sql += " AND artifact_type = ?"
                params.append(artifact_type)

            sql += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit * 3)

            async with db.execute(sql, params) as cursor:
                rows = await cursor.fetchall()

            for row in rows:
                row_tags = json.loads(row["tags"])
                if tags and not all(t in row_tags for t in tags):
                    continue

                # Score across name, description, path
                searchable = f"{row['name']} {row['description'] or ''} {row['path_or_uri']}".lower()
                score = sum(
                    1.0 / len(query_terms)
                    for term in query_terms
                    if term in searchable
                )

                if score > 0:
                    results.append({
                        "entry_id": row["entry_id"],
                        "name": row["name"],
                        "artifact_type": row["artifact_type"],
                        "path_or_uri": row["path_or_uri"],
                        "description": row["description"],
                        "tags": row_tags,
                        "metadata": json.loads(row["metadata"]),
                        "last_validated": row["last_validated"],
                        "created_at": row["created_at"],
                        "relevance": min(score, 1.0),
                    })

        results.sort(key=lambda x: x["relevance"], reverse=True)
        return results[:limit]

    async def get_context_fragments(
        self, query: str, limit: int = 5
    ) -> List[Dict[str, Any]]:
        """Retrieve L4 content as context fragments for the Context Router."""
        results = await self.search(query, limit=limit)
        return [
            {
                "tier": "L4",
                "content": f"[{r['artifact_type']}] {r['name']}: {r['description'] or r['path_or_uri']}",
                "relevance": r["relevance"],
                "metadata": {
                    "entry_id": r["entry_id"],
                    "artifact_type": r["artifact_type"],
                    "path_or_uri": r["path_or_uri"],
                },
            }
            for r in results
        ]

    async def validate_artifact(self, entry_id: str) -> bool:
        """
        Mark an artifact as validated (freshness check passed).

        Args:
            entry_id: The artifact to validate.

        Returns:
            True if updated, False if not found.
        """
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "UPDATE l4_artifacts SET last_validated = ? WHERE entry_id = ?",
                (now, entry_id),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def count(self) -> int:
        """Return the total number of L4 entries."""
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM l4_artifacts") as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

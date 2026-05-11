# aegis/agents/janus/storage.py
"""
Policy Storage — SQLite-backed persistence for governance rules.

Implements: Part XIV, CHUNK-007 — Policy storage deliverable.
"""

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from aegis.schemas.janus import PolicyRule

logger = logging.getLogger(__name__)


class PolicyStore:
    """
    SQLite-backed policy storage with full CRUD operations.

    Policies are stored per-tenant (tenant_id=None means system-wide).
    Thread-safe via SQLite's built-in locking.
    """

    def __init__(self, db_path: str | Path):
        """
        Initialize the PolicyStore.

        Args:
            db_path: Path to the SQLite database file for policy storage.
        """
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._initialize_db()

    def _initialize_db(self) -> None:
        """Create the policies table if it does not exist."""
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS policies (
                rule_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                condition TEXT NOT NULL,
                action_on_match TEXT NOT NULL,
                priority INTEGER DEFAULT 0,
                active INTEGER DEFAULT 1,
                tenant_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                tags TEXT DEFAULT '[]'
            )
        """)
        # Index for fast tenant-scoped lookups
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_policies_tenant
            ON policies(tenant_id, active, priority DESC)
        """)
        self._conn.commit()
        logger.info(f"PolicyStore initialized at: {self._db_path}")

    def add_policy(self, rule: PolicyRule) -> PolicyRule:
        """
        Add a new policy rule to the store.

        Args:
            rule: The PolicyRule to persist.

        Returns:
            The persisted PolicyRule.

        Raises:
            ValueError: If a rule with the same rule_id already exists.
        """
        existing = self.get_policy(rule.rule_id)
        if existing is not None:
            raise ValueError(f"Policy with rule_id '{rule.rule_id}' already exists.")

        self._conn.execute(
            """
            INSERT INTO policies
                (rule_id, name, description, condition, action_on_match,
                 priority, active, tenant_id, created_at, updated_at, tags)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rule.rule_id,
                rule.name,
                rule.description,
                rule.condition,
                rule.action_on_match,
                rule.priority,
                int(rule.active),
                rule.tenant_id,
                rule.created_at.isoformat(),
                rule.updated_at.isoformat(),
                json.dumps(rule.tags),
            ),
        )
        self._conn.commit()
        logger.debug(f"Policy added: {rule.rule_id} ({rule.name})")
        return rule

    def get_policy(self, rule_id: str) -> Optional[PolicyRule]:
        """
        Retrieve a single policy by its rule_id.

        Args:
            rule_id: The unique identifier of the policy.

        Returns:
            The PolicyRule if found, else None.
        """
        cursor = self._conn.execute(
            "SELECT * FROM policies WHERE rule_id = ?", (rule_id,)
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_policy(row)

    def update_policy(self, rule: PolicyRule) -> PolicyRule:
        """
        Update an existing policy rule.

        Args:
            rule: The PolicyRule with updated fields.

        Returns:
            The updated PolicyRule.

        Raises:
            ValueError: If the policy does not exist.
        """
        existing = self.get_policy(rule.rule_id)
        if existing is None:
            raise ValueError(f"Policy with rule_id '{rule.rule_id}' not found.")

        now = datetime.now(timezone.utc)
        self._conn.execute(
            """
            UPDATE policies SET
                name = ?, description = ?, condition = ?, action_on_match = ?,
                priority = ?, active = ?, tenant_id = ?, updated_at = ?, tags = ?
            WHERE rule_id = ?
            """,
            (
                rule.name,
                rule.description,
                rule.condition,
                rule.action_on_match,
                rule.priority,
                int(rule.active),
                rule.tenant_id,
                now.isoformat(),
                json.dumps(rule.tags),
                rule.rule_id,
            ),
        )
        self._conn.commit()
        rule.updated_at = now
        logger.debug(f"Policy updated: {rule.rule_id} ({rule.name})")
        return rule

    def delete_policy(self, rule_id: str) -> bool:
        """
        Delete a policy by rule_id.

        Args:
            rule_id: The unique identifier of the policy to delete.

        Returns:
            True if deleted, False if not found.
        """
        cursor = self._conn.execute(
            "DELETE FROM policies WHERE rule_id = ?", (rule_id,)
        )
        self._conn.commit()
        deleted = cursor.rowcount > 0
        if deleted:
            logger.debug(f"Policy deleted: {rule_id}")
        return deleted

    def list_policies(
        self,
        tenant_id: Optional[str] = None,
        active_only: bool = True,
        tags: Optional[list[str]] = None,
    ) -> list[PolicyRule]:
        """
        List policies with optional filtering.

        Args:
            tenant_id: If provided, return tenant-specific + system-wide policies.
                       If None, return only system-wide policies.
            active_only: If True, return only active policies.
            tags: If provided, filter by policies containing ANY of these tags.

        Returns:
            List of matching PolicyRule objects, ordered by priority descending.
        """
        query = "SELECT * FROM policies WHERE 1=1"
        params: list = []

        if tenant_id is not None:
            # Return both tenant-specific and system-wide (tenant_id IS NULL) policies
            query += " AND (tenant_id = ? OR tenant_id IS NULL)"
            params.append(tenant_id)
        else:
            query += " AND tenant_id IS NULL"

        if active_only:
            query += " AND active = 1"

        query += " ORDER BY priority DESC, created_at ASC"

        cursor = self._conn.execute(query, params)
        policies = [self._row_to_policy(row) for row in cursor.fetchall()]

        # Filter by tags if specified (post-query since tags are JSON)
        if tags:
            tag_set = set(tags)
            policies = [p for p in policies if tag_set & set(p.tags)]

        return policies

    def get_policies_for_evaluation(self, tenant_id: Optional[str] = None) -> list[PolicyRule]:
        """
        Retrieve all active policies applicable for evaluation, ordered by priority.

        This is the primary method used by the PolicyEngine during evaluation.
        Returns system-wide + tenant-scoped policies, sorted by priority DESC.

        Args:
            tenant_id: The tenant context for evaluation.

        Returns:
            Sorted list of active PolicyRule objects.
        """
        return self.list_policies(tenant_id=tenant_id, active_only=True)

    def count_policies(self, tenant_id: Optional[str] = None) -> int:
        """Return the count of policies (optionally filtered by tenant)."""
        if tenant_id is not None:
            cursor = self._conn.execute(
                "SELECT COUNT(*) FROM policies WHERE (tenant_id = ? OR tenant_id IS NULL)",
                (tenant_id,),
            )
        else:
            cursor = self._conn.execute("SELECT COUNT(*) FROM policies")
        return cursor.fetchone()[0]

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
            logger.debug("PolicyStore connection closed.")

    def _row_to_policy(self, row: sqlite3.Row) -> PolicyRule:
        """Convert a database row to a PolicyRule model."""
        return PolicyRule(
            rule_id=row["rule_id"],
            name=row["name"],
            description=row["description"],
            condition=row["condition"],
            action_on_match=row["action_on_match"],
            priority=row["priority"],
            active=bool(row["active"]),
            tenant_id=row["tenant_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            tags=json.loads(row["tags"]),
        )

# aegis/agents/lexicon/storage.py
# Implements: Part IV §4.2 — Storage Layout & SQLite Schema Management
"""
Storage manager for Lexicon.
Handles path resolution, SQLite database initialization, and schema management
for memory tiers L1–L4.
"""

import logging
import os
from pathlib import Path
from typing import Optional

import aiosqlite

logger = logging.getLogger(__name__)

# Default base data directory
DEFAULT_DATA_DIR = "aegis_data"


def get_user_data_path(
    tenant_id: str,
    user_id: str,
    base_dir: Optional[str] = None
) -> Path:
    """
    Resolve the data directory path for a specific tenant/user.

    Storage Layout (from spec §4.2):
        aegis_data/{tenant_id}/{user_id}/

    Args:
        tenant_id: The tenant identifier.
        user_id: The user identifier.
        base_dir: Override for the base data directory.

    Returns:
        Path to the user's data directory.
    """
    base = Path(base_dir) if base_dir else Path(DEFAULT_DATA_DIR)
    return base / tenant_id / user_id


def get_memory_db_path(
    tenant_id: str,
    user_id: str,
    base_dir: Optional[str] = None
) -> Path:
    """Get path to the user's memory.db SQLite database."""
    return get_user_data_path(tenant_id, user_id, base_dir) / "memory.db"


def get_l0_path(
    tenant_id: str,
    user_id: str,
    base_dir: Optional[str] = None
) -> Path:
    """Get path to the user's l0_identity.yaml file."""
    return get_user_data_path(tenant_id, user_id, base_dir) / "l0_identity.yaml"


def get_sessions_dir(
    tenant_id: str,
    user_id: str,
    base_dir: Optional[str] = None
) -> Path:
    """Get path to the user's sessions directory (L5 scratchpad snapshots)."""
    return get_user_data_path(tenant_id, user_id, base_dir) / "sessions"


async def ensure_user_storage(
    tenant_id: str,
    user_id: str,
    base_dir: Optional[str] = None
) -> Path:
    """
    Ensure the complete storage structure exists for a user.
    Creates directories and initializes the SQLite database with all tier schemas.

    Args:
        tenant_id: The tenant identifier.
        user_id: The user identifier.
        base_dir: Override for the base data directory.

    Returns:
        Path to the user's data directory.
    """
    user_path = get_user_data_path(tenant_id, user_id, base_dir)

    # Create directory structure
    user_path.mkdir(parents=True, exist_ok=True)
    (user_path / "sessions").mkdir(exist_ok=True)

    # Create l0_identity.yaml if it doesn't exist
    l0_path = user_path / "l0_identity.yaml"
    if not l0_path.exists():
        l0_path.write_text(_default_l0_template(user_id), encoding="utf-8", newline="\n")
        logger.info(f"Created default L0 identity file: {l0_path}")

    # Initialize SQLite database with tier schemas
    db_path = user_path / "memory.db"
    await _init_memory_db(db_path)

    logger.info(f"Storage initialized for tenant={tenant_id}, user={user_id}")
    return user_path


def _default_l0_template(user_id: str) -> str:
    """Generate a default L0 identity YAML template."""
    return f"""# L0 Core Identity — User Constitution
# This file is USER-EDITABLE ONLY. Agents may suggest updates but cannot modify directly.
# user_id: {user_id}

identity:
  display_name: ""
  description: "A new Aegis user."

principles: []
  # - "Example: Always prioritize clarity over brevity."

values: []
  # - "Example: Continuous learning."

preferences:
  communication_style: "balanced"
  detail_level: "standard"
  # Add custom preferences here.

domains: []
  # - name: "Example Domain"
  #   description: "Knowledge area description."
"""


async def _init_memory_db(db_path: Path) -> None:
    """
    Initialize the SQLite memory database with schemas for L1–L4 tiers.

    Tier Table Descriptions:
        - l1_domain: Factual domain knowledge (permanent, agent-writable via promotion).
        - l2_workflow: Procedural/workflow calibration memory (permanent, agent-writable).
        - l3_episodic: Timestamped episodic log with FTS5 index (append-only, retention policy).
        - l4_artifacts: Metadata index of external artifacts/resources (permanent pointers).
    """
    async with aiosqlite.connect(str(db_path)) as db:
        # Enable WAL mode for better concurrent read performance
        await db.execute("PRAGMA journal_mode=WAL")

        # L1: Domain Knowledge
        await db.execute("""
            CREATE TABLE IF NOT EXISTS l1_domain (
                entry_id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                tags TEXT DEFAULT '[]',
                source TEXT,
                metadata TEXT DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT
            )
        """)

        # L2: Workflow Calibration
        await db.execute("""
            CREATE TABLE IF NOT EXISTS l2_workflow (
                entry_id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                pattern_type TEXT DEFAULT 'general',
                tags TEXT DEFAULT '[]',
                source TEXT,
                metadata TEXT DEFAULT '{}',
                confidence REAL DEFAULT 0.5,
                occurrence_count INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT
            )
        """)

        # L3: Episodic Memory (append-only with FTS5 for full-text search)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS l3_episodic (
                entry_id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                event_type TEXT DEFAULT 'general',
                tags TEXT DEFAULT '[]',
                source TEXT,
                session_id TEXT,
                metadata TEXT DEFAULT '{}',
                created_at TEXT NOT NULL
            )
        """)

        # L3 FTS5 virtual table for full-text search
        await db.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS l3_episodic_fts USING fts5(
                content,
                tags,
                event_type,
                content_rowid='rowid',
                tokenize='porter'
            )
        """)

        # Trigger to keep FTS5 in sync with l3_episodic
        await db.execute("""
            CREATE TRIGGER IF NOT EXISTS l3_fts_insert AFTER INSERT ON l3_episodic
            BEGIN
                INSERT INTO l3_episodic_fts(rowid, content, tags, event_type)
                VALUES (NEW.rowid, NEW.content, NEW.tags, NEW.event_type);
            END
        """)

        # L4: Artifact Index
        await db.execute("""
            CREATE TABLE IF NOT EXISTS l4_artifacts (
                entry_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                artifact_type TEXT NOT NULL,
                path_or_uri TEXT NOT NULL,
                description TEXT,
                tags TEXT DEFAULT '[]',
                metadata TEXT DEFAULT '{}',
                last_validated TEXT,
                created_at TEXT NOT NULL
            )
        """)

        # Indexes for common query patterns
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_l1_category ON l1_domain(category)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_l2_pattern ON l2_workflow(pattern_type)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_l3_event_type ON l3_episodic(event_type)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_l3_created ON l3_episodic(created_at)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_l3_session ON l3_episodic(session_id)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_l4_type ON l4_artifacts(artifact_type)"
        )

        await db.commit()
        logger.debug(f"Memory database initialized: {db_path}")

# build_chunk_006.py
#
# CHUNK-006: Lexicon (Memory Control Plane)
# Dependencies: CHUNK-001 (Base Layout & Schemas), CHUNK-002 (Redis Message Bus), CHUNK-003 (Warden Security)
# Implements: Part IV (§4.1–§4.5), Part VI §6.3
#
# Run from the root of your project-aegis directory:
#   python build_chunk_006.py

import os
import textwrap

# --- File Manifest ---
CHUNK_006_FILES = {

    # ═══════════════════════════════════════════════════════════════════
    # SCHEMAS
    # ═══════════════════════════════════════════════════════════════════

    "aegis/schemas/lexicon.py": '''
# aegis/schemas/lexicon.py
# Implements: Part IV §4.3, Part VI §6.3 — Lexicon Protocol Contracts
"""
Pydantic models for the Lexicon Memory Control Plane.
Defines all request/response contracts, tier models, and governor decisions.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────
# Lexicon Protocol (Part VI §6.3)
# ─────────────────────────────────────────────

class LexiconAction(str, Enum):
    """Actions supported by the Lexicon agent."""
    ASSEMBLE_CONTEXT = "assemble_context"
    STORE_MEMORY = "store_memory"
    SEARCH_MEMORY = "search_memory"
    PROMOTE_MEMORY = "promote_memory"
    QUERY_TIER = "query_tier"
    GET_GOVERNOR_STATUS = "get_governor_status"
    SESSION_END = "session_end"  # Triggers L5→L3 promotion review


class LexiconRequest(BaseModel):
    """Standard request envelope for all Lexicon operations."""
    action: LexiconAction
    tenant_id: str
    user_id: str
    payload: Dict[str, Any] = {}


class LexiconResponse(BaseModel):
    """Standard response envelope from Lexicon."""
    success: bool
    action: LexiconAction
    data: Dict[str, Any] = {}
    error: Optional[str] = None


# ─────────────────────────────────────────────
# Context Router (Part IV §4.3)
# ─────────────────────────────────────────────

class ContextRequest(BaseModel):
    """
    Request to assemble context from memory tiers.
    Sent by agents (typically TOrchestrator via Oracle) needing memory context.
    """
    query: str
    tenant_id: str
    user_id: str
    scope: List[str] = Field(
        default=["L0", "L1", "L2", "L3"],
        description="Which memory tiers to query."
    )
    token_budget: int = Field(
        default=4000,
        description="Maximum token count for the assembled context."
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Include L5 scratchpad if session_id is provided."
    )


class ContextFragment(BaseModel):
    """A single fragment of context retrieved from a memory tier."""
    tier: str
    content: str
    relevance: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Relevance score (0.0–1.0)."
    )
    metadata: Dict[str, Any] = {}
    token_count: int = 0


class ContextPacket(BaseModel):
    """
    Assembled context packet returned by the Context Router.
    Contains ranked fragments that fit within the token budget.
    """
    tenant_id: str
    user_id: str
    fragments: List[ContextFragment] = []
    total_tokens: int = 0
    tiers_queried: List[str] = []
    assembly_time_ms: float = 0.0


# ─────────────────────────────────────────────
# Memory Governor (Part IV §4.4)
# ─────────────────────────────────────────────

class MemoryGovernorAction(str, Enum):
    """Actions the Memory Governor can perform."""
    PROMOTE = "promote"
    DEMOTE = "demote"
    ARCHIVE = "archive"
    SUGGEST_L0_UPDATE = "suggest_l0_update"


class GovernorDecision(BaseModel):
    """A decision made by the Memory Governor regarding memory lifecycle."""
    source_tier: str
    target_tier: str
    action: MemoryGovernorAction
    content_id: str
    rationale: str
    requires_user_approval: bool = False
    timestamp: datetime = Field(default_factory=_utc_now)


class GovernorStatus(BaseModel):
    """Status report from the Memory Governor."""
    pending_promotions: int = 0
    pending_demotions: int = 0
    last_promotion_run: Optional[datetime] = None
    last_eviction_run: Optional[datetime] = None
    l3_entry_count: int = 0
    l3_retention_days: int = 365


# ─────────────────────────────────────────────
# Tier-Specific Models
# ─────────────────────────────────────────────

class MemoryEntry(BaseModel):
    """Generic memory entry used across tiers."""
    entry_id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: str
    user_id: str
    tier: str
    content: str
    metadata: Dict[str, Any] = {}
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: Optional[datetime] = None
    tags: List[str] = []
    source: Optional[str] = None  # Where this memory originated


class L0Entry(BaseModel):
    """L0 Core Identity entry — user principles, values, preferences."""
    key: str
    value: str
    category: str = "general"
    last_modified: datetime = Field(default_factory=_utc_now)


class L3EpisodicEntry(BaseModel):
    """L3 Episodic Memory — timestamped events and decisions."""
    entry_id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: str
    user_id: str
    content: str
    event_type: str = "general"  # "decision", "conversation", "outcome", "event"
    tags: List[str] = []
    source: Optional[str] = None
    session_id: Optional[str] = None
    created_at: datetime = Field(default_factory=_utc_now)


class L4ArtifactEntry(BaseModel):
    """L4 Artifact Index — metadata pointers to external resources."""
    entry_id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: str
    user_id: str
    name: str
    artifact_type: str  # "file", "url", "document", "image"
    path_or_uri: str
    description: Optional[str] = None
    tags: List[str] = []
    last_validated: Optional[datetime] = None
    created_at: datetime = Field(default_factory=_utc_now)


class L5ScratchpadEntry(BaseModel):
    """L5 Session Scratchpad — volatile per-session working memory."""
    key: str
    value: Any
    session_id: str
    created_at: datetime = Field(default_factory=_utc_now)
    ttl_seconds: Optional[int] = None  # None = expires at session end


class MemorySearchRequest(BaseModel):
    """Request to search memory across tiers."""
    query: str
    tenant_id: str
    user_id: str
    tiers: List[str] = Field(default=["L1", "L2", "L3"])
    limit: int = 20
    tags: Optional[List[str]] = None


class MemoryStoreRequest(BaseModel):
    """Request to store a new memory entry."""
    tier: str
    tenant_id: str
    user_id: str
    content: str
    metadata: Dict[str, Any] = {}
    tags: List[str] = []
    source: Optional[str] = None
    session_id: Optional[str] = None


class MemoryPromoteRequest(BaseModel):
    """Request to promote memory from one tier to another."""
    entry_id: str
    source_tier: str
    target_tier: str
    tenant_id: str
    user_id: str
    rationale: Optional[str] = None
''',

    # ═══════════════════════════════════════════════════════════════════
    # STORAGE MANAGER
    # ═══════════════════════════════════════════════════════════════════

    "aegis/agents/lexicon/__init__.py": '''
# aegis/agents/lexicon/__init__.py
"""
Lexicon — The Aegis Memory Control Plane.
Implements Part IV of the Aegis Genesis OOBE Directive.
"""

from aegis.agents.lexicon.agent import LexiconAgent

__all__ = ["LexiconAgent"]
''',

    "aegis/agents/lexicon/storage.py": '''
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
        l0_path.write_text(_default_l0_template(user_id), encoding="utf-8", newline="\\n")
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
''',

    # ═══════════════════════════════════════════════════════════════════
    # TIER IMPLEMENTATIONS
    # ═══════════════════════════════════════════════════════════════════

    "aegis/agents/lexicon/tiers/__init__.py": '''
# aegis/agents/lexicon/tiers/__init__.py
"""Memory tier implementations for L0–L5."""

from aegis.agents.lexicon.tiers.l0_identity import L0IdentityTier
from aegis.agents.lexicon.tiers.l1_domain import L1DomainTier
from aegis.agents.lexicon.tiers.l2_workflow import L2WorkflowTier
from aegis.agents.lexicon.tiers.l3_episodic import L3EpisodicTier
from aegis.agents.lexicon.tiers.l4_artifacts import L4ArtifactTier
from aegis.agents.lexicon.tiers.l5_scratchpad import L5ScratchpadTier

__all__ = [
    "L0IdentityTier",
    "L1DomainTier",
    "L2WorkflowTier",
    "L3EpisodicTier",
    "L4ArtifactTier",
    "L5ScratchpadTier",
]
''',

    "aegis/agents/lexicon/tiers/l0_identity.py": '''
# aegis/agents/lexicon/tiers/l0_identity.py
# Implements: Part IV §4.2 — L0 Core Identity Tier
"""
L0 Core Identity Tier.
Stable user principles, values, and preferences stored as human-editable YAML.
USER-EDITABLE ONLY — agents may suggest but never directly modify.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from aegis.agents.lexicon.storage import get_l0_path

logger = logging.getLogger(__name__)


class L0IdentityTier:
    """
    Manages L0 Core Identity memory.

    Properties:
        - Format: YAML file (l0_identity.yaml)
        - Mutability: User-editable only
        - TTL: Permanent
    """

    def __init__(self, tenant_id: str, user_id: str, base_dir: Optional[str] = None):
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.base_dir = base_dir
        self._cache: Optional[Dict[str, Any]] = None
        self._path: Path = get_l0_path(tenant_id, user_id, base_dir)

    @property
    def path(self) -> Path:
        """Path to the L0 identity YAML file."""
        return self._path

    async def load(self) -> Dict[str, Any]:
        """
        Load L0 identity from YAML file.
        Results are cached until invalidated.

        Returns:
            Dictionary containing the full L0 identity structure.
        """
        if self._cache is not None:
            return self._cache

        if not self._path.exists():
            logger.warning(f"L0 identity file not found: {self._path}")
            return {}

        try:
            content = self._path.read_text(encoding="utf-8")
            data = yaml.safe_load(content) or {}
            self._cache = data
            logger.debug(f"L0 identity loaded for user={self.user_id}")
            return data
        except yaml.YAMLError as e:
            logger.error(f"Failed to parse L0 identity YAML: {e}")
            return {}

    async def query(self, key: Optional[str] = None) -> Any:
        """
        Query L0 identity data.

        Args:
            key: Optional dot-notation key (e.g., 'identity.display_name').
                 If None, returns the entire L0 structure.

        Returns:
            The value at the specified key, or the full structure.
        """
        data = await self.load()
        if key is None:
            return data

        # Support dot-notation access
        parts = key.split(".")
        current = data
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        return current

    async def get_context_fragments(self, query: str) -> List[Dict[str, Any]]:
        """
        Retrieve L0 content as context fragments for the Context Router.
        L0 is always fully included (it's the user's constitution).

        Args:
            query: The search query (used for metadata, L0 is always fully returned).

        Returns:
            List of context fragments from L0.
        """
        data = await self.load()
        if not data:
            return []

        # Serialize the full L0 as a readable string
        fragments = []

        # Identity section
        identity = data.get("identity", {})
        if identity:
            content = f"User Identity: {yaml.dump(identity, default_flow_style=False).strip()}"
            fragments.append({
                "tier": "L0",
                "content": content,
                "relevance": 1.0,  # L0 is always maximally relevant
                "metadata": {"section": "identity"}
            })

        # Principles
        principles = data.get("principles", [])
        if principles:
            content = "User Principles:\\n" + "\\n".join(f"- {p}" for p in principles)
            fragments.append({
                "tier": "L0",
                "content": content,
                "relevance": 1.0,
                "metadata": {"section": "principles"}
            })

        # Values
        values = data.get("values", [])
        if values:
            content = "User Values:\\n" + "\\n".join(f"- {v}" for v in values)
            fragments.append({
                "tier": "L0",
                "content": content,
                "relevance": 1.0,
                "metadata": {"section": "values"}
            })

        # Preferences
        preferences = data.get("preferences", {})
        if preferences:
            content = f"User Preferences: {yaml.dump(preferences, default_flow_style=False).strip()}"
            fragments.append({
                "tier": "L0",
                "content": content,
                "relevance": 1.0,
                "metadata": {"section": "preferences"}
            })

        # Domains
        domains = data.get("domains", [])
        if domains:
            content = "User Domains:\\n" + yaml.dump(domains, default_flow_style=False).strip()
            fragments.append({
                "tier": "L0",
                "content": content,
                "relevance": 1.0,
                "metadata": {"section": "domains"}
            })

        return fragments

    def invalidate_cache(self) -> None:
        """Invalidate the cached L0 data, forcing a reload on next access."""
        self._cache = None
        logger.debug(f"L0 cache invalidated for user={self.user_id}")

    async def suggest_update(self, key: str, value: Any, rationale: str) -> Dict[str, Any]:
        """
        Suggest an update to L0 (requires user approval).
        Does NOT modify the file — returns a suggestion for the user.

        Args:
            key: The key to update (dot-notation).
            value: The proposed new value.
            rationale: Why this update is suggested.

        Returns:
            A suggestion dict for user review.
        """
        return {
            "type": "l0_update_suggestion",
            "key": key,
            "proposed_value": value,
            "rationale": rationale,
            "requires_user_approval": True,
            "current_value": await self.query(key),
        }
''',

    "aegis/agents/lexicon/tiers/l1_domain.py": '''
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
''',

    "aegis/agents/lexicon/tiers/l2_workflow.py": '''
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
''',

    "aegis/agents/lexicon/tiers/l3_episodic.py": '''
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
''',

    "aegis/agents/lexicon/tiers/l4_artifacts.py": '''
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
''',

    "aegis/agents/lexicon/tiers/l5_scratchpad.py": '''
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

        content = "Session Scratchpad:\\n" + "\\n".join(content_parts)

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
''',

    # ═══════════════════════════════════════════════════════════════════
    # CONTEXT ROUTER
    # ═══════════════════════════════════════════════════════════════════

    "aegis/agents/lexicon/context_router.py": '''
# aegis/agents/lexicon/context_router.py
# Implements: Part IV §4.3 — Context Router
"""
Context Router — Lexicon's primary interface for serving other agents.
Assembles context from multiple memory tiers, ranked by relevance,
within a specified token budget.
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from aegis.schemas.lexicon import (
    ContextFragment,
    ContextPacket,
    ContextRequest,
)
from aegis.agents.lexicon.tiers.l0_identity import L0IdentityTier
from aegis.agents.lexicon.tiers.l1_domain import L1DomainTier
from aegis.agents.lexicon.tiers.l2_workflow import L2WorkflowTier
from aegis.agents.lexicon.tiers.l3_episodic import L3EpisodicTier
from aegis.agents.lexicon.tiers.l4_artifacts import L4ArtifactTier
from aegis.agents.lexicon.tiers.l5_scratchpad import L5ScratchpadTier

logger = logging.getLogger(__name__)

# Approximate token estimation: ~4 chars per token (conservative)
CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    """Estimate token count from text length (conservative approximation)."""
    return len(text) // CHARS_PER_TOKEN + 1


class ContextRouter:
    """
    Assembles context from memory tiers based on a ContextRequest.

    Behavior (from spec §4.3):
        1. Receives a ContextRequest specifying query, scope, token_budget, tenant/user.
        2. Queries each requested tier in parallel.
        3. Ranks and selects results by relevance.
        4. Assembles a ContextPacket that fits within the token_budget.
        5. Returns the ContextPacket.
    """

    def __init__(
        self,
        l0: L0IdentityTier,
        l1: L1DomainTier,
        l2: L2WorkflowTier,
        l3: L3EpisodicTier,
        l4: L4ArtifactTier,
        l5: Optional[L5ScratchpadTier] = None,
    ):
        self._tiers = {
            "L0": l0,
            "L1": l1,
            "L2": l2,
            "L3": l3,
            "L4": l4,
        }
        if l5:
            self._tiers["L5"] = l5

    def set_l5(self, l5: L5ScratchpadTier) -> None:
        """Set or update the L5 scratchpad tier (session-dependent)."""
        self._tiers["L5"] = l5

    def remove_l5(self) -> None:
        """Remove the L5 tier reference (session ended)."""
        self._tiers.pop("L5", None)

    async def assemble(self, request: ContextRequest) -> ContextPacket:
        """
        Assemble a context packet from memory tiers.

        Args:
            request: The ContextRequest specifying what context to assemble.

        Returns:
            A ContextPacket containing ranked fragments within the token budget.
        """
        start_time = time.time()

        # Determine which tiers to query
        tiers_to_query = []
        for tier_name in request.scope:
            if tier_name in self._tiers:
                tiers_to_query.append(tier_name)
            else:
                logger.debug(f"Tier {tier_name} not available, skipping")

        # Include L5 if session_id provided and L5 is available
        if request.session_id and "L5" in self._tiers and "L5" not in tiers_to_query:
            tiers_to_query.append("L5")

        # Query all tiers in parallel
        tasks = []
        tier_names = []
        for tier_name in tiers_to_query:
            tier = self._tiers[tier_name]
            tasks.append(tier.get_context_fragments(request.query))
            tier_names.append(tier_name)

        # Gather results
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Collect all fragments
        all_fragments: List[Dict[str, Any]] = []
        for tier_name, result in zip(tier_names, raw_results):
            if isinstance(result, Exception):
                logger.error(f"Error querying tier {tier_name}: {result}")
                continue
            all_fragments.extend(result)

        # Sort by relevance (descending)
        all_fragments.sort(key=lambda f: f.get("relevance", 0), reverse=True)

        # Assemble within token budget
        assembled_fragments: List[ContextFragment] = []
        total_tokens = 0

        for frag_data in all_fragments:
            content = frag_data.get("content", "")
            token_count = estimate_tokens(content)

            if total_tokens + token_count > request.token_budget:
                # Try to truncate if it's the first fragment and we have nothing yet
                if not assembled_fragments:
                    available_chars = (request.token_budget - total_tokens) * CHARS_PER_TOKEN
                    if available_chars > 100:  # Minimum useful content
                        content = content[:available_chars] + "..."
                        token_count = estimate_tokens(content)
                    else:
                        continue
                else:
                    continue

            fragment = ContextFragment(
                tier=frag_data.get("tier", "unknown"),
                content=content,
                relevance=frag_data.get("relevance", 0.0),
                metadata=frag_data.get("metadata", {}),
                token_count=token_count,
            )
            assembled_fragments.append(fragment)
            total_tokens += token_count

        assembly_time_ms = (time.time() - start_time) * 1000

        packet = ContextPacket(
            tenant_id=request.tenant_id,
            user_id=request.user_id,
            fragments=assembled_fragments,
            total_tokens=total_tokens,
            tiers_queried=tiers_to_query,
            assembly_time_ms=round(assembly_time_ms, 2),
        )

        logger.info(
            f"Context assembled: {len(assembled_fragments)} fragments, "
            f"{total_tokens} tokens, {assembly_time_ms:.1f}ms "
            f"(budget={request.token_budget}, tiers={tiers_to_query})"
        )

        return packet
''',

    # ═══════════════════════════════════════════════════════════════════
    # MEMORY GOVERNOR
    # ═══════════════════════════════════════════════════════════════════

    "aegis/agents/lexicon/governor.py": '''
# aegis/agents/lexicon/governor.py
# Implements: Part IV §4.4 — Memory Governor & Promotion Pipeline
"""
Memory Governor — Manages the lifecycle of memories across tiers.

Promotion Pipeline:
    L5 → L3: At session end, reviews scratchpad for significant items.
    L3 → L1/L2: Periodically analyzes episodic memory for recurring patterns.
    L1/L2 → L0: Never automatic. May suggest updates for user approval.

Demotion / Eviction:
    L5: Expires at session end.
    L3: Subject to retention policies (default 365 days).
    L1/L2: Can be deprecated but never auto-deleted.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from aegis.schemas.lexicon import (
    GovernorDecision,
    GovernorStatus,
    MemoryGovernorAction,
)
from aegis.agents.lexicon.tiers.l3_episodic import L3EpisodicTier
from aegis.agents.lexicon.tiers.l5_scratchpad import L5ScratchpadTier
from aegis.agents.lexicon.storage import get_sessions_dir

logger = logging.getLogger(__name__)


class MemoryGovernor:
    """
    Manages the lifecycle of memories across tiers.
    Handles promotions, demotions, evictions, and L0 update suggestions.
    """

    def __init__(
        self,
        tenant_id: str,
        user_id: str,
        l3: L3EpisodicTier,
        base_dir: Optional[str] = None,
        retention_days: int = 365,
    ):
        self.tenant_id = tenant_id
        self.user_id = user_id
        self._l3 = l3
        self._base_dir = base_dir
        self._retention_days = retention_days
        self._last_promotion_run: Optional[datetime] = None
        self._last_eviction_run: Optional[datetime] = None
        self._pending_decisions: List[GovernorDecision] = []

    async def process_session_end(
        self,
        l5: L5ScratchpadTier,
        significance_threshold: float = 0.3,
    ) -> List[GovernorDecision]:
        """
        Process session end: review L5 scratchpad and promote significant items to L3.

        Promotion Pipeline (L5 → L3):
            At session end, the Governor reviews L5 scratchpad contents.
            Significant decisions, outcomes, and events are promoted to L3.

        Args:
            l5: The L5 scratchpad tier for the ending session.
            significance_threshold: Minimum significance score to promote (0.0–1.0).

        Returns:
            List of GovernorDecisions made during this promotion pass.
        """
        decisions: List[GovernorDecision] = []

        # Get snapshot of L5 before clearing
        snapshot = await l5.snapshot()
        entries = snapshot.get("entries", {})

        if not entries:
            logger.debug("No L5 entries to evaluate for promotion.")
            await l5.clear()
            return decisions

        # Save snapshot to sessions directory for audit trail
        await self._save_session_snapshot(snapshot)

        # Evaluate each entry for promotion significance
        for key, value in entries.items():
            significance = self._evaluate_significance(key, value)

            if significance >= significance_threshold:
                # Promote to L3
                content = self._format_for_l3(key, value)
                entry_id = await self._l3.append(
                    content=content,
                    event_type="session_promoted",
                    tags=["l5_promotion", f"session:{l5.session_id}"],
                    source=f"l5:{l5.session_id}",
                    session_id=l5.session_id,
                )

                decision = GovernorDecision(
                    source_tier="L5",
                    target_tier="L3",
                    action=MemoryGovernorAction.PROMOTE,
                    content_id=entry_id,
                    rationale=f"Significant session entry (score={significance:.2f}): {key}",
                )
                decisions.append(decision)
                logger.debug(f"L5→L3 promotion: {key} (significance={significance:.2f})")

        # Clear the scratchpad
        await l5.clear()

        self._last_promotion_run = datetime.now(timezone.utc)
        logger.info(
            f"Session end processed: {len(decisions)} entries promoted from L5→L3 "
            f"(out of {len(entries)} total)"
        )

        return decisions

    def _evaluate_significance(self, key: str, value: Any) -> float:
        """
        Evaluate the significance of a scratchpad entry for promotion.
        Uses heuristics based on key naming and content characteristics.

        Args:
            key: The scratchpad key.
            value: The scratchpad value.

        Returns:
            Significance score (0.0–1.0).
        """
        score = 0.0

        # Key-based heuristics
        high_signal_keys = ["decision", "outcome", "result", "conclusion", "action", "plan"]
        medium_signal_keys = ["note", "insight", "observation", "context", "summary"]
        low_signal_keys = ["temp", "scratch", "draft", "wip", "debug"]

        key_lower = key.lower()
        if any(k in key_lower for k in high_signal_keys):
            score += 0.5
        elif any(k in key_lower for k in medium_signal_keys):
            score += 0.3
        elif any(k in key_lower for k in low_signal_keys):
            score -= 0.2

        # Content-based heuristics
        content_str = json.dumps(value) if not isinstance(value, str) else value
        content_length = len(content_str)

        # Longer content tends to be more significant
        if content_length > 500:
            score += 0.3
        elif content_length > 100:
            score += 0.2
        elif content_length > 20:
            score += 0.1

        # Structured data (dicts/lists) often represents organized thought
        if isinstance(value, (dict, list)) and len(str(value)) > 50:
            score += 0.1

        return max(0.0, min(1.0, score))

    def _format_for_l3(self, key: str, value: Any) -> str:
        """Format a scratchpad entry for storage in L3 episodic memory."""
        if isinstance(value, str):
            return f"[Session Note — {key}]: {value}"
        else:
            return f"[Session Data — {key}]: {json.dumps(value, indent=2)}"

    async def _save_session_snapshot(self, snapshot: Dict[str, Any]) -> None:
        """Save a session snapshot to the sessions directory for audit."""
        sessions_dir = get_sessions_dir(self.tenant_id, self.user_id, self._base_dir)
        sessions_dir.mkdir(parents=True, exist_ok=True)

        session_id = snapshot.get("session_id", "unknown")
        snapshot_path = sessions_dir / f"{session_id}.json"

        try:
            snapshot_path.write_text(
                json.dumps(snapshot, indent=2, default=str),
                encoding="utf-8",
            )
            logger.debug(f"Session snapshot saved: {snapshot_path}")
        except Exception as e:
            logger.error(f"Failed to save session snapshot: {e}")

    async def run_eviction(self) -> int:
        """
        Run the eviction process for L3 entries past retention period.

        Returns:
            Number of entries evicted.
        """
        evicted = await self._l3.evict_expired()
        self._last_eviction_run = datetime.now(timezone.utc)
        return evicted

    async def get_status(self) -> GovernorStatus:
        """Get the current status of the Memory Governor."""
        l3_count = await self._l3.count()

        return GovernorStatus(
            pending_promotions=len(
                [d for d in self._pending_decisions if d.action == MemoryGovernorAction.PROMOTE]
            ),
            pending_demotions=len(
                [d for d in self._pending_decisions if d.action == MemoryGovernorAction.DEMOTE]
            ),
            last_promotion_run=self._last_promotion_run,
            last_eviction_run=self._last_eviction_run,
            l3_entry_count=l3_count,
            l3_retention_days=self._retention_days,
        )

    async def suggest_l0_update(
        self, key: str, value: Any, rationale: str
    ) -> GovernorDecision:
        """
        Create a suggestion for L0 update (requires user approval).
        L0 is NEVER automatically modified.

        Args:
            key: The L0 key to update.
            value: The proposed value.
            rationale: Why this update is suggested.

        Returns:
            A GovernorDecision with requires_user_approval=True.
        """
        decision = GovernorDecision(
            source_tier="governor",
            target_tier="L0",
            action=MemoryGovernorAction.SUGGEST_L0_UPDATE,
            content_id=key,
            rationale=rationale,
            requires_user_approval=True,
        )
        self._pending_decisions.append(decision)
        logger.info(f"L0 update suggested: {key} — {rationale}")
        return decision
''',

    # ═══════════════════════════════════════════════════════════════════
    # LEXICON AGENT
    # ═══════════════════════════════════════════════════════════════════

    "aegis/agents/lexicon/agent.py": '''
# aegis/agents/lexicon/agent.py
# Implements: Part II §2.1 (Lexicon role), Part IV (full), Part VI §6.3
"""
Lexicon Agent — The Aegis Memory Control Plane.

Role: Memory Governor. Manages all tiers of memory (L0–L5), context assembly,
memory lifecycle, and external memory exposure via MCP.

Subscribes to: aegis:stream:lexicon
Publishes to: aegis:stream:broadcast (memory events)
"""

import logging
from typing import Any, Dict, Optional

from aegis.agents.lexicon.context_router import ContextRouter
from aegis.agents.lexicon.governor import MemoryGovernor
from aegis.agents.lexicon.storage import ensure_user_storage
from aegis.agents.lexicon.tiers.l0_identity import L0IdentityTier
from aegis.agents.lexicon.tiers.l1_domain import L1DomainTier
from aegis.agents.lexicon.tiers.l2_workflow import L2WorkflowTier
from aegis.agents.lexicon.tiers.l3_episodic import L3EpisodicTier
from aegis.agents.lexicon.tiers.l4_artifacts import L4ArtifactTier
from aegis.agents.lexicon.tiers.l5_scratchpad import L5ScratchpadTier
from aegis.schemas.lexicon import (
    ContextRequest,
    LexiconAction,
    LexiconRequest,
    LexiconResponse,
    MemorySearchRequest,
    MemoryStoreRequest,
    MemoryPromoteRequest,
)

logger = logging.getLogger(__name__)


class LexiconAgent:
    """
    The Lexicon Memory Control Plane agent.

    Responsibilities:
        - Manage all memory tiers (L0–L5)
        - Assemble context for other agents via the Context Router
        - Execute the Memory Governor promotion/eviction pipeline
        - Handle memory CRUD operations

    Integration:
        - Subscribes to: aegis:stream:lexicon
        - Publishes to: aegis:stream:broadcast
    """

    agent_id: str = "lexicon"
    subscriptions: list = ["aegis:stream:lexicon"]

    def __init__(
        self,
        redis_client: Optional[Any] = None,
        base_dir: Optional[str] = None,
    ):
        """
        Initialize the Lexicon agent.

        Args:
            redis_client: Async Redis client for L5 scratchpad and bus communication.
            base_dir: Override for the base data directory.
        """
        self._redis = redis_client
        self._base_dir = base_dir
        self._user_contexts: Dict[str, Dict[str, Any]] = {}
        # Cache: {tenant_id:user_id -> {l0, l1, l2, l3, l4, router, governor}}

    async def startup(self) -> None:
        """Agent initialization logic."""
        logger.info("Lexicon agent starting up...")
        # Lexicon is ready to handle messages once startup completes
        logger.info("Lexicon agent ready.")

    async def shutdown(self) -> None:
        """Graceful teardown logic."""
        logger.info("Lexicon agent shutting down...")
        # Clean up any active L5 sessions
        for context_key, ctx in self._user_contexts.items():
            if "l5_sessions" in ctx:
                for session_id, l5 in ctx["l5_sessions"].items():
                    try:
                        governor = ctx.get("governor")
                        if governor:
                            await governor.process_session_end(l5)
                    except Exception as e:
                        logger.error(f"Error during L5 cleanup for {context_key}: {e}")
        logger.info("Lexicon agent stopped.")

    async def handle_message(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Process an incoming message directed to Lexicon.

        Args:
            message: The AegisMessage payload (dict form).

        Returns:
            Response dict or None.
        """
        try:
            # Extract request from message payload
            payload = message.get("payload", {})
            action_str = payload.get("action") or message.get("action", "")

            # Parse as LexiconRequest
            request = LexiconRequest(
                action=LexiconAction(action_str.replace("lexicon.", "")),
                tenant_id=message.get("tenant_id", payload.get("tenant_id", "")),
                user_id=message.get("user_id", payload.get("user_id", "")),
                payload=payload,
            )

            return await self._dispatch(request)

        except Exception as e:
            logger.error(f"Lexicon message handling error: {e}", exc_info=True)
            return LexiconResponse(
                success=False,
                action=LexiconAction.ASSEMBLE_CONTEXT,
                error=str(e),
            ).model_dump()

    async def _dispatch(self, request: LexiconRequest) -> Dict[str, Any]:
        """Dispatch a LexiconRequest to the appropriate handler."""
        handlers = {
            LexiconAction.ASSEMBLE_CONTEXT: self._handle_assemble_context,
            LexiconAction.STORE_MEMORY: self._handle_store_memory,
            LexiconAction.SEARCH_MEMORY: self._handle_search_memory,
            LexiconAction.PROMOTE_MEMORY: self._handle_promote_memory,
            LexiconAction.QUERY_TIER: self._handle_query_tier,
            LexiconAction.GET_GOVERNOR_STATUS: self._handle_governor_status,
            LexiconAction.SESSION_END: self._handle_session_end,
        }

        handler = handlers.get(request.action)
        if not handler:
            return LexiconResponse(
                success=False,
                action=request.action,
                error=f"Unknown action: {request.action}",
            ).model_dump()

        return await handler(request)

    async def _get_user_context(
        self, tenant_id: str, user_id: str
    ) -> Dict[str, Any]:
        """
        Get or initialize the memory context for a specific tenant/user.
        Lazily initializes tier objects and ensures storage exists.
        """
        context_key = f"{tenant_id}:{user_id}"

        if context_key not in self._user_contexts:
            # Ensure storage structure exists
            await ensure_user_storage(tenant_id, user_id, self._base_dir)

            # Initialize tier objects
            l0 = L0IdentityTier(tenant_id, user_id, self._base_dir)
            l1 = L1DomainTier(tenant_id, user_id, self._base_dir)
            l2 = L2WorkflowTier(tenant_id, user_id, self._base_dir)
            l3 = L3EpisodicTier(tenant_id, user_id, self._base_dir)
            l4 = L4ArtifactTier(tenant_id, user_id, self._base_dir)

            router = ContextRouter(l0=l0, l1=l1, l2=l2, l3=l3, l4=l4)
            governor = MemoryGovernor(tenant_id, user_id, l3, self._base_dir)

            self._user_contexts[context_key] = {
                "l0": l0,
                "l1": l1,
                "l2": l2,
                "l3": l3,
                "l4": l4,
                "router": router,
                "governor": governor,
                "l5_sessions": {},  # session_id -> L5ScratchpadTier
            }

        return self._user_contexts[context_key]

    def _get_or_create_l5(
        self, ctx: Dict[str, Any], session_id: str, tenant_id: str, user_id: str
    ) -> L5ScratchpadTier:
        """Get or create an L5 scratchpad for a specific session."""
        if session_id not in ctx["l5_sessions"]:
            l5 = L5ScratchpadTier(
                tenant_id=tenant_id,
                user_id=user_id,
                session_id=session_id,
                redis_client=self._redis,
            )
            ctx["l5_sessions"][session_id] = l5
            ctx["router"].set_l5(l5)
        return ctx["l5_sessions"][session_id]

    # ─────────────────────────────────────────────
    # Action Handlers
    # ─────────────────────────────────────────────

    async def _handle_assemble_context(
        self, request: LexiconRequest
    ) -> Dict[str, Any]:
        """Handle ASSEMBLE_CONTEXT: assemble context from memory tiers."""
        ctx = await self._get_user_context(request.tenant_id, request.user_id)
        router: ContextRouter = ctx["router"]

        # Build ContextRequest from payload
        payload = request.payload
        context_request = ContextRequest(
            query=payload.get("query", ""),
            tenant_id=request.tenant_id,
            user_id=request.user_id,
            scope=payload.get("scope", ["L0", "L1", "L2", "L3"]),
            token_budget=payload.get("token_budget", 4000),
            session_id=payload.get("session_id"),
        )

        # If session_id provided, ensure L5 is available
        if context_request.session_id:
            self._get_or_create_l5(
                ctx, context_request.session_id, request.tenant_id, request.user_id
            )

        packet = await router.assemble(context_request)

        return LexiconResponse(
            success=True,
            action=LexiconAction.ASSEMBLE_CONTEXT,
            data=packet.model_dump(),
        ).model_dump()

    async def _handle_store_memory(self, request: LexiconRequest) -> Dict[str, Any]:
        """Handle STORE_MEMORY: store a new memory entry in the appropriate tier."""
        ctx = await self._get_user_context(request.tenant_id, request.user_id)
        payload = request.payload

        tier = payload.get("tier", "L3")
        content = payload.get("content", "")
        tags = payload.get("tags", [])
        source = payload.get("source")
        metadata = payload.get("metadata", {})
        session_id = payload.get("session_id")

        if not content:
            return LexiconResponse(
                success=False,
                action=LexiconAction.STORE_MEMORY,
                error="Content is required for memory storage.",
            ).model_dump()

        entry_id = None

        if tier == "L1":
            entry_id = await ctx["l1"].store(
                content=content,
                category=metadata.get("category", "general"),
                tags=tags,
                source=source,
                metadata=metadata,
            )
        elif tier == "L2":
            entry_id = await ctx["l2"].store(
                content=content,
                pattern_type=metadata.get("pattern_type", "general"),
                tags=tags,
                source=source,
                metadata=metadata,
                confidence=metadata.get("confidence", 0.5),
            )
        elif tier == "L3":
            entry_id = await ctx["l3"].append(
                content=content,
                event_type=metadata.get("event_type", "general"),
                tags=tags,
                source=source,
                session_id=session_id,
                metadata=metadata,
            )
        elif tier == "L4":
            entry_id = await ctx["l4"].store(
                name=metadata.get("name", "Unnamed artifact"),
                artifact_type=metadata.get("artifact_type", "file"),
                path_or_uri=content,
                description=metadata.get("description"),
                tags=tags,
                metadata=metadata,
            )
        elif tier == "L5":
            if not session_id:
                return LexiconResponse(
                    success=False,
                    action=LexiconAction.STORE_MEMORY,
                    error="session_id is required for L5 storage.",
                ).model_dump()
            l5 = self._get_or_create_l5(ctx, session_id, request.tenant_id, request.user_id)
            key = metadata.get("key", f"entry_{len(await l5.get_all())}")
            await l5.set(key, content)
            entry_id = f"l5:{session_id}:{key}"
        elif tier == "L0":
            return LexiconResponse(
                success=False,
                action=LexiconAction.STORE_MEMORY,
                error="L0 is user-editable only. Use SUGGEST_L0_UPDATE via the governor.",
            ).model_dump()
        else:
            return LexiconResponse(
                success=False,
                action=LexiconAction.STORE_MEMORY,
                error=f"Unknown tier: {tier}",
            ).model_dump()

        return LexiconResponse(
            success=True,
            action=LexiconAction.STORE_MEMORY,
            data={"entry_id": entry_id, "tier": tier},
        ).model_dump()

    async def _handle_search_memory(self, request: LexiconRequest) -> Dict[str, Any]:
        """Handle SEARCH_MEMORY: search across memory tiers."""
        ctx = await self._get_user_context(request.tenant_id, request.user_id)
        payload = request.payload

        query = payload.get("query", "")
        tiers = payload.get("tiers", ["L1", "L2", "L3"])
        limit = payload.get("limit", 20)
        tags = payload.get("tags")

        if not query:
            return LexiconResponse(
                success=False,
                action=LexiconAction.SEARCH_MEMORY,
                error="Query is required for memory search.",
            ).model_dump()

        results: Dict[str, list] = {}

        for tier_name in tiers:
            if tier_name == "L1":
                results["L1"] = await ctx["l1"].search(query, tags=tags, limit=limit)
            elif tier_name == "L2":
                results["L2"] = await ctx["l2"].search(query, limit=limit)
            elif tier_name == "L3":
                results["L3"] = await ctx["l3"].search_fts(query, limit=limit)
            elif tier_name == "L4":
                results["L4"] = await ctx["l4"].search(query, tags=tags, limit=limit)

        return LexiconResponse(
            success=True,
            action=LexiconAction.SEARCH_MEMORY,
            data={"results": results, "query": query, "tiers_searched": tiers},
        ).model_dump()

    async def _handle_promote_memory(self, request: LexiconRequest) -> Dict[str, Any]:
        """Handle PROMOTE_MEMORY: promote an entry from one tier to another."""
        ctx = await self._get_user_context(request.tenant_id, request.user_id)
        payload = request.payload

        source_tier = payload.get("source_tier", "")
        target_tier = payload.get("target_tier", "")
        entry_id = payload.get("entry_id", "")
        rationale = payload.get("rationale", "Manual promotion")

        if target_tier == "L0":
            # L0 updates require user approval — create suggestion only
            governor: MemoryGovernor = ctx["governor"]
            decision = await governor.suggest_l0_update(
                key=entry_id,
                value=payload.get("content", ""),
                rationale=rationale,
            )
            return LexiconResponse(
                success=True,
                action=LexiconAction.PROMOTE_MEMORY,
                data={
                    "decision": decision.model_dump(),
                    "note": "L0 update suggested. Requires user approval.",
                },
            ).model_dump()

        # For L3→L1 or L3→L2 promotions
        if source_tier == "L3" and target_tier in ("L1", "L2"):
            # Fetch the L3 entry
            entry = await ctx["l3"].get_by_id(entry_id)
            if not entry:
                return LexiconResponse(
                    success=False,
                    action=LexiconAction.PROMOTE_MEMORY,
                    error=f"Entry {entry_id} not found in {source_tier}.",
                ).model_dump()

            # Store in target tier
            if target_tier == "L1":
                new_id = await ctx["l1"].store(
                    content=entry["content"],
                    category=payload.get("category", "promoted"),
                    tags=entry.get("tags", []) + ["promoted_from_l3"],
                    source=f"promotion:{entry_id}",
                )
            else:  # L2
                new_id = await ctx["l2"].store(
                    content=entry["content"],
                    pattern_type=payload.get("pattern_type", "observed"),
                    tags=entry.get("tags", []) + ["promoted_from_l3"],
                    source=f"promotion:{entry_id}",
                )

            return LexiconResponse(
                success=True,
                action=LexiconAction.PROMOTE_MEMORY,
                data={
                    "new_entry_id": new_id,
                    "source_tier": source_tier,
                    "target_tier": target_tier,
                    "rationale": rationale,
                },
            ).model_dump()

        return LexiconResponse(
            success=False,
            action=LexiconAction.PROMOTE_MEMORY,
            error=f"Unsupported promotion path: {source_tier} → {target_tier}",
        ).model_dump()

    async def _handle_query_tier(self, request: LexiconRequest) -> Dict[str, Any]:
        """Handle QUERY_TIER: direct query against a specific tier."""
        ctx = await self._get_user_context(request.tenant_id, request.user_id)
        payload = request.payload

        tier = payload.get("tier", "")
        query = payload.get("query", "")

        if tier == "L0":
            key = payload.get("key")  # Optional dot-notation key
            data = await ctx["l0"].query(key)
            return LexiconResponse(
                success=True,
                action=LexiconAction.QUERY_TIER,
                data={"tier": "L0", "result": data},
            ).model_dump()
        elif tier == "L1":
            results = await ctx["l1"].search(query, limit=payload.get("limit", 20))
            return LexiconResponse(
                success=True,
                action=LexiconAction.QUERY_TIER,
                data={"tier": "L1", "results": results},
            ).model_dump()
        elif tier == "L2":
            results = await ctx["l2"].search(query, limit=payload.get("limit", 20))
            return LexiconResponse(
                success=True,
                action=LexiconAction.QUERY_TIER,
                data={"tier": "L2", "results": results},
            ).model_dump()
        elif tier == "L3":
            results = await ctx["l3"].search_fts(query, limit=payload.get("limit", 20))
            return LexiconResponse(
                success=True,
                action=LexiconAction.QUERY_TIER,
                data={"tier": "L3", "results": results},
            ).model_dump()
        elif tier == "L4":
            results = await ctx["l4"].search(query, limit=payload.get("limit", 20))
            return LexiconResponse(
                success=True,
                action=LexiconAction.QUERY_TIER,
                data={"tier": "L4", "results": results},
            ).model_dump()
        else:
            return LexiconResponse(
                success=False,
                action=LexiconAction.QUERY_TIER,
                error=f"Unknown or unsupported tier for direct query: {tier}",
            ).model_dump()

    async def _handle_governor_status(
        self, request: LexiconRequest
    ) -> Dict[str, Any]:
        """Handle GET_GOVERNOR_STATUS: return Memory Governor status."""
        ctx = await self._get_user_context(request.tenant_id, request.user_id)
        governor: MemoryGovernor = ctx["governor"]
        status = await governor.get_status()

        return LexiconResponse(
            success=True,
            action=LexiconAction.GET_GOVERNOR_STATUS,
            data=status.model_dump(),
        ).model_dump()

    async def _handle_session_end(self, request: LexiconRequest) -> Dict[str, Any]:
        """Handle SESSION_END: trigger L5→L3 promotion pipeline."""
        ctx = await self._get_user_context(request.tenant_id, request.user_id)
        payload = request.payload
        session_id = payload.get("session_id", "")

        if not session_id:
            return LexiconResponse(
                success=False,
                action=LexiconAction.SESSION_END,
                error="session_id is required.",
            ).model_dump()

        l5 = ctx["l5_sessions"].get(session_id)
        if not l5:
            return LexiconResponse(
                success=True,
                action=LexiconAction.SESSION_END,
                data={"note": "No active L5 scratchpad for this session.", "promoted": 0},
            ).model_dump()

        governor: MemoryGovernor = ctx["governor"]
        decisions = await governor.process_session_end(l5)

        # Remove the session from active L5 sessions
        del ctx["l5_sessions"][session_id]
        ctx["router"].remove_l5()

        return LexiconResponse(
            success=True,
            action=LexiconAction.SESSION_END,
            data={
                "session_id": session_id,
                "promoted": len(decisions),
                "decisions": [d.model_dump() for d in decisions],
            },
        ).model_dump()

    # ─────────────────────────────────────────────
    # Public API (for direct invocation by other agents in-process)
    # ─────────────────────────────────────────────

    async def assemble_context(self, request: ContextRequest) -> Dict[str, Any]:
        """
        Public convenience method for context assembly.
        Can be called directly by other agents without going through the bus.
        """
        lexicon_request = LexiconRequest(
            action=LexiconAction.ASSEMBLE_CONTEXT,
            tenant_id=request.tenant_id,
            user_id=request.user_id,
            payload={
                "query": request.query,
                "scope": request.scope,
                "token_budget": request.token_budget,
                "session_id": request.session_id,
            },
        )
        return await self._handle_assemble_context(lexicon_request)

    async def initialize_user_memory(self, tenant_id: str, user_id: str) -> None:
        """
        Initialize memory storage for a new user.
        Called during user onboarding (UC-5).
        """
        await ensure_user_storage(tenant_id, user_id, self._base_dir)
        await self._get_user_context(tenant_id, user_id)
        logger.info(f"Memory initialized for user: tenant={tenant_id}, user={user_id}")
''',

    # ═══════════════════════════════════════════════════════════════════
    # TESTS
    # ═══════════════════════════════════════════════════════════════════

    "tests/test_lexicon/__init__.py": '''
# tests/test_lexicon/__init__.py
"""Tests for the Lexicon Memory Control Plane (CHUNK-006)."""
''',

    "tests/test_lexicon/test_tiers.py": '''
# tests/test_lexicon/test_tiers.py
# Unit tests for L0–L5 memory tiers.
"""
Tests for individual memory tier implementations.
"""

import asyncio
import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

from aegis.agents.lexicon.storage import ensure_user_storage
from aegis.agents.lexicon.tiers.l0_identity import L0IdentityTier
from aegis.agents.lexicon.tiers.l1_domain import L1DomainTier
from aegis.agents.lexicon.tiers.l2_workflow import L2WorkflowTier
from aegis.agents.lexicon.tiers.l3_episodic import L3EpisodicTier
from aegis.agents.lexicon.tiers.l4_artifacts import L4ArtifactTier
from aegis.agents.lexicon.tiers.l5_scratchpad import L5ScratchpadTier


# Fixtures
TEST_TENANT = "test-tenant-001"
TEST_USER = "test-user-001"


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test storage."""
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d)


@pytest_asyncio.fixture
async def initialized_storage(temp_dir):
    """Initialize user storage and return the base directory."""
    await ensure_user_storage(TEST_TENANT, TEST_USER, temp_dir)
    return temp_dir


# ─────────────────────────────────────────────
# L0 Tests
# ─────────────────────────────────────────────

class TestL0IdentityTier:
    @pytest.mark.asyncio
    async def test_load_default(self, initialized_storage):
        l0 = L0IdentityTier(TEST_TENANT, TEST_USER, initialized_storage)
        data = await l0.load()
        assert "identity" in data
        assert "preferences" in data

    @pytest.mark.asyncio
    async def test_query_dot_notation(self, initialized_storage):
        l0 = L0IdentityTier(TEST_TENANT, TEST_USER, initialized_storage)
        style = await l0.query("preferences.communication_style")
        assert style == "balanced"

    @pytest.mark.asyncio
    async def test_query_nonexistent_key(self, initialized_storage):
        l0 = L0IdentityTier(TEST_TENANT, TEST_USER, initialized_storage)
        result = await l0.query("nonexistent.key")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_context_fragments(self, initialized_storage):
        l0 = L0IdentityTier(TEST_TENANT, TEST_USER, initialized_storage)
        fragments = await l0.get_context_fragments("test query")
        assert len(fragments) > 0
        assert all(f["tier"] == "L0" for f in fragments)
        assert all(f["relevance"] == 1.0 for f in fragments)

    @pytest.mark.asyncio
    async def test_suggest_update(self, initialized_storage):
        l0 = L0IdentityTier(TEST_TENANT, TEST_USER, initialized_storage)
        suggestion = await l0.suggest_update(
            "preferences.detail_level", "verbose", "User consistently requests detailed responses"
        )
        assert suggestion["requires_user_approval"] is True
        assert suggestion["proposed_value"] == "verbose"

    @pytest.mark.asyncio
    async def test_cache_invalidation(self, initialized_storage):
        l0 = L0IdentityTier(TEST_TENANT, TEST_USER, initialized_storage)
        await l0.load()  # Populate cache
        assert l0._cache is not None
        l0.invalidate_cache()
        assert l0._cache is None


# ─────────────────────────────────────────────
# L1 Tests
# ─────────────────────────────────────────────

class TestL1DomainTier:
    @pytest.mark.asyncio
    async def test_store_and_search(self, initialized_storage):
        l1 = L1DomainTier(TEST_TENANT, TEST_USER, initialized_storage)
        entry_id = await l1.store(
            content="Python async/await enables concurrent I/O operations.",
            category="python",
            tags=["async", "concurrency"],
            source="documentation",
        )
        assert entry_id is not None

        results = await l1.search("async python")
        assert len(results) > 0
        assert results[0]["content"] == "Python async/await enables concurrent I/O operations."

    @pytest.mark.asyncio
    async def test_search_with_category_filter(self, initialized_storage):
        l1 = L1DomainTier(TEST_TENANT, TEST_USER, initialized_storage)
        await l1.store(content="Redis is an in-memory data store.", category="redis")
        await l1.store(content="Python is a programming language.", category="python")

        results = await l1.search("data store", category="redis")
        assert all(r["category"] == "redis" for r in results)

    @pytest.mark.asyncio
    async def test_get_context_fragments(self, initialized_storage):
        l1 = L1DomainTier(TEST_TENANT, TEST_USER, initialized_storage)
        await l1.store(content="FastAPI uses Starlette for the web parts.", tags=["web"])
        fragments = await l1.get_context_fragments("web framework")
        assert all(f["tier"] == "L1" for f in fragments)

    @pytest.mark.asyncio
    async def test_count(self, initialized_storage):
        l1 = L1DomainTier(TEST_TENANT, TEST_USER, initialized_storage)
        assert await l1.count() == 0
        await l1.store(content="Test entry")
        assert await l1.count() == 1

    @pytest.mark.asyncio
    async def test_deprecate(self, initialized_storage):
        l1 = L1DomainTier(TEST_TENANT, TEST_USER, initialized_storage)
        entry_id = await l1.store(content="Outdated info")
        result = await l1.deprecate(entry_id)
        assert result is True


# ─────────────────────────────────────────────
# L2 Tests
# ─────────────────────────────────────────────

class TestL2WorkflowTier:
    @pytest.mark.asyncio
    async def test_store_and_search(self, initialized_storage):
        l2 = L2WorkflowTier(TEST_TENANT, TEST_USER, initialized_storage)
        entry_id = await l2.store(
            content="User prefers bullet-point summaries over prose.",
            pattern_type="format_preference",
            confidence=0.7,
        )
        assert entry_id is not None

        results = await l2.search("bullet summary format")
        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_reinforce(self, initialized_storage):
        l2 = L2WorkflowTier(TEST_TENANT, TEST_USER, initialized_storage)
        entry_id = await l2.store(content="Uses vim keybindings.", confidence=0.5)
        result = await l2.reinforce(entry_id, confidence_boost=0.2)
        assert result is True

    @pytest.mark.asyncio
    async def test_count(self, initialized_storage):
        l2 = L2WorkflowTier(TEST_TENANT, TEST_USER, initialized_storage)
        assert await l2.count() == 0
        await l2.store(content="Pattern entry")
        assert await l2.count() == 1


# ─────────────────────────────────────────────
# L3 Tests
# ─────────────────────────────────────────────

class TestL3EpisodicTier:
    @pytest.mark.asyncio
    async def test_append_and_search(self, initialized_storage):
        l3 = L3EpisodicTier(TEST_TENANT, TEST_USER, initialized_storage)
        entry_id = await l3.append(
            content="Decided to use Redis Streams for the message bus.",
            event_type="decision",
            tags=["architecture", "redis"],
        )
        assert entry_id is not None

        results = await l3.search_fts("Redis Streams")
        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_search_by_recency(self, initialized_storage):
        l3 = L3EpisodicTier(TEST_TENANT, TEST_USER, initialized_storage)
        await l3.append(content="First event", event_type="event")
        await l3.append(content="Second event", event_type="event")

        results = await l3.search_by_recency(limit=5)
        assert len(results) == 2
        # Most recent should be first
        assert "Second" in results[0]["content"]

    @pytest.mark.asyncio
    async def test_search_by_event_type(self, initialized_storage):
        l3 = L3EpisodicTier(TEST_TENANT, TEST_USER, initialized_storage)
        await l3.append(content="A decision was made.", event_type="decision")
        await l3.append(content="A conversation happened.", event_type="conversation")

        results = await l3.search_by_recency(event_type="decision")
        assert all(r["event_type"] == "decision" for r in results)

    @pytest.mark.asyncio
    async def test_get_by_id(self, initialized_storage):
        l3 = L3EpisodicTier(TEST_TENANT, TEST_USER, initialized_storage)
        entry_id = await l3.append(content="Specific event to find.")
        result = await l3.get_by_id(entry_id)
        assert result is not None
        assert result["content"] == "Specific event to find."

    @pytest.mark.asyncio
    async def test_count(self, initialized_storage):
        l3 = L3EpisodicTier(TEST_TENANT, TEST_USER, initialized_storage)
        assert await l3.count() == 0
        await l3.append(content="Entry 1")
        await l3.append(content="Entry 2")
        assert await l3.count() == 2


# ─────────────────────────────────────────────
# L4 Tests
# ─────────────────────────────────────────────

class TestL4ArtifactTier:
    @pytest.mark.asyncio
    async def test_store_and_search(self, initialized_storage):
        l4 = L4ArtifactTier(TEST_TENANT, TEST_USER, initialized_storage)
        entry_id = await l4.store(
            name="Aegis Spec",
            artifact_type="document",
            path_or_uri="/docs/aegis_spec.pdf",
            description="The canonical Project Aegis specification document.",
            tags=["aegis", "spec"],
        )
        assert entry_id is not None

        results = await l4.search("aegis specification")
        assert len(results) > 0
        assert results[0]["name"] == "Aegis Spec"

    @pytest.mark.asyncio
    async def test_validate_artifact(self, initialized_storage):
        l4 = L4ArtifactTier(TEST_TENANT, TEST_USER, initialized_storage)
        entry_id = await l4.store(
            name="Test File",
            artifact_type="file",
            path_or_uri="/tmp/test.txt",
        )
        result = await l4.validate_artifact(entry_id)
        assert result is True

    @pytest.mark.asyncio
    async def test_count(self, initialized_storage):
        l4 = L4ArtifactTier(TEST_TENANT, TEST_USER, initialized_storage)
        assert await l4.count() == 0
        await l4.store(name="Artifact", artifact_type="file", path_or_uri="/a.txt")
        assert await l4.count() == 1


# ─────────────────────────────────────────────
# L5 Tests
# ─────────────────────────────────────────────

class TestL5ScratchpadTier:
    @pytest.mark.asyncio
    async def test_set_and_get(self):
        l5 = L5ScratchpadTier(TEST_TENANT, TEST_USER, "session-001", redis_client=None)
        await l5.set("key1", "value1")
        result = await l5.get("key1")
        assert result == "value1"

    @pytest.mark.asyncio
    async def test_get_default(self):
        l5 = L5ScratchpadTier(TEST_TENANT, TEST_USER, "session-001", redis_client=None)
        result = await l5.get("nonexistent", default="fallback")
        assert result == "fallback"

    @pytest.mark.asyncio
    async def test_delete(self):
        l5 = L5ScratchpadTier(TEST_TENANT, TEST_USER, "session-001", redis_client=None)
        await l5.set("key1", "value1")
        existed = await l5.delete("key1")
        assert existed is True
        result = await l5.get("key1")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_all(self):
        l5 = L5ScratchpadTier(TEST_TENANT, TEST_USER, "session-001", redis_client=None)
        await l5.set("a", 1)
        await l5.set("b", 2)
        all_data = await l5.get_all()
        assert all_data == {"a": 1, "b": 2}

    @pytest.mark.asyncio
    async def test_clear(self):
        l5 = L5ScratchpadTier(TEST_TENANT, TEST_USER, "session-001", redis_client=None)
        await l5.set("x", "y")
        count = await l5.clear()
        assert count == 1
        all_data = await l5.get_all()
        assert all_data == {}

    @pytest.mark.asyncio
    async def test_snapshot(self):
        l5 = L5ScratchpadTier(TEST_TENANT, TEST_USER, "session-002", redis_client=None)
        await l5.set("decision", "Use event sourcing")
        snapshot = await l5.snapshot()
        assert snapshot["session_id"] == "session-002"
        assert snapshot["entries"]["decision"] == "Use event sourcing"

    @pytest.mark.asyncio
    async def test_get_context_fragments(self):
        l5 = L5ScratchpadTier(TEST_TENANT, TEST_USER, "session-001", redis_client=None)
        await l5.set("note", "Important context")
        fragments = await l5.get_context_fragments("context")
        assert len(fragments) == 1
        assert fragments[0]["tier"] == "L5"
        assert "Important context" in fragments[0]["content"]
''',

    "tests/test_lexicon/test_context_router.py": '''
# tests/test_lexicon/test_context_router.py
# Unit tests for the Context Router.
"""
Tests for the Context Router — context assembly from multiple tiers.
"""

import shutil
import tempfile

import pytest
import pytest_asyncio

from aegis.agents.lexicon.context_router import ContextRouter, estimate_tokens
from aegis.agents.lexicon.storage import ensure_user_storage
from aegis.agents.lexicon.tiers.l0_identity import L0IdentityTier
from aegis.agents.lexicon.tiers.l1_domain import L1DomainTier
from aegis.agents.lexicon.tiers.l2_workflow import L2WorkflowTier
from aegis.agents.lexicon.tiers.l3_episodic import L3EpisodicTier
from aegis.agents.lexicon.tiers.l4_artifacts import L4ArtifactTier
from aegis.agents.lexicon.tiers.l5_scratchpad import L5ScratchpadTier
from aegis.schemas.lexicon import ContextRequest


TEST_TENANT = "test-tenant-001"
TEST_USER = "test-user-001"


@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d)


@pytest_asyncio.fixture
async def router_with_data(temp_dir):
    """Set up a Context Router with populated tier data."""
    await ensure_user_storage(TEST_TENANT, TEST_USER, temp_dir)

    l0 = L0IdentityTier(TEST_TENANT, TEST_USER, temp_dir)
    l1 = L1DomainTier(TEST_TENANT, TEST_USER, temp_dir)
    l2 = L2WorkflowTier(TEST_TENANT, TEST_USER, temp_dir)
    l3 = L3EpisodicTier(TEST_TENANT, TEST_USER, temp_dir)
    l4 = L4ArtifactTier(TEST_TENANT, TEST_USER, temp_dir)

    # Populate with test data
    await l1.store("Python uses asyncio for async programming.", category="python", tags=["async"])
    await l1.store("Redis supports pub/sub and streams.", category="redis", tags=["messaging"])
    await l2.store("User prefers structured JSON responses.", pattern_type="format_preference")
    await l3.append("Decided to use Pydantic for all data models.", event_type="decision")
    await l3.append("Meeting about architecture patterns.", event_type="conversation")
    await l4.store(name="API Docs", artifact_type="url", path_or_uri="https://docs.example.com")

    router = ContextRouter(l0=l0, l1=l1, l2=l2, l3=l3, l4=l4)
    return router


class TestContextRouter:
    @pytest.mark.asyncio
    async def test_assemble_basic(self, router_with_data):
        request = ContextRequest(
            query="async programming patterns",
            tenant_id=TEST_TENANT,
            user_id=TEST_USER,
            scope=["L0", "L1", "L2", "L3"],
            token_budget=4000,
        )
        packet = await router_with_data.assemble(request)

        assert packet.tenant_id == TEST_TENANT
        assert packet.user_id == TEST_USER
        assert len(packet.fragments) > 0
        assert packet.total_tokens > 0
        assert packet.total_tokens <= 4000
        assert packet.assembly_time_ms > 0

    @pytest.mark.asyncio
    async def test_assemble_respects_token_budget(self, router_with_data):
        request = ContextRequest(
            query="python redis",
            tenant_id=TEST_TENANT,
            user_id=TEST_USER,
            scope=["L0", "L1", "L2", "L3", "L4"],
            token_budget=50,  # Very small budget
        )
        packet = await router_with_data.assemble(request)
        assert packet.total_tokens <= 50

    @pytest.mark.asyncio
    async def test_assemble_with_l5(self, router_with_data):
        l5 = L5ScratchpadTier(TEST_TENANT, TEST_USER, "sess-001", redis_client=None)
        await l5.set("current_task", "Building the memory system")
        router_with_data.set_l5(l5)

        request = ContextRequest(
            query="memory system",
            tenant_id=TEST_TENANT,
            user_id=TEST_USER,
            scope=["L0", "L1"],
            token_budget=4000,
            session_id="sess-001",
        )
        packet = await router_with_data.assemble(request)

        # L5 should be included because session_id was provided
        tiers_in_fragments = {f.tier for f in packet.fragments}
        assert "L5" in tiers_in_fragments

    @pytest.mark.asyncio
    async def test_assemble_scoped_tiers(self, router_with_data):
        request = ContextRequest(
            query="data models",
            tenant_id=TEST_TENANT,
            user_id=TEST_USER,
            scope=["L1"],  # Only L1
            token_budget=4000,
        )
        packet = await router_with_data.assemble(request)

        # Only L1 should appear (though L0 won't because not in scope)
        tiers_in_fragments = {f.tier for f in packet.fragments}
        assert "L3" not in tiers_in_fragments
        assert "L2" not in tiers_in_fragments


class TestEstimateTokens:
    def test_basic_estimation(self):
        text = "Hello world"  # 11 chars
        tokens = estimate_tokens(text)
        assert tokens >= 1
        assert tokens <= 10

    def test_empty_string(self):
        assert estimate_tokens("") == 1  # Minimum 1

    def test_long_text(self):
        text = "x" * 400  # ~100 tokens
        tokens = estimate_tokens(text)
        assert 90 <= tokens <= 110
''',

    "tests/test_lexicon/test_governor.py": '''
# tests/test_lexicon/test_governor.py
# Unit tests for the Memory Governor.
"""
Tests for the Memory Governor — promotion pipeline and lifecycle management.
"""

import shutil
import tempfile

import pytest
import pytest_asyncio

from aegis.agents.lexicon.governor import MemoryGovernor
from aegis.agents.lexicon.storage import ensure_user_storage
from aegis.agents.lexicon.tiers.l3_episodic import L3EpisodicTier
from aegis.agents.lexicon.tiers.l5_scratchpad import L5ScratchpadTier
from aegis.schemas.lexicon import MemoryGovernorAction


TEST_TENANT = "test-tenant-001"
TEST_USER = "test-user-001"


@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d)


@pytest_asyncio.fixture
async def governor(temp_dir):
    """Set up a Memory Governor with initialized storage."""
    await ensure_user_storage(TEST_TENANT, TEST_USER, temp_dir)
    l3 = L3EpisodicTier(TEST_TENANT, TEST_USER, temp_dir)
    gov = MemoryGovernor(TEST_TENANT, TEST_USER, l3, temp_dir)
    return gov


class TestMemoryGovernor:
    @pytest.mark.asyncio
    async def test_process_session_end_empty(self, governor):
        l5 = L5ScratchpadTier(TEST_TENANT, TEST_USER, "sess-empty", redis_client=None)
        decisions = await governor.process_session_end(l5)
        assert decisions == []

    @pytest.mark.asyncio
    async def test_process_session_end_with_significant_entries(self, governor):
        l5 = L5ScratchpadTier(TEST_TENANT, TEST_USER, "sess-sig", redis_client=None)
        # High-significance keys
        await l5.set("decision_architecture", "Chose event sourcing for the message bus. " * 20)
        await l5.set("outcome_review", "Successfully passed all integration tests. " * 20)
        # Low-significance key
        await l5.set("temp_debug", "x")

        decisions = await governor.process_session_end(l5, significance_threshold=0.3)

        # At least the high-significance entries should be promoted
        assert len(decisions) >= 1
        assert all(d.action == MemoryGovernorAction.PROMOTE for d in decisions)
        assert all(d.source_tier == "L5" and d.target_tier == "L3" for d in decisions)

        # L5 should be cleared after processing
        all_data = await l5.get_all()
        assert all_data == {}

    @pytest.mark.asyncio
    async def test_get_status(self, governor):
        status = await governor.get_status()
        assert status.l3_retention_days == 365
        assert status.pending_promotions == 0

    @pytest.mark.asyncio
    async def test_suggest_l0_update(self, governor):
        decision = await governor.suggest_l0_update(
            key="preferences.detail_level",
            value="verbose",
            rationale="User consistently requests more detail."
        )
        assert decision.requires_user_approval is True
        assert decision.action == MemoryGovernorAction.SUGGEST_L0_UPDATE
        assert decision.target_tier == "L0"

    @pytest.mark.asyncio
    async def test_run_eviction(self, governor):
        # With no old entries, eviction should remove 0
        evicted = await governor.run_eviction()
        assert evicted == 0


class TestSignificanceEvaluation:
    """Test the significance evaluation heuristics."""

    @pytest.mark.asyncio
    async def test_high_signal_key(self, governor):
        score = governor._evaluate_significance("decision_final", "Important architectural choice made here. " * 20)
        assert score >= 0.5

    @pytest.mark.asyncio
    async def test_low_signal_key(self, governor):
        score = governor._evaluate_significance("temp_var", "x")
        assert score < 0.3

    @pytest.mark.asyncio
    async def test_medium_content_length(self, governor):
        score = governor._evaluate_significance("note", "A" * 200)
        assert score >= 0.3
''',

    "tests/test_lexicon/test_agent.py": '''
# tests/test_lexicon/test_agent.py
# Integration tests for the Lexicon Agent.
"""
Tests for the Lexicon Agent — end-to-end message handling.
"""

import shutil
import tempfile

import pytest
import pytest_asyncio

from aegis.agents.lexicon.agent import LexiconAgent
from aegis.schemas.lexicon import LexiconAction


TEST_TENANT = "test-tenant-001"
TEST_USER = "test-user-001"


@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d)


@pytest_asyncio.fixture
async def agent(temp_dir):
    """Create and start a Lexicon agent."""
    a = LexiconAgent(redis_client=None, base_dir=temp_dir)
    await a.startup()
    yield a
    await a.shutdown()


class TestLexiconAgent:
    @pytest.mark.asyncio
    async def test_store_and_search_l3(self, agent):
        # Store a memory
        store_msg = {
            "action": "lexicon.store_memory",
            "tenant_id": TEST_TENANT,
            "user_id": TEST_USER,
            "payload": {
                "action": "store_memory",
                "tier": "L3",
                "content": "Deployed version 2.0 of the API successfully.",
                "tags": ["deployment", "api"],
                "metadata": {"event_type": "outcome"},
            },
        }
        result = await agent.handle_message(store_msg)
        assert result["success"] is True
        assert "entry_id" in result["data"]

        # Search for it
        search_msg = {
            "action": "lexicon.search_memory",
            "tenant_id": TEST_TENANT,
            "user_id": TEST_USER,
            "payload": {
                "action": "search_memory",
                "query": "API deployment",
                "tiers": ["L3"],
            },
        }
        result = await agent.handle_message(search_msg)
        assert result["success"] is True
        assert len(result["data"]["results"].get("L3", [])) > 0

    @pytest.mark.asyncio
    async def test_assemble_context(self, agent):
        # Store some data first
        await agent.handle_message({
            "action": "lexicon.store_memory",
            "tenant_id": TEST_TENANT,
            "user_id": TEST_USER,
            "payload": {
                "action": "store_memory",
                "tier": "L1",
                "content": "FastAPI is built on Starlette and Pydantic.",
                "metadata": {"category": "python"},
                "tags": ["web", "python"],
            },
        })

        # Assemble context
        assemble_msg = {
            "action": "lexicon.assemble_context",
            "tenant_id": TEST_TENANT,
            "user_id": TEST_USER,
            "payload": {
                "action": "assemble_context",
                "query": "web framework python",
                "scope": ["L0", "L1", "L2", "L3"],
                "token_budget": 4000,
            },
        }
        result = await agent.handle_message(assemble_msg)
        assert result["success"] is True
        assert "fragments" in result["data"]
        assert result["data"]["total_tokens"] <= 4000

    @pytest.mark.asyncio
    async def test_store_l0_rejected(self, agent):
        msg = {
            "action": "lexicon.store_memory",
            "tenant_id": TEST_TENANT,
            "user_id": TEST_USER,
            "payload": {
                "action": "store_memory",
                "tier": "L0",
                "content": "Should be rejected.",
            },
        }
        result = await agent.handle_message(msg)
        assert result["success"] is False
        assert "user-editable only" in result["error"]

    @pytest.mark.asyncio
    async def test_store_l5_requires_session(self, agent):
        msg = {
            "action": "lexicon.store_memory",
            "tenant_id": TEST_TENANT,
            "user_id": TEST_USER,
            "payload": {
                "action": "store_memory",
                "tier": "L5",
                "content": "Some scratch data",
            },
        }
        result = await agent.handle_message(msg)
        assert result["success"] is False
        assert "session_id" in result["error"]

    @pytest.mark.asyncio
    async def test_store_l5_with_session(self, agent):
        msg = {
            "action": "lexicon.store_memory",
            "tenant_id": TEST_TENANT,
            "user_id": TEST_USER,
            "payload": {
                "action": "store_memory",
                "tier": "L5",
                "content": "Working context for current task",
                "session_id": "sess-test-001",
                "metadata": {"key": "current_task"},
            },
        }
        result = await agent.handle_message(msg)
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_query_tier_l0(self, agent):
        msg = {
            "action": "lexicon.query_tier",
            "tenant_id": TEST_TENANT,
            "user_id": TEST_USER,
            "payload": {
                "action": "query_tier",
                "tier": "L0",
                "key": "preferences.communication_style",
            },
        }
        result = await agent.handle_message(msg)
        assert result["success"] is True
        assert result["data"]["result"] == "balanced"

    @pytest.mark.asyncio
    async def test_governor_status(self, agent):
        msg = {
            "action": "lexicon.get_governor_status",
            "tenant_id": TEST_TENANT,
            "user_id": TEST_USER,
            "payload": {"action": "get_governor_status"},
        }
        result = await agent.handle_message(msg)
        assert result["success"] is True
        assert "l3_retention_days" in result["data"]

    @pytest.mark.asyncio
    async def test_session_end(self, agent):
        # Store L5 data
        await agent.handle_message({
            "action": "lexicon.store_memory",
            "tenant_id": TEST_TENANT,
            "user_id": TEST_USER,
            "payload": {
                "action": "store_memory",
                "tier": "L5",
                "content": "Final decision: use event sourcing pattern",
                "session_id": "sess-end-test",
                "metadata": {"key": "decision_architecture"},
            },
        })

        # End session
        msg = {
            "action": "lexicon.session_end",
            "tenant_id": TEST_TENANT,
            "user_id": TEST_USER,
            "payload": {"action": "session_end", "session_id": "sess-end-test"},
        }
        result = await agent.handle_message(msg)
        assert result["success"] is True
        assert "promoted" in result["data"]

    @pytest.mark.asyncio
    async def test_initialize_user_memory(self, agent):
        new_tenant = "new-tenant"
        new_user = "new-user"
        await agent.initialize_user_memory(new_tenant, new_user)

        # Should be able to query the new user's L0
        msg = {
            "action": "lexicon.query_tier",
            "tenant_id": new_tenant,
            "user_id": new_user,
            "payload": {"action": "query_tier", "tier": "L0"},
        }
        result = await agent.handle_message(msg)
        assert result["success"] is True
        assert "identity" in result["data"]["result"]

    @pytest.mark.asyncio
    async def test_promote_l3_to_l1(self, agent):
        # First, store an L3 entry
        store_result = await agent.handle_message({
            "action": "lexicon.store_memory",
            "tenant_id": TEST_TENANT,
            "user_id": TEST_USER,
            "payload": {
                "action": "store_memory",
                "tier": "L3",
                "content": "Redis Streams provide durable ordered message delivery.",
                "metadata": {"event_type": "learning"},
                "tags": ["redis", "architecture"],
            },
        })
        entry_id = store_result["data"]["entry_id"]

        # Promote L3→L1
        promote_msg = {
            "action": "lexicon.promote_memory",
            "tenant_id": TEST_TENANT,
            "user_id": TEST_USER,
            "payload": {
                "action": "promote_memory",
                "entry_id": entry_id,
                "source_tier": "L3",
                "target_tier": "L1",
                "category": "redis",
                "rationale": "Confirmed architectural knowledge.",
            },
        }
        result = await agent.handle_message(promote_msg)
        assert result["success"] is True
        assert result["data"]["target_tier"] == "L1"
        assert "new_entry_id" in result["data"]
''',

    # ═══════════════════════════════════════════════════════════════════
    # CONFIGURATION UPDATES
    # ═══════════════════════════════════════════════════════════════════

    "requirements_chunk006.txt": '''
# Additional dependencies for CHUNK-006: Lexicon (Memory)
# Append these to your existing requirements.txt
aiosqlite>=0.19.0
pyyaml>=6.0.1
''',

}


def create_package_init_files(path):
    """Create __init__.py files in parent directories if they don't exist."""
    dir_name = os.path.dirname(path)
    if dir_name and (dir_name.startswith("") or dir_name.startswith("tests/")):
        parts = dir_name.split("/")
        for i in range(2, len(parts) + 1):
            pkg_path = "/".join(parts[:i])
            init_file = os.path.join(pkg_path, "__init__.py")
            if not os.path.exists(init_file):
                os.makedirs(pkg_path, exist_ok=True)
                print(f"  [Created] {init_file} (empty package marker)")
                with open(init_file, "w") as f:
                    pass


def main():
    """Main function to write all files for CHUNK-006."""
    print("═══════════════════════════════════════")
    print("  Assembling CHUNK-006: Lexicon (Memory)")
    print("═══════════════════════════════════════")
    print()

    files_written = 0
    for path, content in CHUNK_006_FILES.items():
        # Ensure the directory exists
        dir_name = os.path.dirname(path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)

        create_package_init_files(path)

        print(f"  [Writing] {path}")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(textwrap.dedent(content).strip() + "\n")
        files_written += 1

    print()
    print("───────────────────────────────────────")
    print(f"  Assembly Complete: {files_written} files written.")
    print()
    print("  New dependencies to install:")
    print("    pip install aiosqlite pyyaml")
    print()
    print("  Run tests:")
    print("    pytest tests/test_lexicon/ -v")
    print("───────────────────────────────────────")


if __name__ == "__main__":
    main()

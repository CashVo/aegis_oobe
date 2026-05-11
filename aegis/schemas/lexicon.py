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

# aegis/schemas/web.py
# Implements: Part X, §10.2 — Chat Page WebSocket Protocol
"""
Pydantic contracts for the User Interface layer (CLI + Web + MCP).
These define the wire-format for all client ↔ server communication.
"""

from time import datetime, utcnow
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(utcnow())


# ── WebSocket Chat Protocol ──────────────────────────────

class ChatInput(BaseModel):
    """Client → Server message for the chat interface."""
    message: str
    session_id: Optional[str] = None
    tenant_id: str
    user_id: str


class ChatOutput(BaseModel):
    """Server → Client message for the chat interface."""
    response: str
    session_id: str
    agent: str = "TOrchestrator"
    timestamp: datetime = Field(default_factory=_utc_now)
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ── Dashboard / Status Models ────────────────────────────

class AgentStatusItem(BaseModel):
    """Health status for a single agent."""
    agent_id: str
    status: str = "unknown"          # running | stopped | degraded | unknown
    last_heartbeat: Optional[datetime] = None
    uptime_seconds: Optional[float] = None
    message_count: int = 0


class SystemStatus(BaseModel):
    """Aggregate system health payload for the dashboard."""
    redis_connected: bool = False
    agents: List[AgentStatusItem] = Field(default_factory=list)
    scheduler_running: bool = False
    total_messages_processed: int = 0
    uptime_seconds: float = 0.0
    timestamp: datetime = Field(default_factory=_utc_now)


# ── Memory Explorer Models ───────────────────────────────

class MemorySearchRequest(BaseModel):
    """Request to search Lexicon memory from the UI."""
    query: str
    tenant_id: str
    user_id: str
    tiers: List[str] = Field(default_factory=lambda: ["L1", "L2", "L3"])
    limit: int = 20


class MemoryFragment(BaseModel):
    """A single memory fragment returned from Lexicon."""
    tier: str
    content: str
    relevance: float = 0.0
    created_at: Optional[datetime] = None
    memory_id: Optional[str] = None


class MemorySearchResponse(BaseModel):
    """Response from a Lexicon memory search."""
    fragments: List[MemoryFragment] = Field(default_factory=list)
    total_results: int = 0
    tiers_queried: List[str] = Field(default_factory=list)
    query: str = ""


# ── Schedule Models ──────────────────────────────────────

class ScheduleJobView(BaseModel):
    """Read-only view of a scheduled job for the UI."""
    job_id: str
    name: str
    description: str = ""
    schedule_type: str              # cron | interval | date
    schedule_config: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None


# ── User / Tenant Management Models ─────────────────────

class UserView(BaseModel):
    """Read-only user representation for the management UI."""
    user_id: str
    tenant_id: str
    username: str
    display_name: str = ""
    email: Optional[str] = None
    role_name: str = "member"
    is_root: bool = False
    status: str = "active"
    created_at: Optional[datetime] = None


class TenantView(BaseModel):
    """Read-only tenant representation."""
    tenant_id: str
    name: str
    status: str = "active"
    created_at: Optional[datetime] = None
    user_count: int = 0


# ── MCP Protocol Models ─────────────────────────────────

class MCPAuthContext(BaseModel):
    """Authentication context for MCP requests."""
    tenant_id: str
    user_id: str
    api_key: str


class MCPToolRequest(BaseModel):
    """Inbound MCP tool invocation."""
    tool_name: str          # memory_search | memory_store | context_assemble | tier_query
    arguments: Dict[str, Any] = Field(default_factory=dict)
    auth: MCPAuthContext


class MCPToolResponse(BaseModel):
    """Outbound MCP tool result."""
    success: bool
    result: Any = None
    error: Optional[str] = None

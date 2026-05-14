# aegis/schemas/torchestrator.py
# Implements: Part II §2.1 — TOrchestrator schemas
# Implements: Part X §10.2 — Chat WebSocket Protocol

from aegis.utils import time
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


# ─── Intent Classification ───────────────────────────────────────────

class IntentCategory(str, Enum):
    """High-level categories of user intent."""
    QUESTION = "question"              # General knowledge question (Oracle only)
    CONTEXTUAL_QUESTION = "contextual_question"  # Question requiring memory context
    FILE_OPERATION = "file_operation"   # File I/O tasks
    GIT_OPERATION = "git_operation"     # Git workflow tasks
    SCHEDULING = "scheduling"          # Schedule/cron tasks
    USER_MANAGEMENT = "user_management"  # Identity/user CRUD
    MEMORY_QUERY = "memory_query"      # Direct memory search/recall
    SYSTEM_COMMAND = "system_command"   # System status, health, config
    MULTI_STEP = "multi_step"          # Complex, requires decomposition
    CONVERSATION = "conversation"      # Casual/conversational (no tools)
    UNKNOWN = "unknown"


class Intent(BaseModel):
    """Parsed intent from user input."""
    category: IntentCategory
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)
    entities: Dict[str, Any] = Field(default_factory=dict)
    requires_tools: List[str] = Field(default_factory=list)
    requires_skills: List[str] = Field(default_factory=list)
    requires_memory: bool = False
    requires_oracle: bool = True
    raw_input: str = ""
    rewritten_query: Optional[str] = None  # Clarified/expanded query


# ─── Task Decomposition ──────────────────────────────────────────────

class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class TaskStep(BaseModel):
    """A single step in a decomposed task plan."""
    step_id: str = Field(default_factory=lambda: str(uuid4()))
    order: int
    description: str
    target_agent: str  # e.g., "forge", "oracle", "lexicon", "identity"
    action: str        # e.g., "forge.execute_tool", "oracle.query"
    payload: Dict[str, Any] = Field(default_factory=dict)
    depends_on: List[str] = Field(default_factory=list)  # step_ids
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class TaskPlan(BaseModel):
    """A complete execution plan for a user request."""
    plan_id: str = Field(default_factory=lambda: str(uuid4()))
    intent: Intent
    steps: List[TaskStep] = Field(default_factory=list)
    created_at: time.datetime = Field(default_factory=time.utcnow)
    completed_at: Optional[time.datetime] = None
    status: TaskStatus = TaskStatus.PENDING
    synthesis_instructions: str = ""  # How to combine step results


# ─── Session Management ──────────────────────────────────────────────

class SessionState(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    CLOSED = "closed"


class ConversationTurn(BaseModel):
    """A single turn in a conversation."""
    turn_id: str = Field(default_factory=lambda: str(uuid4()))
    role: str  # "user" or "assistant"
    content: str
    timestamp: time.datetime = Field(default_factory=time.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    # Metadata can include: tools_used, latency_ms, intent_category, etc.


class Session(BaseModel):
    """A multi-turn conversation session."""
    session_id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: str
    user_id: str
    state: SessionState = SessionState.ACTIVE
    history: List[ConversationTurn] = Field(default_factory=list)
    created_at: time.datetime = Field(default_factory=time.utcnow)
    last_activity: time.datetime = Field(default_factory=time.utcnow)
    context_window_tokens: int = 0
    max_context_tokens: int = 8000  # Configurable budget for history
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def add_turn(self, role: str, content: str, metadata: Optional[Dict[str, Any]] = None) -> ConversationTurn:
        """Add a conversation turn and update last_activity."""
        turn = ConversationTurn(
            role=role,
            content=content,
            metadata=metadata or {}
        )
        self.history.append(turn)
        self.last_activity = time.utcnow()
        return turn

    def get_recent_history(self, max_turns: int = 20) -> List[ConversationTurn]:
        """Get the most recent turns for context assembly."""
        return self.history[-max_turns:]


# ─── Chat Interface Protocol (Part X §10.2) ──────────────────────────

class ChatInput(BaseModel):
    """Client → Server message for chat interfaces."""
    message: str
    session_id: Optional[str] = None
    tenant_id: str
    user_id: str


class ChatOutput(BaseModel):
    """Server → Client message for chat interfaces."""
    response: str
    session_id: str
    agent: str = "TOrchestrator"
    timestamp: time.datetime = Field(default_factory=time.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    # metadata: thinking_time_ms, tools_used, skills_used, intent, etc.


# ─── TOrchestrator Protocol ──────────────────────────────────────────

class TOrchestratorAction(str, Enum):
    """Actions the TOrchestrator handles."""
    CHAT = "chat"                    # Process a user chat message
    RESUME_SESSION = "resume_session"  # Resume an existing session
    LIST_SESSIONS = "list_sessions"    # List user sessions
    CLOSE_SESSION = "close_session"    # Close a session


class TOrchestratorRequest(BaseModel):
    """Request envelope for TOrchestrator."""
    action: TOrchestratorAction
    session_id: Optional[str] = None
    message: Optional[str] = None
    tenant_id: str
    user_id: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TOrchestratorResponse(BaseModel):
    """Response envelope from TOrchestrator."""
    success: bool
    response: str = ""
    session_id: str = ""
    action: TOrchestratorAction
    tools_used: List[str] = Field(default_factory=list)
    skills_used: List[str] = Field(default_factory=list)
    latency_ms: float = 0.0
    error: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

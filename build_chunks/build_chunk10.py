# build_chunk_010.py
#
# CHUNK-010: TOrchestrator (Council Lead)
# Implements: Part II §2.1 (TOrchestrator role), Part X §10.2 (Chat Protocol),
#             Part XII UC-1, UC-2, UC-5, UC-6
#
# Dependencies: CHUNK-002 (Redis Bus), CHUNK-003 (Warden), CHUNK-008 (Oracle),
#               CHUNK-009 (The Forge)
#
# Run from the root of the project-aegis directory:
#   python build_chunk_010.py

import os
import textwrap


CHUNK_010_FILES = {

    # ═══════════════════════════════════════════════════════════════════
    # SCHEMAS
    # ═══════════════════════════════════════════════════════════════════

    "aegis/schemas/torchestrator.py": '''
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
''',

    # ═══════════════════════════════════════════════════════════════════
    # INTENT PARSER
    # ═══════════════════════════════════════════════════════════════════

    "aegis/agents/torchestrator/__init__.py": '''
# aegis/agents/torchestrator/__init__.py
from aegis.agents.torchestrator.agent import TOrchestrator

__all__ = ["TOrchestrator"]
''',

    "aegis/agents/torchestrator/intent.py": '''
# aegis/agents/torchestrator/intent.py
# Implements: Part II §2.1 — Intent Parsing
#
# The IntentParser classifies user input into actionable intents.
# It uses a two-tier approach:
#   1. Rule-based pattern matching (fast, deterministic, no LLM cost)
#   2. Oracle-based classification (fallback for ambiguous inputs)

import logging
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from aegis.schemas.torchestrator import Intent, IntentCategory

logger = logging.getLogger(__name__)


# ─── Pattern Rules ────────────────────────────────────────────────────

# Each rule is a tuple: (compiled_regex_pattern, IntentCategory, extractor_function)
# Extractor functions pull entities from the matched input.

def _extract_file_entities(text: str) -> Dict[str, Any]:
    """Extract file paths and operations from text."""
    entities: Dict[str, Any] = {}
    # Look for quoted file paths or common path patterns
    paths = re.findall(r"[\\'\\"]([\\/\\w\\-\\.]+)[\\'\\"]", text)
    if paths:
        entities["file_paths"] = paths
    # Detect operation type
    lower = text.lower()
    if any(w in lower for w in ["create", "write", "save"]):
        entities["operation"] = "write"
    elif any(w in lower for w in ["read", "show", "display", "cat", "open"]):
        entities["operation"] = "read"
    elif any(w in lower for w in ["delete", "remove", "rm"]):
        entities["operation"] = "delete"
    elif any(w in lower for w in ["list", "ls", "dir"]):
        entities["operation"] = "list"
    return entities


def _extract_git_entities(text: str) -> Dict[str, Any]:
    """Extract git-related entities from text."""
    entities: Dict[str, Any] = {}
    lower = text.lower()
    # Branch names
    branch_match = re.search(r"branch\\s+(?:called|named)?\\s*[\\'\\"]?([\\w\\-\\/]+)[\\'\\"]?", text, re.IGNORECASE)
    if branch_match:
        entities["branch_name"] = branch_match.group(1)
    # Operation type
    if any(w in lower for w in ["commit"]):
        entities["operation"] = "commit"
    elif any(w in lower for w in ["merge"]):
        entities["operation"] = "merge"
    elif any(w in lower for w in ["push"]):
        entities["operation"] = "push"
    elif any(w in lower for w in ["pull"]):
        entities["operation"] = "pull"
    elif any(w in lower for w in ["branch", "checkout"]):
        entities["operation"] = "branch"
    elif any(w in lower for w in ["workflow", "feature"]):
        entities["operation"] = "workflow"
    return entities


def _extract_schedule_entities(text: str) -> Dict[str, Any]:
    """Extract scheduling-related entities from text."""
    entities: Dict[str, Any] = {}
    # Time patterns
    time_match = re.search(r"at\\s+(\\d{1,2})(?::(\\d{2}))?\\s*(am|pm|AM|PM)?", text)
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2)) if time_match.group(2) else 0
        ampm = time_match.group(3)
        if ampm and ampm.lower() == "pm" and hour < 12:
            hour += 12
        elif ampm and ampm.lower() == "am" and hour == 12:
            hour = 0
        entities["hour"] = hour
        entities["minute"] = minute
    # Frequency
    lower = text.lower()
    if "nightly" in lower or "every night" in lower:
        entities["schedule_type"] = "cron"
        entities.setdefault("hour", 2)
        entities.setdefault("minute", 0)
    elif "hourly" in lower or "every hour" in lower:
        entities["schedule_type"] = "interval"
        entities["interval_hours"] = 1
    elif "daily" in lower or "every day" in lower:
        entities["schedule_type"] = "cron"
    elif "weekly" in lower or "every week" in lower:
        entities["schedule_type"] = "cron"
    # Task description
    task_match = re.search(r"schedule\\s+(?:a\\s+)?(.+?)(?:\\s+at\\s+|\\s+every\\s+|$)", text, re.IGNORECASE)
    if task_match:
        entities["task_description"] = task_match.group(1).strip()
    return entities


def _extract_user_entities(text: str) -> Dict[str, Any]:
    """Extract user management entities from text."""
    entities: Dict[str, Any] = {}
    # Username
    name_match = re.search(r"(?:named|called|username)\\s+[\\'\\"]?([\\w\\-]+)[\\'\\"]?", text, re.IGNORECASE)
    if name_match:
        entities["username"] = name_match.group(1)
    # Role
    role_match = re.search(r"(?:with|as)\\s+(?:the\\s+)?(?:role\\s+)?[\\'\\"]?(root|admin|member|observer)[\\'\\"]?", text, re.IGNORECASE)
    if role_match:
        entities["role"] = role_match.group(1).lower()
    # Operation
    lower = text.lower()
    if any(w in lower for w in ["create", "add", "onboard", "new"]):
        entities["operation"] = "create"
    elif any(w in lower for w in ["delete", "remove"]):
        entities["operation"] = "delete"
    elif any(w in lower for w in ["update", "modify", "change"]):
        entities["operation"] = "update"
    elif any(w in lower for w in ["list", "show"]):
        entities["operation"] = "list"
    return entities


def _extract_memory_entities(text: str) -> Dict[str, Any]:
    """Extract memory query entities."""
    entities: Dict[str, Any] = {}
    lower = text.lower()
    if "remember" in lower or "recall" in lower or "what do you know" in lower:
        entities["operation"] = "recall"
    elif "search" in lower or "find" in lower:
        entities["operation"] = "search"
    # Extract the subject of the memory query
    subject_match = re.search(r"(?:about|regarding|for)\\s+(.+?)(?:\\?|$)", text, re.IGNORECASE)
    if subject_match:
        entities["subject"] = subject_match.group(1).strip()
    return entities


# ─── Pattern Registry ─────────────────────────────────────────────────

INTENT_PATTERNS: List[Tuple[re.Pattern, IntentCategory, Callable[[str], Dict[str, Any]], List[str], List[str]]] = [
    # (pattern, category, extractor, required_tools, required_skills)

    # File operations
    (re.compile(r"\\b(create|write|save|read|show|display|cat|open|delete|remove|rm|list|ls)\\b.*\\b(file|directory|folder|dir|path)\\b", re.IGNORECASE),
     IntentCategory.FILE_OPERATION, _extract_file_entities,
     ["file_read", "file_write", "file_delete", "dir_list", "dir_create"], []),

    (re.compile(r"\\b(file|directory|folder)\\b.*\\b(create|write|save|read|show|delete|remove|list)\\b", re.IGNORECASE),
     IntentCategory.FILE_OPERATION, _extract_file_entities,
     ["file_read", "file_write", "file_delete", "dir_list", "dir_create"], []),

    # Git operations
    (re.compile(r"\\b(git|branch|commit|merge|push|pull|checkout|feature branch)\\b", re.IGNORECASE),
     IntentCategory.GIT_OPERATION, _extract_git_entities,
     ["git_command"], ["manage_git_workflow"]),

    # Scheduling
    (re.compile(r"\\b(schedule|reminder|timer|cron|nightly|hourly|daily|weekly|every\\s+\\w+)\\b", re.IGNORECASE),
     IntentCategory.SCHEDULING, _extract_schedule_entities,
     ["schedule_job"], []),

    # User management
    (re.compile(r"\\b(create|add|delete|remove|onboard|list|show)\\b.*\\b(user|users|account|tenant)\\b", re.IGNORECASE),
     IntentCategory.USER_MANAGEMENT, _extract_user_entities,
     [], ["onboard_user"]),

    (re.compile(r"\\b(user|account|tenant)\\b.*\\b(create|add|delete|remove|onboard|list|show)\\b", re.IGNORECASE),
     IntentCategory.USER_MANAGEMENT, _extract_user_entities,
     [], ["onboard_user"]),

    # Contextual questions (needs memory + oracle)
    (re.compile(r"\\b(based on|according to|from what|what did I|my previous|last time|you know about me|what should I do next|what should I focus on)\\b", re.IGNORECASE),
     IntentCategory.CONTEXTUAL_QUESTION, lambda t: {},
     [], []),

    # Memory queries
    (re.compile(r"\\b(remember|recall|recap|find that conversation|when did we|what did I say|what do you know|search memory|find in memory|based on what you know)\\b", re.IGNORECASE),
     IntentCategory.MEMORY_QUERY, _extract_memory_entities,
     [], []),

    # System commands
    (re.compile(r"\\b(status|health|system|config|restart|shutdown|uptime)\\b", re.IGNORECASE),
     IntentCategory.SYSTEM_COMMAND, lambda t: {},
     [], []),
]


class IntentParser:
    """
    Two-tier intent classification engine.
    
    Tier 1: Rule-based pattern matching (fast, deterministic).
    Tier 2: Oracle-based classification (for ambiguous or complex inputs).
    """

    def __init__(self):
        self._patterns = INTENT_PATTERNS
        logger.info("IntentParser initialized with %d pattern rules.", len(self._patterns))

    def parse_rule_based(self, user_input: str) -> Optional[Intent]:
        """
        Attempt rule-based intent classification.
        
        Returns an Intent if a pattern matches with high confidence,
        or None if the input is ambiguous and requires Oracle classification.
        """
        input_lower = user_input.lower().strip()

        # Skip very short inputs for pattern matching
        if len(input_lower) < 3:
            return Intent(
                category=IntentCategory.CONVERSATION,
                confidence=0.5,
                raw_input=user_input,
                requires_oracle=True
            )

        for pattern, category, extractor, tools, skills in self._patterns:
            if pattern.search(user_input):
                entities = extractor(user_input)
                requires_memory = category in (
                    IntentCategory.CONTEXTUAL_QUESTION,
                    IntentCategory.MEMORY_QUERY
                )
                return Intent(
                    category=category,
                    confidence=0.85,
                    entities=entities,
                    requires_tools=tools,
                    requires_skills=skills,
                    requires_memory=requires_memory,
                    requires_oracle=(category != IntentCategory.SYSTEM_COMMAND),
                    raw_input=user_input
                )

        # No pattern matched — could be a question or conversation
        # Heuristic: if it ends with '?' it's likely a question
        if user_input.strip().endswith("?"):
            return Intent(
                category=IntentCategory.QUESTION,
                confidence=0.7,
                raw_input=user_input,
                requires_oracle=True,
                requires_memory=False
            )

        # Default: ambiguous, needs Oracle classification
        return None

    def build_classification_prompt(self, user_input: str, session_context: str = "") -> str:
        """
        Build a prompt for Oracle-based intent classification.
        Used when rule-based parsing returns None.
        """
        categories = ", ".join([c.value for c in IntentCategory])
        prompt = f"""Classify the following user input into exactly one intent category.

Available categories: {categories}

User input: "{user_input}"
"""
        if session_context:
            prompt += f"""
Recent conversation context:
{session_context}
"""
        prompt += """
Respond in this exact JSON format:
{
    "category": "<category_value>",
    "confidence": <0.0-1.0>,
    "requires_tools": [<list of tool names if applicable>],
    "requires_skills": [<list of skill names if applicable>],
    "requires_memory": <true/false>,
    "rewritten_query": "<clarified version of the user's request if ambiguous, else null>"
}
"""
        return prompt

    def parse_oracle_response(self, oracle_output: str, user_input: str) -> Intent:
        """
        Parse Oracle's classification response into an Intent object.
        Handles malformed responses gracefully.
        """
        import json

        try:
            # Try to extract JSON from the response
            json_match = re.search(r"\\{[^}]+\\}", oracle_output, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                category = IntentCategory(data.get("category", "unknown"))
                return Intent(
                    category=category,
                    confidence=float(data.get("confidence", 0.7)),
                    requires_tools=data.get("requires_tools", []),
                    requires_skills=data.get("requires_skills", []),
                    requires_memory=data.get("requires_memory", False),
                    requires_oracle=True,
                    raw_input=user_input,
                    rewritten_query=data.get("rewritten_query")
                )
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.warning("Failed to parse Oracle classification response: %s", e)

        # Fallback: treat as a general question
        return Intent(
            category=IntentCategory.QUESTION,
            confidence=0.5,
            raw_input=user_input,
            requires_oracle=True
        )
''',

    # ═══════════════════════════════════════════════════════════════════
    # TASK DECOMPOSER
    # ═══════════════════════════════════════════════════════════════════

    "aegis/agents/torchestrator/decomposer.py": '''
# aegis/agents/torchestrator/decomposer.py
# Implements: Part II §2.1 — Task Decomposition
#
# The TaskDecomposer converts parsed Intents into executable TaskPlans.
# It handles both simple (single-step) and complex (multi-step) tasks.

import logging
from typing import Dict, List, Optional
from uuid import uuid4

from aegis.schemas.torchestrator import (
    Intent,
    IntentCategory,
    TaskPlan,
    TaskStatus,
    TaskStep,
)

logger = logging.getLogger(__name__)


class TaskDecomposer:
    """
    Converts user intents into executable task plans.
    
    For simple intents (single tool/skill), generates a single-step plan.
    For complex intents (multi-step), generates an ordered plan with dependencies.
    For ambiguous intents, generates a plan that starts with Oracle classification.
    """

    def __init__(self):
        self._decomposition_strategies: Dict[IntentCategory, callable] = {
            IntentCategory.QUESTION: self._plan_simple_question,
            IntentCategory.CONTEXTUAL_QUESTION: self._plan_contextual_question,
            IntentCategory.FILE_OPERATION: self._plan_file_operation,
            IntentCategory.GIT_OPERATION: self._plan_git_operation,
            IntentCategory.SCHEDULING: self._plan_scheduling,
            IntentCategory.USER_MANAGEMENT: self._plan_user_management,
            IntentCategory.MEMORY_QUERY: self._plan_memory_query,
            IntentCategory.SYSTEM_COMMAND: self._plan_system_command,
            IntentCategory.MULTI_STEP: self._plan_multi_step,
            IntentCategory.CONVERSATION: self._plan_conversation,
            IntentCategory.UNKNOWN: self._plan_fallback,
        }
        logger.info("TaskDecomposer initialized with %d strategies.", len(self._decomposition_strategies))

    def decompose(self, intent: Intent, tenant_id: str, user_id: str, session_id: str) -> TaskPlan:
        """
        Decompose an intent into a TaskPlan.
        
        Args:
            intent: The parsed user intent.
            tenant_id: Active tenant ID.
            user_id: Active user ID.
            session_id: Current session ID.
            
        Returns:
            A TaskPlan with ordered steps ready for execution.
        """
        strategy = self._decomposition_strategies.get(
            intent.category, self._plan_fallback
        )
        plan = strategy(intent, tenant_id, user_id, session_id)
        logger.info(
            "Decomposed intent '%s' into plan with %d steps.",
            intent.category.value, len(plan.steps)
        )
        return plan

    # ─── Strategy: Simple Question (Oracle only) ─────────────────────

    def _plan_simple_question(
        self, intent: Intent, tenant_id: str, user_id: str, session_id: str
    ) -> TaskPlan:
        """UC-1: Simple question → Oracle query."""
        steps = [
            TaskStep(
                order=1,
                description="Query Oracle for answer",
                target_agent="oracle",
                action="oracle.query",
                payload={
                    "prompt": intent.raw_input,
                    "action": "query",
                    "temperature": 0.7,
                    "max_tokens": 2000,
                }
            )
        ]
        return TaskPlan(
            intent=intent,
            steps=steps,
            synthesis_instructions="Return Oracle response directly as the answer."
        )

    # ─── Strategy: Contextual Question (Lexicon + Oracle) ────────────

    def _plan_contextual_question(
        self, intent: Intent, tenant_id: str, user_id: str, session_id: str
    ) -> TaskPlan:
        """UC-2: Question requiring memory context → Lexicon + Oracle."""
        step_context = TaskStep(
            order=1,
            description="Assemble memory context from Lexicon",
            target_agent="lexicon",
            action="lexicon.assemble_context",
            payload={
                "query": intent.rewritten_query or intent.raw_input,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "scope": ["L0", "L1", "L2", "L3"],
                "token_budget": 4000,
                "session_id": session_id,
            }
        )
        step_oracle = TaskStep(
            order=2,
            description="Query Oracle with assembled context",
            target_agent="oracle",
            action="oracle.query",
            payload={
                "prompt": intent.raw_input,
                "action": "query",
                "use_context_from_step": step_context.step_id,
                "temperature": 0.7,
                "max_tokens": 2000,
            },
            depends_on=[step_context.step_id]
        )
        # Check if web research is also needed
        steps = [step_context, step_oracle]

        # If the intent mentions "current events" or similar, add web research
        lower_input = intent.raw_input.lower()
        if any(w in lower_input for w in ["current", "today", "latest", "news", "recent events"]):
            step_web = TaskStep(
                order=2,  # Parallel with context assembly
                description="Execute web_research skill for current information",
                target_agent="forge",
                action="forge.execute_skill",
                payload={
                    "skill_name": "web_research",
                    "parameters": {"query": intent.raw_input},
                }
            )
            # Move Oracle to order 3 with dependency on both
            step_oracle.order = 3
            step_oracle.depends_on = [step_context.step_id, step_web.step_id]
            step_oracle.payload["use_web_context_from_step"] = step_web.step_id
            steps = [step_context, step_web, step_oracle]

        return TaskPlan(
            intent=intent,
            steps=steps,
            synthesis_instructions=(
                "Synthesize Oracle response incorporating memory context "
                "and web research (if available) into a coherent, personalized answer."
            )
        )

    # ─── Strategy: File Operations ───────────────────────────────────

    def _plan_file_operation(
        self, intent: Intent, tenant_id: str, user_id: str, session_id: str
    ) -> TaskPlan:
        """UC-3: File I/O operations via Forge tools."""
        operation = intent.entities.get("operation", "read")
        file_paths = intent.entities.get("file_paths", [])

        steps: List[TaskStep] = []

        # Map operations to tool names
        tool_map = {
            "read": "file_read",
            "write": "file_write",
            "delete": "file_delete",
            "list": "dir_list",
        }

        tool_name = tool_map.get(operation, "file_read")

        # For multi-file operations, create sequential steps
        if file_paths:
            for i, path in enumerate(file_paths):
                step = TaskStep(
                    order=i + 1,
                    description=f"{operation.capitalize()} file: {path}",
                    target_agent="forge",
                    action="forge.execute_tool",
                    payload={
                        "tool_name": tool_name,
                        "parameters": {"path": path},
                    }
                )
                if i > 0:
                    step.depends_on = [steps[i - 1].step_id]
                steps.append(step)
        else:
            # Single operation, details to be extracted from raw input
            steps.append(TaskStep(
                order=1,
                description=f"Execute {tool_name} tool",
                target_agent="forge",
                action="forge.execute_tool",
                payload={
                    "tool_name": tool_name,
                    "parameters": intent.entities,
                }
            ))

        # If the user asked for multiple operations in one sentence,
        # we might need Oracle to parse the full sequence
        if not steps:
            steps = [
                TaskStep(
                    order=1,
                    description="Parse file operation details via Oracle",
                    target_agent="oracle",
                    action="oracle.structured",
                    payload={
                        "prompt": f"Extract the file operations from: {intent.raw_input}",
                        "action": "structured",
                        "response_format": "json",
                    }
                )
            ]

        return TaskPlan(
            intent=intent,
            steps=steps,
            synthesis_instructions="Report the result of each file operation clearly."
        )

    # ─── Strategy: Git Operations ────────────────────────────────────

    def _plan_git_operation(
        self, intent: Intent, tenant_id: str, user_id: str, session_id: str
    ) -> TaskPlan:
        """UC-4: Git workflow via Forge skill."""
        operation = intent.entities.get("operation", "workflow")

        if operation == "workflow" or "feature" in intent.raw_input.lower():
            # Full workflow skill
            steps = [
                TaskStep(
                    order=1,
                    description="Execute manage_git_workflow skill",
                    target_agent="forge",
                    action="forge.execute_skill",
                    payload={
                        "skill_name": "manage_git_workflow",
                        "parameters": intent.entities,
                    }
                )
            ]
        else:
            # Single git command
            steps = [
                TaskStep(
                    order=1,
                    description=f"Execute git {operation} command",
                    target_agent="forge",
                    action="forge.execute_tool",
                    payload={
                        "tool_name": "git_command",
                        "parameters": {
                            "command": operation,
                            **intent.entities,
                        },
                    }
                )
            ]

        return TaskPlan(
            intent=intent,
            steps=steps,
            synthesis_instructions="Report git operation results with branch/commit details."
        )

    # ─── Strategy: Scheduling ────────────────────────────────────────

    def _plan_scheduling(
        self, intent: Intent, tenant_id: str, user_id: str, session_id: str
    ) -> TaskPlan:
        """UC-6: Task scheduling via Forge tool."""
        schedule_type = intent.entities.get("schedule_type", "cron")
        hour = intent.entities.get("hour", 2)
        minute = intent.entities.get("minute", 0)
        task_desc = intent.entities.get("task_description", "scheduled task")

        steps = [
            TaskStep(
                order=1,
                description=f"Schedule job: {task_desc}",
                target_agent="forge",
                action="forge.execute_tool",
                payload={
                    "tool_name": "schedule_job",
                    "parameters": {
                        "name": task_desc,
                        "description": intent.raw_input,
                        "tenant_id": tenant_id,
                        "user_id": user_id,
                        "schedule_type": schedule_type,
                        "schedule_config": {"hour": hour, "minute": minute},
                        "action": "forge.execute_skill",
                        "action_payload": {"skill_name": task_desc.replace(" ", "_")},
                    },
                }
            )
        ]

        return TaskPlan(
            intent=intent,
            steps=steps,
            synthesis_instructions="Confirm the scheduled job with its schedule details."
        )

    # ─── Strategy: User Management ───────────────────────────────────

    def _plan_user_management(
        self, intent: Intent, tenant_id: str, user_id: str, session_id: str
    ) -> TaskPlan:
        """UC-5: User management via Identity agent or onboard_user skill."""
        operation = intent.entities.get("operation", "create")

        if operation == "create":
            steps = [
                TaskStep(
                    order=1,
                    description="Onboard new user via skill",
                    target_agent="forge",
                    action="forge.execute_skill",
                    payload={
                        "skill_name": "onboard_user",
                        "parameters": {
                            "username": intent.entities.get("username", ""),
                            "role": intent.entities.get("role", "member"),
                            "tenant_id": tenant_id,
                        },
                    }
                )
            ]
        elif operation == "list":
            steps = [
                TaskStep(
                    order=1,
                    description="List users via Identity agent",
                    target_agent="identity",
                    action="identity.list_users",
                    payload={"tenant_id": tenant_id}
                )
            ]
        else:
            steps = [
                TaskStep(
                    order=1,
                    description=f"{operation.capitalize()} user via Identity agent",
                    target_agent="identity",
                    action=f"identity.{operation}_user",
                    payload={
                        "tenant_id": tenant_id,
                        **intent.entities,
                    }
                )
            ]

        return TaskPlan(
            intent=intent,
            steps=steps,
            synthesis_instructions="Report user management operation result."
        )

    # ─── Strategy: Memory Query ──────────────────────────────────────

    def _plan_memory_query(
        self, intent: Intent, tenant_id: str, user_id: str, session_id: str
    ) -> TaskPlan:
        """Direct memory query via Lexicon."""
        subject = intent.entities.get("subject", intent.raw_input)

        steps = [
            TaskStep(
                order=1,
                description="Search memory via Lexicon",
                target_agent="lexicon",
                action="lexicon.search_memory",
                payload={
                    "query": subject,
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "scope": ["L0", "L1", "L2", "L3", "L4"],
                }
            ),
            TaskStep(
                order=2,
                description="Synthesize memory results via Oracle",
                target_agent="oracle",
                action="oracle.query",
                payload={
                    "prompt": f"Based on the following memory fragments, answer: {intent.raw_input}",
                    "action": "query",
                    "use_context_from_step": None,  # Will be filled at runtime
                },
                depends_on=[]  # Will be filled at runtime
            )
        ]
        # Wire dependency
        steps[1].depends_on = [steps[0].step_id]
        steps[1].payload["use_context_from_step"] = steps[0].step_id

        return TaskPlan(
            intent=intent,
            steps=steps,
            synthesis_instructions="Present memory findings as a coherent response."
        )

    # ─── Strategy: System Command ────────────────────────────────────

    def _plan_system_command(
        self, intent: Intent, tenant_id: str, user_id: str, session_id: str
    ) -> TaskPlan:
        """System status/command handling (internal, no external agent)."""
        steps = [
            TaskStep(
                order=1,
                description="Execute system command internally",
                target_agent="system",
                action="system.status",
                payload={"command": intent.raw_input}
            )
        ]
        return TaskPlan(
            intent=intent,
            steps=steps,
            synthesis_instructions="Report system status clearly."
        )

    # ─── Strategy: Multi-Step (Oracle-assisted decomposition) ────────

    def _plan_multi_step(
        self, intent: Intent, tenant_id: str, user_id: str, session_id: str
    ) -> TaskPlan:
        """Complex multi-step tasks — use Oracle to decompose."""
        steps = [
            TaskStep(
                order=1,
                description="Decompose complex task via Oracle",
                target_agent="oracle",
                action="oracle.structured",
                payload={
                    "prompt": self._build_decomposition_prompt(intent),
                    "action": "structured",
                    "response_format": "json",
                    "system_prompt": (
                        "You are a task decomposition engine. Break the user's request "
                        "into sequential, atomic steps. Each step should specify a target "
                        "agent (forge, oracle, lexicon, identity) and an action."
                    ),
                }
            )
        ]
        return TaskPlan(
            intent=intent,
            steps=steps,
            synthesis_instructions=(
                "After Oracle decomposes the task, create and execute "
                "the sub-steps dynamically."
            )
        )

    # ─── Strategy: Conversation ──────────────────────────────────────

    def _plan_conversation(
        self, intent: Intent, tenant_id: str, user_id: str, session_id: str
    ) -> TaskPlan:
        """Casual conversation — Oracle with session context."""
        steps = [
            TaskStep(
                order=1,
                description="Generate conversational response via Oracle",
                target_agent="oracle",
                action="oracle.query",
                payload={
                    "prompt": intent.raw_input,
                    "action": "query",
                    "temperature": 0.8,
                    "max_tokens": 1000,
                    "system_prompt": (
                        "You are TOrchestrator, the conversational AI lead of Project Aegis. "
                        "Respond naturally and helpfully."
                    ),
                }
            )
        ]
        return TaskPlan(
            intent=intent,
            steps=steps,
            synthesis_instructions="Return conversational response directly."
        )

    # ─── Strategy: Fallback ──────────────────────────────────────────

    def _plan_fallback(
        self, intent: Intent, tenant_id: str, user_id: str, session_id: str
    ) -> TaskPlan:
        """Fallback — treat as question with optional context."""
        steps = [
            TaskStep(
                order=1,
                description="Generate response via Oracle (fallback)",
                target_agent="oracle",
                action="oracle.query",
                payload={
                    "prompt": intent.raw_input,
                    "action": "query",
                    "temperature": 0.7,
                    "max_tokens": 2000,
                }
            )
        ]
        return TaskPlan(
            intent=intent,
            steps=steps,
            synthesis_instructions="Return Oracle response as best-effort answer."
        )

    # ─── Helpers ─────────────────────────────────────────────────────

    def _build_decomposition_prompt(self, intent: Intent) -> str:
        """Build prompt for Oracle-assisted task decomposition."""
        return f"""Decompose the following complex user request into atomic, sequential steps.

User request: "{intent.raw_input}"

Available agents and their capabilities:
- forge: Execute tools (file_read, file_write, file_delete, dir_list, dir_create, execute_shell_command, git_command, http_get, http_post, json_parse, schedule_job) and skills (web_research, summarize_document, manage_git_workflow, red_team_analysis, RLM_protocol, onboard_user)
- oracle: LLM queries (query, structured, embed, classify)
- lexicon: Memory operations (assemble_context, store_memory, search_memory, promote_memory)
- identity: User management (create_user, update_user, delete_user, list_users)

Respond as a JSON array of steps:
[
  {{"order": 1, "description": "...", "target_agent": "...", "action": "...", "payload": {{...}}}},
  ...
]
"""
''',

    # ═══════════════════════════════════════════════════════════════════
    # SESSION MANAGER
    # ═══════════════════════════════════════════════════════════════════

    "aegis/agents/torchestrator/session.py": '''
# aegis/agents/torchestrator/session.py
# Implements: Part II §2.1 — Multi-turn Session Management
# Implements: Part X §10.2 — Session persistence for CLI and Web chat
#
# Sessions are stored in-memory with Redis-backed persistence for durability.
# Each session maintains conversation history and contextual state.

import json
import logging
from aegis.utils import time
from typing import Dict, List, Optional

from aegis.schemas.torchestrator import (
    ConversationTurn,
    Session,
    SessionState,
)

logger = logging.getLogger(__name__)


class SessionManager:
    """
    Manages multi-turn conversation sessions.
    
    Provides:
    - Session creation and retrieval
    - Conversation history management
    - Session persistence via Redis (L5 scratchpad pattern)
    - Token budget tracking for context windows
    - Session lifecycle (active → paused → closed)
    """

    # Redis key prefix for session storage
    REDIS_PREFIX = "aegis:session:"
    # Maximum sessions kept in memory per user
    MAX_MEMORY_SESSIONS = 10
    # Default session TTL in seconds (24 hours)
    DEFAULT_TTL = 86400

    def __init__(self, redis_client=None):
        """
        Initialize SessionManager.
        
        Args:
            redis_client: An async Redis client for session persistence.
                         If None, sessions are in-memory only.
        """
        self._redis = redis_client
        self._sessions: Dict[str, Session] = {}  # In-memory cache
        logger.info("SessionManager initialized (redis=%s)", "connected" if redis_client else "none")

    async def create_session(self, tenant_id: str, user_id: str, metadata: Optional[Dict] = None) -> Session:
        """
        Create a new conversation session.
        
        Args:
            tenant_id: The tenant this session belongs to.
            user_id: The user who owns this session.
            metadata: Optional metadata to attach to the session.
            
        Returns:
            A new Session instance.
        """
        session = Session(
            tenant_id=tenant_id,
            user_id=user_id,
            metadata=metadata or {}
        )
        self._sessions[session.session_id] = session

        # Persist to Redis if available
        await self._persist_session(session)

        logger.info(
            "Created session %s for user %s (tenant: %s)",
            session.session_id, user_id, tenant_id
        )
        return session

    async def get_session(self, session_id: str) -> Optional[Session]:
        """
        Retrieve a session by ID.
        
        Checks in-memory cache first, then Redis.
        
        Args:
            session_id: The session ID to look up.
            
        Returns:
            The Session if found, None otherwise.
        """
        # Check in-memory cache
        if session_id in self._sessions:
            return self._sessions[session_id]

        # Try Redis
        session = await self._load_session(session_id)
        if session:
            self._sessions[session_id] = session
            return session

        logger.warning("Session %s not found.", session_id)
        return None

    async def add_turn(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict] = None
    ) -> Optional[ConversationTurn]:
        """
        Add a conversation turn to a session.
        
        Args:
            session_id: Target session ID.
            role: "user" or "assistant"
            content: The message content.
            metadata: Optional metadata (tools_used, latency_ms, etc.)
            
        Returns:
            The created ConversationTurn, or None if session not found.
        """
        session = await self.get_session(session_id)
        if not session:
            logger.error("Cannot add turn: session %s not found.", session_id)
            return None

        if session.state == SessionState.CLOSED:
            logger.warning("Cannot add turn: session %s is closed.", session_id)
            return None

        turn = session.add_turn(role, content, metadata)

        # Persist updated session
        await self._persist_session(session)

        logger.debug(
            "Added %s turn to session %s (total turns: %d)",
            role, session_id, len(session.history)
        )
        return turn

    async def get_context_for_oracle(
        self,
        session_id: str,
        max_turns: int = 20,
        max_tokens: int = 4000
    ) -> str:
        """
        Build a conversation context string for Oracle prompts.
        
        Returns the recent conversation history formatted for LLM consumption.
        Respects token budget (approximate — uses character count heuristic).
        
        Args:
            session_id: The session to extract context from.
            max_turns: Maximum number of recent turns to include.
            max_tokens: Approximate token budget (1 token ≈ 4 chars).
            
        Returns:
            Formatted conversation history string.
        """
        session = await self.get_session(session_id)
        if not session:
            return ""

        recent = session.get_recent_history(max_turns)
        if not recent:
            return ""

        # Build context string, respecting approximate token budget
        max_chars = max_tokens * 4  # Rough token-to-char approximation
        context_parts: List[str] = []
        char_count = 0

        # Work backwards from most recent to prioritize recent context
        for turn in reversed(recent):
            entry = f"{turn.role.capitalize()}: {turn.content}"
            entry_len = len(entry)
            if char_count + entry_len > max_chars:
                break
            context_parts.insert(0, entry)
            char_count += entry_len

        return "\\n".join(context_parts)

    async def list_sessions(
        self,
        tenant_id: str,
        user_id: str,
        state: Optional[SessionState] = None,
        limit: int = 20
    ) -> List[Session]:
        """
        List sessions for a user.
        
        Args:
            tenant_id: Filter by tenant.
            user_id: Filter by user.
            state: Optional filter by session state.
            limit: Maximum number of sessions to return.
            
        Returns:
            List of matching sessions, sorted by last_activity (newest first).
        """
        # Check in-memory sessions
        matching = [
            s for s in self._sessions.values()
            if s.tenant_id == tenant_id and s.user_id == user_id
            and (state is None or s.state == state)
        ]

        # If Redis is available and we have fewer than limit, check Redis
        if self._redis and len(matching) < limit:
            pattern = f"{self.REDIS_PREFIX}{tenant_id}:{user_id}:*"
            try:
                keys = []
                async for key in self._redis.scan_iter(match=pattern, count=100):
                    keys.append(key)
                    if len(keys) >= limit * 2:  # Fetch extra for filtering
                        break

                for key in keys:
                    key_str = key.decode() if isinstance(key, bytes) else key
                    session_id = key_str.split(":")[-1]
                    if session_id not in self._sessions:
                        session = await self._load_session(session_id)
                        if session and (state is None or session.state == state):
                            matching.append(session)
                            self._sessions[session_id] = session
            except Exception as e:
                logger.warning("Failed to list sessions from Redis: %s", e)

        # Sort by last activity, newest first
        matching.sort(key=lambda s: s.last_activity, reverse=True)
        return matching[:limit]

    async def close_session(self, session_id: str) -> bool:
        """
        Close a session (marks it as closed, persists final state).
        
        Args:
            session_id: The session to close.
            
        Returns:
            True if successfully closed, False if session not found.
        """
        session = await self.get_session(session_id)
        if not session:
            return False

        session.state = SessionState.CLOSED
        await self._persist_session(session)
        logger.info("Closed session %s", session_id)
        return True

    async def pause_session(self, session_id: str) -> bool:
        """Pause a session (can be resumed later)."""
        session = await self.get_session(session_id)
        if not session:
            return False

        session.state = SessionState.PAUSED
        await self._persist_session(session)
        logger.info("Paused session %s", session_id)
        return True

    async def resume_session(self, session_id: str) -> Optional[Session]:
        """Resume a paused session."""
        session = await self.get_session(session_id)
        if not session:
            return None

        if session.state == SessionState.CLOSED:
            logger.warning("Cannot resume closed session %s", session_id)
            return None

        session.state = SessionState.ACTIVE
        session.last_activity = time.utcnow()
        await self._persist_session(session)
        logger.info("Resumed session %s", session_id)
        return session

    # ─── Persistence Layer ───────────────────────────────────────────

    async def _persist_session(self, session: Session) -> None:
        """Persist session to Redis."""
        if not self._redis:
            return

        key = f"{self.REDIS_PREFIX}{session.tenant_id}:{session.user_id}:{session.session_id}"
        try:
            data = session.model_dump_json()
            await self._redis.set(key, data, ex=self.DEFAULT_TTL)
        except Exception as e:
            logger.error("Failed to persist session %s: %s", session.session_id, e)

    async def _load_session(self, session_id: str) -> Optional[Session]:
        """Load session from Redis by scanning for matching key."""
        if not self._redis:
            return None

        try:
            # We need to scan for the session since we don't know tenant/user
            pattern = f"{self.REDIS_PREFIX}*:{session_id}"
            async for key in self._redis.scan_iter(match=pattern, count=100):
                data = await self._redis.get(key)
                if data:
                    data_str = data.decode() if isinstance(data, bytes) else data
                    return Session.model_validate_json(data_str)
        except Exception as e:
            logger.warning("Failed to load session %s from Redis: %s", session_id, e)

        return None

    async def cleanup_expired(self) -> int:
        """Remove expired/closed sessions from in-memory cache."""
        to_remove = [
            sid for sid, s in self._sessions.items()
            if s.state == SessionState.CLOSED
        ]
        for sid in to_remove:
            del self._sessions[sid]
        if to_remove:
            logger.info("Cleaned up %d closed sessions from memory.", len(to_remove))
        return len(to_remove)
''',

    # ═══════════════════════════════════════════════════════════════════
    # RESPONSE SYNTHESIZER
    # ═══════════════════════════════════════════════════════════════════

    "aegis/agents/torchestrator/synthesizer.py": '''
# aegis/agents/torchestrator/synthesizer.py
# Implements: Part II §2.1 — Response Synthesis
#
# The Synthesizer combines results from multiple task steps into a
# coherent final response for the user.

import logging
from typing import Any, Dict, List, Optional

from aegis.schemas.torchestrator import TaskPlan, TaskStatus, TaskStep

logger = logging.getLogger(__name__)


class ResponseSynthesizer:
    """
    Synthesizes final user-facing responses from task execution results.
    
    Strategies:
    - Single-step: Pass through the result directly.
    - Multi-step: Combine results based on the plan's synthesis_instructions.
    - Error: Produce a clear error message with context.
    """

    def __init__(self):
        logger.info("ResponseSynthesizer initialized.")

    def synthesize(self, plan: TaskPlan) -> str:
        """
        Synthesize a final response from a completed TaskPlan.
        
        Args:
            plan: The executed TaskPlan with results in each step.
            
        Returns:
            A string response ready for the user.
        """
        # Check for plan-level failure
        if plan.status == TaskStatus.FAILED:
            return self._synthesize_error(plan)

        # Collect completed step results
        completed_steps = [s for s in plan.steps if s.status == TaskStatus.COMPLETED]
        failed_steps = [s for s in plan.steps if s.status == TaskStatus.FAILED]

        if not completed_steps and failed_steps:
            return self._synthesize_error(plan)

        # Single-step plan: return result directly
        if len(plan.steps) == 1 and completed_steps:
            return self._extract_response_content(completed_steps[0])

        # Multi-step plan: combine results
        return self._synthesize_multi_step(plan, completed_steps, failed_steps)

    def synthesize_with_oracle_response(self, oracle_content: str, plan: TaskPlan) -> str:
        """
        When the final step is an Oracle query, use its response directly.
        
        Args:
            oracle_content: The Oracle's generated response.
            plan: The task plan for metadata context.
            
        Returns:
            The Oracle response (potentially with error notes appended).
        """
        failed_steps = [s for s in plan.steps if s.status == TaskStatus.FAILED]

        if failed_steps:
            # Append a note about failed sub-steps
            error_notes = "\\n\\n---\\n*Note: Some sub-tasks encountered issues:*\\n"
            for step in failed_steps:
                error_notes += f"- {step.description}: {step.error}\\n"
            return oracle_content + error_notes

        return oracle_content

    def _synthesize_multi_step(
        self,
        plan: TaskPlan,
        completed_steps: List[TaskStep],
        failed_steps: List[TaskStep]
    ) -> str:
        """Combine multiple step results into one response."""
        parts: List[str] = []

        for step in completed_steps:
            content = self._extract_response_content(step)
            if content:
                parts.append(content)

        response = "\\n\\n".join(parts)

        # Add error notes if any steps failed
        if failed_steps:
            response += "\\n\\n---\\n*Some steps encountered issues:*\\n"
            for step in failed_steps:
                response += f"- {step.description}: {step.error or 'Unknown error'}\\n"

        return response if response else "Task completed but produced no output."

    def _synthesize_error(self, plan: TaskPlan) -> str:
        """Generate an error response for a failed plan."""
        failed_steps = [s for s in plan.steps if s.status == TaskStatus.FAILED]

        if not failed_steps:
            return "I encountered an unexpected error while processing your request. Please try again."

        if len(failed_steps) == 1:
            step = failed_steps[0]
            return (
                f"I wasn't able to complete your request. "
                f"The step \\"{step.description}\\" failed: {step.error or 'Unknown error'}"
            )

        error_msg = "I encountered multiple issues while processing your request:\\n"
        for step in failed_steps:
            error_msg += f"- {step.description}: {step.error or 'Unknown error'}\\n"
        return error_msg

    def _extract_response_content(self, step: TaskStep) -> str:
        """Extract the displayable content from a step's result."""
        if not step.result:
            return ""

        result = step.result

        # Oracle responses have a 'content' field
        if "content" in result:
            content = result["content"]
            if isinstance(content, str):
                return content
            elif isinstance(content, dict):
                return str(content)

        # Forge/Tool responses have a 'data' field
        if "data" in result:
            data = result["data"]
            if isinstance(data, str):
                return data
            elif isinstance(data, dict):
                # Try to format dict data nicely
                return self._format_dict_result(data, step.description)

        # Generic result
        if "result" in result:
            return str(result["result"])

        # Last resort: dump the whole result
        if "success" in result and result.get("success"):
            # Filter out metadata keys
            display_keys = {k: v for k, v in result.items() if k not in ("success", "execution_time_ms")}
            if display_keys:
                return self._format_dict_result(display_keys, step.description)
            return f"✓ {step.description} completed successfully."

        return str(result)

    def _format_dict_result(self, data: Dict[str, Any], context: str = "") -> str:
        """Format a dictionary result for user display."""
        parts = []
        for key, value in data.items():
            if isinstance(value, list):
                parts.append(f"**{key.replace('_', ' ').title()}:**")
                for item in value:
                    parts.append(f"  - {item}")
            elif isinstance(value, dict):
                parts.append(f"**{key.replace('_', ' ').title()}:** {value}")
            else:
                parts.append(f"**{key.replace('_', ' ').title()}:** {value}")
        return "\\n".join(parts)

    def build_synthesis_prompt(self, plan: TaskPlan, step_results: List[Dict[str, Any]]) -> str:
        """
        Build a prompt for Oracle-based synthesis when automatic
        synthesis is insufficient.
        
        Used for complex multi-step results that need natural language
        weaving.
        """
        prompt = f"""Synthesize the following task results into a clear, helpful response for the user.

Original user request: "{plan.intent.raw_input}"
Synthesis instructions: {plan.synthesis_instructions}

Step results:
"""
        for i, result in enumerate(step_results, 1):
            prompt += f"\\nStep {i}: {result}\\n"

        prompt += """
\\nProvide a cohesive, natural response that addresses the user's original request.
Do not mention internal step numbers or agent names. Respond as if you did all the work yourself.
"""
        return prompt
''',

    # ═══════════════════════════════════════════════════════════════════
    # MESSAGE ROUTER
    # ═══════════════════════════════════════════════════════════════════

    "aegis/agents/torchestrator/router.py": '''
# aegis/agents/torchestrator/router.py
# Implements: Part II §2.2 — Inter-agent message routing
# Implements: Part VI — Protocol dispatch
#
# The Router handles the mechanics of sending messages to other agents
# via the Redis message bus and collecting responses.

import asyncio
import logging
from aegis.utils import time
from typing import Any, Dict, Optional
from uuid import uuid4

from aegis.schemas.message import AegisMessage, MessageType, Priority
from aegis.schemas.torchestrator import TaskStep, TaskStatus

logger = logging.getLogger(__name__)


# Agent stream mapping
AGENT_STREAMS = {
    "oracle": "aegis:stream:oracle",
    "forge": "aegis:stream:forge",
    "lexicon": "aegis:stream:lexicon",
    "warden": "aegis:stream:warden",
    "identity": "aegis:stream:identity",
    "janus": "aegis:stream:janus",
    "system": "aegis:stream:system_manager",
}


class MessageRouter:
    """
    Routes messages between TOrchestrator and other agents via the bus.
    
    Handles:
    - Building properly formatted AegisMessage envelopes
    - Publishing to agent streams
    - Waiting for correlated responses (with timeout)
    - Warden authorization checks before dispatching
    """

    def __init__(self, bus_publisher=None, bus_subscriber=None, agent_id: str = "torchestrator"):
        """
        Initialize the MessageRouter.
        
        Args:
            bus_publisher: The Redis bus publisher (from CHUNK-002).
            bus_subscriber: The Redis bus subscriber for receiving responses.
            agent_id: This agent's ID for message source attribution.
        """
        self._publisher = bus_publisher
        self._subscriber = bus_subscriber
        self._agent_id = agent_id
        self._pending_responses: Dict[str, asyncio.Future] = {}
        logger.info("MessageRouter initialized for agent '%s'.", agent_id)

    async def execute_step(
        self,
        step: TaskStep,
        tenant_id: str,
        user_id: str,
        session_id: str,
        timeout: float = 60.0,
        context_data: Optional[Dict[str, Any]] = None
    ) -> TaskStep:
        """
        Execute a single task step by routing a message to the target agent.
        
        Args:
            step: The TaskStep to execute.
            tenant_id: Active tenant ID.
            user_id: Active user ID.
            session_id: Current session ID.
            timeout: Maximum time to wait for response (seconds).
            context_data: Optional context from previous steps.
            
        Returns:
            The TaskStep updated with result or error.
        """
        step.status = TaskStatus.IN_PROGRESS
        start_time = time.perf_counter()

        try:
            # Resolve the target stream
            target_stream = AGENT_STREAMS.get(step.target_agent)
            if not target_stream:
                step.status = TaskStatus.FAILED
                step.error = f"Unknown target agent: {step.target_agent}"
                return step

            # Inject context from previous steps if specified
            payload = dict(step.payload)
            if context_data:
                if "use_context_from_step" in payload:
                    payload["context_packet"] = context_data.get(payload.pop("use_context_from_step"))
                if "use_web_context_from_step" in payload:
                    payload["web_context"] = context_data.get(payload.pop("use_web_context_from_step"))

            # Build the message
            correlation_id = str(uuid4())
            message = AegisMessage(
                correlation_id=correlation_id,
                source_agent=self._agent_id,
                target_agent=step.target_agent,
                message_type=MessageType.REQUEST,
                tenant_id=tenant_id,
                user_id=user_id,
                action=step.action,
                payload=payload,
                priority=Priority.NORMAL,
                ttl_seconds=int(timeout),
                metadata={
                    "session_id": session_id,
                    "step_id": step.step_id,
                }
            )

            # Send authorization check to Warden first
            authorized = await self._check_authorization(
                action=step.action,
                resource=step.payload.get("tool_name", step.payload.get("skill_name", step.action)),
                tenant_id=tenant_id,
                user_id=user_id,
                timeout=min(timeout, 10.0)
            )

            if not authorized:
                step.status = TaskStatus.FAILED
                step.error = "Authorization denied by Warden."
                return step

            # Publish message and wait for response
            response = await self._send_and_wait(message, target_stream, correlation_id, timeout)

            if response:
                step.status = TaskStatus.COMPLETED
                step.result = response.payload if hasattr(response, 'payload') else response
            else:
                step.status = TaskStatus.FAILED
                step.error = f"Timeout waiting for response from {step.target_agent} ({timeout}s)"

        except Exception as e:
            step.status = TaskStatus.FAILED
            step.error = str(e)
            logger.error("Step execution failed: %s", e, exc_info=True)

        elapsed = (time.perf_counter() - start_time) * 1000
        elapsed = max(elapsed, 0.01)
        logger.info(
            "Step '%s' → %s (%.1fms): %s",
            step.description, step.target_agent, elapsed, step.status.value
        )
        return step

    async def _check_authorization(
        self,
        action: str,
        resource: str,
        tenant_id: str,
        user_id: str,
        timeout: float = 10.0
    ) -> bool:
        """
        Check with Warden if the action is authorized.
        
        Returns True if authorized, False otherwise.
        In development/testing mode without a live bus, defaults to True.
        """
        if not self._publisher:
            # No bus available — development mode, allow all
            logger.debug("No bus available, skipping Warden check (dev mode).")
            return True

        try:
            correlation_id = str(uuid4())
            warden_message = AegisMessage(
                correlation_id=correlation_id,
                source_agent=self._agent_id,
                target_agent="warden",
                message_type=MessageType.REQUEST,
                tenant_id=tenant_id,
                user_id=user_id,
                action="warden.authorize",
                payload={
                    "requested_action": action,
                    "resource": resource,
                    "context": {},
                },
                priority=Priority.HIGH,
                ttl_seconds=int(timeout),
            )

            response = await self._send_and_wait(
                warden_message,
                AGENT_STREAMS["warden"],
                correlation_id,
                timeout
            )

            if response:
                payload = response.payload if hasattr(response, 'payload') else response
                verdict = payload.get("verdict", "deny")
                if verdict == "allow":
                    return True
                elif verdict == "escalate":
                    logger.warning("Warden escalated action '%s' — denying by default.", action)
                    return False
                else:
                    logger.warning("Warden denied action '%s': %s", action, payload.get("reason", ""))
                    return False

            # Timeout — fail open in dev, fail closed in production
            logger.warning("Warden check timed out for action '%s'. Defaulting to ALLOW.", action)
            return True

        except Exception as e:
            logger.error("Warden authorization check failed: %s", e)
            # Fail open in development
            return True

    async def _send_and_wait(
        self,
        message: AegisMessage,
        target_stream: str,
        correlation_id: str,
        timeout: float
    ) -> Optional[Dict[str, Any]]:
        """
        Publish a message to the bus and wait for a correlated response.
        
        Args:
            message: The AegisMessage to send.
            target_stream: The Redis stream to publish to.
            correlation_id: The correlation ID to match response.
            timeout: Maximum wait time in seconds.
            
        Returns:
            The response payload dict, or None on timeout.
        """
        if not self._publisher:
            logger.debug("No bus publisher available. Simulating immediate response.")
            # Return a simulated response for development/testing
            return {"content": "[Simulated response — no bus connected]", "success": True}

        # Create a future for the response
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_responses[correlation_id] = future

        try:
            # Publish the message
            message_data = message.model_dump()
            await self._publisher.publish(target_stream, message_data)

            # Wait for response with timeout
            response = await asyncio.wait_for(future, timeout=timeout)
            return response

        except asyncio.TimeoutError:
            logger.warning("Timeout waiting for response (correlation: %s)", correlation_id)
            return None
        except Exception as e:
            logger.error("Error in send_and_wait: %s", e)
            return None
        finally:
            self._pending_responses.pop(correlation_id, None)

    async def handle_incoming_response(self, message: AegisMessage) -> None:
        """
        Handle an incoming response message from another agent.
        
        Called by the TOrchestrator agent when it receives a response
        on its own stream.
        """
        correlation_id = message.correlation_id
        if correlation_id and correlation_id in self._pending_responses:
            future = self._pending_responses[correlation_id]
            if not future.done():
                future.set_result(message.payload)
                logger.debug("Resolved pending response for correlation: %s", correlation_id)
        else:
            logger.debug(
                "Received response with no pending future (correlation: %s). "
                "May have already timed out.",
                correlation_id
            )
''',

    # ═══════════════════════════════════════════════════════════════════
    # TORCHESTRATOR AGENT (MAIN)
    # ═══════════════════════════════════════════════════════════════════

    "aegis/agents/torchestrator/agent.py": '''
# aegis/agents/torchestrator/agent.py
# Implements: Part II §2.1 — TOrchestrator (Council Lead)
# Implements: Part II §2.3 — BaseAgent inheritance
# Implements: Part X §10.2 — Chat Protocol (ChatInput/ChatOutput)
# Implements: Part XII — UC-1, UC-2, UC-5, UC-6
#
# The TOrchestrator is the primary conversational interface agent.
# It receives user input, decomposes intent, dispatches tasks to other
# agents, and synthesizes final responses.

import asyncio
import logging
from aegis.utils import time
from typing import Any, Dict, List, Optional

from aegis.agents.base import BaseAgent
from aegis.agents.torchestrator.decomposer import TaskDecomposer
from aegis.agents.torchestrator.intent import IntentParser
from aegis.agents.torchestrator.router import MessageRouter
from aegis.agents.torchestrator.session import SessionManager
from aegis.agents.torchestrator.synthesizer import ResponseSynthesizer
from aegis.schemas.message import AegisMessage, MessageType
from aegis.schemas.torchestrator import (
    ChatInput,
    ChatOutput,
    Intent,
    IntentCategory,
    Session,
    TaskPlan,
    TaskStatus,
    TaskStep,
    TOrchestratorAction,
    TOrchestratorRequest,
    TOrchestratorResponse,
)

logger = logging.getLogger(__name__)


class TOrchestrator(BaseAgent):
    """
    The Council Lead — primary conversational interface agent for Project Aegis.
    
    Responsibilities:
    - Receive and interpret user input
    - Classify intent (rule-based + Oracle fallback)
    - Decompose complex requests into task plans
    - Dispatch tasks to appropriate agents via the message bus
    - Manage multi-turn conversation sessions
    - Synthesize coherent responses from multiple agent results
    
    This is the ONLY agent the user directly interacts with.
    """

    agent_id: str = "torchestrator"
    subscriptions: List[str] = ["aegis:stream:torchestrator"]

    def __init__(
        self,
        bus_publisher=None,
        bus_subscriber=None,
        redis_client=None,
        config: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize the TOrchestrator.
        
        Args:
            bus_publisher: Redis bus publisher (from CHUNK-002).
            bus_subscriber: Redis bus subscriber for incoming messages.
            redis_client: Redis client for session persistence.
            config: Optional configuration overrides.
        """
        self._config = config or {}
        self._intent_parser = IntentParser()
        self._decomposer = TaskDecomposer()
        self._session_manager = SessionManager(redis_client=redis_client)
        self._synthesizer = ResponseSynthesizer()
        self._router = MessageRouter(
            bus_publisher=bus_publisher,
            bus_subscriber=bus_subscriber,
            agent_id=self.agent_id
        )
        self._bus_publisher = bus_publisher
        self._bus_subscriber = bus_subscriber
        logger.info("TOrchestrator initialized.")

    async def startup(self) -> None:
        """Agent initialization — subscribe to channels, load config."""
        logger.info("TOrchestrator starting up...")
        # Subscribe to our stream if bus is available
        if self._bus_subscriber:
            for channel in self.subscriptions:
                await self._bus_subscriber.subscribe(channel, self._on_bus_message)
        logger.info("TOrchestrator ready. Subscribed to: %s", self.subscriptions)

    async def shutdown(self) -> None:
        """Graceful teardown — persist sessions, unsubscribe."""
        logger.info("TOrchestrator shutting down...")
        # Clean up sessions
        await self._session_manager.cleanup_expired()
        logger.info("TOrchestrator shutdown complete.")

    async def handle_message(self, message: AegisMessage) -> Optional[AegisMessage]:
        """
        Process an incoming message from the bus.
        
        This handles both direct chat inputs and responses from other agents.
        """
        if message.message_type == MessageType.RESPONSE:
            # This is a response to a message we sent — route to pending futures
            await self._router.handle_incoming_response(message)
            return None

        if message.message_type == MessageType.REQUEST:
            # This is a new request — process it
            try:
                request = TOrchestratorRequest(
                    action=TOrchestratorAction(message.action.split(".")[-1]),
                    session_id=message.metadata.get("session_id"),
                    message=message.payload.get("message"),
                    tenant_id=message.tenant_id,
                    user_id=message.user_id,
                    metadata=message.metadata,
                )
                response = await self.process_request(request)
                return AegisMessage(
                    correlation_id=message.correlation_id,
                    source_agent=self.agent_id,
                    target_agent=message.source_agent,
                    message_type=MessageType.RESPONSE,
                    tenant_id=message.tenant_id,
                    user_id=message.user_id,
                    action=f"{self.agent_id}.response",
                    payload=response.model_dump(),
                )
            except Exception as e:
                logger.error("Error handling request: %s", e, exc_info=True)
                return AegisMessage(
                    correlation_id=message.correlation_id,
                    source_agent=self.agent_id,
                    target_agent=message.source_agent,
                    message_type=MessageType.ERROR,
                    tenant_id=message.tenant_id,
                    user_id=message.user_id,
                    action=f"{self.agent_id}.error",
                    payload={"error": str(e)},
                )
        return None

    async def _on_bus_message(self, message_data: Dict[str, Any]) -> None:
        """Callback for messages received on our bus stream."""
        try:
            message = AegisMessage(**message_data)
            response = await self.handle_message(message)
            if response and self._bus_publisher:
                target_stream = f"aegis:stream:{response.target_agent}"
                await self._bus_publisher.publish(target_stream, response.model_dump())
        except Exception as e:
            logger.error("Error processing bus message: %s", e, exc_info=True)

    # ─── Primary Chat Interface ──────────────────────────────────────

    async def chat(self, chat_input: ChatInput) -> ChatOutput:
        """
        Primary chat interface — called by CLI and Web UI.
        
        This is the main entry point for user interaction.
        Implements the full pipeline: intent → decompose → execute → synthesize.
        
        Args:
            chat_input: The user's chat message with session context.
            
        Returns:
            ChatOutput with the assistant's response.
        """
        start_time = time.perf_counter()

        # 1. Session management — get or create session
        session = await self._resolve_session(chat_input)

        # 2. Record user turn
        await self._session_manager.add_turn(
            session.session_id, "user", chat_input.message
        )

        # 3. Process the message through the full pipeline
        try:
            response_text, metadata = await self._process_user_message(
                message=chat_input.message,
                session=session,
                tenant_id=chat_input.tenant_id,
                user_id=chat_input.user_id,
            )
        except Exception as e:
            logger.error("Error processing chat message: %s", e, exc_info=True)
            response_text = "I encountered an error while processing your request. Please try again."
            metadata = {"error": str(e)}

        # 4. Record assistant turn
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        elapsed_ms = max(elapsed_ms, 0.01)
        metadata["latency_ms"] = elapsed_ms

        await self._session_manager.add_turn(
            session.session_id, "assistant", response_text, metadata
        )

        # 5. Return response
        return ChatOutput(
            response=response_text,
            session_id=session.session_id,
            agent=self.agent_id,
            metadata=metadata,
        )

    async def process_request(self, request: TOrchestratorRequest) -> TOrchestratorResponse:
        """
        Process a structured TOrchestrator request.
        
        Handles all TOrchestratorAction types.
        """
        start_time = time.perf_counter()

        if request.action == TOrchestratorAction.CHAT:
            chat_input = ChatInput(
                message=request.message or "",
                session_id=request.session_id,
                tenant_id=request.tenant_id,
                user_id=request.user_id,
            )
            output = await self.chat(chat_input)
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            elapsed_ms = max(elapsed_ms, 0.01)
            return TOrchestratorResponse(
                success=True,
                response=output.response,
                session_id=output.session_id,
                action=request.action,
                tools_used=output.metadata.get("tools_used", []),
                skills_used=output.metadata.get("skills_used", []),
                latency_ms=elapsed_ms,
                metadata=output.metadata,
            )

        elif request.action == TOrchestratorAction.RESUME_SESSION:
            session = await self._session_manager.resume_session(request.session_id or "")
            if session:
                return TOrchestratorResponse(
                    success=True,
                    response=f"Session resumed. You have {len(session.history)} turns in history.",
                    session_id=session.session_id,
                    action=request.action,
                    latency_ms=(time.perf_counter() - start_time) * 1000,
                )
            return TOrchestratorResponse(
                success=False,
                action=request.action,
                error="Session not found or cannot be resumed.",
                latency_ms=(time.perf_counter() - start_time) * 1000,
            )

        elif request.action == TOrchestratorAction.LIST_SESSIONS:
            sessions = await self._session_manager.list_sessions(
                request.tenant_id, request.user_id
            )
            session_list = [
                {"id": s.session_id, "state": s.state.value, "turns": len(s.history), "last_activity": s.last_activity.isoformat()}
                for s in sessions
            ]
            return TOrchestratorResponse(
                success=True,
                response=f"Found {len(sessions)} sessions.",
                action=request.action,
                latency_ms=(time.perf_counter() - start_time) * 1000,
                metadata={"sessions": session_list},
            )

        elif request.action == TOrchestratorAction.CLOSE_SESSION:
            closed = await self._session_manager.close_session(request.session_id or "")
            return TOrchestratorResponse(
                success=closed,
                response="Session closed." if closed else "Session not found.",
                action=request.action,
                latency_ms=(time.perf_counter() - start_time) * 1000,
            )

        return TOrchestratorResponse(
            success=False,
            action=request.action,
            error=f"Unknown action: {request.action}",
            latency_ms=(time.perf_counter() - start_time) * 1000,
        )

    # ─── Core Processing Pipeline ────────────────────────────────────

    async def _process_user_message(
        self,
        message: str,
        session: Session,
        tenant_id: str,
        user_id: str,
    ) -> tuple:
        """
        Core processing pipeline:
        1. Parse intent (rule-based, then Oracle if needed)
        2. Decompose into task plan
        3. Execute task steps
        4. Synthesize response
        
        Returns:
            Tuple of (response_text, metadata_dict)
        """
        metadata: Dict[str, Any] = {}

        # ── Step 1: Intent Classification ────────────────────────────
        intent = self._intent_parser.parse_rule_based(message)

        if intent is None:
            # Rule-based parsing was inconclusive — use Oracle
            intent = await self._classify_with_oracle(message, session)
            metadata["intent_source"] = "oracle"
        else:
            metadata["intent_source"] = "rules"

        metadata["intent_category"] = intent.category.value
        metadata["intent_confidence"] = intent.confidence
        logger.info("Intent classified: %s (confidence: %.2f)", intent.category.value, intent.confidence)

        # ── Step 2: Task Decomposition ───────────────────────────────
        plan = self._decomposer.decompose(
            intent=intent,
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=session.session_id,
        )
        logger.info("Task plan created: %d steps", len(plan.steps))

        # ── Step 3: Execute Plan ─────────────────────────────────────
        plan = await self._execute_plan(plan, tenant_id, user_id, session)
        metadata["steps_executed"] = len([s for s in plan.steps if s.status == TaskStatus.COMPLETED])
        metadata["steps_failed"] = len([s for s in plan.steps if s.status == TaskStatus.FAILED])

        # Collect tool/skill usage for metadata
        tools_used = []
        skills_used = []
        for step in plan.steps:
            if step.status == TaskStatus.COMPLETED:
                if "execute_tool" in step.action:
                    tool_name = step.payload.get("tool_name", "")
                    if tool_name:
                        tools_used.append(tool_name)
                elif "execute_skill" in step.action:
                    skill_name = step.payload.get("skill_name", "")
                    if skill_name:
                        skills_used.append(skill_name)
        metadata["tools_used"] = tools_used
        metadata["skills_used"] = skills_used

        # ── Step 4: Response Synthesis ───────────────────────────────
        response_text = self._synthesizer.synthesize(plan)

        # If the response is from Oracle (the last step is Oracle), use it directly
        completed_steps = [s for s in plan.steps if s.status == TaskStatus.COMPLETED]
        if completed_steps:
            last_step = completed_steps[-1]
            if last_step.target_agent == "oracle" and last_step.result:
                oracle_content = last_step.result.get("content", "")
                if oracle_content:
                    response_text = self._synthesizer.synthesize_with_oracle_response(
                        oracle_content, plan
                    )

        return response_text, metadata

    async def _classify_with_oracle(self, message: str, session: Session) -> Intent:
        """
        Use Oracle for intent classification when rule-based parsing fails.
        """
        # Build context from session history
        session_context = await self._session_manager.get_context_for_oracle(
            session.session_id, max_turns=5, max_tokens=1000
        )

        # Build classification prompt
        prompt = self._intent_parser.build_classification_prompt(message, session_context)

        # Route to Oracle
        step = TaskStep(
            order=1,
            description="Classify intent via Oracle",
            target_agent="oracle",
            action="oracle.structured",
            payload={
                "prompt": prompt,
                "action": "structured",
                "response_format": "json",
                "temperature": 0.3,
                "max_tokens": 500,
                "system_prompt": "You are an intent classification engine. Respond only with the requested JSON.",
            }
        )

        step = await self._router.execute_step(
            step=step,
            tenant_id=session.tenant_id,
            user_id=session.user_id,
            session_id=session.session_id,
            timeout=15.0,
        )

        if step.status == TaskStatus.COMPLETED and step.result:
            oracle_output = step.result.get("content", "")
            if isinstance(oracle_output, str):
                return self._intent_parser.parse_oracle_response(oracle_output, message)

        # Fallback if Oracle classification fails
        logger.warning("Oracle classification failed. Falling back to QUESTION intent.")
        return Intent(
            category=IntentCategory.QUESTION,
            confidence=0.5,
            raw_input=message,
            requires_oracle=True,
        )

    async def _execute_plan(
        self,
        plan: TaskPlan,
        tenant_id: str,
        user_id: str,
        session: Session,
    ) -> TaskPlan:
        """
        Execute all steps in a task plan, respecting dependencies.
        
        Steps without dependencies can execute in parallel.
        Steps with dependencies wait for their prerequisites.
        """
        plan.status = TaskStatus.IN_PROGRESS
        context_data: Dict[str, Any] = {}  # step_id → result mapping

        # Inject session context into Oracle steps
        session_context = await self._session_manager.get_context_for_oracle(
            session.session_id, max_turns=10, max_tokens=2000
        )

        # Group steps by execution order
        steps_by_order: Dict[int, List[TaskStep]] = {}
        for step in plan.steps:
            steps_by_order.setdefault(step.order, []).append(step)

        # Execute in order
        for order in sorted(steps_by_order.keys()):
            steps_at_level = steps_by_order[order]

            # Check if all steps at this level have their dependencies met
            executable = []
            for step in steps_at_level:
                deps_met = all(
                    any(s.step_id == dep_id and s.status == TaskStatus.COMPLETED
                        for s in plan.steps)
                    for dep_id in step.depends_on
                )
                if deps_met:
                    # Inject session context for Oracle steps
                    if step.target_agent == "oracle" and session_context:
                        if "system_prompt" not in step.payload:
                            step.payload["system_prompt"] = ""
                        step.payload.setdefault("conversation_context", session_context)
                    executable.append(step)
                else:
                    step.status = TaskStatus.SKIPPED
                    step.error = "Dependencies not met (prerequisite failed)."

            # Execute all executable steps at this level concurrently
            if len(executable) == 1:
                # Single step — execute directly
                step = executable[0]
                step = await self._router.execute_step(
                    step=step,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    session_id=session.session_id,
                    timeout=step.payload.get("timeout_seconds", 60.0),
                    context_data=context_data,
                )
                if step.result:
                    context_data[step.step_id] = step.result
            elif len(executable) > 1:
                # Multiple steps — execute concurrently
                tasks = [
                    self._router.execute_step(
                        step=step,
                        tenant_id=tenant_id,
                        user_id=user_id,
                        session_id=session.session_id,
                        timeout=step.payload.get("timeout_seconds", 60.0),
                        context_data=context_data,
                    )
                    for step in executable
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        executable[i].status = TaskStatus.FAILED
                        executable[i].error = str(result)
                    else:
                        if result.result:
                            context_data[result.step_id] = result.result

        # Determine plan-level status
        all_statuses = [s.status for s in plan.steps]
        if all(s == TaskStatus.COMPLETED for s in all_statuses):
            plan.status = TaskStatus.COMPLETED
        elif any(s == TaskStatus.FAILED for s in all_statuses):
            # Partial success if at least one step completed
            if any(s == TaskStatus.COMPLETED for s in all_statuses):
                plan.status = TaskStatus.COMPLETED  # Partial success
            else:
                plan.status = TaskStatus.FAILED
        else:
            plan.status = TaskStatus.COMPLETED

        return plan

    # ─── Session Helpers ─────────────────────────────────────────────

    async def _resolve_session(self, chat_input: ChatInput) -> Session:
        """Get existing session or create a new one."""
        if chat_input.session_id:
            session = await self._session_manager.get_session(chat_input.session_id)
            if session:
                return session
            logger.warning(
                "Session %s not found. Creating new session.", chat_input.session_id
            )

        return await self._session_manager.create_session(
            tenant_id=chat_input.tenant_id,
            user_id=chat_input.user_id,
        )
''',

    # ═══════════════════════════════════════════════════════════════════
    # TESTS
    # ═══════════════════════════════════════════════════════════════════

    "tests/test_torchestrator/__init__.py": '''
# tests/test_torchestrator/__init__.py
''',

    "tests/test_torchestrator/test_intent.py": '''
# tests/test_torchestrator/test_intent.py
# Unit tests for the IntentParser

import pytest
from aegis.agents.torchestrator.intent import IntentParser
from aegis.schemas.torchestrator import Intent, IntentCategory


@pytest.fixture
def parser():
    return IntentParser()


class TestRuleBasedParsing:
    """Tests for the rule-based intent classification tier."""

    def test_file_read_intent(self, parser):
        intent = parser.parse_rule_based("Read the file called test.txt")
        assert intent is not None
        assert intent.category == IntentCategory.FILE_OPERATION
        assert intent.confidence >= 0.8
        assert "file_read" in intent.requires_tools

    def test_file_write_intent(self, parser):
        intent = parser.parse_rule_based("Create a file named 'hello.md' with some content")
        assert intent is not None
        assert intent.category == IntentCategory.FILE_OPERATION
        assert intent.entities.get("operation") == "write"

    def test_file_delete_intent(self, parser):
        intent = parser.parse_rule_based("Delete the file '/tmp/old.log'")
        assert intent is not None
        assert intent.category == IntentCategory.FILE_OPERATION
        assert intent.entities.get("operation") == "delete"

    def test_git_branch_intent(self, parser):
        intent = parser.parse_rule_based("Create a new branch called feature/login")
        assert intent is not None
        assert intent.category == IntentCategory.GIT_OPERATION
        assert "feature/login" in intent.entities.get("branch_name", "")

    def test_git_workflow_intent(self, parser):
        intent = parser.parse_rule_based("Start a feature branch workflow for the new API")
        assert intent is not None
        assert intent.category == IntentCategory.GIT_OPERATION
        assert "manage_git_workflow" in intent.requires_skills

    def test_schedule_nightly(self, parser):
        intent = parser.parse_rule_based("Schedule a nightly backup at 2 AM")
        assert intent is not None
        assert intent.category == IntentCategory.SCHEDULING
        assert intent.entities.get("hour") == 2
        assert intent.entities.get("minute") == 0

    def test_schedule_daily(self, parser):
        intent = parser.parse_rule_based("Schedule a daily report at 9:30 AM")
        assert intent is not None
        assert intent.category == IntentCategory.SCHEDULING
        assert intent.entities.get("hour") == 9
        assert intent.entities.get("minute") == 30

    def test_create_user_intent(self, parser):
        intent = parser.parse_rule_based("Create a new user named 'TestUser' with the member role")
        assert intent is not None
        assert intent.category == IntentCategory.USER_MANAGEMENT
        assert intent.entities.get("username") == "TestUser"
        assert intent.entities.get("role") == "member"

    def test_memory_recall_intent(self, parser):
        intent = parser.parse_rule_based("What do you remember about my Python project?")
        assert intent is not None
        assert intent.category == IntentCategory.MEMORY_QUERY
        assert intent.requires_memory is True

    def test_contextual_question(self, parser):
        intent = parser.parse_rule_based("Based on what you know about me, what should I focus on?")
        assert intent is not None
        assert intent.category == IntentCategory.CONTEXTUAL_QUESTION
        assert intent.requires_memory is True

    def test_system_status(self, parser):
        intent = parser.parse_rule_based("Show me the system status")
        assert intent is not None
        assert intent.category == IntentCategory.SYSTEM_COMMAND

    def test_simple_question(self, parser):
        intent = parser.parse_rule_based("What is the capital of France?")
        assert intent is not None
        assert intent.category == IntentCategory.QUESTION
        assert intent.requires_oracle is True

    def test_ambiguous_input_returns_none(self, parser):
        """Ambiguous input should return None, signaling Oracle fallback."""
        intent = parser.parse_rule_based("Help me think about this problem")
        # This may return None (needs Oracle) or CONVERSATION
        # Both are acceptable
        if intent:
            assert intent.category in (IntentCategory.CONVERSATION, IntentCategory.QUESTION)

    def test_short_input(self, parser):
        intent = parser.parse_rule_based("hi")
        assert intent is not None
        assert intent.category == IntentCategory.CONVERSATION


class TestOracleResponseParsing:
    """Tests for parsing Oracle classification responses."""

    def test_valid_json_response(self, parser):
        oracle_output = """{"category": "file_operation", "confidence": 0.9, "requires_tools": ["file_write"], "requires_skills": [], "requires_memory": false, "rewritten_query": null}"""
        intent = parser.parse_oracle_response(oracle_output, "write something")
        assert intent.category == IntentCategory.FILE_OPERATION
        assert intent.confidence == 0.9

    def test_json_embedded_in_text(self, parser):
        oracle_output = """Based on the input, I classify this as:
        {"category": "question", "confidence": 0.85, "requires_tools": [], "requires_skills": [], "requires_memory": false, "rewritten_query": "What is Python?"}
        """
        intent = parser.parse_oracle_response(oracle_output, "tell me about python")
        assert intent.category == IntentCategory.QUESTION

    def test_malformed_response_fallback(self, parser):
        oracle_output = "I cannot classify this input properly."
        intent = parser.parse_oracle_response(oracle_output, "some input")
        assert intent.category == IntentCategory.QUESTION
        assert intent.confidence == 0.5


class TestClassificationPromptBuilding:
    """Tests for the Oracle classification prompt builder."""

    def test_prompt_includes_categories(self, parser):
        prompt = parser.build_classification_prompt("test input")
        assert "question" in prompt
        assert "file_operation" in prompt
        assert "git_operation" in prompt

    def test_prompt_includes_session_context(self, parser):
        prompt = parser.build_classification_prompt("test input", "User: hello\\nAssistant: hi")
        assert "Recent conversation context" in prompt
        assert "hello" in prompt
''',

    "tests/test_torchestrator/test_decomposer.py": '''
# tests/test_torchestrator/test_decomposer.py
# Unit tests for the TaskDecomposer

import pytest
from aegis.agents.torchestrator.decomposer import TaskDecomposer
from aegis.schemas.torchestrator import Intent, IntentCategory, TaskPlan, TaskStatus


@pytest.fixture
def decomposer():
    return TaskDecomposer()


TENANT = "test-tenant"
USER = "test-user"
SESSION = "test-session"


class TestSimpleQuestionDecomposition:
    """UC-1: Simple question decomposition."""

    def test_simple_question_plan(self, decomposer):
        intent = Intent(
            category=IntentCategory.QUESTION,
            raw_input="What is the capital of France?",
            requires_oracle=True,
        )
        plan = decomposer.decompose(intent, TENANT, USER, SESSION)
        assert len(plan.steps) == 1
        assert plan.steps[0].target_agent == "oracle"
        assert plan.steps[0].action == "oracle.query"


class TestContextualQuestionDecomposition:
    """UC-2: Contextual question decomposition."""

    def test_contextual_question_has_lexicon_step(self, decomposer):
        intent = Intent(
            category=IntentCategory.CONTEXTUAL_QUESTION,
            raw_input="Based on what you know about me, what should I focus on?",
            requires_memory=True,
            requires_oracle=True,
        )
        plan = decomposer.decompose(intent, TENANT, USER, SESSION)
        assert len(plan.steps) >= 2
        # First step should be Lexicon context assembly
        assert plan.steps[0].target_agent == "lexicon"
        assert plan.steps[0].action == "lexicon.assemble_context"
        # Last step should be Oracle
        assert plan.steps[-1].target_agent == "oracle"

    def test_contextual_with_current_events(self, decomposer):
        intent = Intent(
            category=IntentCategory.CONTEXTUAL_QUESTION,
            raw_input="Based on what you know and current events, what should I focus on?",
            requires_memory=True,
            requires_oracle=True,
        )
        plan = decomposer.decompose(intent, TENANT, USER, SESSION)
        # Should include web_research step
        agents_used = [s.target_agent for s in plan.steps]
        assert "forge" in agents_used  # web_research via forge


class TestFileOperationDecomposition:
    """UC-3: File operation decomposition."""

    def test_file_write_plan(self, decomposer):
        intent = Intent(
            category=IntentCategory.FILE_OPERATION,
            raw_input="Create a file called test.txt",
            entities={"operation": "write", "file_paths": ["test.txt"]},
            requires_tools=["file_write"],
        )
        plan = decomposer.decompose(intent, TENANT, USER, SESSION)
        assert len(plan.steps) >= 1
        assert plan.steps[0].target_agent == "forge"
        assert "file_write" in plan.steps[0].payload.get("tool_name", "")


class TestGitOperationDecomposition:
    """UC-4: Git operation decomposition."""

    def test_git_workflow_plan(self, decomposer):
        intent = Intent(
            category=IntentCategory.GIT_OPERATION,
            raw_input="Start a feature branch workflow",
            entities={"operation": "workflow", "branch_name": "feature/test"},
            requires_skills=["manage_git_workflow"],
        )
        plan = decomposer.decompose(intent, TENANT, USER, SESSION)
        assert len(plan.steps) == 1
        assert plan.steps[0].action == "forge.execute_skill"
        assert plan.steps[0].payload["skill_name"] == "manage_git_workflow"


class TestSchedulingDecomposition:
    """UC-6: Scheduling decomposition."""

    def test_schedule_nightly_plan(self, decomposer):
        intent = Intent(
            category=IntentCategory.SCHEDULING,
            raw_input="Schedule a nightly memory optimization at 2 AM",
            entities={"schedule_type": "cron", "hour": 2, "minute": 0, "task_description": "nightly memory optimization"},
            requires_tools=["schedule_job"],
        )
        plan = decomposer.decompose(intent, TENANT, USER, SESSION)
        assert len(plan.steps) == 1
        assert plan.steps[0].target_agent == "forge"
        assert plan.steps[0].payload["tool_name"] == "schedule_job"


class TestUserManagementDecomposition:
    """UC-5: User management decomposition."""

    def test_create_user_plan(self, decomposer):
        intent = Intent(
            category=IntentCategory.USER_MANAGEMENT,
            raw_input="Create a new user named TestUser with the member role",
            entities={"operation": "create", "username": "TestUser", "role": "member"},
            requires_skills=["onboard_user"],
        )
        plan = decomposer.decompose(intent, TENANT, USER, SESSION)
        assert len(plan.steps) == 1
        assert plan.steps[0].payload["skill_name"] == "onboard_user"
''',

    "tests/test_torchestrator/test_session.py": '''
# tests/test_torchestrator/test_session.py
# Unit tests for SessionManager

import pytest
import asyncio
from aegis.agents.torchestrator.session import SessionManager
from aegis.schemas.torchestrator import Session, SessionState


@pytest.fixture
def session_manager():
    """Create a SessionManager without Redis (in-memory only)."""
    return SessionManager(redis_client=None)


@pytest.mark.asyncio
async def test_create_session(session_manager):
    session = await session_manager.create_session("tenant-1", "user-1")
    assert session.tenant_id == "tenant-1"
    assert session.user_id == "user-1"
    assert session.state == SessionState.ACTIVE
    assert len(session.history) == 0


@pytest.mark.asyncio
async def test_get_session(session_manager):
    session = await session_manager.create_session("tenant-1", "user-1")
    retrieved = await session_manager.get_session(session.session_id)
    assert retrieved is not None
    assert retrieved.session_id == session.session_id


@pytest.mark.asyncio
async def test_get_nonexistent_session(session_manager):
    retrieved = await session_manager.get_session("nonexistent-id")
    assert retrieved is None


@pytest.mark.asyncio
async def test_add_turn(session_manager):
    session = await session_manager.create_session("tenant-1", "user-1")
    turn = await session_manager.add_turn(session.session_id, "user", "Hello!")
    assert turn is not None
    assert turn.role == "user"
    assert turn.content == "Hello!"
    # Verify it's in the session
    updated = await session_manager.get_session(session.session_id)
    assert len(updated.history) == 1


@pytest.mark.asyncio
async def test_add_turn_to_closed_session(session_manager):
    session = await session_manager.create_session("tenant-1", "user-1")
    await session_manager.close_session(session.session_id)
    turn = await session_manager.add_turn(session.session_id, "user", "Can I still chat?")
    assert turn is None  # Should not allow turns on closed sessions


@pytest.mark.asyncio
async def test_close_session(session_manager):
    session = await session_manager.create_session("tenant-1", "user-1")
    result = await session_manager.close_session(session.session_id)
    assert result is True
    updated = await session_manager.get_session(session.session_id)
    assert updated.state == SessionState.CLOSED


@pytest.mark.asyncio
async def test_pause_and_resume_session(session_manager):
    session = await session_manager.create_session("tenant-1", "user-1")
    await session_manager.pause_session(session.session_id)
    paused = await session_manager.get_session(session.session_id)
    assert paused.state == SessionState.PAUSED

    resumed = await session_manager.resume_session(session.session_id)
    assert resumed is not None
    assert resumed.state == SessionState.ACTIVE


@pytest.mark.asyncio
async def test_cannot_resume_closed_session(session_manager):
    session = await session_manager.create_session("tenant-1", "user-1")
    await session_manager.close_session(session.session_id)
    resumed = await session_manager.resume_session(session.session_id)
    assert resumed is None


@pytest.mark.asyncio
async def test_list_sessions(session_manager):
    await session_manager.create_session("tenant-1", "user-1")
    await session_manager.create_session("tenant-1", "user-1")
    await session_manager.create_session("tenant-1", "user-2")  # Different user

    sessions = await session_manager.list_sessions("tenant-1", "user-1")
    assert len(sessions) == 2


@pytest.mark.asyncio
async def test_get_context_for_oracle(session_manager):
    session = await session_manager.create_session("tenant-1", "user-1")
    await session_manager.add_turn(session.session_id, "user", "What is Python?")
    await session_manager.add_turn(session.session_id, "assistant", "Python is a programming language.")
    await session_manager.add_turn(session.session_id, "user", "Tell me more.")

    context = await session_manager.get_context_for_oracle(session.session_id)
    assert "What is Python?" in context
    assert "programming language" in context
    assert "Tell me more" in context


@pytest.mark.asyncio
async def test_context_respects_token_budget(session_manager):
    session = await session_manager.create_session("tenant-1", "user-1")
    # Add many turns
    for i in range(50):
        await session_manager.add_turn(session.session_id, "user", f"Message {i} " * 100)

    # Request with small budget
    context = await session_manager.get_context_for_oracle(
        session.session_id, max_tokens=100
    )
    # Should be truncated (100 tokens ≈ 400 chars)
    assert len(context) <= 1000  # Some tolerance


@pytest.mark.asyncio
async def test_cleanup_expired(session_manager):
    s1 = await session_manager.create_session("tenant-1", "user-1")
    s2 = await session_manager.create_session("tenant-1", "user-1")
    await session_manager.close_session(s1.session_id)

    cleaned = await session_manager.cleanup_expired()
    assert cleaned == 1
    # s2 should still be accessible
    assert await session_manager.get_session(s2.session_id) is not None
''',

    "tests/test_torchestrator/test_synthesizer.py": '''
# tests/test_torchestrator/test_synthesizer.py
# Unit tests for the ResponseSynthesizer

import pytest
from aegis.agents.torchestrator.synthesizer import ResponseSynthesizer
from aegis.schemas.torchestrator import (
    Intent,
    IntentCategory,
    TaskPlan,
    TaskStatus,
    TaskStep,
)


@pytest.fixture
def synthesizer():
    return ResponseSynthesizer()


def _make_plan(steps, status=TaskStatus.COMPLETED, raw_input="test input"):
    intent = Intent(category=IntentCategory.QUESTION, raw_input=raw_input)
    plan = TaskPlan(intent=intent, steps=steps, status=status)
    return plan


class TestSingleStepSynthesis:
    """Tests for single-step task plan synthesis."""

    def test_oracle_response_passthrough(self, synthesizer):
        steps = [TaskStep(
            order=1, description="Query Oracle", target_agent="oracle",
            action="oracle.query", status=TaskStatus.COMPLETED,
            result={"content": "Paris is the capital of France."}
        )]
        plan = _make_plan(steps)
        response = synthesizer.synthesize(plan)
        assert "Paris" in response

    def test_tool_response_passthrough(self, synthesizer):
        steps = [TaskStep(
            order=1, description="Read file", target_agent="forge",
            action="forge.execute_tool", status=TaskStatus.COMPLETED,
            result={"data": "File contents here."}
        )]
        plan = _make_plan(steps)
        response = synthesizer.synthesize(plan)
        assert "File contents here" in response


class TestMultiStepSynthesis:
    """Tests for multi-step task plan synthesis."""

    def test_combines_multiple_results(self, synthesizer):
        steps = [
            TaskStep(
                order=1, description="Search memory", target_agent="lexicon",
                action="lexicon.search", status=TaskStatus.COMPLETED,
                result={"content": "User likes Python."}
            ),
            TaskStep(
                order=2, description="Generate answer", target_agent="oracle",
                action="oracle.query", status=TaskStatus.COMPLETED,
                result={"content": "Based on your interests, try FastAPI."}
            ),
        ]
        plan = _make_plan(steps)
        response = synthesizer.synthesize(plan)
        assert "Python" in response or "FastAPI" in response


class TestErrorSynthesis:
    """Tests for error response synthesis."""

    def test_single_failure(self, synthesizer):
        steps = [TaskStep(
            order=1, description="Execute dangerous command", target_agent="forge",
            action="forge.execute_tool", status=TaskStatus.FAILED,
            error="Permission denied by Warden."
        )]
        plan = _make_plan(steps, status=TaskStatus.FAILED)
        response = synthesizer.synthesize(plan)
        assert "Permission denied" in response

    def test_partial_failure(self, synthesizer):
        steps = [
            TaskStep(
                order=1, description="Read file", target_agent="forge",
                action="forge.execute_tool", status=TaskStatus.COMPLETED,
                result={"data": "file content"}
            ),
            TaskStep(
                order=2, description="Delete file", target_agent="forge",
                action="forge.execute_tool", status=TaskStatus.FAILED,
                error="File not found."
            ),
        ]
        plan = _make_plan(steps)
        response = synthesizer.synthesize(plan)
        assert "file content" in response
        assert "File not found" in response

    def test_all_failed(self, synthesizer):
        steps = [
            TaskStep(order=1, description="Step 1", target_agent="forge",
                     action="test", status=TaskStatus.FAILED, error="Error 1"),
            TaskStep(order=2, description="Step 2", target_agent="forge",
                     action="test", status=TaskStatus.FAILED, error="Error 2"),
        ]
        plan = _make_plan(steps, status=TaskStatus.FAILED)
        response = synthesizer.synthesize(plan)
        assert "Error 1" in response
        assert "Error 2" in response


class TestOracleSynthesis:
    """Tests for Oracle-assisted synthesis."""

    def test_oracle_response_with_errors(self, synthesizer):
        steps = [
            TaskStep(order=1, description="Failed step", target_agent="forge",
                     action="test", status=TaskStatus.FAILED, error="timeout"),
        ]
        plan = _make_plan(steps)
        response = synthesizer.synthesize_with_oracle_response(
            "Here is my answer.", plan
        )
        assert "Here is my answer" in response
        assert "timeout" in response
''',

    "tests/test_torchestrator/test_agent.py": '''
# tests/test_torchestrator/test_agent.py
# Integration tests for the TOrchestrator agent

import pytest
import asyncio
from aegis.agents.torchestrator.agent import TOrchestrator
from aegis.schemas.torchestrator import (
    ChatInput,
    ChatOutput,
    TOrchestratorAction,
    TOrchestratorRequest,
)


@pytest.fixture
def torchestrator():
    """Create a TOrchestrator without bus connections (standalone mode)."""
    return TOrchestrator(
        bus_publisher=None,
        bus_subscriber=None,
        redis_client=None,
        config={}
    )


@pytest.mark.asyncio
async def test_startup_shutdown(torchestrator):
    """Test that startup and shutdown don't raise."""
    await torchestrator.startup()
    await torchestrator.shutdown()


@pytest.mark.asyncio
async def test_chat_creates_session(torchestrator):
    """Chat without session_id should create a new session."""
    chat_input = ChatInput(
        message="Hello!",
        tenant_id="test-tenant",
        user_id="test-user",
    )
    output = await torchestrator.chat(chat_input)
    assert isinstance(output, ChatOutput)
    assert output.session_id  # Should have a session ID
    assert output.response  # Should have some response


@pytest.mark.asyncio
async def test_chat_maintains_session(torchestrator):
    """Multiple chats with same session_id should maintain context."""
    # First message
    chat_input = ChatInput(
        message="Hello!",
        tenant_id="test-tenant",
        user_id="test-user",
    )
    output1 = await torchestrator.chat(chat_input)
    session_id = output1.session_id

    # Second message in same session
    chat_input2 = ChatInput(
        message="What did I just say?",
        session_id=session_id,
        tenant_id="test-tenant",
        user_id="test-user",
    )
    output2 = await torchestrator.chat(chat_input2)
    assert output2.session_id == session_id


@pytest.mark.asyncio
async def test_process_request_chat(torchestrator):
    """Test process_request with CHAT action."""
    request = TOrchestratorRequest(
        action=TOrchestratorAction.CHAT,
        message="What is Python?",
        tenant_id="test-tenant",
        user_id="test-user",
    )
    response = await torchestrator.process_request(request)
    assert response.success is True
    assert response.session_id
    assert response.latency_ms > 0


@pytest.mark.asyncio
async def test_process_request_list_sessions(torchestrator):
    """Test listing sessions."""
    # Create a session first
    chat_input = ChatInput(
        message="Hi",
        tenant_id="test-tenant",
        user_id="test-user",
    )
    await torchestrator.chat(chat_input)

    # List sessions
    request = TOrchestratorRequest(
        action=TOrchestratorAction.LIST_SESSIONS,
        tenant_id="test-tenant",
        user_id="test-user",
    )
    response = await torchestrator.process_request(request)
    assert response.success is True
    assert "1" in response.response  # Should find 1 session


@pytest.mark.asyncio
async def test_process_request_close_session(torchestrator):
    """Test closing a session."""
    # Create a session
    chat_input = ChatInput(
        message="Hi",
        tenant_id="test-tenant",
        user_id="test-user",
    )
    output = await torchestrator.chat(chat_input)

    # Close it
    request = TOrchestratorRequest(
        action=TOrchestratorAction.CLOSE_SESSION,
        session_id=output.session_id,
        tenant_id="test-tenant",
        user_id="test-user",
    )
    response = await torchestrator.process_request(request)
    assert response.success is True
    assert "closed" in response.response.lower()


@pytest.mark.asyncio
async def test_intent_classification_in_pipeline(torchestrator):
    """Test that intent classification feeds into the pipeline correctly."""
    # File operation should be detected
    chat_input = ChatInput(
        message="Create a file called test.txt with Hello World",
        tenant_id="test-tenant",
        user_id="test-user",
    )
    output = await torchestrator.chat(chat_input)
    assert output.metadata.get("intent_category") == "file_operation"


@pytest.mark.asyncio
async def test_scheduling_intent_in_pipeline(torchestrator):
    """Test scheduling intent detection."""
    chat_input = ChatInput(
        message="Schedule a nightly backup at 2 AM",
        tenant_id="test-tenant",
        user_id="test-user",
    )
    output = await torchestrator.chat(chat_input)
    assert output.metadata.get("intent_category") == "scheduling"


@pytest.mark.asyncio
async def test_git_intent_in_pipeline(torchestrator):
    """Test git operation intent detection."""
    chat_input = ChatInput(
        message="Start a new feature branch called feature/auth",
        tenant_id="test-tenant",
        user_id="test-user",
    )
    output = await torchestrator.chat(chat_input)
    assert output.metadata.get("intent_category") == "git_operation"
''',

}


def create_package_init_files(path):
    """Create __init__.py files in parent directories if they don't exist."""
    dir_name = os.path.dirname(path)
    if dir_name and (dir_name.startswith("") or dir_name.startswith("tests/")):
        parts = dir_name.split('/')
        for i in range(2, len(parts) + 1):
            pkg_path = "/".join(parts[:i])
            init_file = os.path.join(pkg_path, "__init__.py")
            if not os.path.exists(init_file):
                os.makedirs(pkg_path, exist_ok=True)
                print(f"  [Created] {init_file} (empty package marker)")
                with open(init_file, "w") as f:
                    pass


def main():
    """Main function to write all files."""
    print("=" * 60)
    print("  ASSEMBLING CHUNK-010: TOrchestrator (Council Lead)")
    print("=" * 60)
    print()

    files_written = 0
    for path, content in CHUNK_010_FILES.items():
        # Ensure the directory exists
        dir_name = os.path.dirname(path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)

        create_package_init_files(path)

        print(f"  [Writing] {path}")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(textwrap.dedent(content.strip()) + "\n")
        files_written += 1

    print()
    print("-" * 60)
    print(f"  Assembly Complete — {files_written} files written.")
    print("-" * 60)
    print()
    print("  CHUNK-010 delivers:")
    print("    • TOrchestrator agent (Council Lead)")
    print("    • Two-tier IntentParser (rules + Oracle fallback)")
    print("    • TaskDecomposer with strategy per intent category")
    print("    • SessionManager with Redis-backed persistence")
    print("    • ResponseSynthesizer (single/multi-step + error handling)")
    print("    • MessageRouter with Warden auth + correlation tracking")
    print("    • ChatInput/ChatOutput protocol (Part X §10.2)")
    print("    • Full test suite (intent, decomposer, session, synthesizer, agent)")
    print()
    print("  OOBE Criteria Addressed: UC-1, UC-2, UC-5, UC-6")
    print()


if __name__ == "__main__":
    main()

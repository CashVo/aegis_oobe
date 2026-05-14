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
    paths = re.findall(r"[\'\"]([\/\w\-\.]+)[\'\"]", text)
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
    branch_match = re.search(r"branch\s+(?:called|named)?\s*[\'\"]?([\w\-\/]+)[\'\"]?", text, re.IGNORECASE)
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
    time_match = re.search(r"at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm|AM|PM)?", text)
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
    task_match = re.search(r"schedule\s+(?:a\s+)?(.+?)(?:\s+at\s+|\s+every\s+|$)", text, re.IGNORECASE)
    if task_match:
        entities["task_description"] = task_match.group(1).strip()
    return entities


def _extract_user_entities(text: str) -> Dict[str, Any]:
    """Extract user management entities from text."""
    entities: Dict[str, Any] = {}
    # Username
    name_match = re.search(r"(?:named|called|username)\s+[\'\"]?([\w\-]+)[\'\"]?", text, re.IGNORECASE)
    if name_match:
        entities["username"] = name_match.group(1)
    # Role
    role_match = re.search(r"(?:with|as)\s+(?:the\s+)?(?:role\s+)?[\'\"]?(root|admin|member|observer)[\'\"]?", text, re.IGNORECASE)
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
    subject_match = re.search(r"(?:about|regarding|for)\s+(.+?)(?:\?|$)", text, re.IGNORECASE)
    if subject_match:
        entities["subject"] = subject_match.group(1).strip()
    return entities


# ─── Pattern Registry ─────────────────────────────────────────────────

INTENT_PATTERNS: List[Tuple[re.Pattern, IntentCategory, Callable[[str], Dict[str, Any]], List[str], List[str]]] = [
    # (pattern, category, extractor, required_tools, required_skills)

    # File operations
    (re.compile(r"\b(create|write|save|read|show|display|cat|open|delete|remove|rm|list|ls)\b.*\b(file|directory|folder|dir|path)\b", re.IGNORECASE),
     IntentCategory.FILE_OPERATION, _extract_file_entities,
     ["file_read", "file_write", "file_delete", "dir_list", "dir_create"], []),

    (re.compile(r"\b(file|directory|folder)\b.*\b(create|write|save|read|show|delete|remove|list)\b", re.IGNORECASE),
     IntentCategory.FILE_OPERATION, _extract_file_entities,
     ["file_read", "file_write", "file_delete", "dir_list", "dir_create"], []),

    # Git operations
    (re.compile(r"\b(git|branch|commit|merge|push|pull|checkout|feature branch)\b", re.IGNORECASE),
     IntentCategory.GIT_OPERATION, _extract_git_entities,
     ["git_command"], ["manage_git_workflow"]),

    # Scheduling
    (re.compile(r"\b(schedule|reminder|timer|cron|nightly|hourly|daily|weekly|every\s+\w+)\b", re.IGNORECASE),
     IntentCategory.SCHEDULING, _extract_schedule_entities,
     ["schedule_job"], []),

    # User management
    (re.compile(r"\b(create|add|delete|remove|onboard|list|show)\b.*\b(user|users|account|tenant)\b", re.IGNORECASE),
     IntentCategory.USER_MANAGEMENT, _extract_user_entities,
     [], ["onboard_user"]),

    (re.compile(r"\b(user|account|tenant)\b.*\b(create|add|delete|remove|onboard|list|show)\b", re.IGNORECASE),
     IntentCategory.USER_MANAGEMENT, _extract_user_entities,
     [], ["onboard_user"]),

    # Contextual questions (needs memory + oracle)
    (re.compile(r"\b(based on|according to|from what|what did I|my previous|last time|you know about me|what should I do next|what should I focus on)\b", re.IGNORECASE),
     IntentCategory.CONTEXTUAL_QUESTION, lambda t: {},
     [], []),

    # Memory queries
    (re.compile(r"\b(remember|recall|recap|find that conversation|when did we|what did I say|what do you know|search memory|find in memory|based on what you know)\b", re.IGNORECASE),
     IntentCategory.MEMORY_QUERY, _extract_memory_entities,
     [], []),

    # System commands
    (re.compile(r"\b(status|health|system|config|restart|shutdown|uptime)\b", re.IGNORECASE),
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
            json_match = re.search(r"\{[^}]+\}", oracle_output, re.DOTALL)
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

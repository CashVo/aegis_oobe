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

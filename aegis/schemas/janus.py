# aegis/schemas/janus.py
"""
Janus (Governance Engine) protocol schemas.

Implements: Part VI, §6.6 — Janus Protocol
"""

from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field
from datetime import datetime, timezone


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JanusAction(str, Enum):
    """Actions supported by the Janus governance agent."""
    EVALUATE_POLICY = "evaluate_policy"
    ADD_POLICY = "add_policy"
    LIST_POLICIES = "list_policies"
    UPDATE_POLICY = "update_policy"
    DELETE_POLICY = "delete_policy"
    GET_POLICY = "get_policy"


class PolicyRule(BaseModel):
    """
    A single governance policy rule.

    Implements: Part VI, §6.6 — PolicyRule model.

    The `condition` field holds a safe DSL expression evaluated against
    the request context. Supported operators:
      - Comparison: ==, !=, in, not_in, contains, startswith
      - Logical: and, or, not
      - Field access via dot notation on the context dict
    """
    rule_id: str = Field(..., description="Unique identifier for this policy rule.")
    name: str = Field(..., description="Human-readable policy name.")
    description: str = Field(default="", description="Detailed description of what this policy enforces.")
    condition: str = Field(
        ...,
        description=(
            "Evaluatable condition expression. Uses a safe DSL subset. "
            "Example: 'action == \"forge.execute_tool\" and resource == \"tool:execute_shell_command\"'"
        )
    )
    action_on_match: str = Field(
        ...,
        description="Action to take when condition matches: 'allow', 'deny', 'warn', 'log', 'escalate'."
    )
    priority: int = Field(
        default=0,
        description="Higher priority rules are evaluated first. Range: 0-1000."
    )
    active: bool = Field(default=True, description="Whether this rule is currently active.")
    tenant_id: Optional[str] = Field(
        default=None,
        description="If set, rule applies only to this tenant. None = system-wide."
    )
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    tags: list[str] = Field(default_factory=list, description="Categorization tags for filtering.")


class JanusRequest(BaseModel):
    """
    Request envelope for Janus agent interactions.

    Implements: Part VI, §6.6 — JanusRequest model.
    """
    action: JanusAction
    tenant_id: str = Field(..., description="Tenant scope for the request.")
    user_id: str = Field(..., description="User making the request.")
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Context dict for policy evaluation (action, resource, agent, etc.)."
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Action-specific payload (e.g., PolicyRule dict for ADD_POLICY)."
    )


class PolicyEvalResult(BaseModel):
    """Result of evaluating a single policy rule against a context."""
    rule_id: str
    rule_name: str
    matched: bool
    action_on_match: str
    priority: int


class JanusResponse(BaseModel):
    """
    Response envelope from Janus agent.

    Implements: Part VI, §6.6 — JanusResponse model.
    """
    success: bool
    action: JanusAction
    verdict: Optional[str] = Field(
        default=None,
        description="Final verdict for EVALUATE_POLICY: 'allow', 'deny', 'warn', 'log', 'escalate'."
    )
    policies_evaluated: int = Field(default=0, description="Number of policies evaluated.")
    matched_policies: list[str] = Field(
        default_factory=list,
        description="List of rule_ids that matched."
    )
    eval_details: list[PolicyEvalResult] = Field(
        default_factory=list,
        description="Detailed evaluation results per rule."
    )
    data: dict[str, Any] = Field(default_factory=dict, description="Action-specific response data.")
    error: Optional[str] = Field(default=None, description="Error message if success=False.")

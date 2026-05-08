# aegis/schemas/warden.py
"""
Warden Protocol Schemas.
Implements: Part VI, §6.4 — Warden Protocol

Defines the request/response contracts for all security authorization
interactions mediated by the Warden agent.
"""

from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class WardenVerdict(str, Enum):
    """Possible authorization verdicts issued by the Warden."""
    ALLOW = "allow"
    DENY = "deny"
    ESCALATE = "escalate"


class WardenRequest(BaseModel):
    """
    A request to the Warden for authorization of an action.

    Every inter-agent message and every tool/skill invocation must be
    validated by the Warden before execution.
    """
    action: str = Field(
        ...,
        description="The action being requested (e.g., 'forge.execute_tool', 'oracle.query')."
    )
    resource: str = Field(
        ...,
        description="The resource being accessed (e.g., 'tool:file_write', 'skill:web_research')."
    )
    tenant_id: str = Field(
        ...,
        description="The tenant context for this request."
    )
    user_id: str = Field(
        ...,
        description="The user requesting authorization."
    )
    context: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional context for policy evaluation (e.g., parameters, target paths)."
    )


class WardenResponse(BaseModel):
    """
    The Warden's authorization verdict for a given request.
    """
    verdict: WardenVerdict = Field(
        ...,
        description="The authorization decision: allow, deny, or escalate."
    )
    reason: str = Field(
        ...,
        description="Human-readable explanation of the verdict."
    )
    policy_applied: Optional[str] = Field(
        None,
        description="The identifier of the policy rule that produced this verdict."
    )
    escalation_target: Optional[str] = Field(
        None,
        description="If verdict is ESCALATE, the agent or user to escalate to."
    )


class WardenAction(str, Enum):
    """Actions the Warden agent handles on the message bus."""
    AUTHORIZE = "authorize"
    CHECK_PERMISSION = "check_permission"
    CHECK_ALLOWLIST = "check_allowlist"
    ENABLE_BYPASS = "enable_bypass"
    DISABLE_BYPASS = "disable_bypass"
    GET_STATUS = "get_status"
    RELOAD_POLICIES = "reload_policies"

# aegis/forge/skills/base.py
# Implements: Part VII, §7.2 — Skill Interface
"""
Base classes for the Skill interface.

Every skill module must expose:
    - manifest: SkillManifest
    - async def execute(params: dict, forge_context: ForgeContext) -> SkillResult
"""

from typing import Any, Optional
from pydantic import BaseModel


class SkillManifest(BaseModel):
    """
    Declarative manifest for a Skill.

    Attributes:
        name: Unique skill identifier.
        description: Human-readable description.
        version: Semantic version string.
        parameters_schema: JSON Schema defining valid input parameters.
        permissions_required: Permission strings required for execution.
        tools_used: List of tool names this skill depends on.
        requires_oracle: Whether this skill needs LLM access.
        scope: "system" (shared) or "user" (per-user).
        timeout_seconds: Maximum execution time.
    """
    name: str
    description: str
    version: str
    parameters_schema: dict = {}
    permissions_required: list[str] = []
    tools_used: list[str] = []
    requires_oracle: bool = False
    scope: str = "system"
    timeout_seconds: int = 120


class SkillResult(BaseModel):
    """
    Standard result returned by all skill executions.

    Attributes:
        success: Whether the skill completed successfully.
        data: Output data from the skill.
        steps_executed: Audit trail of operations performed.
        error: Error message if success is False.
    """
    success: bool
    data: Any = None
    steps_executed: list[str] = []
    error: Optional[str] = None

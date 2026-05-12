# aegis/schemas/forge.py
# Implements: Part VI, §6.1 — Forge Protocol
"""
Forge protocol schemas defining the request/response contracts
for tool and skill execution via The Forge agent.
"""

from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


class ForgeAction(str, Enum):
    """Actions supported by The Forge agent."""
    EXECUTE_TOOL = "execute_tool"
    EXECUTE_SKILL = "execute_skill"
    LIST_TOOLS = "list_tools"
    LIST_SKILLS = "list_skills"
    REGISTER_TOOL = "register_tool"
    REGISTER_SKILL = "register_skill"


class ForgeRequest(BaseModel):
    """
    Request payload for Forge operations.

    Attributes:
        action: The Forge action to perform.
        tool_or_skill_name: Name of the tool/skill to execute (required for execute actions).
        parameters: Input parameters for the tool/skill.
        timeout_seconds: Maximum execution time before timeout.
    """
    action: ForgeAction
    tool_or_skill_name: Optional[str] = None
    parameters: dict = {}
    timeout_seconds: int = 60


class ForgeResponse(BaseModel):
    """
    Response payload from Forge operations.

    Attributes:
        success: Whether the operation completed successfully.
        action: The action that was performed.
        result: The output data from the operation.
        error: Error message if success is False.
        execution_time_ms: Time taken to execute in milliseconds.
    """
    success: bool
    action: ForgeAction
    result: Any = None
    error: Optional[str] = None
    execution_time_ms: float = 0.0

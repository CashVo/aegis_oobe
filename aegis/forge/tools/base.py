# aegis/forge/tools/base.py
# Implements: Part VII, §7.1 — Tool Interface
"""
Base classes for the Tool interface.

Every tool module must expose:
    - manifest: ToolManifest
    - async def execute(params: dict) -> ToolResult
"""

from typing import Any, Optional
from pydantic import BaseModel


class ToolManifest(BaseModel):
    """
    Declarative manifest for a Tool.

    Attributes:
        name: Unique tool identifier.
        description: Human-readable description of what this tool does.
        version: Semantic version string.
        parameters_schema: JSON Schema defining valid input parameters.
        permissions_required: List of permission strings required to execute.
        timeout_seconds: Maximum allowed execution time.
    """
    name: str
    description: str
    version: str
    parameters_schema: dict = {}
    permissions_required: list[str] = []
    timeout_seconds: int = 30


class ToolResult(BaseModel):
    """
    Standard result returned by all tool executions.

    Attributes:
        success: Whether the tool executed successfully.
        data: Output data from the tool (type varies by tool).
        error: Error message if success is False.
    """
    success: bool
    data: Any = None
    error: Optional[str] = None

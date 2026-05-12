# aegis/forge/tools/dir_create.py
# Implements: Part VIII, §8.1 — dir_create tool
"""
Tool: dir_create
Create a directory (with mkdir -p semantics).
"""

import os

from aegis.forge.tools.base import ToolManifest, ToolResult


manifest = ToolManifest(
    name="dir_create",
    description="Create a directory (with mkdir -p semantics).",
    version="1.0.0",
    parameters_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Directory path to create."},
        },
        "required": ["path"],
    },
    permissions_required=["file.write"],
    timeout_seconds=5,
)


async def execute(params: dict) -> ToolResult:
    """
    Create a directory and all intermediate directories.

    Args:
        params: {"path": str}

    Returns:
        ToolResult confirming creation, or error message.
    """
    path = params.get("path")

    if not path:
        return ToolResult(success=False, error="Parameter 'path' is required.")

    try:
        already_existed = os.path.exists(path)
        os.makedirs(path, exist_ok=True)
        return ToolResult(success=True, data={
            "path": path,
            "created": not already_existed,
            "already_existed": already_existed,
        })
    except PermissionError:
        return ToolResult(success=False, error=f"Permission denied: {path}")
    except Exception as e:
        return ToolResult(success=False, error=f"Failed to create directory: {str(e)}")

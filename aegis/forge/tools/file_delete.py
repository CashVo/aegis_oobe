# aegis/forge/tools/file_delete.py
# Implements: Part VIII, §8.1 — file_delete tool
"""
Tool: file_delete
Delete a file at a given path.
"""

import os

from aegis.forge.tools.base import ToolManifest, ToolResult


manifest = ToolManifest(
    name="file_delete",
    description="Delete a file at a given path.",
    version="1.0.0",
    parameters_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute or relative file path to delete."},
        },
        "required": ["path"],
    },
    permissions_required=["file.delete"],
    timeout_seconds=10,
)


async def execute(params: dict) -> ToolResult:
    """
    Delete a file.

    Args:
        params: {"path": str}

    Returns:
        ToolResult confirming deletion, or error message.
    """
    path = params.get("path")

    if not path:
        return ToolResult(success=False, error="Parameter 'path' is required.")

    if not os.path.exists(path):
        return ToolResult(success=False, error=f"File not found: {path}")

    if not os.path.isfile(path):
        return ToolResult(success=False, error=f"Path is not a file (use caution with directories): {path}")

    try:
        os.remove(path)
        return ToolResult(success=True, data={"path": path, "deleted": True})
    except PermissionError:
        return ToolResult(success=False, error=f"Permission denied: {path}")
    except Exception as e:
        return ToolResult(success=False, error=f"Failed to delete file: {str(e)}")

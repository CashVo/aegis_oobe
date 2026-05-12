# aegis/forge/tools/file_write.py
# Implements: Part VIII, §8.1 — file_write tool
"""
Tool: file_write
Write content to a file (create or overwrite).
"""

import os
import aiofiles

from aegis.forge.tools.base import ToolManifest, ToolResult


manifest = ToolManifest(
    name="file_write",
    description="Write content to a file (create or overwrite).",
    version="1.0.0",
    parameters_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute or relative file path to write."},
            "content": {"type": "string", "description": "Content to write to the file."},
            "encoding": {"type": "string", "default": "utf-8", "description": "File encoding."},
            "create_dirs": {"type": "boolean", "default": True, "description": "Create parent directories if they don't exist."},
        },
        "required": ["path", "content"],
    },
    permissions_required=["file.write"],
    timeout_seconds=10,
)


async def execute(params: dict) -> ToolResult:
    """
    Write content to a file.

    Args:
        params: {"path": str, "content": str, "encoding": str, "create_dirs": bool}

    Returns:
        ToolResult confirming write, or error message.
    """
    path = params.get("path")
    content = params.get("content")
    encoding = params.get("encoding", "utf-8")
    create_dirs = params.get("create_dirs", True)

    if not path:
        return ToolResult(success=False, error="Parameter 'path' is required.")
    if content is None:
        return ToolResult(success=False, error="Parameter 'content' is required.")

    try:
        if create_dirs:
            dir_name = os.path.dirname(path)
            if dir_name:
                os.makedirs(dir_name, exist_ok=True)

        async with aiofiles.open(path, mode="w", encoding=encoding) as f:
            await f.write(content)

        size_bytes = len(content.encode(encoding))
        return ToolResult(success=True, data={"path": path, "size_bytes": size_bytes, "created": True})
    except PermissionError:
        return ToolResult(success=False, error=f"Permission denied: {path}")
    except Exception as e:
        return ToolResult(success=False, error=f"Failed to write file: {str(e)}")

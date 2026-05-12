# aegis/forge/tools/file_read.py
# Implements: Part VIII, §8.1 — file_read tool
"""
Tool: file_read
Read the contents of a file at a given path.
"""

import os
import aiofiles

from aegis.forge.tools.base import ToolManifest, ToolResult


manifest = ToolManifest(
    name="file_read",
    description="Read the contents of a file at a given path.",
    version="1.0.0",
    parameters_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute or relative file path to read."},
            "encoding": {"type": "string", "default": "utf-8", "description": "File encoding."},
        },
        "required": ["path"],
    },
    permissions_required=["file.read"],
    timeout_seconds=10,
)


async def execute(params: dict) -> ToolResult:
    """
    Read file contents.

    Args:
        params: {"path": str, "encoding": str (optional, default utf-8)}

    Returns:
        ToolResult with file contents as data, or error message.
    """
    path = params.get("path")
    encoding = params.get("encoding", "utf-8")

    if not path:
        return ToolResult(success=False, error="Parameter 'path' is required.")

    if not os.path.exists(path):
        return ToolResult(success=False, error=f"File not found: {path}")

    if not os.path.isfile(path):
        return ToolResult(success=False, error=f"Path is not a file: {path}")

    try:
        async with aiofiles.open(path, mode="r", encoding=encoding) as f:
            content = await f.read()
        return ToolResult(success=True, data={"content": content, "path": path, "size_bytes": len(content.encode(encoding))})
    except PermissionError:
        return ToolResult(success=False, error=f"Permission denied: {path}")
    except UnicodeDecodeError as e:
        return ToolResult(success=False, error=f"Encoding error reading {path}: {str(e)}")
    except Exception as e:
        return ToolResult(success=False, error=f"Failed to read file: {str(e)}")

# aegis/forge/tools/dir_list.py
# Implements: Part VIII, §8.1 — dir_list tool
"""
Tool: dir_list
List contents of a directory.
"""

import os

from aegis.forge.tools.base import ToolManifest, ToolResult


manifest = ToolManifest(
    name="dir_list",
    description="List contents of a directory.",
    version="1.0.0",
    parameters_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Directory path to list."},
            "recursive": {"type": "boolean", "default": False, "description": "List recursively."},
            "include_hidden": {"type": "boolean", "default": False, "description": "Include hidden files/dirs."},
        },
        "required": ["path"],
    },
    permissions_required=["file.read"],
    timeout_seconds=15,
)


async def execute(params: dict) -> ToolResult:
    """
    List directory contents.

    Args:
        params: {"path": str, "recursive": bool, "include_hidden": bool}

    Returns:
        ToolResult with list of entries, or error message.
    """
    path = params.get("path")
    recursive = params.get("recursive", False)
    include_hidden = params.get("include_hidden", False)

    if not path:
        return ToolResult(success=False, error="Parameter 'path' is required.")

    if not os.path.exists(path):
        return ToolResult(success=False, error=f"Directory not found: {path}")

    if not os.path.isdir(path):
        return ToolResult(success=False, error=f"Path is not a directory: {path}")

    try:
        entries = []

        if recursive:
            for root, dirs, files in os.walk(path):
                if not include_hidden:
                    dirs[:] = [d for d in dirs if not d.startswith(".")]
                    files = [f for f in files if not f.startswith(".")]
                for name in dirs:
                    full_path = os.path.join(root, name)
                    entries.append({"name": name, "path": full_path, "type": "directory"})
                for name in files:
                    full_path = os.path.join(root, name)
                    entries.append({
                        "name": name,
                        "path": full_path,
                        "type": "file",
                        "size_bytes": os.path.getsize(full_path),
                    })
        else:
            for name in sorted(os.listdir(path)):
                if not include_hidden and name.startswith("."):
                    continue
                full_path = os.path.join(path, name)
                entry_type = "directory" if os.path.isdir(full_path) else "file"
                entry = {"name": name, "path": full_path, "type": entry_type}
                if entry_type == "file":
                    entry["size_bytes"] = os.path.getsize(full_path)
                entries.append(entry)

        return ToolResult(success=True, data={"path": path, "entries": entries, "count": len(entries)})
    except PermissionError:
        return ToolResult(success=False, error=f"Permission denied: {path}")
    except Exception as e:
        return ToolResult(success=False, error=f"Failed to list directory: {str(e)}")

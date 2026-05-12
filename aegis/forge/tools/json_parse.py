# aegis/forge/tools/json_parse.py
# Implements: Part VIII, §8.1 — json_parse tool
"""
Tool: json_parse
Parse and extract data from a JSON string/file.
Stateless utility — no permissions required.
"""

import json
from typing import Any

from aegis.forge.tools.base import ToolManifest, ToolResult


manifest = ToolManifest(
    name="json_parse",
    description="Parse and extract data from a JSON string/file.",
    version="1.0.0",
    parameters_schema={
        "type": "object",
        "properties": {
            "data": {"type": "string", "description": "JSON string to parse."},
            "path": {"type": "string", "description": "Optional dot-notation path to extract (e.g., 'results.0.name')."},
        },
        "required": ["data"],
    },
    permissions_required=[],  # Stateless utility
    timeout_seconds=5,
)


def _extract_path(obj: Any, path: str) -> Any:
    """Extract a value from a nested structure using dot notation."""
    parts = path.split(".")
    current = obj
    for part in parts:
        if isinstance(current, dict):
            if part in current:
                current = current[part]
            else:
                raise KeyError(f"Key '{part}' not found in object.")
        elif isinstance(current, (list, tuple)):
            try:
                idx = int(part)
                current = current[idx]
            except (ValueError, IndexError) as e:
                raise KeyError(f"Invalid index '{part}': {str(e)}")
        else:
            raise KeyError(f"Cannot traverse into {type(current).__name__} with key '{part}'.")
    return current


async def execute(params: dict) -> ToolResult:
    """
    Parse JSON and optionally extract a value by path.

    Args:
        params: {"data": str, "path": str (optional)}

    Returns:
        ToolResult with parsed JSON data or extracted value.
    """
    data = params.get("data")
    path = params.get("path")

    if not data:
        return ToolResult(success=False, error="Parameter 'data' is required.")

    try:
        parsed = json.loads(data)
    except json.JSONDecodeError as e:
        return ToolResult(success=False, error=f"Invalid JSON: {str(e)}")

    if path:
        try:
            extracted = _extract_path(parsed, path)
            return ToolResult(success=True, data={"extracted": extracted, "path": path})
        except KeyError as e:
            return ToolResult(success=False, error=f"Path extraction failed: {str(e)}")
    else:
        return ToolResult(success=True, data={"parsed": parsed})

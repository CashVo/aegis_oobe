# aegis/forge/tools/git_command.py
# Implements: Part VIII, §8.1 — git_command tool
"""
Tool: git_command
Execute a Git command (wrapper around shell for git-specific operations).
"""

import asyncio
import shlex

from aegis.forge.tools.base import ToolManifest, ToolResult


manifest = ToolManifest(
    name="git_command",
    description="Execute a Git command (wrapper around shell for git-specific operations).",
    version="1.0.0",
    parameters_schema={
        "type": "object",
        "properties": {
            "args": {"type": "string", "description": "Git arguments (e.g., 'status', 'commit -m \"msg\"')."},
            "cwd": {"type": "string", "description": "Repository working directory."},
            "timeout": {"type": "integer", "default": 30, "description": "Timeout in seconds."},
        },
        "required": ["args"],
    },
    permissions_required=["git.execute"],
    timeout_seconds=60,
)


async def execute(params: dict) -> ToolResult:
    """
    Execute a git command.

    Args:
        params: {"args": str, "cwd": str, "timeout": int}

    Returns:
        ToolResult with git command output.
    """
    args = params.get("args")
    cwd = params.get("cwd", ".")
    timeout = params.get("timeout", 30)

    if not args:
        return ToolResult(success=False, error="Parameter 'args' is required.")

    command = f"git {args}"

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )

        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)

        stdout_str = stdout.decode("utf-8", errors="replace").strip()
        stderr_str = stderr.decode("utf-8", errors="replace").strip()

        return ToolResult(
            success=(proc.returncode == 0),
            data={
                "stdout": stdout_str,
                "stderr": stderr_str,
                "return_code": proc.returncode,
                "command": command,
            },
            error=stderr_str if proc.returncode != 0 else None,
        )
    except asyncio.TimeoutError:
        return ToolResult(success=False, error=f"Git command timed out after {timeout}s: {command}")
    except Exception as e:
        return ToolResult(success=False, error=f"Git command failed: {str(e)}")

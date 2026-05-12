# aegis/forge/tools/execute_shell_command.py
# Implements: Part VIII, §8.1 — execute_shell_command tool
# Security: Part XIII, RT-6 — Warden enforces allowlist
"""
Tool: execute_shell_command
Execute an arbitrary shell command. Warden-gated with explicit allowlist.

SECURITY NOTE: This tool is inherently dangerous. The Warden agent enforces
an allowlist of permitted commands/patterns BEFORE this tool is invoked.
The tool itself performs basic sanity checks but relies on Warden for policy.
"""

import asyncio
import shlex
from typing import Optional

from aegis.forge.tools.base import ToolManifest, ToolResult


# Default allowlist — restrictive. Expansion requires root/admin.
DEFAULT_ALLOWLIST_PREFIXES = [
    "git", "ls", "cat", "echo", "mkdir", "cp", "mv", "rm",
    "find", "grep", "wc", "head", "tail", "sort", "uniq",
    "python", "pip", "pytest", "which", "pwd", "date",
]

manifest = ToolManifest(
    name="execute_shell_command",
    description="Execute an arbitrary shell command. Warden-gated with explicit allowlist.",
    version="1.0.0",
    parameters_schema={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The shell command to execute."},
            "cwd": {"type": "string", "description": "Working directory for the command."},
            "timeout": {"type": "integer", "default": 30, "description": "Timeout in seconds."},
            "shell": {"type": "boolean", "default": True, "description": "Execute via shell."},
        },
        "required": ["command"],
    },
    permissions_required=["shell.execute"],
    timeout_seconds=60,
)


def _check_allowlist(command: str) -> Optional[str]:
    """
    Basic local allowlist check. This is a secondary defense —
    Warden performs the primary authorization check.

    Returns None if allowed, or an error string if blocked.
    """
    # Extract the base command
    try:
        parts = shlex.split(command)
        if not parts:
            return "Empty command."
        base_cmd = parts[0].split("/")[-1]  # Handle full paths
    except ValueError:
        # shlex can't parse — let shell handle it but flag
        base_cmd = command.strip().split()[0] if command.strip() else ""

    if not any(base_cmd.startswith(prefix) for prefix in DEFAULT_ALLOWLIST_PREFIXES):
        return (
            f"Command '{base_cmd}' is not in the local allowlist. "
            f"Allowed prefixes: {DEFAULT_ALLOWLIST_PREFIXES}"
        )
    return None


async def execute(params: dict) -> ToolResult:
    """
    Execute a shell command.

    Args:
        params: {"command": str, "cwd": str, "timeout": int, "shell": bool}

    Returns:
        ToolResult with stdout, stderr, and return code.
    """
    command = params.get("command")
    cwd = params.get("cwd")
    timeout = params.get("timeout", 30)
    use_shell = params.get("shell", True)

    if not command:
        return ToolResult(success=False, error="Parameter 'command' is required.")

    # Local allowlist check (secondary defense)
    block_reason = _check_allowlist(command)
    if block_reason:
        return ToolResult(success=False, error=f"Command blocked: {block_reason}")

    try:
        if use_shell:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
        else:
            args = shlex.split(command)
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )

        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)

        return ToolResult(
            success=(proc.returncode == 0),
            data={
                "stdout": stdout.decode("utf-8", errors="replace").strip(),
                "stderr": stderr.decode("utf-8", errors="replace").strip(),
                "return_code": proc.returncode,
                "command": command,
            },
            error=stderr.decode("utf-8", errors="replace").strip() if proc.returncode != 0 else None,
        )
    except asyncio.TimeoutError:
        return ToolResult(success=False, error=f"Command timed out after {timeout}s: {command}")
    except FileNotFoundError:
        return ToolResult(success=False, error=f"Command not found or cwd does not exist.")
    except Exception as e:
        return ToolResult(success=False, error=f"Shell execution failed: {str(e)}")

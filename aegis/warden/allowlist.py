# aegis/warden/allowlist.py
"""
Allowlist Engine — Shell Command Authorization.
Implements: Part XIII, RT-6 — Unbounded Shell Execution Mitigation

Enforces an allowlist of permitted shell commands and patterns.
Default allowlist is restrictive (git, ls, cat, echo, mkdir).
Expansion requires root or admin role. All executions are logged.
"""

import logging
import re
import shlex
from typing import Any, Dict, List, Optional, Set

from aegis.schemas.warden import WardenVerdict, WardenResponse

logger = logging.getLogger(__name__)


# Default restrictive allowlist per RT-6
DEFAULT_ALLOWED_COMMANDS: List[str] = [
    "git",
    "ls",
    "cat",
    "echo",
    "mkdir",
    "cp",
    "mv",
    "rm",
    "pwd",
    "cd",
    "head",
    "tail",
    "grep",
    "find",
    "wc",
    "sort",
    "uniq",
    "diff",
    "touch",
    "chmod",
    "python",
    "pip",
    "pytest",
]

# Patterns that are always denied regardless of command
DENY_PATTERNS: List[str] = [
    r"rm\s+-rf\s+/",          # rm -rf / (catastrophic delete)
    r"rm\s+-rf\s+~",          # rm -rf ~ (home directory wipe)
    r":(\s*)\{.*\|.*\}",    # Fork bomb patterns
    r"mkfs\.",                  # Filesystem format
    r"dd\s+if=",               # Raw disk operations
    r">(\s*)/dev/sd",          # Direct device writes
    r"curl.*\|.*sh",           # Pipe remote scripts to shell
    r"wget.*\|.*sh",           # Pipe remote scripts to shell
    r"eval\s+",               # Eval execution
    r"\$\(.*\)",            # Command substitution (when nested dangerously)
]

# Patterns that trigger escalation rather than outright deny
ESCALATION_PATTERNS: List[str] = [
    r"sudo\s+",               # Privilege escalation
    r"apt\s+(install|remove)", # Package management
    r"pip\s+install",         # Package installation
    r"npm\s+install",         # Package installation
    r"systemctl\s+",          # Service management
    r"kill\s+",               # Process termination
]


class AllowlistEngine:
    """
    Shell command allowlist enforcement engine.

    Validates shell commands against a configurable allowlist and
    deny/escalation pattern lists. Ensures that only pre-approved
    commands can be executed through the Forge's execute_shell_command tool.
    """

    def __init__(
        self,
        allowed_commands: Optional[List[str]] = None,
        additional_deny_patterns: Optional[List[str]] = None,
        additional_escalation_patterns: Optional[List[str]] = None,
    ):
        """
        Initialize the allowlist engine.

        Args:
            allowed_commands: Override the default command allowlist.
                            If None, uses DEFAULT_ALLOWED_COMMANDS.
            additional_deny_patterns: Additional regex patterns to always deny.
            additional_escalation_patterns: Additional patterns that trigger escalation.
        """
        self._allowed_commands: Set[str] = set(
            allowed_commands if allowed_commands is not None else DEFAULT_ALLOWED_COMMANDS
        )
        self._deny_patterns: List[re.Pattern] = [
            re.compile(p) for p in DENY_PATTERNS
        ]
        self._escalation_patterns: List[re.Pattern] = [
            re.compile(p) for p in ESCALATION_PATTERNS
        ]

        if additional_deny_patterns:
            self._deny_patterns.extend(
                re.compile(p) for p in additional_deny_patterns
            )
        if additional_escalation_patterns:
            self._escalation_patterns.extend(
                re.compile(p) for p in additional_escalation_patterns
            )

        logger.info(
            "AllowlistEngine initialized",
            extra={
                "allowed_commands": sorted(self._allowed_commands),
                "deny_patterns": len(self._deny_patterns),
                "escalation_patterns": len(self._escalation_patterns),
            },
        )

    @property
    def allowed_commands(self) -> Set[str]:
        """Return the current set of allowed commands."""
        return set(self._allowed_commands)

    def add_command(self, command: str) -> None:
        """
        Add a command to the allowlist.

        Args:
            command: The base command to allow (e.g., 'docker').
        """
        self._allowed_commands.add(command)
        logger.info(f"Command '{command}' added to allowlist.")

    def remove_command(self, command: str) -> None:
        """
        Remove a command from the allowlist.

        Args:
            command: The base command to remove.
        """
        self._allowed_commands.discard(command)
        logger.info(f"Command '{command}' removed from allowlist.")

    def _extract_base_command(self, command_string: str) -> Optional[str]:
        """
        Extract the base command from a full command string.

        Handles:
            - Simple commands: "ls -la" -> "ls"
            - Path-qualified commands: "/usr/bin/git status" -> "git"
            - Environment prefixes: "ENV=val command" -> "command"

        Args:
            command_string: The full shell command string.

        Returns:
            The base command name, or None if parsing fails.
        """
        if not command_string or not command_string.strip():
            return None

        try:
            # Handle environment variable prefixes
            parts = shlex.split(command_string.strip())
        except ValueError:
            # shlex can't parse (unmatched quotes, etc.)
            # Fall back to simple split
            parts = command_string.strip().split()

        if not parts:
            return None

        # Skip env var assignments (KEY=VALUE command ...)
        idx = 0
        while idx < len(parts) and "=" in parts[idx] and not parts[idx].startswith("-"):
            idx += 1

        if idx >= len(parts):
            return None

        # Extract base command (strip path)
        base = parts[idx].split("/")[-1]
        return base

    def _check_deny_patterns(self, command_string: str) -> Optional[str]:
        """
        Check if a command matches any deny pattern.

        Args:
            command_string: The full command string to check.

        Returns:
            The matched pattern string if denied, None if no match.
        """
        for pattern in self._deny_patterns:
            if pattern.search(command_string):
                return pattern.pattern
        return None

    def _check_escalation_patterns(self, command_string: str) -> Optional[str]:
        """
        Check if a command matches any escalation pattern.

        Args:
            command_string: The full command string to check.

        Returns:
            The matched pattern string if escalation needed, None if no match.
        """
        for pattern in self._escalation_patterns:
            if pattern.search(command_string):
                return pattern.pattern
        return None

    def evaluate(
        self,
        command_string: str,
        user_id: str,
        is_root: bool = False,
        is_admin: bool = False,
        context: Optional[Dict[str, Any]] = None,
    ) -> WardenResponse:
        """
        Evaluate a shell command against the allowlist.

        Evaluation order:
            1. Check deny patterns (always blocked, even for root)
            2. Check escalation patterns (escalated unless root/admin)
            3. Check base command against allowlist
            4. Root/admin bypass for non-deny commands

        Args:
            command_string: The full shell command to evaluate.
            user_id: The requesting user ID.
            is_root: Whether the user has root privileges.
            is_admin: Whether the user has admin privileges.
            context: Additional context.

        Returns:
            WardenResponse with the verdict.
        """
        if not command_string or not command_string.strip():
            return WardenResponse(
                verdict=WardenVerdict.DENY,
                reason="Empty command string.",
                policy_applied="allowlist_empty_command",
            )

        # Step 1: Deny patterns (absolute — even root can't bypass)
        deny_match = self._check_deny_patterns(command_string)
        if deny_match:
            logger.warning(
                "Shell command matched DENY pattern",
                extra={
                    "command": command_string,
                    "pattern": deny_match,
                    "user_id": user_id,
                },
            )
            return WardenResponse(
                verdict=WardenVerdict.DENY,
                reason=f"Command matches dangerous pattern and is unconditionally blocked.",
                policy_applied=f"allowlist_deny_pattern:{deny_match}",
            )

        # Step 2: Escalation patterns (root/admin can proceed, others escalate)
        escalation_match = self._check_escalation_patterns(command_string)
        if escalation_match and not (is_root or is_admin):
            logger.info(
                "Shell command requires escalation",
                extra={
                    "command": command_string,
                    "pattern": escalation_match,
                    "user_id": user_id,
                },
            )
            return WardenResponse(
                verdict=WardenVerdict.ESCALATE,
                reason=f"Command requires elevated privileges. Escalating to admin.",
                policy_applied=f"allowlist_escalation:{escalation_match}",
                escalation_target="admin",
            )

        # Step 3: Extract base command and check allowlist
        base_command = self._extract_base_command(command_string)
        if base_command is None:
            return WardenResponse(
                verdict=WardenVerdict.DENY,
                reason="Unable to parse command. Denied for safety.",
                policy_applied="allowlist_parse_failure",
            )

        # Root and admin can execute any non-denied command
        if is_root or is_admin:
            logger.info(
                "Shell command allowed (elevated privileges)",
                extra={
                    "command": command_string,
                    "base_command": base_command,
                    "user_id": user_id,
                    "elevated": True,
                },
            )
            return WardenResponse(
                verdict=WardenVerdict.ALLOW,
                reason=f"Command '{base_command}' allowed (elevated privileges).",
                policy_applied="allowlist_elevated_allow",
            )

        # Standard users — must be on the allowlist
        if base_command in self._allowed_commands:
            logger.debug(
                "Shell command allowed",
                extra={
                    "command": command_string,
                    "base_command": base_command,
                    "user_id": user_id,
                },
            )
            return WardenResponse(
                verdict=WardenVerdict.ALLOW,
                reason=f"Command '{base_command}' is on the approved allowlist.",
                policy_applied="allowlist_approved",
            )
        else:
            logger.info(
                "Shell command denied (not on allowlist)",
                extra={
                    "command": command_string,
                    "base_command": base_command,
                    "user_id": user_id,
                },
            )
            return WardenResponse(
                verdict=WardenVerdict.DENY,
                reason=f"Command '{base_command}' is not on the approved allowlist. Contact an admin to expand the allowlist.",
                policy_applied="allowlist_not_approved",
            )

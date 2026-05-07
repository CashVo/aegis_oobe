# aegis/warden/interceptor.py
"""
Message Interceptor — Universal Authorization Gate.
Implements: Part II §2.1 — "Every inter-agent message and every tool/skill
invocation passes through the Warden agent for authorization. No exceptions."

The interceptor sits in the message path and validates every AegisMessage
before it reaches its target agent.
"""

import logging
import time
from typing import Any, Callable, Dict, Optional, Set

from aegis.schemas.message import AegisMessage, MessageType
from aegis.schemas.warden import WardenRequest, WardenResponse, WardenVerdict
from aegis.warden.permission_model import PermissionModel
from aegis.warden.allowlist import AllowlistEngine
from aegis.warden.bypass import BypassManager

logger = logging.getLogger(__name__)


# Messages from these source agents are always allowed (internal system messages)
TRUSTED_SYSTEM_AGENTS: Set[str] = {
    "system_manager",
    "observer",
}

# These actions are always allowed without authorization (low-risk reads)
PASSTHROUGH_ACTIONS: Set[str] = {
    "warden.authorize",      # Avoid infinite recursion
    "warden.get_status",
    "observer.log",
    "observer.heartbeat",
}


class MessageInterceptor:
    """
    Universal message authorization interceptor.

    Evaluates every AegisMessage against the permission model before
    allowing it to proceed to its target agent. This is the enforcement
    point for the Warden's security guarantees.
    """

    def __init__(
        self,
        permission_model: PermissionModel,
        allowlist_engine: AllowlistEngine,
        bypass_manager: BypassManager,
        user_permission_resolver: Optional[Callable[[str, str], Set[str]]] = None,
    ):
        """
        Initialize the message interceptor.

        Args:
            permission_model: The RBAC permission evaluation engine.
            allowlist_engine: The shell command allowlist engine.
            bypass_manager: The emergency bypass manager.
            user_permission_resolver: A callable that resolves (tenant_id, user_id)
                                     to a set of permissions. If None, defaults to
                                     empty permissions (deny all non-passthrough).
        """
        self._permission_model = permission_model
        self._allowlist_engine = allowlist_engine
        self._bypass_manager = bypass_manager
        self._resolve_permissions = user_permission_resolver or self._default_resolver

        # Metrics
        self._total_evaluated: int = 0
        self._total_allowed: int = 0
        self._total_denied: int = 0
        self._total_escalated: int = 0
        self._total_bypassed: int = 0

        logger.info("MessageInterceptor initialized.")

    @staticmethod
    def _default_resolver(tenant_id: str, user_id: str) -> Set[str]:
        """Default resolver returns empty permissions (deny-by-default)."""
        return set()

    @property
    def metrics(self) -> Dict[str, int]:
        """Return interceptor metrics."""
        return {
            "total_evaluated": self._total_evaluated,
            "total_allowed": self._total_allowed,
            "total_denied": self._total_denied,
            "total_escalated": self._total_escalated,
            "total_bypassed": self._total_bypassed,
        }

    def _is_passthrough(self, message: AegisMessage) -> bool:
        """
        Check if a message should bypass authorization.

        Passthrough conditions:
            1. Source is a trusted system agent
            2. Action is in the passthrough list
            3. Message is a RESPONSE or ERROR type (responses don't need auth)
        """
        if message.source_agent in TRUSTED_SYSTEM_AGENTS:
            return True
        if message.action in PASSTHROUGH_ACTIONS:
            return True
        if message.message_type in (MessageType.RESPONSE, MessageType.ERROR):
            return True
        return False

    def _is_shell_command(self, message: AegisMessage) -> bool:
        """Check if this message is a shell command execution request."""
        return (
            message.action == "forge.execute_tool"
            and message.payload.get("tool_or_skill_name") == "execute_shell_command"
        )

    def _extract_resource(self, message: AegisMessage) -> str:
        """
        Extract the resource identifier from a message.

        For tool/skill execution, the resource is the tool/skill name.
        For other actions, the resource is the target agent.
        """
        if message.action in ("forge.execute_tool", "forge.execute_skill"):
            name = message.payload.get("tool_or_skill_name", "unknown")
            prefix = "tool" if "tool" in message.action else "skill"
            return f"{prefix}:{name}"
        return f"agent:{message.target_agent}"

    def intercept(self, message: AegisMessage) -> WardenResponse:
        """
        Intercept and authorize a message.

        This is the primary entry point for message authorization.
        Every message in the system should pass through this method.

        Args:
            message: The AegisMessage to authorize.

        Returns:
            WardenResponse with the authorization verdict.
        """
        start_time = time.perf_counter()
        self._total_evaluated += 1

        # Check passthrough conditions
        if self._is_passthrough(message):
            self._total_allowed += 1
            return WardenResponse(
                verdict=WardenVerdict.ALLOW,
                reason="Message qualifies for passthrough (system/response/internal).",
                policy_applied="passthrough",
            )

        # Check emergency bypass mode
        if self._bypass_manager.is_active:
            bypass_response = self._bypass_manager.evaluate_bypass(
                user_id=message.user_id,
                tenant_id=message.tenant_id,
                action=message.action,
            )
            if bypass_response.verdict == WardenVerdict.ALLOW:
                self._total_bypassed += 1
                self._total_allowed += 1
                return bypass_response

        # Resolve user permissions
        user_permissions = self._resolve_permissions(
            message.tenant_id, message.user_id
        )

        # Special handling for shell commands
        if self._is_shell_command(message):
            command_string = message.payload.get("parameters", {}).get("command", "")
            is_root = "*" in user_permissions
            is_admin = "system.config" in user_permissions
            response = self._allowlist_engine.evaluate(
                command_string=command_string,
                user_id=message.user_id,
                is_root=is_root,
                is_admin=is_admin,
                context=message.metadata,
            )
        else:
            # Standard RBAC evaluation
            resource = self._extract_resource(message)
            response = self._permission_model.evaluate(
                action=message.action,
                resource=resource,
                user_permissions=user_permissions,
                user_id=message.user_id,
                context=message.payload,
            )

        # Update metrics
        if response.verdict == WardenVerdict.ALLOW:
            self._total_allowed += 1
        elif response.verdict == WardenVerdict.DENY:
            self._total_denied += 1
        elif response.verdict == WardenVerdict.ESCALATE:
            self._total_escalated += 1

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.debug(
            "Intercept complete",
            extra={
                "message_id": message.message_id,
                "action": message.action,
                "verdict": response.verdict.value,
                "elapsed_ms": round(elapsed_ms, 2),
            },
        )

        return response

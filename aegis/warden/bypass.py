# aegis/warden/bypass.py
"""
Emergency Bypass Manager.
Implements: Part XIII, RT-4 — Warden SPOF Mitigation

Emergency bypass mode is available to root user only during Warden
recovery scenarios. All bypass operations are logged to Observer.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Optional

from aegis.schemas.warden import WardenVerdict, WardenResponse

logger = logging.getLogger(__name__)


class BypassManager:
    """
    Manages the emergency bypass mode for the Warden.

    When the Warden is recovering from a crash or restart, the bypass
    mode allows root users to continue operating while security is
    being restored. All bypass operations are logged for audit.

    Constraints:
        - Only root users can activate bypass mode.
        - Only root users can operate under bypass mode.
        - Bypass mode has a maximum TTL (auto-deactivates).
        - All bypass operations are logged at WARNING level.
    """

    DEFAULT_BYPASS_TTL_SECONDS: int = 300  # 5 minutes max

    def __init__(self, max_ttl_seconds: int = DEFAULT_BYPASS_TTL_SECONDS):
        """
        Initialize the bypass manager.

        Args:
            max_ttl_seconds: Maximum time bypass mode can remain active.
        """
        self._active: bool = False
        self._activated_at: Optional[float] = None
        self._activated_by: Optional[str] = None
        self._max_ttl: int = max_ttl_seconds
        self._operations_count: int = 0
        self._activation_reason: Optional[str] = None

        logger.info(
            "BypassManager initialized",
            extra={"max_ttl_seconds": max_ttl_seconds},
        )

    @property
    def is_active(self) -> bool:
        """
        Check if bypass mode is currently active.

        Automatically deactivates if TTL has expired.
        """
        if self._active and self._activated_at:
            elapsed = time.time() - self._activated_at
            if elapsed >= self._max_ttl:
                logger.warning(
                    "Bypass mode auto-deactivated (TTL expired)",
                    extra={
                        "elapsed_seconds": round(elapsed, 1),
                        "max_ttl": self._max_ttl,
                        "operations_during_bypass": self._operations_count,
                    },
                )
                self._deactivate()
                return False
        return self._active

    @property
    def status(self) -> dict:
        """Return the current bypass status."""
        return {
            "active": self.is_active,
            "activated_at": (
                datetime.fromtimestamp(self._activated_at, tz=timezone.utc).isoformat()
                if self._activated_at
                else None
            ),
            "activated_by": self._activated_by,
            "reason": self._activation_reason,
            "operations_count": self._operations_count,
            "ttl_remaining_seconds": (
                max(0, self._max_ttl - (time.time() - self._activated_at))
                if self._active and self._activated_at
                else 0
            ),
        }

    def activate(
        self,
        user_id: str,
        is_root: bool,
        reason: str = "Emergency bypass activated",
    ) -> WardenResponse:
        """
        Activate emergency bypass mode.

        Args:
            user_id: The user requesting activation.
            is_root: Whether the user has root privileges.
            reason: The reason for activation.

        Returns:
            WardenResponse confirming or denying activation.
        """
        if not is_root:
            logger.warning(
                "Non-root user attempted bypass activation",
                extra={"user_id": user_id},
            )
            return WardenResponse(
                verdict=WardenVerdict.DENY,
                reason="Only root users can activate emergency bypass mode.",
                policy_applied="bypass_root_only",
            )

        self._active = True
        self._activated_at = time.time()
        self._activated_by = user_id
        self._activation_reason = reason
        self._operations_count = 0

        logger.warning(
            "EMERGENCY BYPASS MODE ACTIVATED",
            extra={
                "user_id": user_id,
                "reason": reason,
                "max_ttl_seconds": self._max_ttl,
            },
        )

        return WardenResponse(
            verdict=WardenVerdict.ALLOW,
            reason=f"Emergency bypass activated. TTL: {self._max_ttl}s. Reason: {reason}",
            policy_applied="bypass_activated",
        )

    def deactivate(self, user_id: str, is_root: bool) -> WardenResponse:
        """
        Manually deactivate emergency bypass mode.

        Args:
            user_id: The user requesting deactivation.
            is_root: Whether the user has root privileges.

        Returns:
            WardenResponse confirming deactivation.
        """
        if not is_root:
            return WardenResponse(
                verdict=WardenVerdict.DENY,
                reason="Only root users can deactivate emergency bypass mode.",
                policy_applied="bypass_root_only",
            )

        ops = self._operations_count
        self._deactivate()

        logger.warning(
            "EMERGENCY BYPASS MODE DEACTIVATED",
            extra={"user_id": user_id, "operations_during_bypass": ops},
        )

        return WardenResponse(
            verdict=WardenVerdict.ALLOW,
            reason=f"Emergency bypass deactivated. {ops} operations were performed during bypass.",
            policy_applied="bypass_deactivated",
        )

    def _deactivate(self) -> None:
        """Internal deactivation logic."""
        self._active = False
        self._activated_at = None
        self._activated_by = None
        self._activation_reason = None
        self._operations_count = 0

    def evaluate_bypass(
        self,
        user_id: str,
        tenant_id: str,
        action: str,
    ) -> WardenResponse:
        """
        Evaluate whether a request should be allowed under bypass mode.

        Only root users can operate under bypass. All bypass operations
        are logged at WARNING level for audit trail.

        Args:
            user_id: The requesting user.
            tenant_id: The tenant context.
            action: The action being requested.

        Returns:
            WardenResponse — ALLOW if root user during bypass, DENY otherwise.
        """
        if not self.is_active:
            return WardenResponse(
                verdict=WardenVerdict.DENY,
                reason="Bypass mode is not active.",
                policy_applied="bypass_inactive",
            )

        # During bypass, only the activating root user gets access
        # In a full system, we'd check is_root via Identity Agent
        # For now, we allow the activating user and log everything
        if user_id == self._activated_by:
            self._operations_count += 1
            logger.warning(
                "BYPASS: Operation allowed under emergency bypass",
                extra={
                    "user_id": user_id,
                    "tenant_id": tenant_id,
                    "action": action,
                    "operation_number": self._operations_count,
                },
            )
            return WardenResponse(
                verdict=WardenVerdict.ALLOW,
                reason=f"Allowed under emergency bypass (operation #{self._operations_count}).",
                policy_applied="bypass_root_allow",
            )
        else:
            logger.warning(
                "BYPASS: Non-activating user denied during bypass",
                extra={"user_id": user_id, "action": action},
            )
            return WardenResponse(
                verdict=WardenVerdict.DENY,
                reason="Only the root user who activated bypass can operate during bypass mode.",
                policy_applied="bypass_non_root_deny",
            )

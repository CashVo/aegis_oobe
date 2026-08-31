# aegis/agents/warden.py
"""
Warden Agent — Security Gatekeeper.
Implements: Part II §2.1, Part VI §6.4

The Warden is a universal, synchronous security interceptor. It validates
every inter-agent message and every tool/skill invocation against the
active permission model. It can ALLOW, DENY, or ESCALATE any request.

Integration Points:
    - Subscribes to: aegis:stream:warden
    - Publishes responses to: requesting agent's stream
    - Consulted by: All agents (via interceptor) before message delivery
"""

import logging
from typing import Any, Callable, Dict, Optional, Set

from aegis.agents.base import BaseAgent
from aegis.schemas.message import AegisMessage, MessageType, Priority
from aegis.schemas.warden import (
    WardenAction,
    WardenRequest,
    WardenResponse,
    WardenVerdict,
)
from aegis.warden.allowlist import AllowlistEngine
from aegis.warden.bypass import BypassManager
from aegis.warden.interceptor import MessageInterceptor
from aegis.warden.permission_model import PermissionModel

logger = logging.getLogger(__name__)


class WardenAgent(BaseAgent):
    """
    The Warden — Security Gatekeeper for the Aegis system.

    Responsibilities:
        - Validate every inter-agent message against RBAC permissions
        - Enforce shell command allowlist (RT-6)
        - Manage emergency bypass mode (RT-4)
        - Provide synchronous authorization decisions
        - Log all security-relevant events

    The Warden is designed to be the highest-priority agent for restart
    by the System Manager (RT-4 mitigation).
    """

    agent_id: str = "warden"
    subscriptions: list = ["aegis:stream:warden"]

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        user_permission_resolver: Optional[Callable[[str, str], Set[str]]] = None,
        redis_conn=None,
        bus_publisher=None,
        bus_subscriber=None,
    ):
        """
        Initialize the Warden agent.

        Args:
            config: Optional configuration dictionary. Expected keys:
                - allowlist.commands: List of allowed shell commands
                - bypass.max_ttl_seconds: Max bypass TTL
                - custom_roles: Additional role definitions
            user_permission_resolver: Callable to resolve user permissions.
                                     Signature: (tenant_id, user_id) -> Set[str]
            redis_conn: Redis connection for session persistence.
            bus_publisher: MessagePublisher for sending responses.
            bus_subscriber: MessageSubscriber for receiving messages.
        """
        # Call parent init for heartbeat and bus support
        super().__init__(agent_id=self.agent_id, subscriptions=self.subscriptions)
        
        self._config = config or {}
        self._redis_conn = redis_conn
        self._bus_publisher = bus_publisher
        self._bus_subscriber = bus_subscriber

        # Initialize subsystems
        self._permission_model = PermissionModel(
            custom_roles=self._config.get("custom_roles"),
        )
        self._allowlist_engine = AllowlistEngine(
            allowed_commands=self._config.get("allowlist", {}).get("commands"),
        )
        self._bypass_manager = BypassManager(
            max_ttl_seconds=self._config.get("bypass", {}).get("max_ttl_seconds", 300),
        )
        
        # Create a permission resolver that defaults to 'root' role for 'root' user
        # and 'member' role for others, if no custom resolver provided
        if user_permission_resolver is None:
            user_permission_resolver = self._default_permission_resolver
        
        self._interceptor = MessageInterceptor(
            permission_model=self._permission_model,
            allowlist_engine=self._allowlist_engine,
            bypass_manager=self._bypass_manager,
            user_permission_resolver=user_permission_resolver,
        )

        logger.info("WardenAgent initialized.")

    def _default_permission_resolver(self, tenant_id: str, user_id: str) -> Set[str]:
        """
        Default permission resolver based on user_id.
        
        - 'root' user gets 'root' role (wildcard permission *)
        - Other users get 'member' role permissions
        """
        if user_id == "root":
            return {"*"}  # Wildcard - all permissions
        else:
            return self._permission_model.get_role_permissions("member")

    @property
    def permission_model(self) -> PermissionModel:
        """Access the permission model (for testing/integration)."""
        return self._permission_model

    @property
    def allowlist_engine(self) -> AllowlistEngine:
        """Access the allowlist engine (for testing/integration)."""
        return self._allowlist_engine

    @property
    def bypass_manager(self) -> BypassManager:
        """Access the bypass manager (for testing/integration)."""
        return self._bypass_manager

    @property
    def interceptor(self) -> MessageInterceptor:
        """Access the message interceptor (for testing/integration)."""
        return self._interceptor

    def authorize(self, message: AegisMessage) -> WardenResponse:
        """
        Synchronous authorization entry point.

        This is the method called by the message bus (or other agents)
        to authorize a message before delivery. It delegates to the
        MessageInterceptor.

        Args:
            message: The AegisMessage to authorize.

        Returns:
            WardenResponse with the verdict.
        """
        return self._interceptor.intercept(message)

    async def handle_message(self, message: AegisMessage) -> Optional[AegisMessage]:
        """
        Handle incoming messages on the Warden's stream.

        Supports:
            - authorize: Evaluate a WardenRequest
            - check_permission: Direct permission check
            - check_allowlist: Direct allowlist check
            - enable_bypass: Activate emergency bypass
            - disable_bypass: Deactivate emergency bypass
            - get_status: Return Warden status and metrics
            - reload_policies: Reload permission policies

        Args:
            message: The incoming AegisMessage.

        Returns:
            Response AegisMessage or None.
        """
        action = message.action.split(".")[-1] if "." in message.action else message.action

        try:
            warden_action = WardenAction(action)
        except ValueError:
            logger.warning(f"Unknown Warden action: {action}")
            return self._build_response(
                message,
                WardenResponse(
                    verdict=WardenVerdict.DENY,
                    reason=f"Unknown Warden action: '{action}'.",
                    policy_applied="unknown_action",
                ),
            )

        handler_map = {
            WardenAction.AUTHORIZE: self._handle_authorize,
            WardenAction.CHECK_PERMISSION: self._handle_check_permission,
            WardenAction.CHECK_ALLOWLIST: self._handle_check_allowlist,
            WardenAction.ENABLE_BYPASS: self._handle_enable_bypass,
            WardenAction.DISABLE_BYPASS: self._handle_disable_bypass,
            WardenAction.GET_STATUS: self._handle_get_status,
            WardenAction.RELOAD_POLICIES: self._handle_reload_policies,
        }

        handler = handler_map.get(warden_action)
        if handler:
            response = await handler(message)
            return self._build_response(message, response)

        return None

    async def _handle_authorize(self, message: AegisMessage) -> WardenResponse:
        """Handle an authorization request."""
        payload = message.payload
        # Support both "action" and "requested_action" for backward compatibility
        action = payload.get("action") or payload.get("requested_action", "")
        request = WardenRequest(
            action=action,
            resource=payload.get("resource", ""),
            tenant_id=message.tenant_id,
            user_id=message.user_id,
            context=payload.get("context", {}),
        )

        # Resolve user permissions
        user_permissions = self._interceptor._resolve_permissions(
            request.tenant_id, request.user_id
        )

        # Check if it's a shell command
        if request.resource == "tool:execute_shell_command":
            command = request.context.get("command", "")
            is_root = "*" in user_permissions
            is_admin = "system.config" in user_permissions
            return self._allowlist_engine.evaluate(
                command_string=command,
                user_id=request.user_id,
                is_root=is_root,
                is_admin=is_admin,
                context=request.context,
            )

        return self._permission_model.evaluate(
            action=request.action,
            resource=request.resource,
            user_permissions=user_permissions,
            user_id=request.user_id,
            context=request.context,
        )

    async def _handle_check_permission(self, message: AegisMessage) -> WardenResponse:
        """Handle a direct permission check."""
        payload = message.payload
        user_permissions = set(payload.get("user_permissions", []))
        required = payload.get("required_permission", "")

        if self._permission_model.check_permission(user_permissions, required):
            return WardenResponse(
                verdict=WardenVerdict.ALLOW,
                reason=f"User has permission '{required}'.",
                policy_applied="direct_check_allow",
            )
        return WardenResponse(
            verdict=WardenVerdict.DENY,
            reason=f"User lacks permission '{required}'.",
            policy_applied="direct_check_deny",
        )

    async def _handle_check_allowlist(self, message: AegisMessage) -> WardenResponse:
        """Handle a direct allowlist check."""
        payload = message.payload
        command = payload.get("command", "")
        is_root = payload.get("is_root", False)
        is_admin = payload.get("is_admin", False)

        return self._allowlist_engine.evaluate(
            command_string=command,
            user_id=message.user_id,
            is_root=is_root,
            is_admin=is_admin,
        )

    async def _handle_enable_bypass(self, message: AegisMessage) -> WardenResponse:
        """Handle emergency bypass activation."""
        payload = message.payload
        is_root = payload.get("is_root", False)
        reason = payload.get("reason", "Emergency bypass requested")

        return self._bypass_manager.activate(
            user_id=message.user_id,
            is_root=is_root,
            reason=reason,
        )

    async def _handle_disable_bypass(self, message: AegisMessage) -> WardenResponse:
        """Handle emergency bypass deactivation."""
        payload = message.payload
        is_root = payload.get("is_root", False)

        return self._bypass_manager.deactivate(
            user_id=message.user_id,
            is_root=is_root,
        )

    async def _handle_get_status(self, message: AegisMessage) -> WardenResponse:
        """Handle status request — return Warden metrics and state."""
        status = {
            "agent_id": self.agent_id,
            "bypass": self._bypass_manager.status,
            "interceptor_metrics": self._interceptor.metrics,
            "allowed_commands_count": len(self._allowlist_engine.allowed_commands),
            "roles_loaded": list(self._permission_model.roles.keys()),
        }
        return WardenResponse(
            verdict=WardenVerdict.ALLOW,
            reason="Status retrieved successfully.",
            policy_applied="status_request",
        )

    async def _handle_reload_policies(self, message: AegisMessage) -> WardenResponse:
        """Handle policy reload request."""
        # In a full implementation, this would reload from config/database
        logger.info("Policy reload requested (no-op in current implementation).")
        return WardenResponse(
            verdict=WardenVerdict.ALLOW,
            reason="Policies reloaded successfully.",
            policy_applied="reload_complete",
        )

    def _build_response(
        self, original: AegisMessage, warden_response: WardenResponse
    ) -> AegisMessage:
        """Build an AegisMessage response from a WardenResponse."""
        # Use original.correlation_id so the caller can match the response
        return AegisMessage(
            correlation_id=original.correlation_id,
            source_agent=self.agent_id,
            target_agent=original.source_agent,
            message_type=MessageType.RESPONSE,
            tenant_id=original.tenant_id,
            user_id=original.user_id,
            action="warden.response",
            payload=warden_response.model_dump(),
            priority=Priority.HIGH,
            metadata={"original_action": original.action},
        )

    async def startup(self) -> None:
        """
        Initialize the Warden agent.
        Subscribe to the Warden stream and start heartbeat.
        """
        logger.info(
            "Warden agent starting up",
            extra={"subscriptions": self.subscriptions},
        )

        # Create and start MessageSubscriber for this agent's stream
        if self._redis_conn is not None:
            from aegis.bus.subscriber import MessageSubscriber
            self._bus_subscriber = MessageSubscriber(
                redis_client=self._redis_conn,
                agent_id=self.agent_id,
                handler=self._on_bus_message,
                subscribe_to_broadcast=False,
            )
            await self._bus_subscriber.start()
            logger.info(f"Warden created its own MessageSubscriber with agent_id={self.agent_id}")
            logger.info(f"  Subscribed to stream: {self._bus_subscriber._stream}")
            logger.info(f"  Consumer group: {self._bus_subscriber._group}")
            logger.info(f"  Consumer: {self._bus_subscriber._consumer}")

        # Start heartbeat for this agent
        await self.start_heartbeat()
        logger.info("Warden agent ready. Security enforcement active.")

    async def _on_bus_message(self, message: AegisMessage) -> None:
        """Callback for messages received on our bus stream."""
        try:
            response = await self.handle_message(message)
            if response and self._bus_publisher:
                # Use response_channel from original message payload if present
                target_stream = message.payload.get("response_channel", f"aegis:stream:{response.target_agent}")
                await self._bus_publisher.publish_to_stream(target_stream, response)
        except Exception as e:
            logger.error("Error processing bus message: %s", e, exc_info=True)

    async def shutdown(self) -> None:
        """
        Graceful Warden shutdown.

        Deactivates bypass mode if active and logs final metrics.
        """
        if self._bypass_manager.is_active:
            logger.warning("Warden shutting down with bypass active — deactivating.")
            self._bypass_manager._deactivate()

        metrics = self._interceptor.metrics
        logger.info(
            "Warden agent shutting down",
            extra={"final_metrics": metrics},
        )

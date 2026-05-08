# aegis/agents/identity/agent.py
# Implements: Part II, §2.1 — Identity Agent (Council Roster)
# Implements: Part V, §5.3 — Identity Agent Protocol
# Implements: Part II, §2.3 — Agent Base Class

"""
IdentityAgent — Manages the full lifecycle of Tenants, Users, and Roles.

This is a council-level agent that:
- Subscribes to aegis:stream:identity
- Handles all IdentityAction requests
- Is the source of truth for auth data consumed by Warden
- Follows the BaseAgent ABC contract
"""

import logging
from typing import Any, Dict, Optional

from aegis.agents.base import BaseAgent
from aegis.identity.store import IdentityStore
from aegis.identity.bootstrap import IdentityBootstrap
from aegis.schemas.identity import (
    IdentityAction,
    IdentityRequest,
    IdentityResponse,
)
from aegis.schemas.message import AegisMessage, MessageType, Priority

logger = logging.getLogger(__name__)


class IdentityAgent(BaseAgent):
    """
    The Identity Agent — Council member responsible for IAM.

    Manages Tenant, User, and Role lifecycle. Source of truth for
    authentication and authorization data consumed by the Warden.
    """

    agent_id: str = "identity"
    subscriptions: list = ["aegis:stream:identity"]

    def __init__(self, store: IdentityStore):
        """
        Initialize the Identity Agent.

        Args:
            store: The IdentityStore instance for persistence.
        """
        self._store = store
        self._bootstrap = IdentityBootstrap(store)
        self._action_handlers = {
            IdentityAction.CREATE_TENANT: self._handle_create_tenant,
            IdentityAction.CREATE_USER: self._handle_create_user,
            IdentityAction.UPDATE_USER: self._handle_update_user,
            IdentityAction.DELETE_USER: self._handle_delete_user,
            IdentityAction.ASSIGN_ROLE: self._handle_assign_role,
            IdentityAction.CREATE_ROLE: self._handle_create_role,
            IdentityAction.LIST_USERS: self._handle_list_users,
            IdentityAction.LIST_TENANTS: self._handle_list_tenants,
            IdentityAction.LIST_ROLES: self._handle_list_roles,
            IdentityAction.GET_USER: self._handle_get_user,
            IdentityAction.GET_TENANT: self._handle_get_tenant,
            IdentityAction.AUTHENTICATE: self._handle_authenticate,
        }

    async def startup(self) -> None:
        """Initialize the Identity Agent — open store, check bootstrap."""
        await self._store.initialize()
        logger.info(f"IdentityAgent [{self.agent_id}] started.")
        logger.info(f"  Subscriptions: {self.subscriptions}")

        # Check if bootstrap is needed (first-run detection)
        if await self._bootstrap.needs_bootstrap():
            logger.warning(
                "Identity store is empty — bootstrap required. "
                "Awaiting bootstrap command from System Manager."
            )

    async def shutdown(self) -> None:
        """Graceful shutdown — close the store."""
        await self._store.close()
        logger.info(f"IdentityAgent [{self.agent_id}] shut down.")

    async def handle_message(self, message: AegisMessage) -> Optional[AegisMessage]:
        """
        Process an incoming AegisMessage and route to the appropriate handler.

        Args:
            message: The incoming AegisMessage with action="identity.*"

        Returns:
            A response AegisMessage, or None if no response needed.
        """
        try:
            # Parse the IdentityRequest from the message payload
            request = IdentityRequest(
                action=IdentityAction(message.payload.get("action", "")),
                tenant_id=message.payload.get("tenant_id", message.tenant_id),
                user_id=message.payload.get("user_id", message.user_id),
                payload=message.payload.get("payload", {}),
            )
        except (ValueError, KeyError) as e:
            return self._error_response(
                message,
                action_str=message.payload.get("action", "unknown"),
                error=f"Invalid request: {str(e)}",
            )

        # Route to handler
        handler = self._action_handlers.get(request.action)
        if not handler:
            return self._error_response(
                message,
                action_str=request.action.value,
                error=f"Unknown action: {request.action.value}",
            )

        try:
            response = await handler(request)
        except ValueError as e:
            response = IdentityResponse(
                success=False,
                action=request.action,
                error=str(e),
            )
        except Exception as e:
            logger.exception(f"Unhandled error in action {request.action.value}")
            response = IdentityResponse(
                success=False,
                action=request.action,
                error=f"Internal error: {str(e)}",
            )

        # Wrap response in AegisMessage envelope
        return AegisMessage(
            correlation_id=message.message_id,
            source_agent=self.agent_id,
            target_agent=message.source_agent,
            message_type=MessageType.RESPONSE,
            tenant_id=message.tenant_id,
            user_id=message.user_id,
            action=f"identity.{request.action.value}.response",
            payload=response.model_dump(),
            priority=message.priority,
            metadata={"correlation_id": message.message_id},
        )

    # ─────────────────────────────────────────────
    # ACTION HANDLERS
    # ─────────────────────────────────────────────

    async def _handle_create_tenant(
        self, request: IdentityRequest
    ) -> IdentityResponse:
        """Handle CREATE_TENANT action."""
        name = request.payload.get("name")
        if not name:
            return IdentityResponse(
                success=False,
                action=request.action,
                error="Payload must include 'name' for tenant creation.",
            )

        tenant = await self._store.create_tenant(name=name)
        return IdentityResponse(
            success=True,
            action=request.action,
            data=tenant.model_dump(mode="json"),
        )

    async def _handle_create_user(
        self, request: IdentityRequest
    ) -> IdentityResponse:
        """Handle CREATE_USER action."""
        payload = request.payload
        required = ["username", "display_name"]
        for field in required:
            if field not in payload:
                return IdentityResponse(
                    success=False,
                    action=request.action,
                    error=f"Payload must include '{field}'.",
                )

        if not request.tenant_id:
            return IdentityResponse(
                success=False,
                action=request.action,
                error="tenant_id is required for user creation.",
            )

        user = await self._store.create_user(
            tenant_id=request.tenant_id,
            username=payload["username"],
            display_name=payload["display_name"],
            role_name=payload.get("role_name", "member"),
            email=payload.get("email"),
            is_root=payload.get("is_root", False),
            passphrase=payload.get("passphrase"),
        )
        return IdentityResponse(
            success=True,
            action=request.action,
            data=user.model_dump(mode="json"),
        )

    async def _handle_update_user(
        self, request: IdentityRequest
    ) -> IdentityResponse:
        """Handle UPDATE_USER action."""
        target_user_id = request.payload.get("target_user_id")
        updates = request.payload.get("updates", {})

        if not target_user_id:
            return IdentityResponse(
                success=False,
                action=request.action,
                error="Payload must include 'target_user_id'.",
            )

        user = await self._store.update_user(target_user_id, updates)
        if not user:
            return IdentityResponse(
                success=False,
                action=request.action,
                error=f"User '{target_user_id}' not found.",
            )
        return IdentityResponse(
            success=True,
            action=request.action,
            data=user.model_dump(mode="json"),
        )

    async def _handle_delete_user(
        self, request: IdentityRequest
    ) -> IdentityResponse:
        """Handle DELETE_USER action."""
        target_user_id = request.payload.get("target_user_id")
        if not target_user_id:
            return IdentityResponse(
                success=False,
                action=request.action,
                error="Payload must include 'target_user_id'.",
            )

        deleted = await self._store.delete_user(target_user_id)
        if not deleted:
            return IdentityResponse(
                success=False,
                action=request.action,
                error=f"User '{target_user_id}' not found.",
            )
        return IdentityResponse(
            success=True,
            action=request.action,
            data={"deleted_user_id": target_user_id},
        )

    async def _handle_assign_role(
        self, request: IdentityRequest
    ) -> IdentityResponse:
        """Handle ASSIGN_ROLE action."""
        target_user_id = request.payload.get("target_user_id")
        role_name = request.payload.get("role_name")

        if not target_user_id or not role_name:
            return IdentityResponse(
                success=False,
                action=request.action,
                error="Payload must include 'target_user_id' and 'role_name'.",
            )

        user = await self._store.assign_role(target_user_id, role_name)
        if not user:
            return IdentityResponse(
                success=False,
                action=request.action,
                error=f"User '{target_user_id}' not found or role invalid.",
            )
        return IdentityResponse(
            success=True,
            action=request.action,
            data=user.model_dump(mode="json"),
        )

    async def _handle_create_role(
        self, request: IdentityRequest
    ) -> IdentityResponse:
        """Handle CREATE_ROLE action."""
        payload = request.payload
        if not request.tenant_id:
            return IdentityResponse(
                success=False,
                action=request.action,
                error="tenant_id is required for role creation.",
            )
        if "name" not in payload or "permissions" not in payload:
            return IdentityResponse(
                success=False,
                action=request.action,
                error="Payload must include 'name' and 'permissions'.",
            )

        role = await self._store.create_role(
            tenant_id=request.tenant_id,
            name=payload["name"],
            permissions=payload["permissions"],
            is_system_role=payload.get("is_system_role", False),
        )
        return IdentityResponse(
            success=True,
            action=request.action,
            data=role.model_dump(mode="json"),
        )

    async def _handle_list_users(
        self, request: IdentityRequest
    ) -> IdentityResponse:
        """Handle LIST_USERS action."""
        if not request.tenant_id:
            return IdentityResponse(
                success=False,
                action=request.action,
                error="tenant_id is required.",
            )
        users = await self._store.list_users(request.tenant_id)
        return IdentityResponse(
            success=True,
            action=request.action,
            data={"users": [u.model_dump(mode="json") for u in users]},
        )

    async def _handle_list_tenants(
        self, request: IdentityRequest
    ) -> IdentityResponse:
        """Handle LIST_TENANTS action."""
        tenants = await self._store.list_tenants()
        return IdentityResponse(
            success=True,
            action=request.action,
            data={"tenants": [t.model_dump(mode="json") for t in tenants]},
        )

    async def _handle_list_roles(
        self, request: IdentityRequest
    ) -> IdentityResponse:
        """Handle LIST_ROLES action."""
        if not request.tenant_id:
            return IdentityResponse(
                success=False,
                action=request.action,
                error="tenant_id is required.",
            )
        roles = await self._store.list_roles(request.tenant_id)
        return IdentityResponse(
            success=True,
            action=request.action,
            data={"roles": [r.model_dump(mode="json") for r in roles]},
        )

    async def _handle_get_user(
        self, request: IdentityRequest
    ) -> IdentityResponse:
        """Handle GET_USER action."""
        target_user_id = request.payload.get("target_user_id")
        if not target_user_id:
            return IdentityResponse(
                success=False,
                action=request.action,
                error="Payload must include 'target_user_id'.",
            )
        user = await self._store.get_user(target_user_id)
        if not user:
            return IdentityResponse(
                success=False,
                action=request.action,
                error=f"User '{target_user_id}' not found.",
            )
        return IdentityResponse(
            success=True,
            action=request.action,
            data=user.model_dump(mode="json"),
        )

    async def _handle_get_tenant(
        self, request: IdentityRequest
    ) -> IdentityResponse:
        """Handle GET_TENANT action."""
        if not request.tenant_id:
            return IdentityResponse(
                success=False,
                action=request.action,
                error="tenant_id is required.",
            )
        tenant = await self._store.get_tenant(request.tenant_id)
        if not tenant:
            return IdentityResponse(
                success=False,
                action=request.action,
                error=f"Tenant '{request.tenant_id}' not found.",
            )
        return IdentityResponse(
            success=True,
            action=request.action,
            data=tenant.model_dump(mode="json"),
        )

    async def _handle_authenticate(
        self, request: IdentityRequest
    ) -> IdentityResponse:
        """Handle AUTHENTICATE action — session token issuance."""
        payload = request.payload
        if not request.tenant_id:
            return IdentityResponse(
                success=False,
                action=request.action,
                error="tenant_id is required for authentication.",
            )
        username = payload.get("username")
        passphrase = payload.get("passphrase", "")

        if not username:
            return IdentityResponse(
                success=False,
                action=request.action,
                error="Payload must include 'username'.",
            )

        user = await self._store.authenticate(
            request.tenant_id, username, passphrase
        )
        if not user:
            return IdentityResponse(
                success=False,
                action=request.action,
                error="Authentication failed: invalid credentials.",
            )

        # Get permissions for session context
        permissions = await self._store.get_user_permissions(user.user_id)

        return IdentityResponse(
            success=True,
            action=request.action,
            data={
                "user": user.model_dump(mode="json"),
                "permissions": permissions,
                "session_context": {
                    "tenant_id": user.tenant_id,
                    "user_id": user.user_id,
                    "role_id": user.role_id,
                    "is_root": user.is_root,
                },
            },
        )

    # ─────────────────────────────────────────────
    # BOOTSTRAP ACCESS (for System Manager)
    # ─────────────────────────────────────────────

    async def needs_bootstrap(self) -> bool:
        """Check if the identity store requires first-run bootstrap."""
        return await self._bootstrap.needs_bootstrap()

    async def run_bootstrap(
        self,
        root_username: str = "root",
        root_display_name: str = "System Root",
        root_passphrase: Optional[str] = None,
        tenant_name: str = "Default",
    ) -> Dict[str, Any]:
        """
        Execute the bootstrap sequence. Called by System Manager only.

        Returns:
            Dict with tenant and root_user data.
        """
        tenant, root_user = await self._bootstrap.execute(
            root_username=root_username,
            root_display_name=root_display_name,
            root_passphrase=root_passphrase,
            tenant_name=tenant_name,
        )
        return {
            "tenant": tenant.model_dump(mode="json"),
            "root_user": root_user.model_dump(mode="json"),
        }

    # ─────────────────────────────────────────────
    # UTILITIES
    # ─────────────────────────────────────────────

    def _error_response(
        self, original_msg: AegisMessage, action_str: str, error: str
    ) -> AegisMessage:
        """Build an error AegisMessage response."""
        return AegisMessage(
            correlation_id=original_msg.message_id,
            source_agent=self.agent_id,
            target_agent=original_msg.source_agent,
            message_type=MessageType.ERROR,
            tenant_id=original_msg.tenant_id,
            user_id=original_msg.user_id,
            action=f"identity.{action_str}.error",
            payload={
                "success": False,
                "action": action_str,
                "error": error,
            },
            priority=original_msg.priority,
        )

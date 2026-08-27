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
import os
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
from aegis.bus.constants import CONSUMER_GROUP_PREFIX

logger = logging.getLogger(__name__)


class IdentityAgent(BaseAgent):
    """
    The Identity Agent — Council member responsible for IAM.

    Manages Tenant, User, and Role lifecycle. Source of truth for
    authentication and authorization data consumed by the Warden.
    """

    agent_id: str = "identity"
    subscriptions: list = ["aegis:stream:identity"]

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        redis_conn: Optional[Any] = None,
        bus_publisher: Optional[Any] = None,
        bus_subscriber: Optional[Any] = None,
        store: Optional[IdentityStore] = None,
    ):
        """
        Initialize the Identity Agent.

        Args:
            config: Optional configuration dict. Expected keys:
                - data_dir: Base directory for data storage (default: aegis_data)
            redis_conn: Optional Redis connection (not used directly, but accepted for compatibility)
            bus_publisher: Optional MessagePublisher for sending responses
            bus_subscriber: Optional MessageSubscriber for subscribing to streams
            store: Optional pre-created IdentityStore instance. If not provided, one will be created from config.
        """
        # Call parent init for heartbeat and bus support
        super().__init__(agent_id=self.agent_id, subscriptions=self.subscriptions)
        
        self._config = config or {}
        self._bus_publisher = bus_publisher
        self._bus_subscriber = bus_subscriber
        self._redis_conn = redis_conn
        
        # Determine data directory from config
        data_dir = self._config.get("data_dir", "aegis_data")
        db_path = os.path.join(data_dir, "identity.db")
        
        # Create or use provided store
        if store is not None:
            self._store = store
        else:
            self._store = IdentityStore(db_path=db_path)
            
        self._bootstrap = IdentityBootstrap(self._store)
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
            IdentityAction.RUN_BOOTSTRAP: self._handle_run_bootstrap,
        }

    async def startup(self) -> None:
        """Initialize the Identity Agent — open store, check bootstrap, subscribe to bus."""
        await self._store.initialize()
        logger.info(f"IdentityAgent [{self.agent_id}] started.")
        logger.info(f"  Subscriptions: {self.subscriptions}")

        # Clean up legacy consumer group that was created by old subscribe() method
        # This group (aegis:group:identity:aegis_stream_identity) was created by old code
        # and splits message delivery without a handler
        if self._redis_conn is not None:
            legacy_group = f"{CONSUMER_GROUP_PREFIX}{self.agent_id}:aegis_stream_{self.agent_id}"
            stream_name = f"aegis:stream:{self.agent_id}"
            try:
                await self._redis_conn.xgroup_destroy(stream_name, legacy_group)
                logger.info(f"Cleaned up legacy consumer group '{legacy_group}' on '{stream_name}'")
            except Exception as e:
                logger.debug(f"Legacy group cleanup skipped (may not exist): {e}")
        # Start heartbeat for this agent
        await self.start_heartbeat()

        # Always create our own MessageSubscriber for our agent_id to ensure correct consumer groups
        if self._redis_conn is not None:
            from aegis.bus.subscriber import MessageSubscriber
            self._bus_subscriber = MessageSubscriber(
                redis_client=self._redis_conn,
                agent_id=self.agent_id,
                handler=self._on_bus_message,
                subscribe_to_broadcast=False,
            )
            # Start the subscriber FIRST (it subscribes to our main stream)
            await self._bus_subscriber.start()
            logger.info(f"IdentityAgent created its own MessageSubscriber with agent_id={self.agent_id}")
            logger.info(f"  Subscribed to stream: {self._bus_subscriber._stream}")
            logger.info(f"  Consumer group: {self._bus_subscriber._group}")
            logger.info(f"  Consumer: {self._bus_subscriber._consumer}")

            # Now subscribe to additional channels (after start so _running is True)
            # Skip the main stream since we're already subscribed via the subscriber
            main_stream = self._bus_subscriber._stream
            if self._bus_subscriber:
                for channel in self.subscriptions:
                    if channel == main_stream:
                        logger.debug(f"Skipping subscription to main stream '{channel}' (already subscribed)")
                        continue
                    await self._bus_subscriber.subscribe(channel, self._on_bus_message)
                logger.info(f"IdentityAgent subscribed to additional channels: {[c for c in self.subscriptions if c != main_stream]}")

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

    async def _on_bus_message(self, message: AegisMessage | dict[str, Any]) -> None:
        """Callback for messages received on our bus stream."""
        # Handle both AegisMessage and dict (from subscriber)
        if isinstance(message, dict):
            message = AegisMessage(**message)
        logger.info(f"IdentityAgent._on_bus_message received: action={message.action}, tenant={message.tenant_id}, user={message.user_id}, metadata={message.metadata}")
        try:
            response = await self.handle_message(message)
            # handle_message returns None if it already published to response_channel
            if response and self._bus_publisher:
                logger.info(f"Publishing response for correlation_id={response.correlation_id}")
                await self._bus_publisher.publish(response)
            elif response is None:
                logger.info(f"handle_message returned None (already published to response_channel)")
            else:
                logger.warning(f"handle_message returned response but no bus_publisher available")
        except Exception as e:
            logger.error(f"Error processing bus message: {e}", exc_info=True)

    async def handle_message(self, message: AegisMessage) -> Optional[AegisMessage]:
        """
        Process an incoming AegisMessage and route to the appropriate handler.

        Args:
            message: The incoming AegisMessage with action="identity.*"

        Returns:
            A response AegisMessage, or None if no response needed.
        """
        logger.info(f"IdentityAgent.handle_message called with action={message.action}, tenant={message.tenant_id}, user={message.user_id}, metadata={message.metadata}")
        try:
            # Parse the IdentityRequest from the message
            # The action is in message.action (e.g., "identity.run_bootstrap")
            action_str = message.action
            if action_str.startswith("identity."):
                action_str = action_str[len("identity."):]
            
            request = IdentityRequest(
                action=IdentityAction(action_str),
                tenant_id=message.payload.get("tenant_id", message.tenant_id),
                user_id=message.payload.get("user_id", message.user_id),
                payload=message.payload,
            )
            logger.info(f"Parsed IdentityRequest: action={request.action}, tenant_id={request.tenant_id}, user_id={request.user_id}")
        except (ValueError, KeyError) as e:
            return self._error_response(
                message,
                action_str=message.action,
                error=f"Invalid request: {str(e)}",
            )

        # Route to handler
        handler = self._action_handlers.get(request.action)
        logger.info(f"Routing to handler for action: {request.action}, handler: {handler}")
        if not handler:
            logger.error(f"No handler found for action: {request.action}")
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
        # Check if there's a response_channel in metadata for request-response pattern
        response_channel = message.metadata.get("response_channel") if message.metadata else None
        
        response_msg = AegisMessage(
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
        
        # If there's a response_channel, publish directly to it using the bus publisher
        if response_channel and self._bus_publisher:
            try:
                logger.info(f"Publishing bootstrap response to response_channel: {response_channel}")
                result = await self._bus_publisher.publish_to_stream(response_channel, response_msg)
                logger.info(f"Successfully published bootstrap response to response_channel: {response_channel}, entry_id={result}")
            except Exception as e:
                logger.error(f"Failed to publish to response_channel {response_channel}: {e}", exc_info=True)
            return None  # Don't return the message since we published it directly
        
        return response_msg

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

    async def _handle_run_bootstrap(self, request: IdentityRequest) -> IdentityResponse:
        """Handle RUN_BOOTSTRAP action — first-run initialization."""
        logger.info(f"Handling RUN_BOOTSTRAP request: {request.payload}")
        payload = request.payload
        root_username = payload.get("root_username", "root")
        root_display_name = payload.get("root_display_name", "System Root")
        root_passphrase = payload.get("root_passphrase")
        tenant_name = payload.get("tenant_name", "Default")

        try:
            result = await self.run_bootstrap(
                root_username=root_username,
                root_display_name=root_display_name,
                root_passphrase=root_passphrase,
                tenant_name=tenant_name,
            )
            logger.info(f"Bootstrap completed successfully: {result}")
            
            response = IdentityResponse(
                success=True,
                action=IdentityAction.RUN_BOOTSTRAP,
                data=result,
            )
            logger.info(f"Returning bootstrap response: {response.model_dump()}")
            return response
        except RuntimeError as e:
            return IdentityResponse(
                success=False,
                action=IdentityAction.RUN_BOOTSTRAP,
                error=str(e),
            )
        except Exception as e:
            logger.exception("Bootstrap execution failed")
            return IdentityResponse(
                success=False,
                action=IdentityAction.RUN_BOOTSTRAP,
                error=f"Bootstrap failed: {str(e)}",
            )

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

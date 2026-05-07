# aegis/warden/permission_model.py
"""
Permission Model — Role-Based Access Control Engine.
Implements: Part V §5.2 (Default Roles), Part VI §6.4 (Warden Protocol)

Evaluates whether a user (identified by role and permissions) is authorized
to perform a given action on a given resource.
"""

import logging
from typing import Any, Dict, List, Optional, Set

from aegis.schemas.warden import WardenVerdict, WardenResponse

logger = logging.getLogger(__name__)


class PermissionDeniedError(Exception):
    """Raised when a user lacks the required permissions for an action."""

    def __init__(self, user_id: str, action: str, resource: str, reason: str = ""):
        self.user_id = user_id
        self.action = action
        self.resource = resource
        self.reason = reason
        super().__init__(
            f"Permission denied for user '{user_id}' on action '{action}' "
            f"resource '{resource}': {reason}"
        )


# Default role definitions per Part V §5.2
DEFAULT_ROLES: Dict[str, Dict[str, Any]] = {
    "root": {
        "permissions": ["*"],
        "is_system_role": True,
        "description": "Full system access. All permissions granted.",
    },
    "admin": {
        "permissions": [
            "user.create", "user.update", "user.delete",
            "role.assign",
            "memory.read", "memory.write",
            "tool.execute", "skill.execute",
            "system.config",
        ],
        "is_system_role": True,
        "description": "Administrative access. User and system management.",
    },
    "member": {
        "permissions": [
            "memory.read", "memory.write.own",
            "tool.execute", "skill.execute", "file.read",
        ],
        "is_system_role": True,
        "description": "Standard user access. Can use tools and manage own memory.",
    },
    "observer": {
        "permissions": [
            "memory.read.own",
        ],
        "is_system_role": True,
        "description": "Read-only access to own memory.",
    },
}

# Maps action prefixes to required permission prefixes
ACTION_PERMISSION_MAP: Dict[str, str] = {
    "forge.execute_tool": "tool.execute",
    "forge.execute_skill": "skill.execute",
    "forge.list_tools": "tool.execute",
    "forge.list_skills": "skill.execute",
    "forge.register_tool": "system.config",
    "forge.register_skill": "system.config",
    "oracle.query": "tool.execute",
    "oracle.structured": "tool.execute",
    "oracle.embed": "tool.execute",
    "oracle.classify": "tool.execute",
    "lexicon.assemble_context": "memory.read",
    "lexicon.store_memory": "memory.write",
    "lexicon.search_memory": "memory.read",
    "lexicon.promote_memory": "memory.write",
    "lexicon.query_tier": "memory.read",
    "identity.create_tenant": "system.config",
    "identity.create_user": "user.create",
    "identity.update_user": "user.update",
    "identity.delete_user": "user.delete",
    "identity.assign_role": "role.assign",
    "identity.list_users": "user.create",
    "identity.authenticate": "system.config",
    "janus.evaluate_policy": "system.config",
    "janus.add_policy": "system.config",
    "janus.list_policies": "system.config",
    "janus.update_policy": "system.config",
    "scheduler.manage": "tool.execute",
}

# Resource-specific permission overrides
RESOURCE_PERMISSION_MAP: Dict[str, str] = {
    "tool:file_read": "file.read",
    "tool:file_write": "file.write",
    "tool:file_delete": "file.delete",
    "tool:dir_list": "file.read",
    "tool:dir_create": "file.write",
    "tool:execute_shell_command": "shell.execute",
    "tool:git_command": "git.execute",
    "tool:http_get": "network.http",
    "tool:http_post": "network.http",
    "tool:json_parse": "",  # No permission needed — stateless utility
    "tool:schedule_job": "scheduler.manage",
}


class PermissionModel:
    """
    Role-Based Access Control (RBAC) evaluation engine.

    Determines whether a user's permissions satisfy the requirements
    for a given action and resource combination.
    """

    def __init__(self, custom_roles: Optional[Dict[str, Dict[str, Any]]] = None):
        """
        Initialize the permission model.

        Args:
            custom_roles: Optional dictionary of additional role definitions
                         to merge with the default roles.
        """
        self._roles: Dict[str, Dict[str, Any]] = dict(DEFAULT_ROLES)
        if custom_roles:
            self._roles.update(custom_roles)

        # Cache for user permission lookups (tenant:user -> permissions set)
        self._user_permission_cache: Dict[str, Set[str]] = {}

        logger.info(
            "PermissionModel initialized",
            extra={"roles_loaded": list(self._roles.keys())},
        )

    @property
    def roles(self) -> Dict[str, Dict[str, Any]]:
        """Return the current role definitions."""
        return dict(self._roles)

    def get_role_permissions(self, role_name: str) -> Set[str]:
        """
        Get the permission set for a given role.

        Args:
            role_name: The role to look up.

        Returns:
            Set of permission strings for the role.

        Raises:
            ValueError: If the role is not defined.
        """
        role = self._roles.get(role_name)
        if role is None:
            raise ValueError(f"Role '{role_name}' is not defined.")
        return set(role["permissions"])

    def has_wildcard(self, permissions: Set[str]) -> bool:
        """Check if the permission set includes the wildcard (root) permission."""
        return "*" in permissions

    def resolve_required_permission(self, action: str, resource: str) -> Optional[str]:
        """
        Resolve the required permission for an action + resource combination.

        Priority:
            1. Resource-specific permission (RESOURCE_PERMISSION_MAP)
            2. Action-level permission (ACTION_PERMISSION_MAP)
            3. None (no permission mapping found — defaults to DENY for safety)

        Args:
            action: The action being performed.
            resource: The resource being accessed.

        Returns:
            The required permission string, empty string for no-permission-needed,
            or None if no mapping exists.
        """
        # Check resource-specific first
        if resource in RESOURCE_PERMISSION_MAP:
            perm = RESOURCE_PERMISSION_MAP[resource]
            if perm == "":
                return ""  # Explicitly no permission needed
            return perm

        # Fall back to action-level
        if action in ACTION_PERMISSION_MAP:
            return ACTION_PERMISSION_MAP[action]

        # No mapping found
        return None

    def check_permission(
        self,
        user_permissions: Set[str],
        required_permission: str,
    ) -> bool:
        """
        Check if a set of user permissions satisfies a required permission.

        Supports wildcard, exact match, and prefix matching (e.g., having
        'a.b' grants permission for the more specific 'a.b.c').
        """
        if not required_permission:
            return True

        if "*" in user_permissions:
            return True

        # Check for exact match or if a broader permission exists.
        for perm in user_permissions:
            # Case 1: The user has the exact permission required.
            if perm == required_permission:
                return True

            # Case 2: The user has a broader permission that is a prefix
            # of the required one (e.g., user has 'a.b', req is 'a.b.c').
            if required_permission.startswith(perm + '.'):
                return True

        return False


    def evaluate(
        self,
        action: str,
        resource: str,
        user_permissions: Set[str],
        user_id: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> WardenResponse:
        """
        Evaluate whether a user is authorized to perform an action on a resource.

        Args:
            action: The action being requested.
            resource: The resource being accessed.
            user_permissions: The set of permissions granted to the user.
            user_id: The user ID (for logging/response).
            context: Additional evaluation context.

        Returns:
            WardenResponse with the verdict.
        """
        required = self.resolve_required_permission(action, resource)

        # No mapping found — deny by default (secure by default principle)
        if required is None:
            logger.warning(
                "No permission mapping for action/resource",
                extra={"action": action, "resource": resource, "user_id": user_id},
            )
            return WardenResponse(
                verdict=WardenVerdict.DENY,
                reason=f"No permission mapping found for action '{action}' on resource '{resource}'. Denied by default.",
                policy_applied="default_deny",
            )

        # Empty string means no permission required
        if required == "":
            return WardenResponse(
                verdict=WardenVerdict.ALLOW,
                reason=f"No permission required for resource '{resource}'.",
                policy_applied="no_permission_required",
            )

        # Evaluate permission
        if self.check_permission(user_permissions, required):
            logger.debug(
                "Permission granted",
                extra={
                    "action": action,
                    "resource": resource,
                    "user_id": user_id,
                    "required": required,
                },
            )
            return WardenResponse(
                verdict=WardenVerdict.ALLOW,
                reason=f"User has required permission '{required}' for action '{action}' on resource '{resource}'.",
                policy_applied="rbac_allow",
            )
        else:
            logger.info(
                "Permission denied",
                extra={
                    "action": action,
                    "resource": resource,
                    "user_id": user_id,
                    "required": required,
                    "user_permissions": list(user_permissions),
                },
            )
            return WardenResponse(
                verdict=WardenVerdict.DENY,
                reason=f"User lacks required permission '{required}' for action '{action}' on resource '{resource}'.",
                policy_applied="rbac_deny",
            )

    def add_role(self, role_name: str, permissions: List[str], is_system_role: bool = False, description: str = "") -> None:
        """
        Add or update a role definition.

        Args:
            role_name: The name of the role.
            permissions: List of permission strings for this role.
            is_system_role: Whether this is a system-managed role.
            description: Human-readable description.
        """
        self._roles[role_name] = {
            "permissions": permissions,
            "is_system_role": is_system_role,
            "description": description,
        }
        logger.info(f"Role '{role_name}' added/updated with {len(permissions)} permissions.")

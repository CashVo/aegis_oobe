# aegis/schemas/identity.py
# Implements: Part V, §5.3 — Identity Agent Protocol
# Implements: Part VI, §6.5 — Identity Protocol

from enum import Enum
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field


class IdentityAction(str, Enum):
    """All actions supported by the Identity Agent."""
    CREATE_TENANT = "create_tenant"
    CREATE_USER = "create_user"
    UPDATE_USER = "update_user"
    DELETE_USER = "delete_user"
    ASSIGN_ROLE = "assign_role"
    CREATE_ROLE = "create_role"
    LIST_USERS = "list_users"
    LIST_TENANTS = "list_tenants"
    LIST_ROLES = "list_roles"
    GET_USER = "get_user"
    GET_TENANT = "get_tenant"
    AUTHENTICATE = "authenticate"  # For session token issuance
    RUN_BOOTSTRAP = "run_bootstrap"  # First-run bootstrap (bypasses auth)


class IdentityRequest(BaseModel):
    """
    Request model for Identity Agent operations.

    All actions except CREATE_TENANT require tenant_id.
    User-specific actions require user_id or target user info in payload.
    """
    action: IdentityAction
    tenant_id: Optional[str] = None  # Required for all except CREATE_TENANT
    user_id: Optional[str] = None    # The requesting user (for auth context)
    payload: Dict[str, Any] = {}


class IdentityResponse(BaseModel):
    """Response model from Identity Agent operations."""
    success: bool
    action: IdentityAction
    data: Dict[str, Any] = {}
    error: Optional[str] = None


# --- Domain Models (§5.1 Data Model) ---

class TenantStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class UserStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class Tenant(BaseModel):
    """Tenant domain model. Implements: Part V, §5.1"""
    tenant_id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    reated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: TenantStatus = TenantStatus.ACTIVE


class Role(BaseModel):
    """Role domain model. Implements: Part V, §5.1"""
    role_id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: str
    name: str
    permissions: List[str] = []
    is_system_role: bool = False
    reated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class User(BaseModel):
    """User domain model. Implements: Part V, §5.1"""
    user_id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: str
    username: str  # Unique per tenant
    display_name: str
    email: Optional[str] = None
    role_id: str
    is_root: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: UserStatus = UserStatus.ACTIVE
    passphrase_hash: Optional[str] = None  # Stored hashed, never exposed


# --- Default Role Definitions (§5.2) ---

class DefaultPermissions:
    """Default role permission sets. Implements: Part V, §5.2"""
    ROOT = ["*"]
    ADMIN = [
        "user.create", "user.update", "user.delete",
        "role.assign", "memory.read", "memory.write",
        "tool.execute", "skill.execute", "system.config"
    ]
    MEMBER = [
        "memory.read", "memory.write.own",
        "tool.execute", "skill.execute"
    ]
    OBSERVER = ["memory.read.own"]

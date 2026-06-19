# AMCP Assembly-Only Build: CHUNK-004

# build_chunk_004.py
#
# This script assembles Aegis CHUNK-004: Identity Agent.
# Run from the root of the project-aegis directory.
# Dependencies: CHUNK-001 (Base Layout & Schemas), CHUNK-003 (Warden)
#
# Implements: Part V (§5.1–§5.4), Part VI §6.5, Part XIV CHUNK-004

import os
import textwrap


# --- File Manifest ---
CHUNK_004_FILES = {

    # ═══════════════════════════════════════════════════════════
    # SCHEMAS
    # ═══════════════════════════════════════════════════════════

    "aegis/schemas/identity.py": '''
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
''',

    # ═══════════════════════════════════════════════════════════
    # IDENTITY PACKAGE — PERSISTENCE LAYER
    # ═══════════════════════════════════════════════════════════

    "aegis/identity/__init__.py": '''
# aegis/identity/__init__.py
# Identity subsystem package.

from aegis.identity.store import IdentityStore
from aegis.identity.bootstrap import IdentityBootstrap
from aegis.identity.constants import DEFAULT_SYSTEM_ROLES

__all__ = ["IdentityStore", "IdentityBootstrap", "DEFAULT_SYSTEM_ROLES"]
''',

    "aegis/identity/constants.py": '''
# aegis/identity/constants.py
# Implements: Part V, §5.2 — Default Roles

"""
System-wide constants for the Identity subsystem.
Default roles are created during tenant provisioning.
"""

DEFAULT_SYSTEM_ROLES = {
    "root": {
        "name": "root",
        "permissions": ["*"],
        "is_system_role": True,
    },
    "admin": {
        "name": "admin",
        "permissions": [
            "user.create", "user.update", "user.delete",
            "role.assign", "memory.read", "memory.write",
            "tool.execute", "skill.execute", "system.config",
        ],
        "is_system_role": True,
    },
    "member": {
        "name": "member",
        "permissions": [
            "memory.read", "memory.write.own",
            "tool.execute", "skill.execute",
        ],
        "is_system_role": True,
    },
    "observer": {
        "name": "observer",
        "permissions": ["memory.read.own"],
        "is_system_role": True,
    },
}
''',

    "aegis/identity/store.py": '''
# aegis/identity/store.py
# Implements: Part V, §5.1 — Data Model (SQLite persistence)
# Implements: Part V, §5.2 — Default Roles

"""
IdentityStore — SQLite-backed persistence for Tenants, Users, and Roles.
All operations are async via aiosqlite.
Data is partitioned by tenant_id from day zero (Principle #5: Multi-Tenant by Design).
"""

import hashlib
import logging
import os
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

import aiosqlite

from aegis.schemas.identity import (
    DefaultPermissions,
    Role,
    Tenant,
    TenantStatus,
    User,
    UserStatus,
)
from aegis.identity.constants import DEFAULT_SYSTEM_ROLES

logger = logging.getLogger(__name__)


def _hash_passphrase(passphrase: str, salt: Optional[str] = None) -> str:
    """
    Hash a passphrase using SHA-256 with a salt.
    Returns 'salt:hash' format string.
    """
    if salt is None:
        salt = secrets.token_hex(16)
    hash_val = hashlib.sha256(f"{salt}{passphrase}".encode()).hexdigest()
    return f"{salt}:{hash_val}"


def _verify_passphrase(passphrase: str, stored_hash: str) -> bool:
    """Verify a passphrase against a stored 'salt:hash' string."""
    if not stored_hash or ":" not in stored_hash:
        return False
    salt = stored_hash.split(":")[0]
    return _hash_passphrase(passphrase, salt) == stored_hash


class IdentityStore:
    """
    Async SQLite persistence layer for the Identity subsystem.
    
    Manages CRUD operations for Tenants, Users, and Roles with
    full multi-tenant isolation.
    """

    def __init__(self, db_path: str):
        """
        Initialize the IdentityStore.
        
        Args:
            db_path: Path to the SQLite database file.
        """
        self.db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None

    async def initialize(self) -> None:
        """Open the database connection and create tables if they don't exist."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._create_tables()
        logger.info(f"IdentityStore initialized at: {self.db_path}")

    async def close(self) -> None:
        """Close the database connection gracefully."""
        if self._db:
            await self._db.close()
            self._db = None
            logger.info("IdentityStore connection closed.")

    async def _create_tables(self) -> None:
        """Create the identity schema tables."""
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS tenants (
                tenant_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active'
            );

            CREATE TABLE IF NOT EXISTS roles (
                role_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                name TEXT NOT NULL,
                permissions TEXT NOT NULL DEFAULT '[]',
                is_system_role INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id),
                UNIQUE(tenant_id, name)
            );

            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                username TEXT NOT NULL,
                display_name TEXT NOT NULL,
                email TEXT,
                role_id TEXT NOT NULL,
                is_root INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                passphrase_hash TEXT,
                FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id),
                FOREIGN KEY (role_id) REFERENCES roles(role_id),
                UNIQUE(tenant_id, username)
            );

            CREATE INDEX IF NOT EXISTS idx_users_tenant 
                ON users(tenant_id);
            CREATE INDEX IF NOT EXISTS idx_roles_tenant 
                ON roles(tenant_id);
        """)
        await self._db.commit()

    # ─────────────────────────────────────────────
    # TENANT OPERATIONS
    # ─────────────────────────────────────────────

    async def is_empty(self) -> bool:
        """Check if the identity store has zero tenants (triggers bootstrap)."""
        async with self._db.execute("SELECT COUNT(*) FROM tenants") as cursor:
            row = await cursor.fetchone()
            return row[0] == 0

    async def create_tenant(self, name: str, tenant_id: Optional[str] = None) -> Tenant:
        """
        Create a new tenant and provision default system roles.
        
        Args:
            name: Human-readable tenant name.
            tenant_id: Optional pre-generated UUID. Auto-generated if None.
            
        Returns:
            The created Tenant object.
            
        Raises:
            ValueError: If a tenant with the same name already exists.
        """
        tenant_id = tenant_id or str(uuid4())
        now = datetime.now(timezone.utc).isoformat()

        # Check for duplicate name
        async with self._db.execute(
            "SELECT tenant_id FROM tenants WHERE name = ?", (name,)
        ) as cursor:
            if await cursor.fetchone():
                raise ValueError(f"Tenant with name '{name}' already exists.")

        await self._db.execute(
            "INSERT INTO tenants (tenant_id, name, created_at, status) VALUES (?, ?, ?, ?)",
            (tenant_id, name, now, TenantStatus.ACTIVE.value),
        )
        await self._db.commit()

        # Provision default system roles for this tenant
        await self._provision_default_roles(tenant_id)

        tenant = Tenant(
            tenant_id=tenant_id,
            name=name,
            created_at=datetime.fromisoformat(now),
            status=TenantStatus.ACTIVE,
        )
        logger.info(f"Created tenant: {name} ({tenant_id})")
        return tenant

    async def get_tenant(self, tenant_id: str) -> Optional[Tenant]:
        """Retrieve a tenant by ID."""
        async with self._db.execute(
            "SELECT * FROM tenants WHERE tenant_id = ?", (tenant_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return Tenant(
                tenant_id=row["tenant_id"],
                name=row["name"],
                created_at=datetime.fromisoformat(row["created_at"]),
                status=TenantStatus(row["status"]),
            )

    async def list_tenants(self) -> List[Tenant]:
        """List all tenants."""
        async with self._db.execute(
            "SELECT * FROM tenants ORDER BY created_at DESC"
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                Tenant(
                    tenant_id=row["tenant_id"],
                    name=row["name"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                    status=TenantStatus(row["status"]),
                )
                for row in rows
            ]

    # ─────────────────────────────────────────────
    # ROLE OPERATIONS
    # ─────────────────────────────────────────────

    async def _provision_default_roles(self, tenant_id: str) -> Dict[str, str]:
        """
        Create the four default system roles for a tenant.
        Returns a mapping of role_name -> role_id.
        """
        import json

        role_ids = {}
        now = datetime.now(timezone.utc).isoformat()

        for role_name, role_def in DEFAULT_SYSTEM_ROLES.items():
            role_id = str(uuid4())
            await self._db.execute(
                """INSERT INTO roles 
                   (role_id, tenant_id, name, permissions, is_system_role, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    role_id,
                    tenant_id,
                    role_def["name"],
                    json.dumps(role_def["permissions"]),
                    1 if role_def["is_system_role"] else 0,
                    now,
                ),
            )
            role_ids[role_name] = role_id

        await self._db.commit()
        logger.info(f"Provisioned default roles for tenant: {tenant_id}")
        return role_ids

    async def create_role(
        self,
        tenant_id: str,
        name: str,
        permissions: List[str],
        is_system_role: bool = False,
    ) -> Role:
        """
        Create a custom role for a tenant.
        
        Args:
            tenant_id: The tenant this role belongs to.
            name: Role name (unique per tenant).
            permissions: List of permission strings.
            is_system_role: Whether this is a system-managed role.
            
        Returns:
            The created Role object.
        """
        import json

        role_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()

        await self._db.execute(
            """INSERT INTO roles 
               (role_id, tenant_id, name, permissions, is_system_role, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (role_id, tenant_id, name, json.dumps(permissions), int(is_system_role), now),
        )
        await self._db.commit()

        role = Role(
            role_id=role_id,
            tenant_id=tenant_id,
            name=name,
            permissions=permissions,
            is_system_role=is_system_role,
            created_at=datetime.fromisoformat(now),
        )
        logger.info(f"Created role: {name} for tenant {tenant_id}")
        return role

    async def get_role_by_name(self, tenant_id: str, role_name: str) -> Optional[Role]:
        """Retrieve a role by tenant_id and role name."""
        import json

        async with self._db.execute(
            "SELECT * FROM roles WHERE tenant_id = ? AND name = ?",
            (tenant_id, role_name),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return Role(
                role_id=row["role_id"],
                tenant_id=row["tenant_id"],
                name=row["name"],
                permissions=json.loads(row["permissions"]),
                is_system_role=bool(row["is_system_role"]),
                created_at=datetime.fromisoformat(row["created_at"]),
            )

    async def get_role_by_id(self, role_id: str) -> Optional[Role]:
        """Retrieve a role by its ID."""
        import json

        async with self._db.execute(
            "SELECT * FROM roles WHERE role_id = ?", (role_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return Role(
                role_id=row["role_id"],
                tenant_id=row["tenant_id"],
                name=row["name"],
                permissions=json.loads(row["permissions"]),
                is_system_role=bool(row["is_system_role"]),
                created_at=datetime.fromisoformat(row["created_at"]),
            )

    async def list_roles(self, tenant_id: str) -> List[Role]:
        """List all roles for a tenant."""
        import json

        async with self._db.execute(
            "SELECT * FROM roles WHERE tenant_id = ? ORDER BY name",
            (tenant_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                Role(
                    role_id=row["role_id"],
                    tenant_id=row["tenant_id"],
                    name=row["name"],
                    permissions=json.loads(row["permissions"]),
                    is_system_role=bool(row["is_system_role"]),
                    created_at=datetime.fromisoformat(row["created_at"]),
                )
                for row in rows
            ]

    # ─────────────────────────────────────────────
    # USER OPERATIONS
    # ─────────────────────────────────────────────

    async def create_user(
        self,
        tenant_id: str,
        username: str,
        display_name: str,
        role_name: str = "member",
        email: Optional[str] = None,
        is_root: bool = False,
        passphrase: Optional[str] = None,
    ) -> User:
        """
        Create a new user within a tenant.
        
        Args:
            tenant_id: The tenant this user belongs to.
            username: Unique username within the tenant.
            display_name: Human-readable display name.
            role_name: Name of the role to assign (must exist in tenant).
            email: Optional email address.
            is_root: Whether this is the root user (first-run only).
            passphrase: Optional passphrase for authentication.
            
        Returns:
            The created User object (passphrase_hash excluded from response).
            
        Raises:
            ValueError: If username is taken or role doesn't exist.
        """
        # Validate role exists
        role = await self.get_role_by_name(tenant_id, role_name)
        if not role:
            raise ValueError(
                f"Role '{role_name}' does not exist for tenant '{tenant_id}'."
            )

        # Check username uniqueness within tenant
        async with self._db.execute(
            "SELECT user_id FROM users WHERE tenant_id = ? AND username = ?",
            (tenant_id, username),
        ) as cursor:
            if await cursor.fetchone():
                raise ValueError(
                    f"Username '{username}' already exists in tenant '{tenant_id}'."
                )

        user_id = str(uuid4())
        now = now = datetime.now(timezone.utc).isoformat()
        passphrase_hash = _hash_passphrase(passphrase) if passphrase else None

        await self._db.execute(
            """INSERT INTO users 
               (user_id, tenant_id, username, display_name, email, 
                role_id, is_root, created_at, status, passphrase_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id,
                tenant_id,
                username,
                display_name,
                email,
                role.role_id,
                int(is_root),
                now,
                UserStatus.ACTIVE.value,
                passphrase_hash,
            ),
        )
        await self._db.commit()

        user = User(
            user_id=user_id,
            tenant_id=tenant_id,
            username=username,
            display_name=display_name,
            email=email,
            role_id=role.role_id,
            is_root=is_root,
            created_at=datetime.fromisoformat(now),
            status=UserStatus.ACTIVE,
            passphrase_hash=None,  # Never expose hash
        )
        logger.info(f"Created user: {username} ({user_id}) in tenant {tenant_id}")
        return user

    async def get_user(self, user_id: str) -> Optional[User]:
        """Retrieve a user by ID (passphrase_hash excluded)."""
        async with self._db.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return User(
                user_id=row["user_id"],
                tenant_id=row["tenant_id"],
                username=row["username"],
                display_name=row["display_name"],
                email=row["email"],
                role_id=row["role_id"],
                is_root=bool(row["is_root"]),
                created_at=datetime.fromisoformat(row["created_at"]),
                status=UserStatus(row["status"]),
                passphrase_hash=None,  # Never expose
            )

    async def get_user_by_username(
        self, tenant_id: str, username: str
    ) -> Optional[User]:
        """Retrieve a user by tenant + username."""
        async with self._db.execute(
            "SELECT * FROM users WHERE tenant_id = ? AND username = ?",
            (tenant_id, username),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return User(
                user_id=row["user_id"],
                tenant_id=row["tenant_id"],
                username=row["username"],
                display_name=row["display_name"],
                email=row["email"],
                role_id=row["role_id"],
                is_root=bool(row["is_root"]),
                created_at=datetime.fromisoformat(row["created_at"]),
                status=UserStatus(row["status"]),
                passphrase_hash=None,
            )

    async def list_users(self, tenant_id: str) -> List[User]:
        """List all users for a tenant."""
        async with self._db.execute(
            "SELECT * FROM users WHERE tenant_id = ? ORDER BY created_at DESC",
            (tenant_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                User(
                    user_id=row["user_id"],
                    tenant_id=row["tenant_id"],
                    username=row["username"],
                    display_name=row["display_name"],
                    email=row["email"],
                    role_id=row["role_id"],
                    is_root=bool(row["is_root"]),
                    created_at=datetime.fromisoformat(row["created_at"]),
                    status=UserStatus(row["status"]),
                    passphrase_hash=None,
                )
                for row in rows
            ]

    async def update_user(
        self, user_id: str, updates: Dict[str, Any]
    ) -> Optional[User]:
        """
        Update a user's mutable fields.
        
        Allowed fields: display_name, email, status, passphrase.
        Role changes use assign_role separately.
        
        Args:
            user_id: The user to update.
            updates: Dict of field_name -> new_value.
            
        Returns:
            Updated User object, or None if user not found.
        """
        allowed_fields = {"display_name", "email", "status"}
        
        set_clauses = []
        values = []

        for field, value in updates.items():
            if field == "passphrase":
                set_clauses.append("passphrase_hash = ?")
                values.append(_hash_passphrase(value))
            elif field in allowed_fields:
                set_clauses.append(f"{field} = ?")
                values.append(value)
            else:
                logger.warning(f"Ignoring disallowed update field: {field}")

        if not set_clauses:
            return await self.get_user(user_id)

        values.append(user_id)
        query = f"UPDATE users SET {', '.join(set_clauses)} WHERE user_id = ?"
        await self._db.execute(query, values)
        await self._db.commit()

        logger.info(f"Updated user {user_id}: fields={list(updates.keys())}")
        return await self.get_user(user_id)

    async def delete_user(self, user_id: str) -> bool:
        """
        Delete a user by ID.
        
        Args:
            user_id: The user to delete.
            
        Returns:
            True if deleted, False if user not found.
            
        Raises:
            ValueError: If attempting to delete a root user.
        """
        user = await self.get_user(user_id)
        if not user:
            return False
        if user.is_root:
            raise ValueError("Cannot delete root user.")

        await self._db.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        await self._db.commit()
        logger.info(f"Deleted user: {user_id}")
        return True

    async def assign_role(self, user_id: str, role_name: str) -> Optional[User]:
        """
        Assign a new role to a user.
        
        Args:
            user_id: The user to reassign.
            role_name: The target role name.
            
        Returns:
            Updated User, or None if user/role not found.
            
        Raises:
            ValueError: If user is root (role is immutable for root).
        """
        user = await self.get_user(user_id)
        if not user:
            return None
        if user.is_root:
            raise ValueError("Cannot reassign root user's role.")

        role = await self.get_role_by_name(user.tenant_id, role_name)
        if not role:
            raise ValueError(
                f"Role '{role_name}' not found in tenant '{user.tenant_id}'."
            )

        await self._db.execute(
            "UPDATE users SET role_id = ? WHERE user_id = ?",
            (role.role_id, user_id),
        )
        await self._db.commit()
        logger.info(f"Assigned role '{role_name}' to user {user_id}")
        return await self.get_user(user_id)

    # ─────────────────────────────────────────────
    # AUTHENTICATION
    # ─────────────────────────────────────────────

    async def authenticate(
        self, tenant_id: str, username: str, passphrase: str
    ) -> Optional[User]:
        """
        Authenticate a user by username and passphrase.
        
        Args:
            tenant_id: The tenant context.
            username: The username to authenticate.
            passphrase: The plaintext passphrase to verify.
            
        Returns:
            The authenticated User object, or None if authentication fails.
        """
        async with self._db.execute(
            "SELECT * FROM users WHERE tenant_id = ? AND username = ? AND status = ?",
            (tenant_id, username, UserStatus.ACTIVE.value),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            if not row["passphrase_hash"]:
                # No passphrase set — allow passthrough (local-first trust)
                logger.warning(
                    f"User '{username}' authenticated without passphrase (none set)."
                )
                return await self.get_user(row["user_id"])
            if _verify_passphrase(passphrase, row["passphrase_hash"]):
                logger.info(f"User '{username}' authenticated successfully.")
                return await self.get_user(row["user_id"])
            return None

    async def get_user_permissions(self, user_id: str) -> List[str]:
        """
        Get the effective permissions for a user based on their role.
        
        Returns:
            List of permission strings. ["*"] for root.
        """
        import json

        async with self._db.execute(
            """SELECT r.permissions FROM users u 
               JOIN roles r ON u.role_id = r.role_id 
               WHERE u.user_id = ?""",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return []
            return json.loads(row["permissions"])
''',

    "aegis/identity/bootstrap.py": '''
# aegis/identity/bootstrap.py
# Implements: Part V, §5.4 — Bootstrap / First-Run

"""
IdentityBootstrap — Handles first-run system initialization.

On first launch (no tenants exist):
1. System Manager detects empty Identity store.
2. Creates "Default" tenant.
3. Creates root user with is_root=True.
4. Root user session is established.

This is the ONLY time a user is created outside the normal authenticated flow.
This directly addresses RT-1 (Bootstrap Paradox) from Part XIII.
"""

import logging
from typing import Optional, Tuple

from aegis.identity.store import IdentityStore
from aegis.schemas.identity import Tenant, User

logger = logging.getLogger(__name__)


class IdentityBootstrap:
    """
    Manages the first-run bootstrap sequence for the Identity subsystem.
    
    This class is invoked by the System Manager when it detects that
    the Identity store is empty (no tenants exist).
    """

    def __init__(self, store: IdentityStore):
        self.store = store

    async def needs_bootstrap(self) -> bool:
        """Check if the system needs initial bootstrapping."""
        return await self.store.is_empty()

    async def execute(
        self,
        root_username: str = "root",
        root_display_name: str = "System Root",
        root_passphrase: Optional[str] = None,
        tenant_name: str = "Default",
    ) -> Tuple[Tenant, User]:
        """
        Execute the full bootstrap sequence.
        
        This creates:
        1. The "Default" tenant with all system roles provisioned.
        2. The root user with full (*) permissions.
        
        Args:
            root_username: Username for the root user.
            root_display_name: Display name for the root user.
            root_passphrase: Optional passphrase. If None, local trust mode.
            tenant_name: Name for the initial tenant.
            
        Returns:
            Tuple of (created Tenant, created root User).
            
        Raises:
            RuntimeError: If bootstrap is called when tenants already exist.
        """
        if not await self.needs_bootstrap():
            raise RuntimeError(
                "Bootstrap aborted: Identity store is not empty. "
                "Tenants already exist."
            )

        logger.info("=" * 60)
        logger.info("IDENTITY BOOTSTRAP — First-Run Initialization")
        logger.info("=" * 60)

        # Step 1: Create the Default tenant (provisions system roles)
        logger.info(f"Step 1: Creating tenant '{tenant_name}'...")
        tenant = await self.store.create_tenant(name=tenant_name)
        logger.info(f"  → Tenant created: {tenant.tenant_id}")

        # Step 2: Create the root user
        logger.info(f"Step 2: Creating root user '{root_username}'...")
        root_user = await self.store.create_user(
            tenant_id=tenant.tenant_id,
            username=root_username,
            display_name=root_display_name,
            role_name="root",
            is_root=True,
            passphrase=root_passphrase,
        )
        logger.info(f"  → Root user created: {root_user.user_id}")

        logger.info("=" * 60)
        logger.info("BOOTSTRAP COMPLETE")
        logger.info(f"  Tenant: {tenant.name} ({tenant.tenant_id})")
        logger.info(f"  Root User: {root_user.username} ({root_user.user_id})")
        logger.info("=" * 60)

        return tenant, root_user
''',

    # ═══════════════════════════════════════════════════════════
    # IDENTITY AGENT
    # ═══════════════════════════════════════════════════════════

    "aegis/agents/identity/__init__.py": '''
# aegis/agents/identity/__init__.py
from aegis.agents.identity.agent import IdentityAgent

__all__ = ["IdentityAgent"]
''',

    "aegis/agents/identity/agent.py": '''
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
''',

    # ═══════════════════════════════════════════════════════════
    # TESTS
    # ═══════════════════════════════════════════════════════════

    "tests/test_identity/__init__.py": '''
# tests/test_identity/__init__.py
''',

    "tests/test_identity/test_store.py": '''
# tests/test_identity/test_store.py
# Unit tests for IdentityStore — SQLite persistence layer.

import os
import pytest
import pytest_asyncio
import tempfile

from aegis.identity.store import IdentityStore, _hash_passphrase, _verify_passphrase


@pytest_asyncio.fixture
async def store():
    """Create a temporary IdentityStore for testing."""
    tmp_dir = tempfile.mkdtemp()
    db_path = os.path.join(tmp_dir, "test_identity.db")
    s = IdentityStore(db_path=db_path)
    await s.initialize()
    yield s
    await s.close()
    os.unlink(db_path)
    os.rmdir(tmp_dir)


class TestPassphraseHashing:
    """Tests for passphrase hashing utilities."""

    def test_hash_produces_salt_colon_hash(self):
        result = _hash_passphrase("testpass")
        assert ":" in result
        parts = result.split(":")
        assert len(parts) == 2
        assert len(parts[0]) == 32  # 16 bytes hex = 32 chars
        assert len(parts[1]) == 64  # SHA-256 hex = 64 chars

    def test_verify_correct_passphrase(self):
        hashed = _hash_passphrase("mypassword")
        assert _verify_passphrase("mypassword", hashed) is True

    def test_verify_incorrect_passphrase(self):
        hashed = _hash_passphrase("mypassword")
        assert _verify_passphrase("wrongpassword", hashed) is False

    def test_verify_empty_hash(self):
        assert _verify_passphrase("anything", "") is False
        assert _verify_passphrase("anything", None) is False


class TestTenantOperations:
    """Tests for tenant CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_tenant(self, store):
        tenant = await store.create_tenant(name="TestCorp")
        assert tenant.name == "TestCorp"
        assert tenant.tenant_id is not None
        assert tenant.status.value == "active"

    @pytest.mark.asyncio
    async def test_create_duplicate_tenant_raises(self, store):
        await store.create_tenant(name="Duplicate")
        with pytest.raises(ValueError, match="already exists"):
            await store.create_tenant(name="Duplicate")

    @pytest.mark.asyncio
    async def test_get_tenant(self, store):
        created = await store.create_tenant(name="FindMe")
        found = await store.get_tenant(created.tenant_id)
        assert found is not None
        assert found.name == "FindMe"

    @pytest.mark.asyncio
    async def test_get_nonexistent_tenant(self, store):
        result = await store.get_tenant("nonexistent-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_tenants(self, store):
        await store.create_tenant(name="T1")
        await store.create_tenant(name="T2")
        tenants = await store.list_tenants()
        assert len(tenants) == 2

    @pytest.mark.asyncio
    async def test_is_empty_true(self, store):
        assert await store.is_empty() is True

    @pytest.mark.asyncio
    async def test_is_empty_false_after_create(self, store):
        await store.create_tenant(name="NotEmpty")
        assert await store.is_empty() is False


class TestRoleOperations:
    """Tests for role operations."""

    @pytest.mark.asyncio
    async def test_default_roles_provisioned(self, store):
        tenant = await store.create_tenant(name="RoleTenant")
        roles = await store.list_roles(tenant.tenant_id)
        role_names = {r.name for r in roles}
        assert role_names == {"root", "admin", "member", "observer"}

    @pytest.mark.asyncio
    async def test_get_role_by_name(self, store):
        tenant = await store.create_tenant(name="RoleLookup")
        role = await store.get_role_by_name(tenant.tenant_id, "admin")
        assert role is not None
        assert role.name == "admin"
        assert "user.create" in role.permissions

    @pytest.mark.asyncio
    async def test_create_custom_role(self, store):
        tenant = await store.create_tenant(name="CustomRole")
        role = await store.create_role(
            tenant_id=tenant.tenant_id,
            name="auditor",
            permissions=["memory.read", "system.audit"],
        )
        assert role.name == "auditor"
        assert role.is_system_role is False

    @pytest.mark.asyncio
    async def test_root_role_has_wildcard(self, store):
        tenant = await store.create_tenant(name="WildcardTest")
        role = await store.get_role_by_name(tenant.tenant_id, "root")
        assert role.permissions == ["*"]


class TestUserOperations:
    """Tests for user CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_user(self, store):
        tenant = await store.create_tenant(name="UserTenant")
        user = await store.create_user(
            tenant_id=tenant.tenant_id,
            username="cashvo",
            display_name="Cash Vo",
            role_name="admin",
            email="cash@example.com",
        )
        assert user.username == "cashvo"
        assert user.display_name == "Cash Vo"
        assert user.email == "cash@example.com"
        assert user.passphrase_hash is None  # Never exposed

    @pytest.mark.asyncio
    async def test_create_duplicate_username_raises(self, store):
        tenant = await store.create_tenant(name="DupUser")
        await store.create_user(
            tenant_id=tenant.tenant_id,
            username="duplicate",
            display_name="First",
        )
        with pytest.raises(ValueError, match="already exists"):
            await store.create_user(
                tenant_id=tenant.tenant_id,
                username="duplicate",
                display_name="Second",
            )

    @pytest.mark.asyncio
    async def test_create_user_invalid_role_raises(self, store):
        tenant = await store.create_tenant(name="BadRole")
        with pytest.raises(ValueError, match="does not exist"):
            await store.create_user(
                tenant_id=tenant.tenant_id,
                username="nobody",
                display_name="Nobody",
                role_name="nonexistent_role",
            )

    @pytest.mark.asyncio
    async def test_get_user(self, store):
        tenant = await store.create_tenant(name="GetUser")
        created = await store.create_user(
            tenant_id=tenant.tenant_id,
            username="findme",
            display_name="Find Me",
        )
        found = await store.get_user(created.user_id)
        assert found is not None
        assert found.username == "findme"

    @pytest.mark.asyncio
    async def test_list_users(self, store):
        tenant = await store.create_tenant(name="ListUsers")
        await store.create_user(
            tenant_id=tenant.tenant_id, username="u1", display_name="U1"
        )
        await store.create_user(
            tenant_id=tenant.tenant_id, username="u2", display_name="U2"
        )
        users = await store.list_users(tenant.tenant_id)
        assert len(users) == 2

    @pytest.mark.asyncio
    async def test_update_user(self, store):
        tenant = await store.create_tenant(name="UpdateUser")
        user = await store.create_user(
            tenant_id=tenant.tenant_id,
            username="updatable",
            display_name="Original",
        )
        updated = await store.update_user(
            user.user_id, {"display_name": "Updated", "email": "new@test.com"}
        )
        assert updated.display_name == "Updated"
        assert updated.email == "new@test.com"

    @pytest.mark.asyncio
    async def test_delete_user(self, store):
        tenant = await store.create_tenant(name="DeleteUser")
        user = await store.create_user(
            tenant_id=tenant.tenant_id, username="deleteme", display_name="Gone"
        )
        result = await store.delete_user(user.user_id)
        assert result is True
        assert await store.get_user(user.user_id) is None

    @pytest.mark.asyncio
    async def test_delete_root_user_raises(self, store):
        tenant = await store.create_tenant(name="ProtectRoot")
        user = await store.create_user(
            tenant_id=tenant.tenant_id,
            username="rootuser",
            display_name="Root",
            role_name="root",
            is_root=True,
        )
        with pytest.raises(ValueError, match="Cannot delete root"):
            await store.delete_user(user.user_id)

    @pytest.mark.asyncio
    async def test_assign_role(self, store):
        tenant = await store.create_tenant(name="AssignRole")
        user = await store.create_user(
            tenant_id=tenant.tenant_id,
            username="promotable",
            display_name="Promo",
            role_name="member",
        )
        admin_role = await store.get_role_by_name(tenant.tenant_id, "admin")
        updated = await store.assign_role(user.user_id, "admin")
        assert updated.role_id == admin_role.role_id


class TestAuthentication:
    """Tests for authentication flow."""

    @pytest.mark.asyncio
    async def test_authenticate_with_passphrase(self, store):
        tenant = await store.create_tenant(name="AuthTenant")
        await store.create_user(
            tenant_id=tenant.tenant_id,
            username="secure",
            display_name="Secure User",
            passphrase="mypassword123",
        )
        user = await store.authenticate(
            tenant.tenant_id, "secure", "mypassword123"
        )
        assert user is not None
        assert user.username == "secure"

    @pytest.mark.asyncio
    async def test_authenticate_wrong_passphrase(self, store):
        tenant = await store.create_tenant(name="FailAuth")
        await store.create_user(
            tenant_id=tenant.tenant_id,
            username="locked",
            display_name="Locked",
            passphrase="correctpass",
        )
        user = await store.authenticate(tenant.tenant_id, "locked", "wrongpass")
        assert user is None

    @pytest.mark.asyncio
    async def test_authenticate_no_passphrase_set(self, store):
        tenant = await store.create_tenant(name="TrustAuth")
        await store.create_user(
            tenant_id=tenant.tenant_id,
            username="trustedlocal",
            display_name="Trusted",
        )
        # Local trust mode: no passphrase set, any passphrase works
        user = await store.authenticate(
            tenant.tenant_id, "trustedlocal", ""
        )
        assert user is not None

    @pytest.mark.asyncio
    async def test_get_user_permissions(self, store):
        tenant = await store.create_tenant(name="PermTest")
        user = await store.create_user(
            tenant_id=tenant.tenant_id,
            username="member1",
            display_name="Member",
            role_name="member",
        )
        perms = await store.get_user_permissions(user.user_id)
        assert "memory.read" in perms
        assert "tool.execute" in perms
''',

    "tests/test_identity/test_bootstrap.py": '''
# tests/test_identity/test_bootstrap.py
# Unit tests for the first-run bootstrap sequence.
# Implements: Part V, §5.4 — Bootstrap / First-Run

import os
import pytest
import pytest_asyncio
import tempfile

from aegis.identity.store import IdentityStore
from aegis.identity.bootstrap import IdentityBootstrap


@pytest_asyncio.fixture
async def store():
    """Create a temporary IdentityStore for testing."""
    tmp_dir = tempfile.mkdtemp()
    db_path = os.path.join(tmp_dir, "test_bootstrap.db")
    s = IdentityStore(db_path=db_path)
    await s.initialize()
    yield s
    await s.close()
    os.unlink(db_path)
    os.rmdir(tmp_dir)


class TestBootstrap:
    """Tests for the IdentityBootstrap sequence."""

    @pytest.mark.asyncio
    async def test_needs_bootstrap_empty_store(self, store):
        bootstrap = IdentityBootstrap(store)
        assert await bootstrap.needs_bootstrap() is True

    @pytest.mark.asyncio
    async def test_needs_bootstrap_after_tenant_exists(self, store):
        await store.create_tenant(name="Existing")
        bootstrap = IdentityBootstrap(store)
        assert await bootstrap.needs_bootstrap() is False

    @pytest.mark.asyncio
    async def test_execute_creates_tenant_and_root(self, store):
        bootstrap = IdentityBootstrap(store)
        tenant, root_user = await bootstrap.execute(
            root_username="admin",
            root_display_name="Admin User",
            root_passphrase="securepass",
            tenant_name="MyOrg",
        )
        assert tenant.name == "MyOrg"
        assert root_user.username == "admin"
        assert root_user.is_root is True

    @pytest.mark.asyncio
    async def test_execute_provisions_system_roles(self, store):
        bootstrap = IdentityBootstrap(store)
        tenant, _ = await bootstrap.execute(tenant_name="RoleCheck")
        roles = await store.list_roles(tenant.tenant_id)
        role_names = {r.name for r in roles}
        assert "root" in role_names
        assert "admin" in role_names
        assert "member" in role_names
        assert "observer" in role_names

    @pytest.mark.asyncio
    async def test_execute_twice_raises(self, store):
        bootstrap = IdentityBootstrap(store)
        await bootstrap.execute()
        with pytest.raises(RuntimeError, match="not empty"):
            await bootstrap.execute()

    @pytest.mark.asyncio
    async def test_root_user_has_root_role(self, store):
        bootstrap = IdentityBootstrap(store)
        tenant, root_user = await bootstrap.execute()
        perms = await store.get_user_permissions(root_user.user_id)
        assert perms == ["*"]

    @pytest.mark.asyncio
    async def test_root_user_authenticates(self, store):
        bootstrap = IdentityBootstrap(store)
        tenant, root_user = await bootstrap.execute(
            root_passphrase="bootstrappass"
        )
        authed = await store.authenticate(
            tenant.tenant_id, "root", "bootstrappass"
        )
        assert authed is not None
        assert authed.user_id == root_user.user_id
''',

    "tests/test_identity/test_agent.py": '''
# tests/test_identity/test_agent.py
# Unit tests for the IdentityAgent message handling.

import os
import pytest
import pytest_asyncio
import tempfile

from aegis.agents.identity.agent import IdentityAgent
from aegis.identity.store import IdentityStore
from aegis.schemas.identity import IdentityAction
from aegis.schemas.message import AegisMessage, MessageType, Priority


def _make_message(action: str, payload: dict, tenant_id: str = "test-tenant", user_id: str = "test-user") -> AegisMessage:
    """Helper to create test AegisMessages."""
    return AegisMessage(
        source_agent="test_client",
        target_agent="identity",
        message_type=MessageType.REQUEST,
        tenant_id=tenant_id,
        user_id=user_id,
        action=f"identity.{action}",
        payload=payload,
        priority=Priority.NORMAL,
    )


@pytest_asyncio.fixture
async def agent():
    """Create an IdentityAgent with a temp store."""
    tmp_dir = tempfile.mkdtemp()
    db_path = os.path.join(tmp_dir, "test_agent.db")
    store = IdentityStore(db_path=db_path)
    identity_agent = IdentityAgent(store=store)
    await identity_agent.startup()
    yield identity_agent
    await identity_agent.shutdown()
    os.unlink(db_path)
    os.rmdir(tmp_dir)


class TestIdentityAgentMessages:
    """Tests for agent message routing and handling."""

    @pytest.mark.asyncio
    async def test_create_tenant_via_message(self, agent):
        msg = _make_message(
            action="create_tenant",
            payload={
                "action": "create_tenant",
                "payload": {"name": "TestOrg"},
            },
        )
        response = await agent.handle_message(msg)
        assert response is not None
        assert response.payload["success"] is True
        assert response.payload["data"]["name"] == "TestOrg"

    @pytest.mark.asyncio
    async def test_create_user_via_message(self, agent):
        # First create a tenant
        create_tenant_msg = _make_message(
            action="create_tenant",
            payload={
                "action": "create_tenant",
                "payload": {"name": "UserOrg"},
            },
        )
        tenant_resp = await agent.handle_message(create_tenant_msg)
        tenant_id = tenant_resp.payload["data"]["tenant_id"]

        # Now create a user
        msg = _make_message(
            action="create_user",
            payload={
                "action": "create_user",
                "tenant_id": tenant_id,
                "payload": {
                    "username": "newuser",
                    "display_name": "New User",
                    "role_name": "member",
                },
            },
            tenant_id=tenant_id,
        )
        response = await agent.handle_message(msg)
        assert response.payload["success"] is True
        assert response.payload["data"]["username"] == "newuser"

    @pytest.mark.asyncio
    async def test_list_users_via_message(self, agent):
        # Create tenant + user
        create_tenant_msg = _make_message(
            action="create_tenant",
            payload={"action": "create_tenant", "payload": {"name": "ListOrg"}},
        )
        tenant_resp = await agent.handle_message(create_tenant_msg)
        tenant_id = tenant_resp.payload["data"]["tenant_id"]

        await agent._store.create_user(
            tenant_id=tenant_id, username="u1", display_name="U1"
        )

        msg = _make_message(
            action="list_users",
            payload={"action": "list_users", "tenant_id": tenant_id},
            tenant_id=tenant_id,
        )
        response = await agent.handle_message(msg)
        assert response.payload["success"] is True
        assert len(response.payload["data"]["users"]) == 1

    @pytest.mark.asyncio
    async def test_authenticate_via_message(self, agent):
        # Create tenant + user with passphrase
        create_tenant_msg = _make_message(
            action="create_tenant",
            payload={"action": "create_tenant", "payload": {"name": "AuthOrg"}},
        )
        tenant_resp = await agent.handle_message(create_tenant_msg)
        tenant_id = tenant_resp.payload["data"]["tenant_id"]

        await agent._store.create_user(
            tenant_id=tenant_id,
            username="authuser",
            display_name="Auth User",
            passphrase="secret123",
        )

        msg = _make_message(
            action="authenticate",
            payload={
                "action": "authenticate",
                "tenant_id": tenant_id,
                "payload": {
                    "username": "authuser",
                    "passphrase": "secret123",
                },
            },
            tenant_id=tenant_id,
        )
        response = await agent.handle_message(msg)
        assert response.payload["success"] is True
        assert "permissions" in response.payload["data"]

    @pytest.mark.asyncio
    async def test_invalid_action_returns_error(self, agent):
        msg = _make_message(
            action="invalid",
            payload={"action": "totally_invalid"},
        )
        response = await agent.handle_message(msg)
        assert response.message_type == MessageType.ERROR

    @pytest.mark.asyncio
    async def test_bootstrap_detection(self, agent):
        assert await agent.needs_bootstrap() is True

    @pytest.mark.asyncio
    async def test_run_bootstrap(self, agent):
        result = await agent.run_bootstrap(
            root_username="root",
            root_passphrase="aegis",
        )
        assert "tenant" in result
        assert "root_user" in result
        assert result["root_user"]["is_root"] is True
        # After bootstrap, needs_bootstrap should be False
        assert await agent.needs_bootstrap() is False
''',
}


def create_package_init_files(path):
    """Create __init__.py files in parent directories if they don't exist."""
    dir_name = os.path.dirname(path)
    if dir_name and (dir_name.startswith("src/") or dir_name.startswith("tests/")):
        parts = dir_name.split("/")
        for i in range(2, len(parts) + 1):
            pkg_path = "/".join(parts[:i])
            init_file = os.path.join(pkg_path, "__init__.py")
            if not os.path.exists(init_file):
                os.makedirs(pkg_path, exist_ok=True)
                print(f"  [Created] {init_file} (empty package marker)")
                with open(init_file, "w") as f:
                    pass


def main():
    """Main function to write all CHUNK-004 files."""
    print("=" * 60)
    print("  ASSEMBLING CHUNK-004: Identity Agent")
    print("=" * 60)
    print()

    for path, content in CHUNK_004_FILES.items():
        # Ensure the directory exists
        dir_name = os.path.dirname(path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)

        create_package_init_files(path)
        print(f"  [Writing] {path}")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(textwrap.dedent(content.strip()) + "\n")

    # Update requirements.txt with new dependency
    req_addition = "aiosqlite>=0.19.0"
    req_file = "requirements.txt"
    print()
    if os.path.exists(req_file):
        with open(req_file, "r") as f:
            existing = f.read()
        if "aiosqlite" not in existing:
            with open(req_file, "a", encoding="utf-8", newline="\n") as f:
                f.write(f"\n# CHUNK-004: Identity Agent\n{req_addition}\n")
            print(f"  [Updated] {req_file} — added {req_addition}")
        else:
            print(f"  [Skipped] {req_file} — aiosqlite already present")
    else:
        with open(req_file, "w", encoding="utf-8", newline="\n") as f:
            f.write(f"# Project Aegis Dependencies\n\n# CHUNK-004: Identity Agent\n{req_addition}\n")
        print(f"  [Created] {req_file}")

    print()
    print("=" * 60)
    print("  ASSEMBLY COMPLETE — CHUNK-004: Identity Agent")
    print("=" * 60)
    print()
    print("  Files written:")
    for path in CHUNK_004_FILES:
        print(f"    ✓ {path}")
    print()
    print("  New dependency: aiosqlite>=0.19.0")
    print()
    print("  Run tests with:")
    print("    pytest tests/test_identity/ -v")
    print()


if __name__ == "__main__":
    main()

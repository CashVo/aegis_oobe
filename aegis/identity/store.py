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

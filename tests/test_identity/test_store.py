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

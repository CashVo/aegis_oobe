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

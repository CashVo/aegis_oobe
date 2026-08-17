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
        payload=payload,  # Action is in message.action, payload is the request payload
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
            payload={"name": "TestOrg"},  # Direct payload, not nested
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
            payload={"name": "UserOrg"},
        )
        tenant_resp = await agent.handle_message(create_tenant_msg)
        tenant_id = tenant_resp.payload["data"]["tenant_id"]

        # Now create a user
        msg = _make_message(
            action="create_user",
            payload={
                "tenant_id": tenant_id,
                "username": "newuser",
                "display_name": "New User",
                "role_name": "member",
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
            payload={"name": "ListOrg"},
        )
        tenant_resp = await agent.handle_message(create_tenant_msg)
        tenant_id = tenant_resp.payload["data"]["tenant_id"]

        await agent._store.create_user(
            tenant_id=tenant_id, username="u1", display_name="U1"
        )

        msg = _make_message(
            action="list_users",
            payload={"tenant_id": tenant_id},
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
            payload={"name": "AuthOrg"},
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
                "tenant_id": tenant_id,
                "username": "authuser",
                "passphrase": "secret123",
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

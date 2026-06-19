# tests/test_warden/test_interceptor.py
"""
Unit tests for the Warden Message Interceptor.
Tests: Message authorization flow, passthrough logic, metrics.
"""

import pytest
from aegis.schemas.message import AegisMessage, MessageType, Priority
from aegis.schemas.warden import WardenVerdict
from aegis.warden.allowlist import AllowlistEngine
from aegis.warden.bypass import BypassManager
from aegis.warden.interceptor import MessageInterceptor
from aegis.warden.permission_model import PermissionModel


def make_message(
    source_agent="torchestrator",
    target_agent="forge",
    action="forge.execute_tool",
    tenant_id="tenant-1",
    user_id="user-1",
    payload=None,
    message_type=MessageType.REQUEST,
) -> AegisMessage:
    """Helper to create test messages."""
    return AegisMessage(
        source_agent=source_agent,
        target_agent=target_agent,
        message_type=message_type,
        tenant_id=tenant_id,
        user_id=user_id,
        action=action,
        payload=payload or {},
    )


@pytest.fixture
def interceptor():
    """Create a MessageInterceptor with a known permission resolver."""
    perm_model = PermissionModel()
    allowlist = AllowlistEngine()
    bypass = BypassManager()

    # Resolver: user-1 = member, root-user = root
    def resolver(tenant_id: str, user_id: str):
        if user_id == "root-user":
            return {"*"}
        elif user_id == "admin-user":
            return set(perm_model.get_role_permissions("admin"))
        elif user_id == "member-user":
            return set(perm_model.get_role_permissions("member"))
        elif user_id == "observer-user":
            return set(perm_model.get_role_permissions("observer"))
        return set()

    return MessageInterceptor(
        permission_model=perm_model,
        allowlist_engine=allowlist,
        bypass_manager=bypass,
        user_permission_resolver=resolver,
    )


class TestPassthrough:
    """Test passthrough conditions."""

    def test_system_manager_always_passes(self, interceptor):
        msg = make_message(source_agent="system_manager")
        response = interceptor.intercept(msg)
        assert response.verdict == WardenVerdict.ALLOW
        assert "passthrough" in response.policy_applied

    def test_observer_always_passes(self, interceptor):
        msg = make_message(source_agent="observer")
        response = interceptor.intercept(msg)
        assert response.verdict == WardenVerdict.ALLOW

    def test_response_messages_pass(self, interceptor):
        msg = make_message(message_type=MessageType.RESPONSE)
        response = interceptor.intercept(msg)
        assert response.verdict == WardenVerdict.ALLOW

    def test_error_messages_pass(self, interceptor):
        msg = make_message(message_type=MessageType.ERROR)
        response = interceptor.intercept(msg)
        assert response.verdict == WardenVerdict.ALLOW

    def test_warden_authorize_passes(self, interceptor):
        msg = make_message(action="warden.authorize")
        response = interceptor.intercept(msg)
        assert response.verdict == WardenVerdict.ALLOW


class TestAuthorization:
    """Test standard authorization flow."""

    def test_root_allowed(self, interceptor):
        msg = make_message(user_id="root-user")
        response = interceptor.intercept(msg)
        assert response.verdict == WardenVerdict.ALLOW

    def test_member_tool_execute_allowed(self, interceptor):
        msg = make_message(
            user_id="member-user",
            action="forge.execute_tool",
            payload={"tool_or_skill_name": "file_read"},
        )
        response = interceptor.intercept(msg)
        assert response.verdict == WardenVerdict.ALLOW

    def test_observer_tool_execute_denied(self, interceptor):
        msg = make_message(
            user_id="observer-user",
            action="forge.execute_tool",
            payload={"tool_or_skill_name": "file_read"},
        )
        response = interceptor.intercept(msg)
        assert response.verdict == WardenVerdict.DENY

    def test_unknown_user_denied(self, interceptor):
        msg = make_message(user_id="unknown-user")
        response = interceptor.intercept(msg)
        assert response.verdict == WardenVerdict.DENY


class TestShellCommands:
    """Test shell command interception."""

    def test_member_allowed_shell_command(self, interceptor):
        msg = make_message(
            user_id="member-user",
            action="forge.execute_tool",
            payload={
                "tool_or_skill_name": "execute_shell_command",
                "parameters": {"command": "ls -la"},
            },
        )
        response = interceptor.intercept(msg)
        assert response.verdict == WardenVerdict.ALLOW

    def test_member_denied_dangerous_command(self, interceptor):
        msg = make_message(
            user_id="member-user",
            action="forge.execute_tool",
            payload={
                "tool_or_skill_name": "execute_shell_command",
                "parameters": {"command": "rm -rf /"},
            },
        )
        response = interceptor.intercept(msg)
        assert response.verdict == WardenVerdict.DENY


class TestMetrics:
    """Test interceptor metrics tracking."""

    def test_metrics_increment(self, interceptor):
        msg = make_message(source_agent="system_manager")
        interceptor.intercept(msg)
        interceptor.intercept(msg)

        metrics = interceptor.metrics
        assert metrics["total_evaluated"] == 2
        assert metrics["total_allowed"] == 2

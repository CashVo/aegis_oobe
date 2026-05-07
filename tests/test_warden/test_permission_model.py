# tests/test_warden/test_permission_model.py
"""
Unit tests for the Warden Permission Model.
Tests: RBAC evaluation, role definitions, permission resolution.
"""

import pytest
from aegis.schemas.warden import WardenVerdict
from aegis.warden.permission_model import (
    PermissionModel,
    DEFAULT_ROLES,
    ACTION_PERMISSION_MAP,
    RESOURCE_PERMISSION_MAP,
)


@pytest.fixture
def model():
    """Create a fresh PermissionModel for each test."""
    return PermissionModel()


class TestRoleDefinitions:
    """Test default role definitions are correctly loaded."""

    def test_default_roles_loaded(self, model):
        assert "root" in model.roles
        assert "admin" in model.roles
        assert "member" in model.roles
        assert "observer" in model.roles

    def test_root_has_wildcard(self, model):
        perms = model.get_role_permissions("root")
        assert "*" in perms

    def test_admin_permissions(self, model):
        perms = model.get_role_permissions("admin")
        assert "user.create" in perms
        assert "system.config" in perms
        assert "*" not in perms

    def test_member_permissions(self, model):
        perms = model.get_role_permissions("member")
        assert "tool.execute" in perms
        assert "memory.read" in perms
        assert "user.create" not in perms

    def test_observer_permissions(self, model):
        perms = model.get_role_permissions("observer")
        assert "memory.read.own" in perms
        assert len(perms) == 1

    def test_unknown_role_raises(self, model):
        with pytest.raises(ValueError):
            model.get_role_permissions("nonexistent")


class TestPermissionChecks:
    """Test permission evaluation logic."""

    def test_wildcard_grants_all(self, model):
        assert model.check_permission({"*"}, "anything.at.all") is True

    def test_exact_match(self, model):
        assert model.check_permission({"file.read"}, "file.read") is True

    def test_no_match(self, model):
        assert model.check_permission({"file.read"}, "file.write") is False

    def test_prefix_match(self, model):
        # "memory.write" should cover "memory.write.own"
        assert model.check_permission({"memory.write"}, "memory.write.own") is True

    def test_specific_does_not_grant_broader(self, model):
        # "memory.write.own" should NOT cover "memory.write"
        assert model.check_permission({"memory.write.own"}, "memory.write") is False

    def test_empty_permission_required(self, model):
        assert model.check_permission(set(), "") is True

    def test_empty_user_permissions_denied(self, model):
        assert model.check_permission(set(), "file.read") is False


class TestEvaluation:
    """Test full evaluation flow."""

    def test_root_can_do_anything(self, model):
        response = model.evaluate(
            action="forge.execute_tool",
            resource="tool:execute_shell_command",
            user_permissions={"*"},
            user_id="root-user",
        )
        assert response.verdict == WardenVerdict.ALLOW

    def test_member_can_execute_tool(self, model):
        response = model.evaluate(
            action="forge.execute_tool",
            resource="tool:file_read",
            user_permissions={"tool.execute", "file.read"},
            user_id="member-user",
        )
        assert response.verdict == WardenVerdict.ALLOW

    def test_observer_cannot_execute_tool(self, model):
        response = model.evaluate(
            action="forge.execute_tool",
            resource="tool:file_read",
            user_permissions={"memory.read.own"},
            user_id="observer-user",
        )
        assert response.verdict == WardenVerdict.DENY

    def test_no_mapping_defaults_to_deny(self, model):
        response = model.evaluate(
            action="unknown.action",
            resource="unknown:resource",
            user_permissions={"tool.execute"},
            user_id="test-user",
        )
        assert response.verdict == WardenVerdict.DENY
        assert "default" in response.policy_applied

    def test_json_parse_no_permission_required(self, model):
        response = model.evaluate(
            action="forge.execute_tool",
            resource="tool:json_parse",
            user_permissions=set(),
            user_id="any-user",
        )
        assert response.verdict == WardenVerdict.ALLOW

    def test_add_custom_role(self, model):
        model.add_role("custom", ["custom.perm"], description="Test role")
        perms = model.get_role_permissions("custom")
        assert "custom.perm" in perms

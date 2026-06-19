# tests/test_warden/test_bypass.py
"""
Unit tests for the Warden Emergency Bypass Manager.
Tests: Activation, deactivation, TTL expiry, root-only enforcement.
"""

import time
import pytest
from aegis.schemas.warden import WardenVerdict
from aegis.warden.bypass import BypassManager


@pytest.fixture
def bypass():
    """Create a fresh BypassManager for each test."""
    return BypassManager(max_ttl_seconds=5)


class TestActivation:
    """Test bypass activation logic."""

    def test_root_can_activate(self, bypass):
        response = bypass.activate(user_id="root-1", is_root=True, reason="Testing")
        assert response.verdict == WardenVerdict.ALLOW
        assert bypass.is_active is True

    def test_non_root_cannot_activate(self, bypass):
        response = bypass.activate(user_id="user-1", is_root=False, reason="Testing")
        assert response.verdict == WardenVerdict.DENY
        assert bypass.is_active is False

    def test_activation_sets_metadata(self, bypass):
        bypass.activate(user_id="root-1", is_root=True, reason="Test reason")
        status = bypass.status
        assert status["active"] is True
        assert status["activated_by"] == "root-1"
        assert status["reason"] == "Test reason"


class TestDeactivation:
    """Test bypass deactivation logic."""

    def test_root_can_deactivate(self, bypass):
        bypass.activate(user_id="root-1", is_root=True)
        response = bypass.deactivate(user_id="root-1", is_root=True)
        assert response.verdict == WardenVerdict.ALLOW
        assert bypass.is_active is False

    def test_non_root_cannot_deactivate(self, bypass):
        bypass.activate(user_id="root-1", is_root=True)
        response = bypass.deactivate(user_id="user-1", is_root=False)
        assert response.verdict == WardenVerdict.DENY
        assert bypass.is_active is True


class TestBypassEvaluation:
    """Test operation evaluation under bypass mode."""

    def test_activating_user_allowed(self, bypass):
        bypass.activate(user_id="root-1", is_root=True)
        response = bypass.evaluate_bypass(
            user_id="root-1", tenant_id="t1", action="forge.execute_tool"
        )
        assert response.verdict == WardenVerdict.ALLOW

    def test_other_user_denied(self, bypass):
        bypass.activate(user_id="root-1", is_root=True)
        response = bypass.evaluate_bypass(
            user_id="other-user", tenant_id="t1", action="forge.execute_tool"
        )
        assert response.verdict == WardenVerdict.DENY

    def test_operations_counter(self, bypass):
        bypass.activate(user_id="root-1", is_root=True)
        bypass.evaluate_bypass(user_id="root-1", tenant_id="t1", action="a")
        bypass.evaluate_bypass(user_id="root-1", tenant_id="t1", action="b")
        assert bypass.status["operations_count"] == 2

    def test_inactive_bypass_denies(self, bypass):
        response = bypass.evaluate_bypass(
            user_id="root-1", tenant_id="t1", action="forge.execute_tool"
        )
        assert response.verdict == WardenVerdict.DENY


class TestTTLExpiry:
    """Test TTL-based auto-deactivation."""

    def test_bypass_expires_after_ttl(self):
        # Use a very short TTL for testing
        bypass = BypassManager(max_ttl_seconds=1)
        bypass.activate(user_id="root-1", is_root=True)
        assert bypass.is_active is True

        # Wait for TTL to expire
        time.sleep(1.1)
        assert bypass.is_active is False

    def test_ttl_remaining_decreases(self, bypass):
        bypass.activate(user_id="root-1", is_root=True)
        status1 = bypass.status
        time.sleep(0.5)
        status2 = bypass.status
        assert status2["ttl_remaining_seconds"] < status1["ttl_remaining_seconds"]

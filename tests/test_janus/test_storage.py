# tests/test_janus/test_storage.py
"""
Unit tests for the Janus PolicyStore (SQLite persistence).
"""

import tempfile
from pathlib import Path

import pytest

from aegis.agents.janus.storage import PolicyStore
from aegis.schemas.janus import PolicyRule


@pytest.fixture
def store(tmp_path):
    """Create a temporary PolicyStore for testing."""
    db_path = tmp_path / "test_policies.db"
    s = PolicyStore(db_path)
    yield s
    s.close()


@pytest.fixture
def sample_policy() -> PolicyRule:
    """A sample policy rule for testing."""
    return PolicyRule(
        rule_id="TEST-001",
        name="Test Policy",
        description="A test policy for unit testing.",
        condition='action == "test.action"',
        action_on_match="deny",
        priority=500,
        active=True,
        tenant_id=None,
        tags=["test", "unit"],
    )


@pytest.fixture
def tenant_policy() -> PolicyRule:
    """A tenant-scoped policy for testing."""
    return PolicyRule(
        rule_id="TEST-TENANT-001",
        name="Tenant Policy",
        description="A tenant-scoped test policy.",
        condition='resource == "sensitive"',
        action_on_match="escalate",
        priority=700,
        active=True,
        tenant_id="tenant-abc",
        tags=["test", "tenant"],
    )


class TestPolicyStoreCRUD:
    """Test basic CRUD operations."""

    def test_add_policy(self, store, sample_policy):
        result = store.add_policy(sample_policy)
        assert result.rule_id == "TEST-001"
        assert store.count_policies() == 1

    def test_add_duplicate_raises(self, store, sample_policy):
        store.add_policy(sample_policy)
        with pytest.raises(ValueError, match="already exists"):
            store.add_policy(sample_policy)

    def test_get_policy(self, store, sample_policy):
        store.add_policy(sample_policy)
        retrieved = store.get_policy("TEST-001")
        assert retrieved is not None
        assert retrieved.name == "Test Policy"
        assert retrieved.condition == 'action == "test.action"'

    def test_get_nonexistent_returns_none(self, store):
        assert store.get_policy("DOES-NOT-EXIST") is None

    def test_update_policy(self, store, sample_policy):
        store.add_policy(sample_policy)
        sample_policy.name = "Updated Policy"
        sample_policy.priority = 999
        updated = store.update_policy(sample_policy)
        assert updated.name == "Updated Policy"
        assert updated.priority == 999

        # Verify persistence
        retrieved = store.get_policy("TEST-001")
        assert retrieved.name == "Updated Policy"

    def test_update_nonexistent_raises(self, store, sample_policy):
        with pytest.raises(ValueError, match="not found"):
            store.update_policy(sample_policy)

    def test_delete_policy(self, store, sample_policy):
        store.add_policy(sample_policy)
        assert store.delete_policy("TEST-001") is True
        assert store.get_policy("TEST-001") is None
        assert store.count_policies() == 0

    def test_delete_nonexistent_returns_false(self, store):
        assert store.delete_policy("DOES-NOT-EXIST") is False


class TestPolicyStoreListing:
    """Test policy listing and filtering."""

    def test_list_system_wide(self, store, sample_policy):
        store.add_policy(sample_policy)
        policies = store.list_policies(tenant_id=None)
        assert len(policies) == 1

    def test_list_tenant_includes_system(self, store, sample_policy, tenant_policy):
        store.add_policy(sample_policy)  # system-wide (tenant_id=None)
        store.add_policy(tenant_policy)  # tenant-scoped
        policies = store.list_policies(tenant_id="tenant-abc")
        assert len(policies) == 2  # Both system-wide and tenant-specific

    def test_list_different_tenant_excludes(self, store, tenant_policy):
        store.add_policy(tenant_policy)  # tenant-abc only
        policies = store.list_policies(tenant_id="tenant-xyz")
        # tenant-xyz should NOT see tenant-abc's policies (only system-wide)
        assert len(policies) == 0

    def test_list_active_only(self, store, sample_policy):
        store.add_policy(sample_policy)
        inactive = PolicyRule(
            rule_id="TEST-INACTIVE",
            name="Inactive Policy",
            description="",
            condition='x == "y"',
            action_on_match="log",
            active=False,
        )
        store.add_policy(inactive)
        policies = store.list_policies(active_only=True)
        assert len(policies) == 1
        assert policies[0].rule_id == "TEST-001"

    def test_list_by_tags(self, store, sample_policy):
        store.add_policy(sample_policy)  # tags: ["test", "unit"]
        other = PolicyRule(
            rule_id="TEST-OTHER",
            name="Other Policy",
            description="",
            condition='a == "b"',
            action_on_match="warn",
            tags=["security"],
        )
        store.add_policy(other)

        # Filter by 'unit' tag
        policies = store.list_policies(tags=["unit"])
        assert len(policies) == 1
        assert policies[0].rule_id == "TEST-001"

    def test_list_ordered_by_priority(self, store):
        low = PolicyRule(
            rule_id="LOW", name="Low", description="", condition='a == "a"',
            action_on_match="log", priority=10
        )
        high = PolicyRule(
            rule_id="HIGH", name="High", description="", condition='b == "b"',
            action_on_match="deny", priority=900
        )
        store.add_policy(low)
        store.add_policy(high)

        policies = store.list_policies()
        assert policies[0].rule_id == "HIGH"
        assert policies[1].rule_id == "LOW"


class TestPolicyStoreEvaluationQuery:
    """Test the evaluation-specific query method."""

    def test_get_policies_for_evaluation(self, store, sample_policy, tenant_policy):
        store.add_policy(sample_policy)
        store.add_policy(tenant_policy)

        # Evaluation for tenant-abc should get both
        policies = store.get_policies_for_evaluation(tenant_id="tenant-abc")
        assert len(policies) == 2

        # Evaluation for different tenant gets only system-wide
        policies = store.get_policies_for_evaluation(tenant_id="other-tenant")
        assert len(policies) == 1
        assert policies[0].rule_id == "TEST-001"

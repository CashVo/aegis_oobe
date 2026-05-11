# tests/test_lexicon/test_tiers.py
# Unit tests for L0–L5 memory tiers.
"""
Tests for individual memory tier implementations.
"""

import asyncio
import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

from aegis.agents.lexicon.storage import ensure_user_storage
from aegis.agents.lexicon.tiers.l0_identity import L0IdentityTier
from aegis.agents.lexicon.tiers.l1_domain import L1DomainTier
from aegis.agents.lexicon.tiers.l2_workflow import L2WorkflowTier
from aegis.agents.lexicon.tiers.l3_episodic import L3EpisodicTier
from aegis.agents.lexicon.tiers.l4_artifacts import L4ArtifactTier
from aegis.agents.lexicon.tiers.l5_scratchpad import L5ScratchpadTier


# Fixtures
TEST_TENANT = "test-tenant-001"
TEST_USER = "test-user-001"


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test storage."""
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d)


@pytest_asyncio.fixture
async def initialized_storage(temp_dir):
    """Initialize user storage and return the base directory."""
    await ensure_user_storage(TEST_TENANT, TEST_USER, temp_dir)
    return temp_dir


# ─────────────────────────────────────────────
# L0 Tests
# ─────────────────────────────────────────────

class TestL0IdentityTier:
    @pytest.mark.asyncio
    async def test_load_default(self, initialized_storage):
        l0 = L0IdentityTier(TEST_TENANT, TEST_USER, initialized_storage)
        data = await l0.load()
        assert "identity" in data
        assert "preferences" in data

    @pytest.mark.asyncio
    async def test_query_dot_notation(self, initialized_storage):
        l0 = L0IdentityTier(TEST_TENANT, TEST_USER, initialized_storage)
        style = await l0.query("preferences.communication_style")
        assert style == "balanced"

    @pytest.mark.asyncio
    async def test_query_nonexistent_key(self, initialized_storage):
        l0 = L0IdentityTier(TEST_TENANT, TEST_USER, initialized_storage)
        result = await l0.query("nonexistent.key")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_context_fragments(self, initialized_storage):
        l0 = L0IdentityTier(TEST_TENANT, TEST_USER, initialized_storage)
        fragments = await l0.get_context_fragments("test query")
        assert len(fragments) > 0
        assert all(f["tier"] == "L0" for f in fragments)
        assert all(f["relevance"] == 1.0 for f in fragments)

    @pytest.mark.asyncio
    async def test_suggest_update(self, initialized_storage):
        l0 = L0IdentityTier(TEST_TENANT, TEST_USER, initialized_storage)
        suggestion = await l0.suggest_update(
            "preferences.detail_level", "verbose", "User consistently requests detailed responses"
        )
        assert suggestion["requires_user_approval"] is True
        assert suggestion["proposed_value"] == "verbose"

    @pytest.mark.asyncio
    async def test_cache_invalidation(self, initialized_storage):
        l0 = L0IdentityTier(TEST_TENANT, TEST_USER, initialized_storage)
        await l0.load()  # Populate cache
        assert l0._cache is not None
        l0.invalidate_cache()
        assert l0._cache is None


# ─────────────────────────────────────────────
# L1 Tests
# ─────────────────────────────────────────────

class TestL1DomainTier:
    @pytest.mark.asyncio
    async def test_store_and_search(self, initialized_storage):
        l1 = L1DomainTier(TEST_TENANT, TEST_USER, initialized_storage)
        entry_id = await l1.store(
            content="Python async/await enables concurrent I/O operations.",
            category="python",
            tags=["async", "concurrency"],
            source="documentation",
        )
        assert entry_id is not None

        results = await l1.search("async python")
        assert len(results) > 0
        assert results[0]["content"] == "Python async/await enables concurrent I/O operations."

    @pytest.mark.asyncio
    async def test_search_with_category_filter(self, initialized_storage):
        l1 = L1DomainTier(TEST_TENANT, TEST_USER, initialized_storage)
        await l1.store(content="Redis is an in-memory data store.", category="redis")
        await l1.store(content="Python is a programming language.", category="python")

        results = await l1.search("data store", category="redis")
        assert all(r["category"] == "redis" for r in results)

    @pytest.mark.asyncio
    async def test_get_context_fragments(self, initialized_storage):
        l1 = L1DomainTier(TEST_TENANT, TEST_USER, initialized_storage)
        await l1.store(content="FastAPI uses Starlette for the web parts.", tags=["web"])
        fragments = await l1.get_context_fragments("web framework")
        assert all(f["tier"] == "L1" for f in fragments)

    @pytest.mark.asyncio
    async def test_count(self, initialized_storage):
        l1 = L1DomainTier(TEST_TENANT, TEST_USER, initialized_storage)
        assert await l1.count() == 0
        await l1.store(content="Test entry")
        assert await l1.count() == 1

    @pytest.mark.asyncio
    async def test_deprecate(self, initialized_storage):
        l1 = L1DomainTier(TEST_TENANT, TEST_USER, initialized_storage)
        entry_id = await l1.store(content="Outdated info")
        result = await l1.deprecate(entry_id)
        assert result is True


# ─────────────────────────────────────────────
# L2 Tests
# ─────────────────────────────────────────────

class TestL2WorkflowTier:
    @pytest.mark.asyncio
    async def test_store_and_search(self, initialized_storage):
        l2 = L2WorkflowTier(TEST_TENANT, TEST_USER, initialized_storage)
        entry_id = await l2.store(
            content="User prefers bullet-point summaries over prose.",
            pattern_type="format_preference",
            confidence=0.7,
        )
        assert entry_id is not None

        results = await l2.search("bullet summary format")
        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_reinforce(self, initialized_storage):
        l2 = L2WorkflowTier(TEST_TENANT, TEST_USER, initialized_storage)
        entry_id = await l2.store(content="Uses vim keybindings.", confidence=0.5)
        result = await l2.reinforce(entry_id, confidence_boost=0.2)
        assert result is True

    @pytest.mark.asyncio
    async def test_count(self, initialized_storage):
        l2 = L2WorkflowTier(TEST_TENANT, TEST_USER, initialized_storage)
        assert await l2.count() == 0
        await l2.store(content="Pattern entry")
        assert await l2.count() == 1


# ─────────────────────────────────────────────
# L3 Tests
# ─────────────────────────────────────────────

class TestL3EpisodicTier:
    @pytest.mark.asyncio
    async def test_append_and_search(self, initialized_storage):
        l3 = L3EpisodicTier(TEST_TENANT, TEST_USER, initialized_storage)
        entry_id = await l3.append(
            content="Decided to use Redis Streams for the message bus.",
            event_type="decision",
            tags=["architecture", "redis"],
        )
        assert entry_id is not None

        results = await l3.search_fts("Redis Streams")
        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_search_by_recency(self, initialized_storage):
        l3 = L3EpisodicTier(TEST_TENANT, TEST_USER, initialized_storage)
        await l3.append(content="First event", event_type="event")
        await l3.append(content="Second event", event_type="event")

        results = await l3.search_by_recency(limit=5)
        assert len(results) == 2
        # Most recent should be first
        assert "Second" in results[0]["content"]

    @pytest.mark.asyncio
    async def test_search_by_event_type(self, initialized_storage):
        l3 = L3EpisodicTier(TEST_TENANT, TEST_USER, initialized_storage)
        await l3.append(content="A decision was made.", event_type="decision")
        await l3.append(content="A conversation happened.", event_type="conversation")

        results = await l3.search_by_recency(event_type="decision")
        assert all(r["event_type"] == "decision" for r in results)

    @pytest.mark.asyncio
    async def test_get_by_id(self, initialized_storage):
        l3 = L3EpisodicTier(TEST_TENANT, TEST_USER, initialized_storage)
        entry_id = await l3.append(content="Specific event to find.")
        result = await l3.get_by_id(entry_id)
        assert result is not None
        assert result["content"] == "Specific event to find."

    @pytest.mark.asyncio
    async def test_count(self, initialized_storage):
        l3 = L3EpisodicTier(TEST_TENANT, TEST_USER, initialized_storage)
        assert await l3.count() == 0
        await l3.append(content="Entry 1")
        await l3.append(content="Entry 2")
        assert await l3.count() == 2


# ─────────────────────────────────────────────
# L4 Tests
# ─────────────────────────────────────────────

class TestL4ArtifactTier:
    @pytest.mark.asyncio
    async def test_store_and_search(self, initialized_storage):
        l4 = L4ArtifactTier(TEST_TENANT, TEST_USER, initialized_storage)
        entry_id = await l4.store(
            name="Aegis Spec",
            artifact_type="document",
            path_or_uri="/docs/aegis_spec.pdf",
            description="The canonical Project Aegis specification document.",
            tags=["aegis", "spec"],
        )
        assert entry_id is not None

        results = await l4.search("aegis specification")
        assert len(results) > 0
        assert results[0]["name"] == "Aegis Spec"

    @pytest.mark.asyncio
    async def test_validate_artifact(self, initialized_storage):
        l4 = L4ArtifactTier(TEST_TENANT, TEST_USER, initialized_storage)
        entry_id = await l4.store(
            name="Test File",
            artifact_type="file",
            path_or_uri="/tmp/test.txt",
        )
        result = await l4.validate_artifact(entry_id)
        assert result is True

    @pytest.mark.asyncio
    async def test_count(self, initialized_storage):
        l4 = L4ArtifactTier(TEST_TENANT, TEST_USER, initialized_storage)
        assert await l4.count() == 0
        await l4.store(name="Artifact", artifact_type="file", path_or_uri="/a.txt")
        assert await l4.count() == 1


# ─────────────────────────────────────────────
# L5 Tests
# ─────────────────────────────────────────────

class TestL5ScratchpadTier:
    @pytest.mark.asyncio
    async def test_set_and_get(self):
        l5 = L5ScratchpadTier(TEST_TENANT, TEST_USER, "session-001", redis_client=None)
        await l5.set("key1", "value1")
        result = await l5.get("key1")
        assert result == "value1"

    @pytest.mark.asyncio
    async def test_get_default(self):
        l5 = L5ScratchpadTier(TEST_TENANT, TEST_USER, "session-001", redis_client=None)
        result = await l5.get("nonexistent", default="fallback")
        assert result == "fallback"

    @pytest.mark.asyncio
    async def test_delete(self):
        l5 = L5ScratchpadTier(TEST_TENANT, TEST_USER, "session-001", redis_client=None)
        await l5.set("key1", "value1")
        existed = await l5.delete("key1")
        assert existed is True
        result = await l5.get("key1")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_all(self):
        l5 = L5ScratchpadTier(TEST_TENANT, TEST_USER, "session-001", redis_client=None)
        await l5.set("a", 1)
        await l5.set("b", 2)
        all_data = await l5.get_all()
        assert all_data == {"a": 1, "b": 2}

    @pytest.mark.asyncio
    async def test_clear(self):
        l5 = L5ScratchpadTier(TEST_TENANT, TEST_USER, "session-001", redis_client=None)
        await l5.set("x", "y")
        count = await l5.clear()
        assert count == 1
        all_data = await l5.get_all()
        assert all_data == {}

    @pytest.mark.asyncio
    async def test_snapshot(self):
        l5 = L5ScratchpadTier(TEST_TENANT, TEST_USER, "session-002", redis_client=None)
        await l5.set("decision", "Use event sourcing")
        snapshot = await l5.snapshot()
        assert snapshot["session_id"] == "session-002"
        assert snapshot["entries"]["decision"] == "Use event sourcing"

    @pytest.mark.asyncio
    async def test_get_context_fragments(self):
        l5 = L5ScratchpadTier(TEST_TENANT, TEST_USER, "session-001", redis_client=None)
        await l5.set("note", "Important context")
        fragments = await l5.get_context_fragments("context")
        assert len(fragments) == 1
        assert fragments[0]["tier"] == "L5"
        assert "Important context" in fragments[0]["content"]

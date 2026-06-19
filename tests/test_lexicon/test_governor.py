# tests/test_lexicon/test_governor.py
# Unit tests for the Memory Governor.
"""
Tests for the Memory Governor — promotion pipeline and lifecycle management.
"""

import shutil
import tempfile

import pytest
import pytest_asyncio

from aegis.agents.lexicon.governor import MemoryGovernor
from aegis.agents.lexicon.storage import ensure_user_storage
from aegis.agents.lexicon.tiers.l3_episodic import L3EpisodicTier
from aegis.agents.lexicon.tiers.l5_scratchpad import L5ScratchpadTier
from aegis.schemas.lexicon import MemoryGovernorAction


TEST_TENANT = "test-tenant-001"
TEST_USER = "test-user-001"


@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d)


@pytest_asyncio.fixture
async def governor(temp_dir):
    """Set up a Memory Governor with initialized storage."""
    await ensure_user_storage(TEST_TENANT, TEST_USER, temp_dir)
    l3 = L3EpisodicTier(TEST_TENANT, TEST_USER, temp_dir)
    gov = MemoryGovernor(TEST_TENANT, TEST_USER, l3, temp_dir)
    return gov


class TestMemoryGovernor:
    @pytest.mark.asyncio
    async def test_process_session_end_empty(self, governor):
        l5 = L5ScratchpadTier(TEST_TENANT, TEST_USER, "sess-empty", redis_client=None)
        decisions = await governor.process_session_end(l5)
        assert decisions == []

    @pytest.mark.asyncio
    async def test_process_session_end_with_significant_entries(self, governor):
        l5 = L5ScratchpadTier(TEST_TENANT, TEST_USER, "sess-sig", redis_client=None)
        # High-significance keys
        await l5.set("decision_architecture", "Chose event sourcing for the message bus. " * 20)
        await l5.set("outcome_review", "Successfully passed all integration tests. " * 20)
        # Low-significance key
        await l5.set("temp_debug", "x")

        decisions = await governor.process_session_end(l5, significance_threshold=0.3)

        # At least the high-significance entries should be promoted
        assert len(decisions) >= 1
        assert all(d.action == MemoryGovernorAction.PROMOTE for d in decisions)
        assert all(d.source_tier == "L5" and d.target_tier == "L3" for d in decisions)

        # L5 should be cleared after processing
        all_data = await l5.get_all()
        assert all_data == {}

    @pytest.mark.asyncio
    async def test_get_status(self, governor):
        status = await governor.get_status()
        assert status.l3_retention_days == 365
        assert status.pending_promotions == 0

    @pytest.mark.asyncio
    async def test_suggest_l0_update(self, governor):
        decision = await governor.suggest_l0_update(
            key="preferences.detail_level",
            value="verbose",
            rationale="User consistently requests more detail."
        )
        assert decision.requires_user_approval is True
        assert decision.action == MemoryGovernorAction.SUGGEST_L0_UPDATE
        assert decision.target_tier == "L0"

    @pytest.mark.asyncio
    async def test_run_eviction(self, governor):
        # With no old entries, eviction should remove 0
        evicted = await governor.run_eviction()
        assert evicted == 0


class TestSignificanceEvaluation:
    """Test the significance evaluation heuristics."""

    @pytest.mark.asyncio
    async def test_high_signal_key(self, governor):
        score = governor._evaluate_significance("decision_final", "Important architectural choice made here. " * 20)
        assert score >= 0.5

    @pytest.mark.asyncio
    async def test_low_signal_key(self, governor):
        score = governor._evaluate_significance("temp_var", "x")
        assert score < 0.3

    @pytest.mark.asyncio
    async def test_medium_content_length(self, governor):
        score = governor._evaluate_significance("note", "A" * 200)
        assert score >= 0.3

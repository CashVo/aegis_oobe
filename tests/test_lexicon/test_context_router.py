# tests/test_lexicon/test_context_router.py
# Unit tests for the Context Router.
"""
Tests for the Context Router — context assembly from multiple tiers.
"""

import shutil
import tempfile

import pytest
import pytest_asyncio

from aegis.agents.lexicon.context_router import ContextRouter, estimate_tokens
from aegis.agents.lexicon.storage import ensure_user_storage
from aegis.agents.lexicon.tiers.l0_identity import L0IdentityTier
from aegis.agents.lexicon.tiers.l1_domain import L1DomainTier
from aegis.agents.lexicon.tiers.l2_workflow import L2WorkflowTier
from aegis.agents.lexicon.tiers.l3_episodic import L3EpisodicTier
from aegis.agents.lexicon.tiers.l4_artifacts import L4ArtifactTier
from aegis.agents.lexicon.tiers.l5_scratchpad import L5ScratchpadTier
from aegis.schemas.lexicon import ContextRequest


TEST_TENANT = "test-tenant-001"
TEST_USER = "test-user-001"


@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d)


@pytest_asyncio.fixture
async def router_with_data(temp_dir):
    """Set up a Context Router with populated tier data."""
    await ensure_user_storage(TEST_TENANT, TEST_USER, temp_dir)

    l0 = L0IdentityTier(TEST_TENANT, TEST_USER, temp_dir)
    l1 = L1DomainTier(TEST_TENANT, TEST_USER, temp_dir)
    l2 = L2WorkflowTier(TEST_TENANT, TEST_USER, temp_dir)
    l3 = L3EpisodicTier(TEST_TENANT, TEST_USER, temp_dir)
    l4 = L4ArtifactTier(TEST_TENANT, TEST_USER, temp_dir)

    # Populate with test data
    await l1.store("Python uses asyncio for async programming.", category="python", tags=["async"])
    await l1.store("Redis supports pub/sub and streams.", category="redis", tags=["messaging"])
    await l2.store("User prefers structured JSON responses.", pattern_type="format_preference")
    await l3.append("Decided to use Pydantic for all data models.", event_type="decision")
    await l3.append("Meeting about architecture patterns.", event_type="conversation")
    await l4.store(name="API Docs", artifact_type="url", path_or_uri="https://docs.example.com")

    router = ContextRouter(l0=l0, l1=l1, l2=l2, l3=l3, l4=l4)
    return router


class TestContextRouter:
    @pytest.mark.asyncio
    async def test_assemble_basic(self, router_with_data):
        request = ContextRequest(
            query="async programming patterns",
            tenant_id=TEST_TENANT,
            user_id=TEST_USER,
            scope=["L0", "L1", "L2", "L3"],
            token_budget=4000,
        )
        packet = await router_with_data.assemble(request)

        assert packet.tenant_id == TEST_TENANT
        assert packet.user_id == TEST_USER
        assert len(packet.fragments) > 0
        assert packet.total_tokens > 0
        assert packet.total_tokens <= 4000
        assert packet.assembly_time_ms > 0

    @pytest.mark.asyncio
    async def test_assemble_respects_token_budget(self, router_with_data):
        request = ContextRequest(
            query="python redis",
            tenant_id=TEST_TENANT,
            user_id=TEST_USER,
            scope=["L0", "L1", "L2", "L3", "L4"],
            token_budget=50,  # Very small budget
        )
        packet = await router_with_data.assemble(request)
        assert packet.total_tokens <= 50

    @pytest.mark.asyncio
    async def test_assemble_with_l5(self, router_with_data):
        l5 = L5ScratchpadTier(TEST_TENANT, TEST_USER, "sess-001", redis_client=None)
        await l5.set("current_task", "Building the memory system")
        router_with_data.set_l5(l5)

        request = ContextRequest(
            query="memory system",
            tenant_id=TEST_TENANT,
            user_id=TEST_USER,
            scope=["L0", "L1"],
            token_budget=4000,
            session_id="sess-001",
        )
        packet = await router_with_data.assemble(request)

        # L5 should be included because session_id was provided
        tiers_in_fragments = {f.tier for f in packet.fragments}
        assert "L5" in tiers_in_fragments

    @pytest.mark.asyncio
    async def test_assemble_scoped_tiers(self, router_with_data):
        request = ContextRequest(
            query="data models",
            tenant_id=TEST_TENANT,
            user_id=TEST_USER,
            scope=["L1"],  # Only L1
            token_budget=4000,
        )
        packet = await router_with_data.assemble(request)

        # Only L1 should appear (though L0 won't because not in scope)
        tiers_in_fragments = {f.tier for f in packet.fragments}
        assert "L3" not in tiers_in_fragments
        assert "L2" not in tiers_in_fragments


class TestEstimateTokens:
    def test_basic_estimation(self):
        text = "Hello world"  # 11 chars
        tokens = estimate_tokens(text)
        assert tokens >= 1
        assert tokens <= 10

    def test_empty_string(self):
        assert estimate_tokens("") == 1  # Minimum 1

    def test_long_text(self):
        text = "x" * 400  # ~100 tokens
        tokens = estimate_tokens(text)
        assert 90 <= tokens <= 110

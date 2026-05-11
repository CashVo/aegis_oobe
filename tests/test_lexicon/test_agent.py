# tests/test_lexicon/test_agent.py
# Integration tests for the Lexicon Agent.
"""
Tests for the Lexicon Agent — end-to-end message handling.
"""

import shutil
import tempfile

import pytest
import pytest_asyncio

from aegis.agents.lexicon.agent import LexiconAgent
from aegis.schemas.lexicon import LexiconAction


TEST_TENANT = "test-tenant-001"
TEST_USER = "test-user-001"


@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d)


@pytest_asyncio.fixture
async def agent(temp_dir):
    """Create and start a Lexicon agent."""
    a = LexiconAgent(redis_client=None, base_dir=temp_dir)
    await a.startup()
    yield a
    await a.shutdown()


class TestLexiconAgent:
    @pytest.mark.asyncio
    async def test_store_and_search_l3(self, agent):
        # Store a memory
        store_msg = {
            "action": "lexicon.store_memory",
            "tenant_id": TEST_TENANT,
            "user_id": TEST_USER,
            "payload": {
                "action": "store_memory",
                "tier": "L3",
                "content": "Deployed version 2.0 of the API successfully.",
                "tags": ["deployment", "api"],
                "metadata": {"event_type": "outcome"},
            },
        }
        result = await agent.handle_message(store_msg)
        assert result["success"] is True
        assert "entry_id" in result["data"]

        # Search for it
        search_msg = {
            "action": "lexicon.search_memory",
            "tenant_id": TEST_TENANT,
            "user_id": TEST_USER,
            "payload": {
                "action": "search_memory",
                "query": "API deployment",
                "tiers": ["L3"],
            },
        }
        result = await agent.handle_message(search_msg)
        assert result["success"] is True
        assert len(result["data"]["results"].get("L3", [])) > 0

    @pytest.mark.asyncio
    async def test_assemble_context(self, agent):
        # Store some data first
        await agent.handle_message({
            "action": "lexicon.store_memory",
            "tenant_id": TEST_TENANT,
            "user_id": TEST_USER,
            "payload": {
                "action": "store_memory",
                "tier": "L1",
                "content": "FastAPI is built on Starlette and Pydantic.",
                "metadata": {"category": "python"},
                "tags": ["web", "python"],
            },
        })

        # Assemble context
        assemble_msg = {
            "action": "lexicon.assemble_context",
            "tenant_id": TEST_TENANT,
            "user_id": TEST_USER,
            "payload": {
                "action": "assemble_context",
                "query": "web framework python",
                "scope": ["L0", "L1", "L2", "L3"],
                "token_budget": 4000,
            },
        }
        result = await agent.handle_message(assemble_msg)
        assert result["success"] is True
        assert "fragments" in result["data"]
        assert result["data"]["total_tokens"] <= 4000

    @pytest.mark.asyncio
    async def test_store_l0_rejected(self, agent):
        msg = {
            "action": "lexicon.store_memory",
            "tenant_id": TEST_TENANT,
            "user_id": TEST_USER,
            "payload": {
                "action": "store_memory",
                "tier": "L0",
                "content": "Should be rejected.",
            },
        }
        result = await agent.handle_message(msg)
        assert result["success"] is False
        assert "user-editable only" in result["error"]

    @pytest.mark.asyncio
    async def test_store_l5_requires_session(self, agent):
        msg = {
            "action": "lexicon.store_memory",
            "tenant_id": TEST_TENANT,
            "user_id": TEST_USER,
            "payload": {
                "action": "store_memory",
                "tier": "L5",
                "content": "Some scratch data",
            },
        }
        result = await agent.handle_message(msg)
        assert result["success"] is False
        assert "session_id" in result["error"]

    @pytest.mark.asyncio
    async def test_store_l5_with_session(self, agent):
        msg = {
            "action": "lexicon.store_memory",
            "tenant_id": TEST_TENANT,
            "user_id": TEST_USER,
            "payload": {
                "action": "store_memory",
                "tier": "L5",
                "content": "Working context for current task",
                "session_id": "sess-test-001",
                "metadata": {"key": "current_task"},
            },
        }
        result = await agent.handle_message(msg)
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_query_tier_l0(self, agent):
        msg = {
            "action": "lexicon.query_tier",
            "tenant_id": TEST_TENANT,
            "user_id": TEST_USER,
            "payload": {
                "action": "query_tier",
                "tier": "L0",
                "key": "preferences.communication_style",
            },
        }
        result = await agent.handle_message(msg)
        assert result["success"] is True
        assert result["data"]["result"] == "balanced"

    @pytest.mark.asyncio
    async def test_governor_status(self, agent):
        msg = {
            "action": "lexicon.get_governor_status",
            "tenant_id": TEST_TENANT,
            "user_id": TEST_USER,
            "payload": {"action": "get_governor_status"},
        }
        result = await agent.handle_message(msg)
        assert result["success"] is True
        assert "l3_retention_days" in result["data"]

    @pytest.mark.asyncio
    async def test_session_end(self, agent):
        # Store L5 data
        await agent.handle_message({
            "action": "lexicon.store_memory",
            "tenant_id": TEST_TENANT,
            "user_id": TEST_USER,
            "payload": {
                "action": "store_memory",
                "tier": "L5",
                "content": "Final decision: use event sourcing pattern",
                "session_id": "sess-end-test",
                "metadata": {"key": "decision_architecture"},
            },
        })

        # End session
        msg = {
            "action": "lexicon.session_end",
            "tenant_id": TEST_TENANT,
            "user_id": TEST_USER,
            "payload": {"action": "session_end", "session_id": "sess-end-test"},
        }
        result = await agent.handle_message(msg)
        assert result["success"] is True
        assert "promoted" in result["data"]

    @pytest.mark.asyncio
    async def test_initialize_user_memory(self, agent):
        new_tenant = "new-tenant"
        new_user = "new-user"
        await agent.initialize_user_memory(new_tenant, new_user)

        # Should be able to query the new user's L0
        msg = {
            "action": "lexicon.query_tier",
            "tenant_id": new_tenant,
            "user_id": new_user,
            "payload": {"action": "query_tier", "tier": "L0"},
        }
        result = await agent.handle_message(msg)
        assert result["success"] is True
        assert "identity" in result["data"]["result"]

    @pytest.mark.asyncio
    async def test_promote_l3_to_l1(self, agent):
        # First, store an L3 entry
        store_result = await agent.handle_message({
            "action": "lexicon.store_memory",
            "tenant_id": TEST_TENANT,
            "user_id": TEST_USER,
            "payload": {
                "action": "store_memory",
                "tier": "L3",
                "content": "Redis Streams provide durable ordered message delivery.",
                "metadata": {"event_type": "learning"},
                "tags": ["redis", "architecture"],
            },
        })
        entry_id = store_result["data"]["entry_id"]

        # Promote L3→L1
        promote_msg = {
            "action": "lexicon.promote_memory",
            "tenant_id": TEST_TENANT,
            "user_id": TEST_USER,
            "payload": {
                "action": "promote_memory",
                "entry_id": entry_id,
                "source_tier": "L3",
                "target_tier": "L1",
                "category": "redis",
                "rationale": "Confirmed architectural knowledge.",
            },
        }
        result = await agent.handle_message(promote_msg)
        assert result["success"] is True
        assert result["data"]["target_tier"] == "L1"
        assert "new_entry_id" in result["data"]

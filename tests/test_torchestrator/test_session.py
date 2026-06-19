# tests/test_torchestrator/test_session.py
# Unit tests for SessionManager

import pytest
import asyncio
from aegis.agents.torchestrator.session import SessionManager
from aegis.schemas.torchestrator import Session, SessionState


@pytest.fixture
def session_manager():
    """Create a SessionManager without Redis (in-memory only)."""
    return SessionManager(redis_client=None)


@pytest.mark.asyncio
async def test_create_session(session_manager):
    session = await session_manager.create_session("tenant-1", "user-1")
    assert session.tenant_id == "tenant-1"
    assert session.user_id == "user-1"
    assert session.state == SessionState.ACTIVE
    assert len(session.history) == 0


@pytest.mark.asyncio
async def test_get_session(session_manager):
    session = await session_manager.create_session("tenant-1", "user-1")
    retrieved = await session_manager.get_session(session.session_id)
    assert retrieved is not None
    assert retrieved.session_id == session.session_id


@pytest.mark.asyncio
async def test_get_nonexistent_session(session_manager):
    retrieved = await session_manager.get_session("nonexistent-id")
    assert retrieved is None


@pytest.mark.asyncio
async def test_add_turn(session_manager):
    session = await session_manager.create_session("tenant-1", "user-1")
    turn = await session_manager.add_turn(session.session_id, "user", "Hello!")
    assert turn is not None
    assert turn.role == "user"
    assert turn.content == "Hello!"
    # Verify it's in the session
    updated = await session_manager.get_session(session.session_id)
    assert len(updated.history) == 1


@pytest.mark.asyncio
async def test_add_turn_to_closed_session(session_manager):
    session = await session_manager.create_session("tenant-1", "user-1")
    await session_manager.close_session(session.session_id)
    turn = await session_manager.add_turn(session.session_id, "user", "Can I still chat?")
    assert turn is None  # Should not allow turns on closed sessions


@pytest.mark.asyncio
async def test_close_session(session_manager):
    session = await session_manager.create_session("tenant-1", "user-1")
    result = await session_manager.close_session(session.session_id)
    assert result is True
    updated = await session_manager.get_session(session.session_id)
    assert updated.state == SessionState.CLOSED


@pytest.mark.asyncio
async def test_pause_and_resume_session(session_manager):
    session = await session_manager.create_session("tenant-1", "user-1")
    await session_manager.pause_session(session.session_id)
    paused = await session_manager.get_session(session.session_id)
    assert paused.state == SessionState.PAUSED

    resumed = await session_manager.resume_session(session.session_id)
    assert resumed is not None
    assert resumed.state == SessionState.ACTIVE


@pytest.mark.asyncio
async def test_cannot_resume_closed_session(session_manager):
    session = await session_manager.create_session("tenant-1", "user-1")
    await session_manager.close_session(session.session_id)
    resumed = await session_manager.resume_session(session.session_id)
    assert resumed is None


@pytest.mark.asyncio
async def test_list_sessions(session_manager):
    await session_manager.create_session("tenant-1", "user-1")
    await session_manager.create_session("tenant-1", "user-1")
    await session_manager.create_session("tenant-1", "user-2")  # Different user

    sessions = await session_manager.list_sessions("tenant-1", "user-1")
    assert len(sessions) == 2


@pytest.mark.asyncio
async def test_get_context_for_oracle(session_manager):
    session = await session_manager.create_session("tenant-1", "user-1")
    await session_manager.add_turn(session.session_id, "user", "What is Python?")
    await session_manager.add_turn(session.session_id, "assistant", "Python is a programming language.")
    await session_manager.add_turn(session.session_id, "user", "Tell me more.")

    context = await session_manager.get_context_for_oracle(session.session_id)
    assert "What is Python?" in context
    assert "programming language" in context
    assert "Tell me more" in context


@pytest.mark.asyncio
async def test_context_respects_token_budget(session_manager):
    session = await session_manager.create_session("tenant-1", "user-1")
    # Add many turns
    for i in range(50):
        await session_manager.add_turn(session.session_id, "user", f"Message {i} " * 100)

    # Request with small budget
    context = await session_manager.get_context_for_oracle(
        session.session_id, max_tokens=100
    )
    # Should be truncated (100 tokens ≈ 400 chars)
    assert len(context) <= 1000  # Some tolerance


@pytest.mark.asyncio
async def test_cleanup_expired(session_manager):
    s1 = await session_manager.create_session("tenant-1", "user-1")
    s2 = await session_manager.create_session("tenant-1", "user-1")
    await session_manager.close_session(s1.session_id)

    cleaned = await session_manager.cleanup_expired()
    assert cleaned == 1
    # s2 should still be accessible
    assert await session_manager.get_session(s2.session_id) is not None

# tests/test_torchestrator/test_agent.py
# Integration tests for the TOrchestrator agent

import pytest
import asyncio
from aegis.agents.torchestrator.agent import TOrchestrator
from aegis.schemas.torchestrator import (
    ChatInput,
    ChatOutput,
    TOrchestratorAction,
    TOrchestratorRequest,
)


@pytest.fixture
def torchestrator():
    """Create a TOrchestrator without bus connections (standalone mode)."""
    return TOrchestrator(
        bus_publisher=None,
        bus_subscriber=None,
        redis_client=None,
        config={}
    )


@pytest.mark.asyncio
async def test_startup_shutdown(torchestrator):
    """Test that startup and shutdown don't raise."""
    await torchestrator.startup()
    await torchestrator.shutdown()


@pytest.mark.asyncio
async def test_chat_creates_session(torchestrator):
    """Chat without session_id should create a new session."""
    chat_input = ChatInput(
        message="Hello!",
        tenant_id="test-tenant",
        user_id="test-user",
    )
    output = await torchestrator.chat(chat_input)
    assert isinstance(output, ChatOutput)
    assert output.session_id  # Should have a session ID
    assert output.response  # Should have some response


@pytest.mark.asyncio
async def test_chat_maintains_session(torchestrator):
    """Multiple chats with same session_id should maintain context."""
    # First message
    chat_input = ChatInput(
        message="Hello!",
        tenant_id="test-tenant",
        user_id="test-user",
    )
    output1 = await torchestrator.chat(chat_input)
    session_id = output1.session_id

    # Second message in same session
    chat_input2 = ChatInput(
        message="What did I just say?",
        session_id=session_id,
        tenant_id="test-tenant",
        user_id="test-user",
    )
    output2 = await torchestrator.chat(chat_input2)
    assert output2.session_id == session_id


@pytest.mark.asyncio
async def test_process_request_chat(torchestrator):
    """Test process_request with CHAT action."""
    request = TOrchestratorRequest(
        action=TOrchestratorAction.CHAT,
        message="What is Python?",
        tenant_id="test-tenant",
        user_id="test-user",
    )
    response = await torchestrator.process_request(request)
    assert response.success is True
    assert response.session_id
    assert response.latency_ms > 0


@pytest.mark.asyncio
async def test_process_request_list_sessions(torchestrator):
    """Test listing sessions."""
    # Create a session first
    chat_input = ChatInput(
        message="Hi",
        tenant_id="test-tenant",
        user_id="test-user",
    )
    await torchestrator.chat(chat_input)

    # List sessions
    request = TOrchestratorRequest(
        action=TOrchestratorAction.LIST_SESSIONS,
        tenant_id="test-tenant",
        user_id="test-user",
    )
    response = await torchestrator.process_request(request)
    assert response.success is True
    assert "1" in response.response  # Should find 1 session


@pytest.mark.asyncio
async def test_process_request_close_session(torchestrator):
    """Test closing a session."""
    # Create a session
    chat_input = ChatInput(
        message="Hi",
        tenant_id="test-tenant",
        user_id="test-user",
    )
    output = await torchestrator.chat(chat_input)

    # Close it
    request = TOrchestratorRequest(
        action=TOrchestratorAction.CLOSE_SESSION,
        session_id=output.session_id,
        tenant_id="test-tenant",
        user_id="test-user",
    )
    response = await torchestrator.process_request(request)
    assert response.success is True
    assert "closed" in response.response.lower()


@pytest.mark.asyncio
async def test_intent_classification_in_pipeline(torchestrator):
    """Test that intent classification feeds into the pipeline correctly."""
    # File operation should be detected
    chat_input = ChatInput(
        message="Create a file called test.txt with Hello World",
        tenant_id="test-tenant",
        user_id="test-user",
    )
    output = await torchestrator.chat(chat_input)
    assert output.metadata.get("intent_category") == "file_operation"


@pytest.mark.asyncio
async def test_scheduling_intent_in_pipeline(torchestrator):
    """Test scheduling intent detection."""
    chat_input = ChatInput(
        message="Schedule a nightly backup at 2 AM",
        tenant_id="test-tenant",
        user_id="test-user",
    )
    output = await torchestrator.chat(chat_input)
    assert output.metadata.get("intent_category") == "scheduling"


@pytest.mark.asyncio
async def test_git_intent_in_pipeline(torchestrator):
    """Test git operation intent detection."""
    chat_input = ChatInput(
        message="Start a new feature branch called feature/auth",
        tenant_id="test-tenant",
        user_id="test-user",
    )
    output = await torchestrator.chat(chat_input)
    assert output.metadata.get("intent_category") == "git_operation"

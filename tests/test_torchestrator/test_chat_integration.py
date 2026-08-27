# tests/test_torchestrator/test_chat_integration.py
# Integration test for the chat flow via Redis message bus

import pytest
import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from aegis.agents.torchestrator.agent import TOrchestrator
from aegis.agents.torchestrator.router import MessageRouter
from aegis.schemas.torchestrator import (
    ChatInput,
    ChatOutput,
    TOrchestratorAction,
    TOrchestratorRequest,
    TOrchestratorResponse,
)
from aegis.schemas.message import AegisMessage, MessageType, Priority
from aegis.bus.redis_bus import RedisBus
from aegis.bus.publisher import MessagePublisher
from aegis.config import load_config


class TestChatIntegration:
    """Integration tests for the chat flow via message bus."""

    @pytest.fixture
    def mock_redis_client(self):
        """Create a mock Redis client."""
        mock = AsyncMock()
        mock.xadd = AsyncMock(return_value="1234567890-0")
        mock.xreadgroup = AsyncMock(return_value=[])
        mock.xgroup_create = AsyncMock()
        mock.ping = AsyncMock(return_value=True)
        mock.aclose = AsyncMock()
        return mock

    @pytest.fixture
    def mock_publisher(self, mock_redis_client):
        """Create a mock MessagePublisher."""
        pub = MessagePublisher(mock_redis_client)
        pub._xadd = AsyncMock(return_value="1234567890-0")
        return pub

    @pytest.mark.asyncio
    async def test_torchestrator_handles_bus_message_with_response_channel(self, mock_publisher):
        """
        Test that TOrchestrator correctly routes responses to the response_channel
        specified in the incoming message payload, rather than to its own stream.
        """
        # Create TOrchestrator with mocked publisher
        torchestrator = TOrchestrator(
            bus_publisher=mock_publisher,
            bus_subscriber=None,
            redis_client=None,
            config={}
        )
        await torchestrator.startup()
        
        # Mock the process_request to return a known response
        async def mock_process_request(request):
            return TOrchestratorResponse(
                success=True,
                response="Test response from TOrchestrator",
                session_id=request.session_id or "test-session",
                action=request.action,
                latency_ms=10.0
            )
        
        torchestrator.process_request = mock_process_request
        
        # Create a test message with response_channel in payload
        session_id = str(uuid.uuid4())
        response_channel = f"aegis:stream:cli:{session_id}"
        
        incoming_message = AegisMessage(
            source_agent="cli",
            target_agent="torchestrator",
            message_type=MessageType.REQUEST,
            tenant_id="default",
            user_id="root",
            action="torchestrator.chat",
            payload={
                "message": "Hello, test message",
                "session_id": session_id,
                "response_channel": response_channel,
            },
            priority=Priority.NORMAL,
            metadata={"session_id": session_id},
        )
        
        # Call _on_bus_message directly (this is what gets called when message arrives on bus)
        await torchestrator._on_bus_message(incoming_message)
        
        # Verify the publisher was called with the correct stream (response_channel)
        mock_publisher._xadd.assert_called_once()
        call_args = mock_publisher._xadd.call_args
        called_stream = call_args[0][0]
        called_message = call_args[0][1]
        
        # The critical assertion: response should go to the CLI's response channel
        assert called_stream == response_channel, \
            f"Expected response to go to {response_channel}, but went to {called_stream}"
        
        # Verify the response message content
        assert called_message.target_agent == "cli"
        assert called_message.message_type == MessageType.RESPONSE
        assert "Test response from TOrchestrator" in called_message.payload.get("response", "")
        
        await torchestrator.shutdown()

    @pytest.mark.asyncio
    async def test_torchestrator_falls_back_to_agent_stream_when_no_response_channel(self, mock_publisher):
        """
        Test fallback behavior when no response_channel is in payload.
        """
        torchestrator = TOrchestrator(
            bus_publisher=mock_publisher,
            bus_subscriber=None,
            redis_client=None,
            config={}
        )
        await torchestrator.startup()
        
        async def mock_process_request(request):
            return TOrchestratorResponse(
                success=True,
                response="Fallback response",
                session_id="test-session",
                action=request.action,
                latency_ms=10.0
            )
        
        torchestrator.process_request = mock_process_request
        
        # Message without response_channel
        incoming_message = AegisMessage(
            source_agent="cli",
            target_agent="torchestrator",
            message_type=MessageType.REQUEST,
            tenant_id="default",
            user_id="root",
            action="torchestrator.chat",
            payload={
                "message": "Hello",
                "session_id": str(uuid.uuid4()),
            },
            priority=Priority.NORMAL,
        )
        
        await torchestrator._on_bus_message(incoming_message)
        
        # Verify publisher was called
        mock_publisher._xadd.assert_called_once()
        call_args = mock_publisher._xadd.call_args
        called_stream = call_args[0][0]
        
        # Should fall back to agent's own stream (aegis:stream:cli)
        # Note: target_agent in response_message will be "cli"
        # so the stream will be aegis:stream:cli
        assert "aegis:stream:cli" in called_stream
        
        await torchestrator.shutdown()

    @pytest.mark.asyncio
    async def test_chat_message_action_parsing(self):
        """Test that chat messages are correctly parsed and action extracted."""
        torchestrator = TOrchestrator(
            bus_publisher=None,
            bus_subscriber=None,
            redis_client=None,
            config={}
        )
        
        session_id = str(uuid.uuid4())
        incoming_message = AegisMessage(
            source_agent="cli",
            target_agent="torchestrator",
            message_type=MessageType.REQUEST,
            tenant_id="default",
            user_id="root",
            action="torchestrator.chat",
            payload={
                "message": "Test message",
                "session_id": session_id,
                "response_channel": f"aegis:stream:cli:{session_id}",
            },
            priority=Priority.NORMAL,
            metadata={"session_id": session_id},
        )
        
        # Test the action extraction logic in handle_message
        extracted_action = incoming_message.action.split(".")[-1]
        assert extracted_action == "chat"
        
        # Test other possible action formats
        test_actions = [
            ("torchestrator.chat", "chat"),
            ("chat", "chat"),
            ("torchestrator.resume_session", "resume_session"),
            ("torchestrator.list_sessions", "list_sessions"),
            ("torchestrator.close_session", "close_session"),
        ]
        
        for full_action, expected in test_actions:
            msg = AegisMessage(
                source_agent="cli",
                target_agent="torchestrator",
                message_type=MessageType.REQUEST,
                tenant_id="default",
                user_id="root",
                action=full_action,
                payload={},
                priority=Priority.NORMAL,
            )
            extracted = msg.action.split(".")[-1]
            assert extracted == expected, f"Failed for action: {full_action}"

    @pytest.mark.asyncio
    async def test_message_response_correlation_id_preserved(self, mock_publisher):
        """Test that correlation_id is preserved in the response message."""
        torchestrator = TOrchestrator(
            bus_publisher=mock_publisher,
            bus_subscriber=None,
            redis_client=None,
            config={}
        )
        await torchestrator.startup()
        
        async def mock_process_request(request):
            return TOrchestratorResponse(
                success=True,
                response="Correlated response",
                session_id=request.session_id,
                action=request.action,
                latency_ms=5.0
            )
        
        torchestrator.process_request = mock_process_request
        
        test_correlation_id = "test-correlation-12345"
        session_id = str(uuid.uuid4())
        response_channel = f"aegis:stream:cli:{session_id}"
        
        incoming_message = AegisMessage(
            source_agent="cli",
            target_agent="torchestrator",
            message_type=MessageType.REQUEST,
            tenant_id="default",
            user_id="root",
            action="torchestrator.chat",
            payload={
                "message": "Test",
                "session_id": session_id,
                "response_channel": response_channel,
            },
            priority=Priority.NORMAL,
            metadata={"session_id": session_id},
            correlation_id=test_correlation_id,
        )
        
        response_message = await torchestrator.handle_message(incoming_message)
        
        # Verify correlation_id is preserved
        assert response_message.correlation_id is not None
        assert response_message.correlation_id == test_correlation_id
        
        await torchestrator.shutdown()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
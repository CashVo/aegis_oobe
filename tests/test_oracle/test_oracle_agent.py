# tests/test_oracle/test_oracle_agent.py
"""Unit tests for the Oracle Agent."""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from aegis.schemas.message import AegisMessage, MessageType, Priority
from aegis.schemas.oracle import OracleAction, OracleRequest, OracleResponse
from aegis.agents.oracle.agent import OracleAgent


@pytest.fixture
def oracle_config():
    """Minimal Oracle configuration for testing."""
    return {
        "oracle": {
            "max_concurrent_requests": 2,
            "providers": {
                "ollama": {
                    "provider_type": "ollama",
                    "base_url": "http://localhost:11434",
                    "enabled": True,
                    "timeout_seconds": 30,
                    "max_concurrent": 2,
                    "max_retries": 1,
                }
            },
            "models": {
                "test-model": {
                    "llm_id": "test-model",
                    "provider": "ollama",
                    "context_window": 4096,
                    "preference_tags": ["default", "fast", "local"],
                    "supports_json_mode": True,
                    "supports_embeddings": False,
                }
            },
            "cache": {"enabled": False},
            "rate_limit": {"enabled": False},
        }
    }


@pytest.fixture
def sample_message():
    """Sample AegisMessage with an Oracle QUERY request."""
    return AegisMessage(
        source_agent="torchestrator",
        target_agent="oracle",
        message_type=MessageType.REQUEST,
        tenant_id="test-tenant",
        user_id="test-user",
        action="oracle.query",
        payload={
            "action": "query",
            "prompt": "What is the capital of France?",
            "temperature": 0.7,
            "max_tokens": 500,
        },
    )


class TestOracleAgent:
    """Tests for OracleAgent initialization and message handling."""

    def test_agent_id(self, oracle_config):
        agent = OracleAgent(config=oracle_config)
        assert agent.agent_id == "oracle"

    def test_subscriptions(self, oracle_config):
        agent = OracleAgent(config=oracle_config)
        assert "aegis:stream:oracle" in agent.subscriptions

    def test_initialization_subsystems(self, oracle_config):
        agent = OracleAgent(config=oracle_config)
        assert agent.llm_registry is not None
        assert agent.prompt_engine is not None
        assert agent.token_manager is not None
        assert agent.cache is not None
        assert agent.rate_limiter is not None

    @pytest.mark.asyncio
    async def test_handle_message_query(self, oracle_config, sample_message):
        """Test that a QUERY message is handled and returns a response."""
        agent = OracleAgent(config=oracle_config)

        # Mock the provider
        mock_provider = AsyncMock()
        mock_provider.generate.return_value = {
            "content": "The capital of France is Paris.",
            "tokens_used": {"prompt": 20, "completion": 10, "total": 30},
            "model": "test-model",
            "finish_reason": "stop",
        }

        agent.llm_registry._providers["ollama"] = mock_provider

        result = await agent.handle_message(sample_message)

        assert result is not None
        assert result.message_type == MessageType.RESPONSE
        assert result.target_agent == "torchestrator"
        payload = result.payload
        assert payload["success"] is True
        assert "Paris" in payload["content"]

    @pytest.mark.asyncio
    async def test_handle_message_error(self, oracle_config, sample_message):
        """Test that provider errors are handled gracefully."""
        agent = OracleAgent(config=oracle_config)

        # No providers registered → should error
        agent.llm_registry._providers.clear()

        result = await agent.handle_message(sample_message)

        assert result is not None
        assert result.message_type == MessageType.ERROR

    @pytest.mark.asyncio
    async def test_handle_embed(self, oracle_config):
        """Test embedding action handling."""
        agent = OracleAgent(config=oracle_config)

        # Register an embedding model
        from aegis.schemas.oracle import ModelDefinition
        agent.llm_registry._models["test-embed"] = ModelDefinition(
            llm_id="test-embed",
            provider="ollama",
            context_window=8192,
            preference_tags=["embedding"],
            supports_embeddings=True,
        )

        mock_provider = AsyncMock()
        mock_provider.embed.return_value = {
            "embeddings": [[0.1, 0.2, 0.3]],
            "dimensions": 3,
            "tokens_used": {"prompt": 5, "completion": 0, "total": 5},
        }
        agent.llm_registry._providers["ollama"] = mock_provider

        message = AegisMessage(
            source_agent="lexicon",
            target_agent="oracle",
            message_type=MessageType.REQUEST,
            tenant_id="test-tenant",
            user_id="test-user",
            action="oracle.embed",
            payload={
                "action": "embed",
                "prompt": "Hello world",
            },
        )

        result = await agent.handle_message(message)
        assert result is not None
        assert result.payload["success"] is True
        assert len(result.payload["content"]) == 1  # One embedding vector

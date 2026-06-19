# tests/test_oracle/test_llm_registry.py
"""Unit tests for the Model Registry."""

import pytest
from unittest.mock import AsyncMock

from aegis.schemas.oracle import ModelDefinition, ProviderConfig
from aegis.agents.oracle.llm_registry import (
    LLMRegistry,
    ModelNotFoundError,
    ProviderNotFoundError,
)


@pytest.fixture
def registry_config():
    return {
        "providers": {
            "ollama": {
                "provider_type": "ollama",
                "base_url": "http://localhost:11434",
                "enabled": True,
                "timeout_seconds": 30,
                "max_concurrent": 4,
                "max_retries": 1,
            }
        },
        "models": {
            "fast-model": {
                "llm_id": "fast-model",
                "provider": "ollama",
                "context_window": 4096,
                "preference_tags": ["fast", "default"],
                "supports_json_mode": True,
                "supports_embeddings": False,
            },
            "capable-model": {
                "llm_id": "capable-model",
                "provider": "ollama",
                "context_window": 128000,
                "preference_tags": ["capable"],
                "supports_json_mode": True,
                "supports_embeddings": False,
            },
            "embed-model": {
                "llm_id": "embed-model",
                "provider": "ollama",
                "context_window": 8192,
                "preference_tags": ["embedding"],
                "supports_embeddings": True,
                "supports_json_mode": False,
            },
        },
    }


class TestLLMRegistry:

    def test_list_models(self, registry_config):
        reg = LLMRegistry(registry_config)
        models = reg.list_models()
        assert "fast-model" in models
        assert "capable-model" in models
        assert "embed-model" in models

    def test_select_by_exact_name(self, registry_config):
        reg = LLMRegistry(registry_config)
        # Simulate active provider
        reg._providers["ollama"] = AsyncMock()
        model = reg.select_model("capable-model")
        assert model.llm_id == "capable-model"

    def test_select_by_tag(self, registry_config):
        reg = LLMRegistry(registry_config)
        reg._providers["ollama"] = AsyncMock()
        model = reg.select_model("fast")
        assert "fast" in model.preference_tags

    def test_select_default(self, registry_config):
        reg = LLMRegistry(registry_config)
        reg._providers["ollama"] = AsyncMock()
        model = reg.select_model(None)
        assert "default" in model.preference_tags

    def test_select_no_provider_raises(self, registry_config):
        reg = LLMRegistry(registry_config)
        # No active providers
        with pytest.raises(ModelNotFoundError):
            reg.select_model("fast")

    def test_select_embedding_model(self, registry_config):
        reg = LLMRegistry(registry_config)
        reg._providers["ollama"] = AsyncMock()
        model = reg.select_embedding_model()
        assert model.supports_embeddings is True

    def test_get_provider_missing(self, registry_config):
        reg = LLMRegistry(registry_config)
        with pytest.raises(ProviderNotFoundError):
            reg.get_provider("nonexistent")

    def test_register_model(self, registry_config):
        reg = LLMRegistry(registry_config)
        new_model = ModelDefinition(
            llm_id="new-model",
            provider="ollama",
            context_window=32000,
            preference_tags=["new"],
        )
        reg.register_model(new_model)
        assert "new-model" in reg.list_models()

    def test_select_json_mode(self, registry_config):
        reg = LLMRegistry(registry_config)
        reg._providers["ollama"] = AsyncMock()
        model = reg.select_model(None, require_json=True)
        assert model.supports_json_mode is True

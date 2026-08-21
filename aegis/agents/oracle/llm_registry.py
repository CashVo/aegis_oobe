# aegis/agents/oracle/llm_registry.py
# Implements: Part II §2.1 — Model selection and provider management
"""
Model Registry — Manages available LLM models, their capabilities,
and the providers that serve them. Handles model selection based on
preference tags ("fast", "capable", "local").
"""

from __future__ import annotations

import logging
from typing import Optional

import structlog

from aegis.schemas.oracle import ModelDefinition, ProviderConfig
from aegis.agents.oracle.providers.base import LLMProvider
from aegis.agents.oracle.providers.ollama import OllamaProvider
from aegis.agents.oracle.providers.openai_compat import OpenAICompatProvider
from aegis.agents.oracle.providers.openrouter import OpenRouterProvider

logger = structlog.get_logger(__name__)

# Default models — local-first per Part I, Principle 1
DEFAULT_MODELS: dict[str, dict] = {
    "llama3.2": {
        "llm_id": "llama3.2",
        "provider": "ollama",
        "display_name": "Llama 3.2 (Local)",
        "context_window": 128000,
        "preference_tags": ["local", "fast", "default"],
        "supports_json_mode": True,
        "supports_embeddings": False,
        "max_output_tokens": 4096,
    },
    "llama3.1:70b": {
        "llm_id": "llama3.1:70b",
        "provider": "ollama",
        "display_name": "Llama 3.1 70B (Local)",
        "context_window": 128000,
        "preference_tags": ["local", "capable"],
        "supports_json_mode": True,
        "supports_embeddings": False,
        "max_output_tokens": 4096,
    },
    "nomic-embed-text": {
        "llm_id": "nomic-embed-text",
        "provider": "ollama",
        "display_name": "Nomic Embed Text (Local)",
        "context_window": 8192,
        "preference_tags": ["local", "embedding"],
        "supports_json_mode": False,
        "supports_embeddings": True,
        "max_output_tokens": 0,
    },
    # OpenRouter free tier models (via OpenRouterProvider with tiered fallback)
    "nemotron-3-ultra": {
        "llm_id": "nvidia/nemotron-3-ultra-550b-a55b:free",
        "provider": "openrouter",
        "display_name": "Nemotron 3 Ultra (OpenRouter Free)",
        "context_window": 128000,
        "preference_tags": ["cloud", "capable", "complex", "default"],
        "supports_json_mode": True,
        "supports_embeddings": False,
        "max_output_tokens": 4096,
    },
    "llama-3.1-405b": {
        "llm_id": "meta-llama/llama-3.1-405b-instruct:free",
        "provider": "openrouter",
        "display_name": "Llama 3.1 405B (OpenRouter Free)",
        "context_window": 128000,
        "preference_tags": ["cloud", "capable", "complex"],
        "supports_json_mode": True,
        "supports_embeddings": False,
        "max_output_tokens": 4096,
    },
    "gemma-2-27b": {
        "llm_id": "google/gemma-2-27b-it:free",
        "provider": "openrouter",
        "display_name": "Gemma 2 27B (OpenRouter Free)",
        "context_window": 8192,
        "preference_tags": ["cloud", "fast"],
        "supports_json_mode": True,
        "supports_embeddings": False,
        "max_output_tokens": 4096,
    },
    "mistral-nemo": {
        "llm_id": "mistralai/mistral-nemo:free",
        "provider": "openrouter",
        "display_name": "Mistral Nemo (OpenRouter Free)",
        "context_window": 128000,
        "preference_tags": ["cloud", "long_ctx"],
        "supports_json_mode": True,
        "supports_embeddings": False,
        "max_output_tokens": 4096,
    },
    "qwen-2.5-72b": {
        "llm_id": "qwen/qwen-2.5-72b-instruct:free",
        "provider": "openrouter",
        "display_name": "Qwen 2.5 72B (OpenRouter Free)",
        "context_window": 32768,
        "preference_tags": ["cloud", "multilingual"],
        "supports_json_mode": True,
        "supports_embeddings": False,
        "max_output_tokens": 4096,
    },
    "llama-3.1-70b": {
        "llm_id": "meta-llama/llama-3.1-70b-instruct:free",
        "provider": "openrouter",
        "display_name": "Llama 3.1 70B (OpenRouter Free)",
        "context_window": 128000,
        "preference_tags": ["cloud", "fallback"],
        "supports_json_mode": True,
        "supports_embeddings": False,
        "max_output_tokens": 4096,
    },
}

DEFAULT_PROVIDERS: dict[str, dict] = {
    "ollama": {
        "provider_type": "ollama",
        "base_url": "http://localhost:11434",
        "enabled": True,
        "timeout_seconds": 120,
        "max_concurrent": 4,
        "max_retries": 3,
    },
    "openrouter": {
        "provider_type": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "enabled": True,
        "timeout_seconds": 60,
        "max_concurrent": 8,
        "max_retries": 3,
        "api_key_env": "OPENROUTER_API_KEY",
        "default_model": "nvidia/nemotron-3-ultra-550b-a55b:free",
    },
}

# Maps provider_type strings to their implementation class
PROVIDER_CLASS_MAP: dict[str, type[LLMProvider]] = {
    "ollama": OllamaProvider,
    "openai_compat": OpenAICompatProvider,
    "openrouter": OpenRouterProvider,
}


class ModelNotFoundError(Exception):
    """Raised when no model matches the requested preference."""
    pass


class ProviderNotFoundError(Exception):
    """Raised when the provider for a model is not registered or not enabled."""
    pass


class LLMRegistry:
    """
    Manages LLM model definitions and provider instances.

    Responsibilities:
    - Register and store model definitions
    - Select models based on preference tags
    - Instantiate and manage provider connections
    - Verify provider health on startup
    """

    def __init__(self, config: dict | None = None) -> None:
        """
        Initialize the registry from configuration.

        Args:
            config: Oracle section of aegis_config.yaml.
        """
        config = config or {}
        self._models: dict[str, ModelDefinition] = {}
        self._providers: dict[str, LLMProvider] = {}
        self._provider_configs: dict[str, ProviderConfig] = {}

        # Load provider configs
        providers_cfg = config.get("providers", DEFAULT_PROVIDERS)
        for name, pcfg in providers_cfg.items():
            self._provider_configs[name] = ProviderConfig(**pcfg)

        # Load model definitions
        models_cfg = config.get("models", DEFAULT_MODELS)
        for name, mcfg in models_cfg.items():
            self._models[name] = ModelDefinition(**mcfg)

        # Apply config overrides
        default_model = config.get("default_model")
        if default_model and default_model in self._models:
            model = self._models[default_model]
            if "default" not in model.preference_tags:
                model.preference_tags.append("default")

        logger.debug(
            "llm_registry.loaded",
            models=list(self._models.keys()),
            providers=list(self._provider_configs.keys()),
        )

    async def initialize_providers(self) -> None:
        """
        Instantiate provider objects and verify connectivity.
        Called during Oracle startup.
        """
        for name, pcfg in self._provider_configs.items():
            if not pcfg.enabled:
                logger.info("llm_registry.provider_disabled", provider=name)
                continue

            provider_cls = PROVIDER_CLASS_MAP.get(pcfg.provider_type)
            if provider_cls is None:
                logger.warning(
                    "llm_registry.unknown_provider_type",
                    provider=name,
                    provider_type=pcfg.provider_type,
                )
                continue

            provider = provider_cls(config=pcfg)
            healthy = await provider.health_check()

            if healthy:
                self._providers[name] = provider
                logger.info("llm_registry.provider_ready", provider=name)
            else:
                logger.warning(
                    "llm_registry.provider_unhealthy",
                    provider=name,
                    base_url=pcfg.base_url,
                )

    async def shutdown_providers(self) -> None:
        """Gracefully close all provider connections."""
        for name, provider in self._providers.items():
            await provider.close()
            logger.info("llm_registry.provider_closed", provider=name)
        self._providers.clear()

    def select_model(
        self,
        preference: str | None = None,
        require_json: bool = False,
    ) -> ModelDefinition:
        """
        Select the best model matching the preference.

        Selection priority:
        1. Exact llm_id match (if preference is a model name)
        2. Tag-based match (if preference is a tag like "fast", "capable")
        3. Default model (tagged "default")
        4. First available model

        Args:
            preference: Model name or preference tag.
            require_json: If True, only select models with JSON mode support.

        Returns:
            The selected ModelDefinition.

        Raises:
            ModelNotFoundError: If no suitable model is found.
        """
        candidates = list(self._models.values())

        # Filter to models whose provider is active
        active_providers = set(self._providers.keys())
        candidates = [m for m in candidates if m.provider in active_providers]

        # Filter out embedding-only models for generation
        candidates = [m for m in candidates if not m.supports_embeddings or m.supports_json_mode]

        if require_json:
            candidates = [m for m in candidates if m.supports_json_mode]

        if not candidates:
            raise ModelNotFoundError(
                f"No suitable model found for preference='{preference}', "
                f"require_json={require_json}"
            )

        if preference:
            # 1. Exact llm_id match
            for m in candidates:
                if m.llm_id == preference:
                    return m

            # 2. Tag-based match
            tagged = [m for m in candidates if preference in m.preference_tags]
            if tagged:
                return tagged[0]

        # 3. Default tag
        defaults = [m for m in candidates if "default" in m.preference_tags]
        if defaults:
            return defaults[0]

        # 4. First available
        return candidates[0]

    def select_embedding_model(
        self, preference: str | None = None
    ) -> ModelDefinition:
        """
        Select a model suitable for embedding generation.

        Args:
            preference: Optional model name or preference tag.

        Returns:
            ModelDefinition with embedding capability.

        Raises:
            ModelNotFoundError: If no embedding model is available.
        """
        active_providers = set(self._providers.keys())
        candidates = [
            m for m in self._models.values()
            if m.supports_embeddings and m.provider in active_providers
        ]

        if not candidates:
            raise ModelNotFoundError("No embedding model available.")

        if preference:
            for m in candidates:
                if m.llm_id == preference or preference in m.preference_tags:
                    return m

        return candidates[0]

    def get_provider(self, provider_name: str) -> LLMProvider:
        """
        Retrieve an active provider instance by name.

        Args:
            provider_name: The provider key (e.g., "ollama").

        Returns:
            The LLMProvider instance.

        Raises:
            ProviderNotFoundError: If the provider is not registered or not active.
        """
        provider = self._providers.get(provider_name)
        if provider is None:
            raise ProviderNotFoundError(
                f"Provider '{provider_name}' is not available. "
                f"Active providers: {list(self._providers.keys())}"
            )
        return provider

    def list_models(self) -> list[str]:
        """Return a list of all registered model IDs."""
        return list(self._models.keys())

    def list_providers(self) -> list[str]:
        """Return a list of all active (healthy) provider names."""
        return list(self._providers.keys())

    def register_model(self, llm_def: ModelDefinition) -> None:
        """
        Dynamically register a new model definition.

        Args:
            llm_def: The model definition to register.
        """
        self._models[llm_def.llm_id] = llm_def
        logger.info("llm_registry.llm_registered", model=llm_def.llm_id)

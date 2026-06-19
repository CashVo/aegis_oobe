# build_chunk_008.py
#
# CHUNK-008: Oracle (LLM Gateway)
# Implements: Part II §2.1 (Oracle role), Part VI §6.2 (Oracle Protocol),
#             Part I (Local-First, Event-Driven, Security as First-Class Citizen)
#
# Dependencies: CHUNK-001 (Base Layout & Schemas), CHUNK-002 (Redis Message Bus),
#               CHUNK-003 (Warden Security), CHUNK-006 (Lexicon Memory)
#
# Run from the root of the project-aegis directory:
#   python build_chunk_008.py

import os
import textwrap

CHUNK_008_FILES = {

    # ──────────────────────────────────────────────────────────────────────
    # 1. ORACLE PROTOCOL SCHEMAS
    # Implements: Part VI §6.2 — Oracle Protocol
    # ──────────────────────────────────────────────────────────────────────
    "aegis/schemas/oracle.py": '''
# aegis/schemas/oracle.py
# Implements: Part VI §6.2 — Oracle Protocol
"""
Oracle protocol schemas. Defines the canonical request/response contracts
for all LLM inference operations routed through The Oracle agent.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional, Union

from pydantic import BaseModel, Field

# Integration with CHUNK-006: Lexicon schemas for ContextPacket
try:
    from aegis.schemas.lexicon import ContextPacket
except ImportError:
    # Graceful degradation if Lexicon schemas not yet available
    ContextPacket = None  # type: ignore[assignment, misc]


class OracleAction(str, Enum):
    """Supported Oracle operations. Implements Part VI §6.2."""
    QUERY = "query"            # Standard LLM request
    STRUCTURED = "structured"  # JSON-mode / structured output
    EMBED = "embed"            # Embedding generation
    CLASSIFY = "classify"      # Classification task


class OracleRequest(BaseModel):
    """
    Canonical Oracle request contract.
    Implements: Part VI §6.2 — OracleRequest
    """
    action: OracleAction
    prompt: str
    system_prompt: Optional[str] = None
    context_packet: Optional[dict] = None  # Serialized ContextPacket from Lexicon
    llm_preference: Optional[str] = None  # "fast", "capable", "local", or model name
    temperature: float = 0.7
    max_tokens: int = 2000
    response_format: Optional[str] = None  # "json", "text", etc.


class OracleResponse(BaseModel):
    """
    Canonical Oracle response contract.
    Implements: Part VI §6.2 — OracleResponse
    """
    success: bool
    content: Union[str, dict, list] = ""
    llm_used: str = ""
    tokens_used: dict = Field(default_factory=lambda: {
        "prompt": 0, "completion": 0, "total": 0
    })
    cached: bool = False
    latency_ms: float = 0.0


class ModelDefinition(BaseModel):
    """Configuration for a registered LLM model."""
    llm_id: str
    provider: str  # "ollama", "openai_compat"
    display_name: Optional[str] = None
    context_window: int = 4096
    preference_tags: list[str] = Field(default_factory=list)
    supports_json_mode: bool = False
    supports_embeddings: bool = False
    default_temperature: float = 0.7
    max_output_tokens: int = 4096


class ProviderConfig(BaseModel):
    """Configuration for an LLM provider backend."""
    provider_type: str  # "ollama", "openai_compat"
    base_url: str = "http://localhost:11434"
    api_key_env: Optional[str] = None
    enabled: bool = True
    timeout_seconds: int = 120
    max_concurrent: int = 4
    max_retries: int = 3


class EmbeddingRequest(BaseModel):
    """Request specifically for embedding generation."""
    texts: list[str]
    model: Optional[str] = None


class EmbeddingResponse(BaseModel):
    """Response containing generated embeddings."""
    embeddings: list[list[float]]
    used: str
    dimensions: int
    latency_ms: float


class CacheEntry(BaseModel):
    """Schema for a cached Oracle response."""
    cache_key: str
    response_json: str
    used: str
    created_at: str
    expires_at: str
    hit_count: int = 0
''',

    # ──────────────────────────────────────────────────────────────────────
    # 2. ORACLE AGENT — Main Agent Implementation
    # Implements: Part II §2.1 (Oracle role), §2.3 (BaseAgent)
    # ──────────────────────────────────────────────────────────────────────
    "aegis/agents/oracle/__init__.py": '''
# aegis/agents/oracle/__init__.py
"""
Oracle — The LLM Gateway Agent.
Implements: Part II §2.1

A singleton gateway for all non-deterministic (LLM) requests. Every agent
requiring LLM inference must route through The Oracle. Manages model selection,
prompt templating, token budgets, rate limiting, and response caching.
"""

from aegis.agents.oracle.agent import OracleAgent

__all__ = ["OracleAgent"]
''',

    "aegis/agents/oracle/agent.py": '''
# aegis/agents/oracle/agent.py
# Implements: Part II §2.1, §2.2, §2.3 — Oracle Agent
"""
The Oracle Agent — singleton LLM Gateway for Project Aegis.

Responsibilities:
- Model selection via preference tags
- Prompt assembly with context packet integration
- Token budget management
- Response caching
- Rate limiting
- Embedding generation
- Structured (JSON-mode) output support

All requests are authorized through Warden before execution.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

import structlog

from aegis.agents.base import BaseAgent
from aegis.schemas.message import AegisMessage, MessageType, Priority
from aegis.schemas.oracle import (
    OracleAction,
    OracleRequest,
    OracleResponse,
)
from aegis.agents.oracle.llm_registry import LLMRegistry
from aegis.agents.oracle.prompt_engine import PromptEngine
from aegis.agents.oracle.token_manager import TokenManager
from aegis.agents.oracle.cache import ResponseCache
from aegis.agents.oracle.rate_limiter import RateLimiter
from aegis.agents.oracle.providers.base import LLMProvider, ProviderError

logger = structlog.get_logger(__name__)


class OracleAgent(BaseAgent):
    """
    The Oracle — LLM Gateway Agent.
    Implements: Part II §2.1, Part VI §6.2

    Singleton gateway for all LLM inference. Routes requests to the appropriate
    provider, manages caching, token budgets, and rate limiting.
    """

    agent_id: str = "oracle"
    subscriptions: list[str] = ["aegis:stream:oracle"]

    def __init__(self, config: dict | None = None) -> None:
        """
        Initialize Oracle with all subsystems.

        Args:
            config: Oracle configuration dict from aegis_config.yaml.
        """
        self._config = config or {}
        oracle_cfg = self._config.get("oracle", {})

        # Initialize subsystems
        self.llm_registry = LLMRegistry(oracle_cfg)
        self.prompt_engine = PromptEngine(oracle_cfg.get("templates", {}))
        self.token_manager = TokenManager(oracle_cfg.get("token_budget", {}))
        self.cache = ResponseCache(oracle_cfg.get("cache", {}))
        self.rate_limiter = RateLimiter(oracle_cfg.get("rate_limit", {}))

        # Internal state
        self._running = False
        self._request_semaphore = asyncio.Semaphore(
            oracle_cfg.get("max_concurrent_requests", 8)
        )

        logger.info("oracle.initialized", models=self.llm_registry.list_models())

    async def startup(self) -> None:
        """
        Agent initialization: subscribe to channels, verify providers.
        Implements: Part II §2.3 — BaseAgent.startup()
        """
        self._running = True

        # Initialize providers (verify connectivity)
        await self.llm_registry.initialize_providers()

        # Initialize cache storage
        await self.cache.initialize()

        logger.info(
            "oracle.started",
            providers=self.llm_registry.list_providers(),
            cache_enabled=self.cache.enabled,
        )

    async def shutdown(self) -> None:
        """
        Graceful teardown: flush cache, close provider connections.
        Implements: Part II §2.3 — BaseAgent.shutdown()
        """
        self._running = False
        await self.cache.flush()
        await self.llm_registry.shutdown_providers()
        logger.info("oracle.shutdown_complete")

    async def handle_message(self, message: AegisMessage) -> AegisMessage | None:
        """
        Process an incoming Oracle request.
        Implements: Part II §2.3 — BaseAgent.handle_message()

        Flow:
        1. Parse and validate request
        2. Acquire rate limiter permit
        3. Select model via registry
        4. Check response cache
        5. Assemble prompt via engine
        6. Validate token budget
        7. Execute LLM call via provider
        8. Cache response
        9. Return OracleResponse envelope

        Args:
            message: Incoming AegisMessage with OracleRequest payload.

        Returns:
            AegisMessage containing OracleResponse, or error response.
        """
        start_time = time.monotonic()
        correlation_id = message.correlation_id or message.message_id

        logger.info(
            "oracle.request_received",
            correlation_id=correlation_id,
            source=message.source_agent,
            action=message.payload.get("action", "unknown"),
        )

        try:
            # 1. Parse request
            request = OracleRequest(**message.payload)

            # 2. Rate limiting
            await self.rate_limiter.acquire(
                tenant_id=message.tenant_id,
                user_id=message.user_id,
            )

            # 3. Route by action type
            async with self._request_semaphore:
                if request.action == OracleAction.EMBED:
                    response = await self._handle_embed(request, message)
                elif request.action == OracleAction.CLASSIFY:
                    response = await self._handle_classify(request, message)
                elif request.action == OracleAction.STRUCTURED:
                    response = await self._handle_structured(request, message)
                else:
                    response = await self._handle_query(request, message)

            elapsed_ms = (time.monotonic() - start_time) * 1000
            response.latency_ms = elapsed_ms

            logger.info(
                "oracle.request_complete",
                correlation_id=correlation_id,
                action=request.action.value,
                model=response.llm_used,
                cached=response.cached,
                latency_ms=round(elapsed_ms, 2),
                tokens=response.tokens_used,
            )

            return self._build_response_message(message, response)

        except ProviderError as e:
            elapsed_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "oracle.provider_error",
                correlation_id=correlation_id,
                error=str(e),
            )
            return self._build_error_message(
                message, f"Provider error: {e}", elapsed_ms
            )
        except Exception as e:
            elapsed_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "oracle.request_failed",
                correlation_id=correlation_id,
                error=str(e),
                exc_info=True,
            )
            return self._build_error_message(
                message, f"Oracle error: {e}", elapsed_ms
            )

    # ── Action Handlers ──────────────────────────────────────────────

    async def _handle_query(
        self, request: OracleRequest, message: AegisMessage
    ) -> OracleResponse:
        """
        Handle a standard QUERY action.
        Implements: Part VI §6.2 — OracleAction.QUERY
        """
        # Select model
        llm_def = self.llm_registry.select_model(request.llm_preference)
        provider = self.llm_registry.get_provider(llm_def.provider)

        # Check cache
        cache_key = self.cache.compute_key(request, llm_def.llm_id)
        cached = await self.cache.get(cache_key)
        if cached is not None:
            return OracleResponse(
                success=True,
                content=cached["content"],
                llm_used=cached["llm_used"],
                tokens_used=cached.get("tokens_used", {}),
                cached=True,
            )

        # Assemble prompt
        system_prompt, user_prompt = self.prompt_engine.assemble(
            prompt=request.prompt,
            system_prompt=request.system_prompt,
            context_packet=request.context_packet,
        )

        # Validate token budget
        estimated_input = self.token_manager.estimate_tokens(
            system_prompt + user_prompt
        )
        self.token_manager.validate_budget(
            estimated_input=estimated_input,
            max_output=request.max_tokens,
            context_window=llm_def.context_window,
        )

        # Execute LLM call
        result = await provider.generate(
            llm_id=llm_def.llm_id,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )

        # Cache the response
        response = OracleResponse(
            success=True,
            content=result["content"],
            llm_used=llm_def.llm_id,
            tokens_used=result.get("tokens_used", {}),
        )
        await self.cache.store(cache_key, response)

        # Track token usage
        self.token_manager.record_usage(
            tenant_id=message.tenant_id,
            user_id=message.user_id,
            tokens=result.get("tokens_used", {}),
        )

        return response

    async def _handle_structured(
        self, request: OracleRequest, message: AegisMessage
    ) -> OracleResponse:
        """
        Handle a STRUCTURED action (JSON-mode output).
        Implements: Part VI §6.2 — OracleAction.STRUCTURED
        """
        llm_def = self.llm_registry.select_model(
            request.llm_preference, require_json=True
        )
        provider = self.llm_registry.get_provider(llm_def.provider)

        system_prompt, user_prompt = self.prompt_engine.assemble(
            prompt=request.prompt,
            system_prompt=request.system_prompt,
            context_packet=request.context_packet,
            force_json_instruction=True,
        )

        estimated_input = self.token_manager.estimate_tokens(
            system_prompt + user_prompt
        )
        self.token_manager.validate_budget(
            estimated_input=estimated_input,
            max_output=request.max_tokens,
            context_window=llm_def.context_window,
        )

        result = await provider.generate(
            llm_id=llm_def.llm_id,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            response_format="json",
        )

        # Attempt to parse JSON content
        import json
        content = result["content"]
        try:
            if isinstance(content, str):
                content = json.loads(content)
        except json.JSONDecodeError:
            logger.warning("oracle.structured_output_not_json", raw=content[:200])

        response = OracleResponse(
            success=True,
            content=content,
            llm_used=llm_def.llm_id,
            tokens_used=result.get("tokens_used", {}),
        )

        self.token_manager.record_usage(
            tenant_id=message.tenant_id,
            user_id=message.user_id,
            tokens=result.get("tokens_used", {}),
        )

        return response

    async def _handle_embed(
        self, request: OracleRequest, message: AegisMessage
    ) -> OracleResponse:
        """
        Handle an EMBED action (embedding generation).
        Implements: Part VI §6.2 — OracleAction.EMBED
        """
        llm_def = self.llm_registry.select_embedding_model(
            request.llm_preference
        )
        provider = self.llm_registry.get_provider(llm_def.provider)

        result = await provider.embed(
            llm_id=llm_def.llm_id,
            texts=[request.prompt],
        )

        return OracleResponse(
            success=True,
            content=result["embeddings"],
            llm_used=llm_def.llm_id,
            tokens_used=result.get("tokens_used", {}),
        )

    async def _handle_classify(
        self, request: OracleRequest, message: AegisMessage
    ) -> OracleResponse:
        """
        Handle a CLASSIFY action (classification via LLM).
        Implements: Part VI §6.2 — OracleAction.CLASSIFY

        Classification is a specialized QUERY that uses the classification
        prompt template and enforces structured JSON output.
        """
        llm_def = self.llm_registry.select_model(
            request.llm_preference, require_json=True
        )
        provider = self.llm_registry.get_provider(llm_def.provider)

        system_prompt, user_prompt = self.prompt_engine.assemble_classification(
            prompt=request.prompt,
            system_prompt=request.system_prompt,
            context_packet=request.context_packet,
        )

        estimated_input = self.token_manager.estimate_tokens(
            system_prompt + user_prompt
        )
        self.token_manager.validate_budget(
            estimated_input=estimated_input,
            max_output=request.max_tokens,
            context_window=llm_def.context_window,
        )

        result = await provider.generate(
            llm_id=llm_def.llm_id,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.2,  # Low temp for classification
            max_tokens=request.max_tokens,
            response_format="json",
        )

        import json
        content = result["content"]
        try:
            if isinstance(content, str):
                content = json.loads(content)
        except json.JSONDecodeError:
            logger.warning("oracle.classify_output_not_json", raw=content[:200])

        response = OracleResponse(
            success=True,
            content=content,
            llm_used=llm_def.llm_id,
            tokens_used=result.get("tokens_used", {}),
        )

        self.token_manager.record_usage(
            tenant_id=message.tenant_id,
            user_id=message.user_id,
            tokens=result.get("tokens_used", {}),
        )

        return response

    # ── Message Builders ─────────────────────────────────────────────

    def _build_response_message(
        self, original: AegisMessage, response: OracleResponse
    ) -> AegisMessage:
        """Build a response AegisMessage envelope from an OracleResponse."""
        return AegisMessage(
            correlation_id=original.correlation_id or original.message_id,
            source_agent=self.agent_id,
            target_agent=original.source_agent,
            message_type=MessageType.RESPONSE,
            tenant_id=original.tenant_id,
            user_id=original.user_id,
            action="oracle.response",
            payload=response.model_dump(),
            priority=original.priority,
            metadata={"original_action": original.action},
        )

    def _build_error_message(
        self, original: AegisMessage, error: str, latency_ms: float
    ) -> AegisMessage:
        """Build an error AegisMessage envelope."""
        response = OracleResponse(
            success=False,
            content=error,
            llm_used="",
            tokens_used={"prompt": 0, "completion": 0, "total": 0},
            latency_ms=latency_ms,
        )
        return AegisMessage(
            correlation_id=original.correlation_id or original.message_id,
            source_agent=self.agent_id,
            target_agent=original.source_agent,
            message_type=MessageType.ERROR,
            tenant_id=original.tenant_id,
            user_id=original.user_id,
            action="oracle.error",
            payload=response.model_dump(),
            priority=Priority.HIGH,
            metadata={"original_action": original.action, "error": error},
        )
''',

    # ──────────────────────────────────────────────────────────────────────
    # 3. MODEL REGISTRY
    # Implements: Part II §2.1 — "Manages model selection"
    # ──────────────────────────────────────────────────────────────────────
    "aegis/agents/oracle/llm_registry.py": '''
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
}

# Maps provider_type strings to their implementation class
PROVIDER_CLASS_MAP: dict[str, type[LLMProvider]] = {
    "ollama": OllamaProvider,
    "openai_compat": OpenAICompatProvider,
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
''',

    # ──────────────────────────────────────────────────────────────────────
    # 4. PROMPT ENGINE
    # Implements: Part II §2.1 — "Manages prompt templating"
    # ──────────────────────────────────────────────────────────────────────
    "aegis/agents/oracle/prompt_engine.py": '''
# aegis/agents/oracle/prompt_engine.py
# Implements: Part II §2.1 — Prompt templating and context assembly
"""
Prompt Engine — Assembles complete prompts from templates, context packets,
and user input. Handles context packet formatting and token-aware truncation.
"""

from __future__ import annotations

from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

# ── Default Templates ────────────────────────────────────────────────

DEFAULT_SYSTEM_PROMPT = (
    "You are Aegis, an intelligent AI assistant built on a multi-agent "
    "architecture. You are helpful, accurate, and concise. When you have "
    "relevant context about the user, incorporate it naturally into your "
    "responses."
)

CLASSIFICATION_SYSTEM_PROMPT = (
    "You are a classification engine. Analyze the input and return a JSON "
    "object with the following fields:\\n"
    '- "label": the classification label\\n'
    '- "confidence": a float between 0.0 and 1.0\\n'
    '- "reasoning": a brief explanation of the classification\\n'
    "Respond ONLY with valid JSON. No other text."
)

JSON_OUTPUT_INSTRUCTION = (
    "\\n\\nIMPORTANT: You MUST respond with valid JSON only. "
    "No markdown fences, no explanatory text outside the JSON structure."
)

CONTEXT_HEADER = "\\n\\n--- Relevant Context ---\\n"
CONTEXT_FOOTER = "\\n--- End Context ---\\n\\n"
CONTEXT_FRAGMENT_TEMPLATE = "[{tier}] (relevance: {relevance:.2f})\\n{content}\\n"


class PromptEngine:
    """
    Assembles prompts from components: system prompt, context packet,
    user prompt, and optional template instructions.

    Responsibilities:
    - Format context packets from Lexicon into prompt-ready text
    - Apply prompt templates for different action types
    - Insert JSON-mode instructions when required
    - Provide classification-specific prompt assembly
    """

    def __init__(self, config: dict | None = None) -> None:
        """
        Initialize the prompt engine.

        Args:
            config: Templates configuration dict.
        """
        config = config or {}
        self._default_system = config.get("default_system", DEFAULT_SYSTEM_PROMPT)
        self._custom_templates: dict[str, str] = config.get("custom", {})

    def assemble(
        self,
        prompt: str,
        system_prompt: str | None = None,
        context_packet: dict | None = None,
        force_json_instruction: bool = False,
    ) -> tuple[str, str]:
        """
        Assemble a complete (system_prompt, user_prompt) pair.

        Args:
            prompt: The user's raw prompt text.
            system_prompt: Optional override for the system prompt.
            context_packet: Serialized ContextPacket from Lexicon (CHUNK-006).
            force_json_instruction: If True, append JSON output instructions.

        Returns:
            Tuple of (assembled_system_prompt, assembled_user_prompt).
        """
        # System prompt
        sys_prompt = system_prompt or self._default_system

        if force_json_instruction:
            sys_prompt += JSON_OUTPUT_INSTRUCTION

        # User prompt with context
        user_prompt = prompt

        if context_packet:
            context_text = self._format_context_packet(context_packet)
            if context_text:
                user_prompt = context_text + user_prompt

        logger.debug(
            "prompt_engine.assembled",
            system_len=len(sys_prompt),
            user_len=len(user_prompt),
            has_context=context_packet is not None,
        )

        return sys_prompt, user_prompt

    def assemble_classification(
        self,
        prompt: str,
        system_prompt: str | None = None,
        context_packet: dict | None = None,
    ) -> tuple[str, str]:
        """
        Assemble prompts specifically for classification tasks.

        Uses the classification system prompt template and enforces
        JSON output format.

        Args:
            prompt: The text to classify.
            system_prompt: Optional override (defaults to classification template).
            context_packet: Optional context from Lexicon.

        Returns:
            Tuple of (system_prompt, user_prompt).
        """
        sys_prompt = system_prompt or CLASSIFICATION_SYSTEM_PROMPT

        user_prompt = prompt
        if context_packet:
            context_text = self._format_context_packet(context_packet)
            if context_text:
                user_prompt = context_text + user_prompt

        return sys_prompt, user_prompt

    def _format_context_packet(self, context_packet: dict) -> str:
        """
        Format a serialized ContextPacket into prompt-ready text.

        Expected context_packet structure (from Lexicon CHUNK-006):
        {
            "fragments": [
                {"tier": "L0", "content": "...", "relevance": 0.95},
                {"tier": "L1", "content": "...", "relevance": 0.82},
                ...
            ],
            "total_tokens": 1200,
            "tiers_queried": ["L0", "L1", "L2", "L3"]
        }

        Args:
            context_packet: Serialized ContextPacket dict.

        Returns:
            Formatted context string, or empty string if no fragments.
        """
        fragments = context_packet.get("fragments", [])
        if not fragments:
            return ""

        # Sort by relevance descending
        sorted_fragments = sorted(
            fragments, key=lambda f: f.get("relevance", 0), reverse=True
        )

        parts = [CONTEXT_HEADER]
        for frag in sorted_fragments:
            parts.append(
                CONTEXT_FRAGMENT_TEMPLATE.format(
                    tier=frag.get("tier", "??"),
                    relevance=frag.get("relevance", 0.0),
                    content=frag.get("content", ""),
                )
            )
        parts.append(CONTEXT_FOOTER)

        return "".join(parts)

    def get_template(self, name: str) -> str | None:
        """
        Retrieve a custom prompt template by name.

        Args:
            name: Template identifier.

        Returns:
            Template string if found, None otherwise.
        """
        return self._custom_templates.get(name)

    def register_template(self, name: str, template: str) -> None:
        """
        Register a custom prompt template.

        Args:
            name: Template identifier.
            template: The template string.
        """
        self._custom_templates[name] = template
        logger.info("prompt_engine.template_registered", name=name)
''',

    # ──────────────────────────────────────────────────────────────────────
    # 5. TOKEN MANAGER
    # Implements: Part II §2.1 — "Manages token budgets"
    # ──────────────────────────────────────────────────────────────────────
    "aegis/agents/oracle/token_manager.py": '''
# aegis/agents/oracle/token_manager.py
# Implements: Part II §2.1 — Token budget management
"""
Token Manager — Estimates token counts, validates requests against model
context windows, and tracks cumulative token usage per tenant/user.

Uses a lightweight word-based approximation (tokens ≈ words × 1.35)
to avoid external dependencies. Supports optional tiktoken integration
for higher accuracy when available.
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

# Approximation factor: ~1.35 tokens per word for English text
TOKENS_PER_WORD = 1.35
# Safety margin: reserve 5% of context window for overhead
SAFETY_MARGIN = 0.05


class TokenBudgetExceededError(Exception):
    """Raised when a request would exceed the model's context window."""
    pass


class TokenManager:
    """
    Manages token estimation, budget validation, and usage tracking.

    Responsibilities:
    - Estimate token count from text (lightweight approximation)
    - Validate that prompt + max_tokens fits within context window
    - Track cumulative token usage per tenant/user
    - Report usage statistics
    """

    def __init__(self, config: dict | None = None) -> None:
        """
        Initialize the token manager.

        Args:
            config: Token budget configuration.
        """
        config = config or {}
        self._tokens_per_word = config.get("tokens_per_word", TOKENS_PER_WORD)
        self._safety_margin = config.get("safety_margin", SAFETY_MARGIN)

        # Usage tracking: {(tenant_id, user_id): {"prompt": N, "completion": N, "total": N}}
        self._usage: dict[tuple[str, str], dict[str, int]] = defaultdict(
            lambda: {"prompt": 0, "completion": 0, "total": 0}
        )

        # Attempt to import tiktoken for accurate counting
        self._tiktoken_encoder = None
        try:
            import tiktoken
            self._tiktoken_encoder = tiktoken.get_encoding("cl100k_base")
            logger.info("token_manager.tiktoken_available")
        except ImportError:
            logger.info("token_manager.using_approximation")

    def estimate_tokens(self, text: str) -> int:
        """
        Estimate the token count of a text string.

        Uses tiktoken if available, otherwise falls back to word-based
        approximation (words × 1.35).

        Args:
            text: The text to estimate.

        Returns:
            Estimated token count.
        """
        if not text:
            return 0

        if self._tiktoken_encoder is not None:
            return len(self._tiktoken_encoder.encode(text))

        # Word-based approximation
        word_count = len(text.split())
        return int(word_count * self._tokens_per_word)

    def validate_budget(
        self,
        estimated_input: int,
        max_output: int,
        context_window: int,
    ) -> None:
        """
        Validate that a request fits within the model's context window.

        Formula: estimated_input + max_output + safety_reserve <= context_window

        Args:
            estimated_input: Estimated input token count.
            max_output: Requested max output tokens.
            context_window: Model's total context window size.

        Raises:
            TokenBudgetExceededError: If the request exceeds the budget.
        """
        safety_reserve = int(context_window * self._safety_margin)
        available = context_window - safety_reserve
        required = estimated_input + max_output

        if required > available:
            raise TokenBudgetExceededError(
                f"Token budget exceeded: {required} required "
                f"({estimated_input} input + {max_output} output) > "
                f"{available} available (context_window={context_window}, "
                f"safety_reserve={safety_reserve})"
            )

        logger.debug(
            "token_manager.budget_validated",
            estimated_input=estimated_input,
            max_output=max_output,
            available=available,
            utilization=f"{required / available * 100:.1f}%",
        )

    def record_usage(
        self,
        tenant_id: str,
        user_id: str,
        tokens: dict,
    ) -> None:
        """
        Record token usage for a tenant/user pair.

        Args:
            tenant_id: The tenant identifier.
            user_id: The user identifier.
            tokens: Dict with "prompt", "completion", "total" keys.
        """
        key = (tenant_id, user_id)
        self._usage[key]["prompt"] += tokens.get("prompt", 0)
        self._usage[key]["completion"] += tokens.get("completion", 0)
        self._usage[key]["total"] += tokens.get("total", 0)

        logger.debug(
            "token_manager.usage_recorded",
            tenant_id=tenant_id,
            user_id=user_id,
            session_total=self._usage[key]["total"],
        )

    def get_usage(self, tenant_id: str, user_id: str) -> dict[str, int]:
        """
        Get cumulative token usage for a tenant/user pair.

        Args:
            tenant_id: The tenant identifier.
            user_id: The user identifier.

        Returns:
            Dict with "prompt", "completion", "total" token counts.
        """
        return dict(self._usage.get((tenant_id, user_id), {
            "prompt": 0, "completion": 0, "total": 0
        }))

    def reset_usage(self, tenant_id: str | None = None, user_id: str | None = None) -> None:
        """
        Reset token usage counters.

        Args:
            tenant_id: If provided with user_id, reset specific user.
                       If None, reset all usage.
            user_id: Specific user to reset.
        """
        if tenant_id and user_id:
            key = (tenant_id, user_id)
            if key in self._usage:
                del self._usage[key]
        else:
            self._usage.clear()
        logger.info("token_manager.usage_reset", tenant_id=tenant_id, user_id=user_id)
''',

    # ──────────────────────────────────────────────────────────────────────
    # 6. RESPONSE CACHE
    # Implements: Part II §2.1 — "Manages response caching"
    # ──────────────────────────────────────────────────────────────────────
    "aegis/agents/oracle/cache.py": '''
# aegis/agents/oracle/cache.py
# Implements: Part II §2.1 — Response caching for Oracle
"""
Response Cache — SQLite-backed cache for LLM responses. Reduces redundant
inference calls by caching responses keyed on a hash of the request parameters.

Features:
- SHA-256 hash keys from (prompt + model + temperature + max_tokens)
- TTL-based expiration
- Hit count tracking
- Periodic cleanup of expired entries
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

import aiosqlite
import structlog

from aegis.schemas.oracle import OracleRequest, OracleResponse

logger = structlog.get_logger(__name__)

DEFAULT_CACHE_DB = "aegis_data/oracle_cache.db"
DEFAULT_TTL_SECONDS = 3600  # 1 hour
DEFAULT_MAX_ENTRIES = 10000


class ResponseCache:
    """
    SQLite-backed response cache for Oracle LLM responses.

    Cache keys are SHA-256 hashes of the canonical request parameters.
    Entries expire based on configurable TTL. Expired entries are cleaned
    up periodically.
    """

    def __init__(self, config: dict | None = None) -> None:
        """
        Initialize the cache.

        Args:
            config: Cache configuration from aegis_config.yaml.
        """
        config = config or {}
        self.enabled: bool = config.get("enabled", True)
        self._db_path: str = config.get("db_path", DEFAULT_CACHE_DB)
        self._ttl_seconds: int = config.get("ttl_seconds", DEFAULT_TTL_SECONDS)
        self._max_entries: int = config.get("max_entries", DEFAULT_MAX_ENTRIES)
        self._db: Optional[aiosqlite.Connection] = None
        self._initialized = False

    async def initialize(self) -> None:
        """Create the cache database and table if they don't exist."""
        if not self.enabled:
            logger.info("oracle_cache.disabled")
            return

        # Ensure directory exists
        db_dir = Path(self._db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS oracle_cache (
                cache_key TEXT PRIMARY KEY,
                response_json TEXT NOT NULL,
                llm_used TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                hit_count INTEGER DEFAULT 0
            )
        """)
        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_cache_expires
            ON oracle_cache(expires_at)
        """)
        await self._db.commit()
        self._initialized = True

        # Cleanup expired entries on startup
        await self._cleanup_expired()

        logger.info(
            "oracle_cache.initialized",
            db_path=self._db_path,
            ttl_seconds=self._ttl_seconds,
        )

    def compute_key(
        self, request: OracleRequest, llm_id: str
    ) -> str:
        """
        Compute a deterministic cache key from request parameters.

        The key is a SHA-256 hash of the canonical JSON representation
        of the cache-relevant fields.

        Args:
            request: The Oracle request.
            llm_id: The resolved model identifier.

        Returns:
            Hex-encoded SHA-256 hash string.
        """
        key_data = {
            "action": request.action.value,
            "prompt": request.prompt,
            "system_prompt": request.system_prompt or "",
            "llm_id": llm_id,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "response_format": request.response_format or "",
        }
        canonical = json.dumps(key_data, sort_keys=True, ensure_ascii=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    async def get(self, cache_key: str) -> dict | None:
        """
        Retrieve a cached response by key.

        Returns None if cache is disabled, key not found, or entry expired.

        Args:
            cache_key: The SHA-256 hash key.

        Returns:
            Dict with "content", "llm_used", "tokens_used" or None.
        """
        if not self.enabled or not self._initialized or self._db is None:
            return None

        now = datetime.now(timezone.utc).isoformat()

        async with self._db.execute(
            """
            SELECT response_json, llm_used, hit_count
            FROM oracle_cache
            WHERE cache_key = ? AND expires_at > ?
            """,
            (cache_key, now),
        ) as cursor:
            row = await cursor.fetchone()

        if row is None:
            return None

        # Increment hit count
        await self._db.execute(
            "UPDATE oracle_cache SET hit_count = ? WHERE cache_key = ?",
            (row[2] + 1, cache_key),
        )
        await self._db.commit()

        try:
            response_data = json.loads(row[0])
        except json.JSONDecodeError:
            logger.warning("oracle_cache.corrupt_entry", key=cache_key[:16])
            return None

        logger.debug("oracle_cache.hit", key=cache_key[:16])
        return response_data

    async def store(
        self, cache_key: str, response: OracleResponse
    ) -> None:
        """
        Store a response in the cache.

        Args:
            cache_key: The SHA-256 hash key.
            response: The OracleResponse to cache.
        """
        if not self.enabled or not self._initialized or self._db is None:
            return

        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=self._ttl_seconds)

        response_data = {
            "content": response.content,
            "llm_used": response.llm_used,
            "tokens_used": response.tokens_used,
        }

        await self._db.execute(
            """
            INSERT OR REPLACE INTO oracle_cache
            (cache_key, response_json, llm_used, created_at, expires_at, hit_count)
            VALUES (?, ?, ?, ?, ?, 0)
            """,
            (
                cache_key,
                json.dumps(response_data, default=str),
                response.llm_used,
                now.isoformat(),
                expires.isoformat(),
            ),
        )
        await self._db.commit()

        logger.debug("oracle_cache.stored", key=cache_key[:16])

    async def flush(self) -> None:
        """Flush all cache entries and close the database connection."""
        if self._db is not None:
            await self._db.execute("DELETE FROM oracle_cache")
            await self._db.commit()
            await self._db.close()
            self._db = None
            self._initialized = False
            logger.info("oracle_cache.flushed")

    async def invalidate(self, cache_key: str) -> None:
        """
        Remove a specific entry from the cache.

        Args:
            cache_key: The entry to invalidate.
        """
        if not self._initialized or self._db is None:
            return

        await self._db.execute(
            "DELETE FROM oracle_cache WHERE cache_key = ?", (cache_key,)
        )
        await self._db.commit()

    async def _cleanup_expired(self) -> None:
        """Remove all expired entries from the cache."""
        if not self._initialized or self._db is None:
            return

        now = datetime.now(timezone.utc).isoformat()
        cursor = await self._db.execute(
            "DELETE FROM oracle_cache WHERE expires_at <= ?", (now,)
        )
        deleted = cursor.rowcount
        await self._db.commit()

        if deleted and deleted > 0:
            logger.info("oracle_cache.cleanup", deleted=deleted)

    async def stats(self) -> dict[str, Any]:
        """
        Return cache statistics.

        Returns:
            Dict with total_entries, total_hits, oldest_entry, etc.
        """
        if not self._initialized or self._db is None:
            return {"enabled": self.enabled, "initialized": False}

        async with self._db.execute(
            "SELECT COUNT(*), COALESCE(SUM(hit_count), 0) FROM oracle_cache"
        ) as cursor:
            row = await cursor.fetchone()

        return {
            "enabled": self.enabled,
            "initialized": True,
            "total_entries": row[0] if row else 0,
            "total_hits": row[1] if row else 0,
            "ttl_seconds": self._ttl_seconds,
            "db_path": self._db_path,
        }
''',

    # ──────────────────────────────────────────────────────────────────────
    # 7. RATE LIMITER
    # Implements: Part II §2.1 — "Manages rate limiting"
    # ──────────────────────────────────────────────────────────────────────
    "aegis/agents/oracle/rate_limiter.py": '''
# aegis/agents/oracle/rate_limiter.py
# Implements: Part II §2.1 — Rate limiting for Oracle requests
"""
Rate Limiter — Sliding-window rate limiter for Oracle LLM requests.
Prevents abuse and manages provider load by limiting requests per
tenant/user within configurable time windows.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

DEFAULT_MAX_REQUESTS_PER_MINUTE = 30
DEFAULT_MAX_REQUESTS_PER_HOUR = 500


class RateLimitExceededError(Exception):
    """Raised when a tenant/user exceeds their rate limit."""
    pass


class RateLimiter:
    """
    Sliding-window rate limiter for Oracle requests.

    Tracks request timestamps per (tenant_id, user_id) and enforces
    configurable per-minute and per-hour limits.
    """

    def __init__(self, config: dict | None = None) -> None:
        """
        Initialize the rate limiter.

        Args:
            config: Rate limit configuration.
        """
        config = config or {}
        self._rpm: int = config.get(
            "max_requests_per_minute", DEFAULT_MAX_REQUESTS_PER_MINUTE
        )
        self._rph: int = config.get(
            "max_requests_per_hour", DEFAULT_MAX_REQUESTS_PER_HOUR
        )
        self._enabled: bool = config.get("enabled", True)

        # Sliding window: {(tenant, user): deque of timestamps}
        self._windows: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def acquire(self, tenant_id: str, user_id: str) -> None:
        """
        Acquire a rate limit permit. Blocks if limit is reached (with timeout).

        Args:
            tenant_id: The tenant identifier.
            user_id: The user identifier.

        Raises:
            RateLimitExceededError: If the rate limit is exceeded.
        """
        if not self._enabled:
            return

        async with self._lock:
            key = (tenant_id, user_id)
            now = time.monotonic()
            window = self._windows[key]

            # Purge timestamps older than 1 hour
            cutoff_hour = now - 3600
            while window and window[0] < cutoff_hour:
                window.popleft()

            # Check per-hour limit
            if len(window) >= self._rph:
                logger.warning(
                    "rate_limiter.hourly_exceeded",
                    tenant_id=tenant_id,
                    user_id=user_id,
                    limit=self._rph,
                )
                raise RateLimitExceededError(
                    f"Hourly rate limit exceeded ({self._rph} requests/hour)"
                )

            # Check per-minute limit
            cutoff_minute = now - 60
            recent = sum(1 for ts in window if ts >= cutoff_minute)
            if recent >= self._rpm:
                logger.warning(
                    "rate_limiter.minute_exceeded",
                    tenant_id=tenant_id,
                    user_id=user_id,
                    limit=self._rpm,
                )
                raise RateLimitExceededError(
                    f"Per-minute rate limit exceeded ({self._rpm} requests/minute)"
                )

            # Record this request
            window.append(now)

    def get_remaining(self, tenant_id: str, user_id: str) -> dict[str, int]:
        """
        Check remaining request allowance for a tenant/user.

        Args:
            tenant_id: The tenant identifier.
            user_id: The user identifier.

        Returns:
            Dict with "remaining_per_minute" and "remaining_per_hour".
        """
        key = (tenant_id, user_id)
        now = time.monotonic()
        window = self._windows.get(key, deque())

        cutoff_minute = now - 60
        cutoff_hour = now - 3600

        recent_minute = sum(1 for ts in window if ts >= cutoff_minute)
        recent_hour = sum(1 for ts in window if ts >= cutoff_hour)

        return {
            "remaining_per_minute": max(0, self._rpm - recent_minute),
            "remaining_per_hour": max(0, self._rph - recent_hour),
        }
''',

    # ──────────────────────────────────────────────────────────────────────
    # 8. PROVIDER — Abstract Base
    # Implements: Part I Principle 1 (Local-First), Part II §2.1
    # ──────────────────────────────────────────────────────────────────────
    "aegis/agents/oracle/providers/__init__.py": '''
# aegis/agents/oracle/providers/__init__.py
"""
LLM Provider implementations for the Oracle agent.
Local-first per Part I, Principle 1.
"""

from aegis.agents.oracle.providers.base import LLMProvider, ProviderError
from aegis.agents.oracle.providers.ollama import OllamaProvider
from aegis.agents.oracle.providers.openai_compat import OpenAICompatProvider

__all__ = ["LLMProvider", "ProviderError", "OllamaProvider", "OpenAICompatProvider"]
''',

    "aegis/agents/oracle/providers/base.py": '''
# aegis/agents/oracle/providers/base.py
# Implements: Part I Principle 1 — Local-First provider abstraction
"""
Abstract base class for LLM providers. All providers implement a common
interface for generation (chat completion), embedding, and health checks.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from aegis.schemas.oracle import ProviderConfig


class ProviderError(Exception):
    """Base exception for provider-related errors."""
    pass


class ProviderConnectionError(ProviderError):
    """Raised when a provider is unreachable."""
    pass


class ProviderTimeoutError(ProviderError):
    """Raised when a provider request times out."""
    pass


class ProviderModelError(ProviderError):
    """Raised when the requested model is not available on the provider."""
    pass


class LLMProvider(ABC):
    """
    Abstract base class for LLM provider implementations.

    All providers must support:
    - generate(): Chat completion / text generation
    - embed(): Embedding generation
    - health_check(): Connectivity verification
    - close(): Resource cleanup
    """

    def __init__(self, config: ProviderConfig) -> None:
        """
        Initialize the provider.

        Args:
            config: Provider configuration.
        """
        self.config = config
        self.base_url = config.base_url
        self.timeout = config.timeout_seconds
        self.max_retries = config.max_retries

    @abstractmethod
    async def generate(
        self,
        llm_id: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        response_format: str | None = None,
    ) -> dict[str, Any]:
        """
        Generate a text response from the LLM.

        Args:
            llm_id: The model to use for generation.
            system_prompt: The system-level prompt.
            user_prompt: The user's prompt.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens to generate.
            response_format: Optional format constraint ("json", None).

        Returns:
            Dict with keys: "content" (str), "tokens_used" (dict),
            "model" (str), "finish_reason" (str).
        """
        ...

    @abstractmethod
    async def embed(
        self,
        llm_id: str,
        texts: list[str],
    ) -> dict[str, Any]:
        """
        Generate embeddings for the given texts.

        Args:
            llm_id: The embedding model to use.
            texts: List of text strings to embed.

        Returns:
            Dict with keys: "embeddings" (list[list[float]]),
            "dimensions" (int), "tokens_used" (dict).
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """
        Check if the provider is reachable and operational.

        Returns:
            True if the provider is healthy, False otherwise.
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """Release any held resources (HTTP sessions, etc.)."""
        ...
''',

    # ──────────────────────────────────────────────────────────────────────
    # 9. PROVIDER — Ollama (Primary, Local-First)
    # Implements: Part I Principle 1 — Local-First
    # ──────────────────────────────────────────────────────────────────────
    "aegis/agents/oracle/providers/ollama.py": '''
# aegis/agents/oracle/providers/ollama.py
# Implements: Part I Principle 1 — Local-First LLM via Ollama
"""
Ollama LLM Provider — Primary provider for Project Aegis.

Connects to a locally running Ollama instance for:
- Chat completion (POST /api/chat)
- Embedding generation (POST /api/embed)
- Health check (GET /api/tags)

This is the default, local-first provider per Part I, Principle 1.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

import httpx
import structlog

from aegis.schemas.oracle import ProviderConfig
from aegis.agents.oracle.providers.base import (
    LLMProvider,
    ProviderConnectionError,
    ProviderTimeoutError,
    ProviderModelError,
    ProviderError,
)

logger = structlog.get_logger(__name__)


class OllamaProvider(LLMProvider):
    """
    Ollama LLM Provider — local inference via Ollama HTTP API.

    API Endpoints:
    - POST /api/chat — Chat completion
    - POST /api/embed — Embedding generation
    - GET  /api/tags — List available models (health check)
    """

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create the async HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout, connect=10.0),
            )
        return self._client

    async def generate(
        self,
        llm_id: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        response_format: str | None = None,
    ) -> dict[str, Any]:
        """
        Generate text via Ollama /api/chat endpoint.

        Args:
            llm_id: Ollama model name (e.g., "llama3.2").
            system_prompt: System message content.
            user_prompt: User message content.
            temperature: Sampling temperature.
            max_tokens: Max tokens in response.
            response_format: "json" for JSON mode, None for text.

        Returns:
            Dict with "content", "tokens_used", "model", "finish_reason".
        """
        client = self._get_client()

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        payload: dict[str, Any] = {
            "model": llm_id,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        if response_format == "json":
            payload["format"] = "json"

        for attempt in range(1, self.max_retries + 1):
            try:
                response = await client.post("/api/chat", json=payload)

                if response.status_code == 404:
                    raise ProviderModelError(
                        f"Model '{llm_id}' not found on Ollama. "
                        f"Run 'ollama pull {llm_id}' to download it."
                    )

                response.raise_for_status()
                data = response.json()

                # Extract token usage from Ollama response
                tokens_used = {
                    "prompt": data.get("prompt_eval_count", 0),
                    "completion": data.get("eval_count", 0),
                    "total": (
                        data.get("prompt_eval_count", 0)
                        + data.get("eval_count", 0)
                    ),
                }

                content = data.get("message", {}).get("content", "")

                logger.debug(
                    "ollama.generate_complete",
                    model=llm_id,
                    tokens=tokens_used,
                    attempt=attempt,
                )

                return {
                    "content": content,
                    "tokens_used": tokens_used,
                    "model": llm_id,
                    "finish_reason": data.get("done_reason", "stop"),
                }

            except httpx.ConnectError as e:
                raise ProviderConnectionError(
                    f"Cannot connect to Ollama at {self.base_url}. "
                    f"Is 'ollama serve' running? Error: {e}"
                ) from e

            except httpx.TimeoutException as e:
                if attempt == self.max_retries:
                    raise ProviderTimeoutError(
                        f"Ollama request timed out after {self.timeout}s "
                        f"({attempt} attempts). Model: {llm_id}"
                    ) from e
                wait = 2 ** attempt
                logger.warning(
                    "ollama.retry",
                    attempt=attempt,
                    wait_seconds=wait,
                    model=llm_id,
                )
                await asyncio.sleep(wait)

            except ProviderError:
                raise  # Re-raise our own errors

            except httpx.HTTPStatusError as e:
                raise ProviderError(
                    f"Ollama HTTP error {e.response.status_code}: {e.response.text[:500]}"
                ) from e

        raise ProviderError(f"Ollama generation failed after {self.max_retries} retries")

    async def embed(
        self,
        llm_id: str,
        texts: list[str],
    ) -> dict[str, Any]:
        """
        Generate embeddings via Ollama /api/embed endpoint.

        Args:
            llm_id: Embedding model name (e.g., "nomic-embed-text").
            texts: List of texts to embed.

        Returns:
            Dict with "embeddings", "dimensions", "tokens_used".
        """
        client = self._get_client()

        try:
            response = await client.post(
                "/api/embed",
                json={"model": llm_id, "input": texts},
            )

            if response.status_code == 404:
                raise ProviderModelError(
                    f"Embedding model '{llm_id}' not found. "
                    f"Run 'ollama pull {llm_id}' to download it."
                )

            response.raise_for_status()
            data = response.json()

            embeddings = data.get("embeddings", [])
            dimensions = len(embeddings[0]) if embeddings else 0

            logger.debug(
                "ollama.embed_complete",
                model=llm_id,
                count=len(texts),
                dimensions=dimensions,
            )

            return {
                "embeddings": embeddings,
                "dimensions": dimensions,
                "tokens_used": {
                    "prompt": data.get("prompt_eval_count", 0),
                    "completion": 0,
                    "total": data.get("prompt_eval_count", 0),
                },
            }

        except httpx.ConnectError as e:
            raise ProviderConnectionError(
                f"Cannot connect to Ollama at {self.base_url}: {e}"
            ) from e
        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(f"Ollama embedding error: {e}") from e

    async def health_check(self) -> bool:
        """
        Check Ollama connectivity via GET /api/tags.

        Returns:
            True if Ollama is reachable and responding.
        """
        try:
            client = self._get_client()
            response = await client.get("/api/tags", timeout=5.0)
            healthy = response.status_code == 200
            if healthy:
                models = [m["name"] for m in response.json().get("models", [])]
                logger.debug("ollama.health_ok", available_models=models)
            return healthy
        except Exception as e:
            logger.warning("ollama.health_failed", error=str(e))
            return False

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
            logger.debug("ollama.client_closed")
''',

    # ──────────────────────────────────────────────────────────────────────
    # 10. PROVIDER — OpenAI-Compatible
    # ──────────────────────────────────────────────────────────────────────
    "aegis/agents/oracle/providers/openai_compat.py": '''
# aegis/agents/oracle/providers/openai_compat.py
# Implements: Part I — Flexible provider for OpenAI-compatible APIs
"""
OpenAI-Compatible LLM Provider — Secondary provider for Project Aegis.

Supports any API compatible with the OpenAI chat completions and
embeddings endpoints. Useful for:
- OpenAI API
- Azure OpenAI
- Local servers with OpenAI-compatible APIs (e.g., LM Studio, vLLM)
- Any other compatible endpoint
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Optional

import httpx
import structlog

from aegis.schemas.oracle import ProviderConfig
from aegis.agents.oracle.providers.base import (
    LLMProvider,
    ProviderConnectionError,
    ProviderTimeoutError,
    ProviderModelError,
    ProviderError,
)

logger = structlog.get_logger(__name__)


class OpenAICompatProvider(LLMProvider):
    """
    OpenAI-compatible API provider.

    API Endpoints:
    - POST /v1/chat/completions — Chat completion
    - POST /v1/embeddings — Embedding generation
    - GET  /v1/models — List available models (health check)
    """

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        self._client: Optional[httpx.AsyncClient] = None
        self._api_key: Optional[str] = None

        # Resolve API key from environment variable
        if config.api_key_env:
            self._api_key = os.environ.get(config.api_key_env)
            if not self._api_key:
                logger.warning(
                    "openai_compat.no_api_key",
                    env_var=config.api_key_env,
                )

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create the async HTTP client with auth headers."""
        if self._client is None or self._client.is_closed:
            headers = {"Content-Type": "application/json"}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"

            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=httpx.Timeout(self.timeout, connect=10.0),
            )
        return self._client

    async def generate(
        self,
        llm_id: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        response_format: str | None = None,
    ) -> dict[str, Any]:
        """
        Generate text via OpenAI-compatible /v1/chat/completions.

        Args:
            llm_id: Model name (e.g., "gpt-4", "gpt-3.5-turbo").
            system_prompt: System message content.
            user_prompt: User message content.
            temperature: Sampling temperature.
            max_tokens: Max tokens in response.
            response_format: "json" for JSON object mode.

        Returns:
            Dict with "content", "tokens_used", "model", "finish_reason".
        """
        client = self._get_client()

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        payload: dict[str, Any] = {
            "model": llm_id,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if response_format == "json":
            payload["response_format"] = {"type": "json_object"}

        for attempt in range(1, self.max_retries + 1):
            try:
                response = await client.post(
                    "/v1/chat/completions", json=payload
                )

                if response.status_code == 404:
                    raise ProviderModelError(
                        f"Model '{llm_id}' not found on provider."
                    )

                if response.status_code == 401:
                    raise ProviderError(
                        "Authentication failed. Check your API key."
                    )

                if response.status_code == 429:
                    if attempt == self.max_retries:
                        raise ProviderError("Rate limited by provider.")
                    wait = 2 ** attempt
                    logger.warning(
                        "openai_compat.rate_limited",
                        attempt=attempt,
                        wait_seconds=wait,
                    )
                    await asyncio.sleep(wait)
                    continue

                response.raise_for_status()
                data = response.json()

                choice = data.get("choices", [{}])[0]
                content = choice.get("message", {}).get("content", "")
                finish_reason = choice.get("finish_reason", "stop")

                usage = data.get("usage", {})
                tokens_used = {
                    "prompt": usage.get("prompt_tokens", 0),
                    "completion": usage.get("completion_tokens", 0),
                    "total": usage.get("total_tokens", 0),
                }

                logger.debug(
                    "openai_compat.generate_complete",
                    model=llm_id,
                    tokens=tokens_used,
                )

                return {
                    "content": content,
                    "tokens_used": tokens_used,
                    "model": data.get("model", llm_id),
                    "finish_reason": finish_reason,
                }

            except httpx.ConnectError as e:
                raise ProviderConnectionError(
                    f"Cannot connect to {self.base_url}: {e}"
                ) from e

            except httpx.TimeoutException as e:
                if attempt == self.max_retries:
                    raise ProviderTimeoutError(
                        f"Request timed out after {self.timeout}s "
                        f"({attempt} attempts)"
                    ) from e
                wait = 2 ** attempt
                logger.warning(
                    "openai_compat.retry",
                    attempt=attempt,
                    wait_seconds=wait,
                )
                await asyncio.sleep(wait)

            except ProviderError:
                raise

            except httpx.HTTPStatusError as e:
                raise ProviderError(
                    f"HTTP error {e.response.status_code}: "
                    f"{e.response.text[:500]}"
                ) from e

        raise ProviderError(f"Generation failed after {self.max_retries} retries")

    async def embed(
        self,
        llm_id: str,
        texts: list[str],
    ) -> dict[str, Any]:
        """
        Generate embeddings via /v1/embeddings endpoint.

        Args:
            llm_id: Embedding model name.
            texts: List of texts to embed.

        Returns:
            Dict with "embeddings", "dimensions", "tokens_used".
        """
        client = self._get_client()

        try:
            response = await client.post(
                "/v1/embeddings",
                json={"model": llm_id, "input": texts},
            )
            response.raise_for_status()
            data = response.json()

            embeddings = [
                item["embedding"] for item in data.get("data", [])
            ]
            dimensions = len(embeddings[0]) if embeddings else 0

            usage = data.get("usage", {})
            tokens_used = {
                "prompt": usage.get("prompt_tokens", 0),
                "completion": 0,
                "total": usage.get("total_tokens", 0),
            }

            return {
                "embeddings": embeddings,
                "dimensions": dimensions,
                "tokens_used": tokens_used,
            }

        except httpx.ConnectError as e:
            raise ProviderConnectionError(
                f"Cannot connect to {self.base_url}: {e}"
            ) from e
        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(f"Embedding error: {e}") from e

    async def health_check(self) -> bool:
        """
        Check provider connectivity via GET /v1/models.

        Returns:
            True if the provider is reachable and responding.
        """
        try:
            client = self._get_client()
            response = await client.get("/v1/models", timeout=5.0)
            return response.status_code == 200
        except Exception as e:
            logger.warning("openai_compat.health_failed", error=str(e))
            return False

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
            logger.debug("openai_compat.client_closed")
''',

    # ──────────────────────────────────────────────────────────────────────
    # 11. UNIT TESTS
    # ──────────────────────────────────────────────────────────────────────
    "tests/test_oracle/__init__.py": '''
# tests/test_oracle/__init__.py
"""Tests for CHUNK-008: Oracle (LLM Gateway)."""
''',

    "tests/test_oracle/test_oracle_agent.py": '''
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
''',

    "tests/test_oracle/test_llm_registry.py": '''
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
''',

    "tests/test_oracle/test_prompt_engine.py": '''
# tests/test_oracle/test_prompt_engine.py
"""Unit tests for the Prompt Engine."""

import pytest
from aegis.agents.oracle.prompt_engine import PromptEngine


class TestPromptEngine:

    def test_basic_assembly(self):
        engine = PromptEngine()
        sys_p, user_p = engine.assemble(prompt="Hello world")
        assert "Hello world" in user_p
        assert len(sys_p) > 0  # Default system prompt

    def test_custom_system_prompt(self):
        engine = PromptEngine()
        sys_p, user_p = engine.assemble(
            prompt="test",
            system_prompt="Custom system instruction.",
        )
        assert sys_p == "Custom system instruction."

    def test_json_instruction(self):
        engine = PromptEngine()
        sys_p, _ = engine.assemble(
            prompt="test",
            force_json_instruction=True,
        )
        assert "JSON" in sys_p

    def test_context_packet_formatting(self):
        engine = PromptEngine()
        context = {
            "fragments": [
                {"tier": "L0", "content": "User prefers concise answers.", "relevance": 0.95},
                {"tier": "L1", "content": "Python expert.", "relevance": 0.80},
            ],
            "total_tokens": 50,
            "tiers_queried": ["L0", "L1"],
        }
        _, user_p = engine.assemble(
            prompt="What is Python?",
            context_packet=context,
        )
        assert "Relevant Context" in user_p
        assert "User prefers concise answers" in user_p
        assert "Python expert" in user_p
        assert "What is Python?" in user_p

    def test_empty_context_packet(self):
        engine = PromptEngine()
        _, user_p = engine.assemble(
            prompt="test",
            context_packet={"fragments": [], "total_tokens": 0, "tiers_queried": []},
        )
        assert user_p == "test"

    def test_classification_assembly(self):
        engine = PromptEngine()
        sys_p, user_p = engine.assemble_classification(prompt="Is this spam?")
        assert "classification" in sys_p.lower()
        assert "JSON" in sys_p
        assert "Is this spam?" in user_p

    def test_template_registration(self):
        engine = PromptEngine()
        engine.register_template("greeting", "Hello {name}!")
        assert engine.get_template("greeting") == "Hello {name}!"
        assert engine.get_template("nonexistent") is None

    def test_context_fragments_sorted_by_relevance(self):
        engine = PromptEngine()
        context = {
            "fragments": [
                {"tier": "L1", "content": "Low relevance.", "relevance": 0.30},
                {"tier": "L0", "content": "High relevance.", "relevance": 0.99},
            ],
        }
        _, user_p = engine.assemble(prompt="test", context_packet=context)
        # High relevance should appear before low relevance
        high_idx = user_p.index("High relevance")
        low_idx = user_p.index("Low relevance")
        assert high_idx < low_idx
''',

    "tests/test_oracle/test_token_manager.py": '''
# tests/test_oracle/test_token_manager.py
"""Unit tests for the Token Manager."""

import pytest
from aegis.agents.oracle.token_manager import TokenManager, TokenBudgetExceededError


class TestTokenManager:

    def test_estimate_empty(self):
        tm = TokenManager()
        assert tm.estimate_tokens("") == 0

    def test_estimate_basic(self):
        tm = TokenManager()
        tokens = tm.estimate_tokens("Hello world this is a test")
        # 6 words * ~1.35 ≈ 8 tokens (approximate)
        assert tokens > 0
        assert tokens < 20

    def test_validate_budget_ok(self):
        tm = TokenManager()
        # Should not raise
        tm.validate_budget(
            estimated_input=100,
            max_output=200,
            context_window=4096,
        )

    def test_validate_budget_exceeded(self):
        tm = TokenManager()
        with pytest.raises(TokenBudgetExceededError):
            tm.validate_budget(
                estimated_input=3000,
                max_output=2000,
                context_window=4096,
            )

    def test_record_and_get_usage(self):
        tm = TokenManager()
        tm.record_usage("t1", "u1", {"prompt": 100, "completion": 50, "total": 150})
        tm.record_usage("t1", "u1", {"prompt": 200, "completion": 100, "total": 300})
        usage = tm.get_usage("t1", "u1")
        assert usage["prompt"] == 300
        assert usage["completion"] == 150
        assert usage["total"] == 450

    def test_get_usage_empty(self):
        tm = TokenManager()
        usage = tm.get_usage("t1", "u_nonexistent")
        assert usage["total"] == 0

    def test_reset_usage(self):
        tm = TokenManager()
        tm.record_usage("t1", "u1", {"prompt": 100, "completion": 50, "total": 150})
        tm.reset_usage("t1", "u1")
        usage = tm.get_usage("t1", "u1")
        assert usage["total"] == 0

    def test_reset_all_usage(self):
        tm = TokenManager()
        tm.record_usage("t1", "u1", {"prompt": 100, "completion": 50, "total": 150})
        tm.record_usage("t2", "u2", {"prompt": 200, "completion": 100, "total": 300})
        tm.reset_usage()
        assert tm.get_usage("t1", "u1")["total"] == 0
        assert tm.get_usage("t2", "u2")["total"] == 0

    def test_safety_margin(self):
        """Context window with safety margin should reduce available tokens."""
        tm = TokenManager({"safety_margin": 0.10})
        # 4096 * 0.10 = ~409 reserved, so 3687 available
        # 3500 + 200 = 3700 > 3687 → should exceed
        with pytest.raises(TokenBudgetExceededError):
            tm.validate_budget(
                estimated_input=3500,
                max_output=200,
                context_window=4096,
            )
''',

    "tests/test_oracle/test_cache.py": '''
# tests/test_oracle/test_cache.py
"""Unit tests for the Oracle Response Cache."""

import pytest
import asyncio
import os
import tempfile

from aegis.schemas.oracle import OracleAction, OracleRequest, OracleResponse
from aegis.agents.oracle.cache import ResponseCache


@pytest.fixture
def cache_db_path(tmp_path):
    return str(tmp_path / "test_oracle_cache.db")


@pytest.fixture
def cache_config(cache_db_path):
    return {
        "enabled": True,
        "db_path": cache_db_path,
        "ttl_seconds": 60,
        "max_entries": 100,
    }


@pytest.fixture
def sample_request():
    return OracleRequest(
        action=OracleAction.QUERY,
        prompt="What is Python?",
        temperature=0.7,
        max_tokens=500,
    )


@pytest.fixture
def sample_response():
    return OracleResponse(
        success=True,
        content="Python is a programming language.",
        llm_used="test-model",
        tokens_used={"prompt": 10, "completion": 8, "total": 18},
    )


class TestResponseCache:

    @pytest.mark.asyncio
    async def test_initialize(self, cache_config):
        cache = ResponseCache(cache_config)
        await cache.initialize()
        assert cache._initialized is True
        await cache.flush()

    @pytest.mark.asyncio
    async def test_store_and_retrieve(
        self, cache_config, sample_request, sample_response
    ):
        cache = ResponseCache(cache_config)
        await cache.initialize()

        key = cache.compute_key(sample_request, "test-model")
        await cache.store(key, sample_response)

        result = await cache.get(key)
        assert result is not None
        assert result["content"] == "Python is a programming language."
        assert result["llm_used"] == "test-model"

        await cache.flush()

    @pytest.mark.asyncio
    async def test_cache_miss(self, cache_config):
        cache = ResponseCache(cache_config)
        await cache.initialize()

        result = await cache.get("nonexistent_key")
        assert result is None

        await cache.flush()

    @pytest.mark.asyncio
    async def test_cache_disabled(self, cache_config, sample_request, sample_response):
        cache_config["enabled"] = False
        cache = ResponseCache(cache_config)
        await cache.initialize()

        key = cache.compute_key(sample_request, "test-model")
        await cache.store(key, sample_response)

        result = await cache.get(key)
        assert result is None  # Cache disabled, always miss

    @pytest.mark.asyncio
    async def test_compute_key_deterministic(self, cache_config, sample_request):
        cache = ResponseCache(cache_config)
        key1 = cache.compute_key(sample_request, "model-a")
        key2 = cache.compute_key(sample_request, "model-a")
        assert key1 == key2

    @pytest.mark.asyncio
    async def test_compute_key_varies_by_model(self, cache_config, sample_request):
        cache = ResponseCache(cache_config)
        key1 = cache.compute_key(sample_request, "model-a")
        key2 = cache.compute_key(sample_request, "model-b")
        assert key1 != key2

    @pytest.mark.asyncio
    async def test_invalidate(self, cache_config, sample_request, sample_response):
        cache = ResponseCache(cache_config)
        await cache.initialize()

        key = cache.compute_key(sample_request, "test-model")
        await cache.store(key, sample_response)
        assert (await cache.get(key)) is not None

        await cache.invalidate(key)
        assert (await cache.get(key)) is None

        await cache.flush()

    @pytest.mark.asyncio
    async def test_stats(self, cache_config, sample_request, sample_response):
        cache = ResponseCache(cache_config)
        await cache.initialize()

        key = cache.compute_key(sample_request, "test-model")
        await cache.store(key, sample_response)
        await cache.get(key)  # One hit

        stats = await cache.stats()
        assert stats["enabled"] is True
        assert stats["total_entries"] == 1
        assert stats["total_hits"] >= 1

        await cache.flush()
''',

    # ──────────────────────────────────────────────────────────────────────
    # 12. CONFIGURATION UPDATE — Oracle section for aegis_config.yaml
    # ──────────────────────────────────────────────────────────────────────
    "config/oracle_config_fragment.yaml": '''
# config/oracle_config_fragment.yaml
# ──────────────────────────────────────────────────────────────────────
# Merge this into your root aegis_config.yaml under the 'oracle:' key.
# Implements: Part II §2.1 — Oracle configuration
# ──────────────────────────────────────────────────────────────────────

oracle:
  # Maximum concurrent LLM requests across all providers
  max_concurrent_requests: 8

  # Default model preference (must match a key in 'models' below)
  default_model: "llama3.2"

  # ── Provider Configuration ──
  providers:
    ollama:
      provider_type: "ollama"
      base_url: "http://localhost:11434"
      enabled: true
      timeout_seconds: 120
      max_concurrent: 4
      max_retries: 3

    openai:
      provider_type: "openai_compat"
      base_url: "https://api.openai.com/v1"
      api_key_env: "OPENAI_API_KEY"
      enabled: false
      timeout_seconds: 60
      max_concurrent: 4
      max_retries: 3

  # ── Model Registry ──
  models:
    llama3.2:
      llm_id: "llama3.2"
      provider: "ollama"
      display_name: "Llama 3.2 (Local)"
      context_window: 128000
      preference_tags: ["local", "fast", "default"]
      supports_json_mode: true
      supports_embeddings: false
      max_output_tokens: 4096

    "llama3.1:70b":
      llm_id: "llama3.1:70b"
      provider: "ollama"
      display_name: "Llama 3.1 70B (Local)"
      context_window: 128000
      preference_tags: ["local", "capable"]
      supports_json_mode: true
      supports_embeddings: false
      max_output_tokens: 4096

    nomic-embed-text:
      llm_id: "nomic-embed-text"
      provider: "ollama"
      display_name: "Nomic Embed Text (Local)"
      context_window: 8192
      preference_tags: ["local", "embedding"]
      supports_json_mode: false
      supports_embeddings: true
      max_output_tokens: 0

  # ── Response Cache ──
  cache:
    enabled: true
    db_path: "aegis_data/oracle_cache.db"
    ttl_seconds: 3600
    max_entries: 10000

  # ── Rate Limiting ──
  rate_limit:
    enabled: true
    max_requests_per_minute: 30
    max_requests_per_hour: 500

  # ── Token Budget ──
  token_budget:
    tokens_per_word: 1.35
    safety_margin: 0.05

  # ── Prompt Templates ──
  templates:
    default_system: "You are Aegis, an intelligent AI assistant. Be helpful, accurate, and concise."
    custom: {}
''',

    # ──────────────────────────────────────────────────────────────────────
    # 13. REQUIREMENTS FRAGMENT
    # ──────────────────────────────────────────────────────────────────────
    "config/chunk_008_requirements.txt": '''
# Additional dependencies for CHUNK-008: Oracle (LLM Gateway)
# Append these to your project's requirements.txt / pyproject.toml
httpx>=0.27.0
aiosqlite>=0.20.0
structlog>=24.1.0
tiktoken>=0.7.0  # Optional: for accurate token counting (falls back to approximation)
''',

}


def create_package_init_files(path):
    """Create __init__.py files in parent directories if they don't exist."""
    dir_name = os.path.dirname(path)
    if dir_name and (dir_name.startswith("") or dir_name.startswith("tests/")):
        parts = dir_name.split("/")
        for i in range(2, len(parts) + 1):
            pkg_path = "/".join(parts[:i])
            init_file = os.path.join(pkg_path, "__init__.py")
            if not os.path.exists(init_file):
                print(f"  [Created] {init_file} (empty package marker)")
                os.makedirs(pkg_path, exist_ok=True)
                with open(init_file, "w") as f:
                    pass


def main():
    """Main function to write all files for CHUNK-008."""
    print("=" * 60)
    print("  CHUNK-008: Oracle (LLM Gateway) — Assembly")
    print("=" * 60)
    print()

    files_written = 0
    for path, content in CHUNK_008_FILES.items():
        # Ensure the directory exists
        dir_name = os.path.dirname(path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)

        create_package_init_files(path)

        print(f"  [Writing] {path}")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(textwrap.dedent(content).strip() + "\n")
        files_written += 1

    print()
    print("-" * 60)
    print(f"  Assembly Complete — {files_written} files written")
    print("-" * 60)
    print()
    print("  Files created:")
    print("    Schemas:    aegis/schemas/oracle.py")
    print("    Agent:      aegis/agents/oracle/agent.py")
    print("    Registry:   aegis/agents/oracle/llm_registry.py")
    print("    Prompts:    aegis/agents/oracle/prompt_engine.py")
    print("    Tokens:     aegis/agents/oracle/token_manager.py")
    print("    Cache:      aegis/agents/oracle/cache.py")
    print("    RateLimit:  aegis/agents/oracle/rate_limiter.py")
    print("    Providers:  ollama.py, openai_compat.py, base.py")
    print("    Tests:      5 test modules (agent, registry, prompt, tokens, cache)")
    print("    Config:     oracle_config_fragment.yaml, chunk_008_requirements.txt")
    print()
    print("  Next steps:")
    print("    1. Merge config/oracle_config_fragment.yaml into aegis_config.yaml")
    print("    2. Install deps: pip install httpx aiosqlite structlog")
    print("    3. Optional: pip install tiktoken (for accurate token counting)")
    print("    4. Ensure Ollama is running: ollama serve")
    print("    5. Pull a model: ollama pull llama3.2")
    print("    6. Run tests: pytest tests/test_oracle/ -v")
    print()


if __name__ == "__main__":
    main()

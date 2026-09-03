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
from aegis.agents.oracle.llm_registry import LLMRegistry, ModelNotFoundError
from aegis.agents.oracle.prompt_engine import PromptEngine
from aegis.agents.oracle.token_manager import TokenManager
from aegis.agents.oracle.cache import ResponseCache
from aegis.agents.oracle.rate_limiter import RateLimiter
from aegis.agents.oracle.providers.base import LLMProvider, ProviderError

# Work Tracker integration
try:
    from aegis.lib.work_tracker import get_client as get_work_tracker_client
    from aegis.lib.work_tracker import get_router as get_model_router
    WORK_TRACKER_AVAILABLE = True
except ImportError:
    WORK_TRACKER_AVAILABLE = False
    get_work_tracker_client = None  # type: ignore
    get_model_router = None  # type: ignore

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

    def __init__(self, config: dict | None = None, redis_conn=None, bus_publisher=None, bus_subscriber=None) -> None:
        """
        Initialize Oracle with all subsystems.

        Args:
            config: Oracle configuration dict (can be either the full config with "oracle" key,
                   or already the oracle section from aegis_config.yaml).
            redis_conn: Redis connection for session persistence.
            bus_publisher: MessagePublisher for sending responses.
            bus_subscriber: MessageSubscriber for receiving messages.
        """
        # Call parent init for heartbeat and bus support
        super().__init__(agent_id=self.agent_id, subscriptions=self.subscriptions)

        self._config = config or {}

        # Config can be either the full config with "oracle" key, or already the oracle section,
        # or an AegisConfig pydantic model. Handle all cases.
        if hasattr(self._config, "model_dump"):
            # It's a pydantic model - convert to dict
            config_dict = self._config.model_dump()
        elif isinstance(self._config, dict):
            config_dict = self._config
        else:
            config_dict = {}

        if "oracle" in config_dict:
            oracle_cfg = config_dict["oracle"]
        else:
            oracle_cfg = config_dict if config_dict else {}

        # Store redis connection for startup() to use
        self._redis_conn = redis_conn
        self._bus_publisher = bus_publisher
        self._bus_subscriber = bus_subscriber

        # Initialize subsystems
        self.llm_registry = LLMRegistry(oracle_cfg)
        self.prompt_engine = PromptEngine(oracle_cfg.get("templates", {}))
        self.token_manager = TokenManager(oracle_cfg.get("token_budget", {}))
        self.cache = ResponseCache(oracle_cfg.get("cache", {}))
        self.rate_limiter = RateLimiter(oracle_cfg.get("rate_limit", {}))

        # Work Tracker integration
        self.work_tracker_client = None
        self.model_router = None
        if WORK_TRACKER_AVAILABLE and get_work_tracker_client and get_model_router:
            try:
                self.work_tracker_client = get_work_tracker_client()
                self.model_router = get_model_router()
                logger.info("oracle.work_tracker_enabled")
            except Exception as e:
                logger.warning("oracle.work_tracker_init_failed", error=str(e))

        # Internal state
        self._running = False
        self._request_semaphore = asyncio.Semaphore(
            oracle_cfg.get("max_concurrent_requests", 8)
        )
        self._request_timeout = oracle_cfg.get("request_timeout_seconds", 120)
        # Fallback configuration: try providers in this order
        self._fallback_order = oracle_cfg.get("fallback_order", ["ollama", "openrouter"])

        logger.info("oracle.initialized", models=self.llm_registry.list_models())

    async def startup(self) -> None:
        """Agent initialization: subscribe to channels, verify providers.
        Implements: Part II §2.3 — BaseAgent.startup()
        """
        self._running = True

        # Initialize providers (verify connectivity)
        await self.llm_registry.initialize_providers()
        # Start heartbeat for this agent
        await self.start_heartbeat()

        # Initialize cache storage
        await self.cache.initialize()

        # Create and start MessageSubscriber for this agent's stream
        if self._redis_conn is not None:
            from aegis.bus.subscriber import MessageSubscriber
            self._bus_subscriber = MessageSubscriber(
                redis_client=self._redis_conn,
                agent_id=self.agent_id,
                handler=self._on_bus_message,
                subscribe_to_broadcast=False,
            )
            await self._bus_subscriber.start()
            logger.info(f"Oracle created its own MessageSubscriber with agent_id={self.agent_id}")
            logger.info(f"  Subscribed to stream: {self._bus_subscriber._stream}")
            logger.info(f"  Consumer group: {self._bus_subscriber._group}")
            logger.info(f"  Consumer: {self._bus_subscriber._consumer}")

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

        # Close ModelRouter if available
        if self.model_router:
            await self.model_router.close()

        # Stop the subscriber
        if self._bus_subscriber:
            await self._bus_subscriber.stop()

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
        7. Execute LLM call via provider with fallback support
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
                    response = await self._handle_structured_with_fallback(request, message)
                else:
                    response = await self._handle_query_with_fallback(request, message)

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
        except asyncio.TimeoutError:
            elapsed_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "oracle.request_timeout",
                correlation_id=correlation_id,
                timeout_s=self._config.get("request_timeout_seconds", 60),
            )
            return self._build_error_message(
                message, f"Request timed out after {self._config.get('request_timeout_seconds', 60)}s", elapsed_ms
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

    def _select_model_for_provider(
        self, models: list, preference: str | None, require_json: bool = False
    ):
        """
        Select the best model from a list of models for a specific provider.
        
        Selection priority:
        1. Exact llm_id match (if preference is a model name)
        2. Tag-based match (if preference is a tag like "fast", "capable")
        3. Default model (tagged "default")
        4. First available model
        """
        candidates = list(models)
        
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

    # ── Action Handlers ──────────────────────────────────────────────

    async def _handle_query_with_fallback(
        self, request: OracleRequest, message: AegisMessage
    ) -> OracleResponse:
        """
        Handle a standard QUERY action with provider fallback support.

        Tries providers in the order specified in config fallback_order.
        First successful provider wins. If all fail, request fails with error
        from the last provider to attempt.

        Handles specific OpenRouter errors (404 guardrail, rate limits) by
        automatically falling back to the next provider.

        Implements: Part VI §6.2 — OracleAction.QUERY
        """
        start_time = time.monotonic()
        llm_def = self.llm_registry.select_model(request.llm_preference)

        # Get fallback order from config: ["ollama", "openrouter"]
        fallback_order = self._fallback_order

        # Build provider configs: provider_name -> provider_config
        provider_configs = {}
        for provider_name in fallback_order:
            if provider_name in self.llm_registry._provider_configs:
                provider_configs[provider_name] = self.llm_registry._provider_configs[provider_name]

        last_error = None
        last_error_provider = None

        # Try each provider in order
        for provider_name in fallback_order:
            if provider_name not in provider_configs:
                logger.warning(f"Provider '{provider_name}' not configured, skipping")
                continue

            try:
                provider = self.llm_registry.get_provider(provider_name)
                
                # Select the best model for THIS specific provider
                # Filter models to those served by this provider
                provider_models = [
                    m for m in self.llm_registry._models.values()
                    if m.provider == provider_name
                ]
                if not provider_models:
                    raise ProviderError(f"No models available for provider '{provider_name}'")
                
                # Select model for this provider based on preference
                provider_llm_def = self._select_model_for_provider(
                    provider_models, request.llm_preference, require_json=False
                )
                
                logger.info(f"Trying LLM provider: {provider_name} (model: {provider_llm_def.llm_id})")

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
                    context_window=provider_llm_def.context_window,
                )

                # Check cache (using provider-specific model ID)
                cache_key = self.cache.compute_key(request, provider_llm_def.llm_id)
                cached = await self.cache.get(cache_key)
                if cached is not None:
                    logger.info(f"Cache hit for model {provider_llm_def.llm_id}")
                    return OracleResponse(
                        success=True,
                        content=cached["content"],
                        llm_used=cached["llm_used"],
                        tokens_used=cached.get("tokens_used", {}),
                        cached=True,
                    )

                # Execute LLM call with timeout
                result = await asyncio.wait_for(
                    provider.generate(
                        llm_id=provider_llm_def.llm_id,
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        temperature=request.temperature,
                        max_tokens=request.max_tokens,
                    ),
                    timeout=self._request_timeout,
                )

                logger.info(f"Provider '{provider_name}' succeeded after {time.monotonic() - start_time:.2f}s")

                response = OracleResponse(
                    success=True,
                    content=result["content"],
                    llm_used=result.get("model", provider_llm_def.llm_id),
                    tokens_used=result.get("tokens_used", {}),
                )

                # Cache the response
                await self.cache.store(cache_key, response)

                # Track token usage
                self.token_manager.record_usage(
                    tenant_id=message.tenant_id,
                    user_id=message.user_id,
                    input_tokens=result.get("tokens_used", {}).get("prompt_tokens", 0),
                    output_tokens=result.get("tokens_used", {}).get("completion_tokens", 0),
                )

                return response

            except asyncio.TimeoutError:
                logger.warning(f"Provider '{provider_name}' timed out after {self._request_timeout}s")
                last_error = ProviderError(f"Provider '{provider_name}' timed out after {self._request_timeout}s")
                last_error_provider = provider_name
                continue
            except ProviderError as e:
                # Check for specific OpenRouter errors that should trigger fallback
                error_msg = str(e).lower()
                should_fallback = False

                # OpenRouter specific errors that should trigger fallback
                if "404" in error_msg and ("no endpoints" in error_msg or "guardrail" in error_msg or "privacy" in error_msg):
                    should_fallback = True
                    logger.warning(f"OpenRouter guardrail/404 error, will fallback: {e}")
                elif "429" in error_msg or "rate limit" in error_msg:
                    should_fallback = True
                    logger.warning(f"OpenRouter rate limit hit, will fallback: {e}")
                elif "503" in error_msg or "unavailable" in error_msg:
                    should_fallback = True
                    logger.warning(f"OpenRouter service unavailable, will fallback: {e}")

                if should_fallback and provider_name != fallback_order[-1]:
                    logger.info(f"Falling back to next provider due to: {e}")
                    last_error = e
                    last_error_provider = provider_name
                    continue
                else:
                    # Last provider or non-retryable error
                    logger.error(f"Provider '{provider_name}' failed (non-retryable): {e}")
                    last_error = e
                    last_error_provider = provider_name
                    raise
            except Exception as e:
                logger.warning(f"Provider '{provider_name}' failed unexpectedly: {str(e)[:100]}")
                last_error = ProviderError(f"Provider '{provider_name}' failed: {e}")
                last_error_provider = provider_name
                # Continue to next provider for unexpected errors
                continue

        # All providers failed
        error_msg = f"All LLM providers failed. Last error from '{last_error_provider}': {last_error}"
        logger.error("oracle.all_providers_failed", error=error_msg)
        raise ProviderError(error_msg)

    async def _handle_embed(
        self, request: OracleRequest, message: AegisMessage
    ) -> OracleResponse:
        """Handle an EMBED action (embedding generation).
        Implements: Part VI §6.2 — OracleAction.EMBED
        """
        llm_def = self.llm_registry.select_embedding_model(request.llm_preference)
        provider = self.llm_registry.get_provider(llm_def.provider)

        # OracleRequest uses `prompt` field, wrap in list for embedding API
        texts = [request.prompt] if isinstance(request.prompt, str) else request.prompt

        result = await provider.embed(
            llm_id=llm_def.llm_id,
            texts=texts,
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
        Handle a CLASSIFY action.
        Implements: Part VI §6.2 — OracleAction.CLASSIFY
        """
        return await self._handle_query_with_fallback(request, message)

    async def _handle_structured_with_fallback(
        self, request: OracleRequest, message: AegisMessage
    ) -> OracleResponse:
        """
        Handle a STRUCTURED action (JSON-mode output) with provider fallback support.
        Implements: Part VI §6.2 — OracleAction.STRUCTURED
        """
        start_time = time.monotonic()

        # Get fallback order from config
        fallback_order = self._fallback_order

        # Build provider configs
        provider_configs = {}
        for provider_name in fallback_order:
            if provider_name in self.llm_registry._provider_configs:
                provider_configs[provider_name] = self.llm_registry._provider_configs[provider_name]

        last_error = None
        last_error_provider = None

        # Try each provider in order
        for provider_name in fallback_order:
            if provider_name not in provider_configs:
                logger.warning(f"Provider '{provider_name}' not configured, skipping")
                continue

            try:
                provider = self.llm_registry.get_provider(provider_name)
                
                # Select the best model for THIS specific provider (with JSON mode support)
                provider_models = [
                    m for m in self.llm_registry._models.values()
                    if m.provider == provider_name
                ]
                if not provider_models:
                    raise ProviderError(f"No models available for provider '{provider_name}'")
                
                # Select model for this provider based on preference, requiring JSON mode
                provider_llm_def = self._select_model_for_provider(
                    provider_models, request.llm_preference, require_json=True
                )
                
                logger.info(f"Trying structured LLM provider: {provider_name} (model: {provider_llm_def.llm_id})")

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
                    context_window=provider_llm_def.context_window,
                )

                # Check cache (using provider-specific model ID)
                cache_key = self.cache.compute_key(request, provider_llm_def.llm_id)
                cached = await self.cache.get(cache_key)
                if cached is not None:
                    logger.info(f"Cache hit for structured model {provider_llm_def.llm_id}")
                    return OracleResponse(
                        success=True,
                        content=cached["content"],
                        llm_used=cached["llm_used"],
                        tokens_used=cached.get("tokens_used", {}),
                        cached=True,
                    )

                result = await asyncio.wait_for(
                    provider.generate(
                        llm_id=provider_llm_def.llm_id,
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        temperature=request.temperature,
                        max_tokens=request.max_tokens,
                        response_format="json",
                    ),
                    timeout=self._request_timeout,
                )

                logger.info(f"Structured provider '{provider_name}' succeeded after {time.monotonic() - start_time:.2f}s")

                response = OracleResponse(
                    success=True,
                    content=result["content"],
                    llm_used=result.get("model", provider_llm_def.llm_id),
                    tokens_used=result.get("tokens_used", {}),
                )
                await self.cache.store(cache_key, response)

                self.token_manager.record_usage(
                    tenant_id=message.tenant_id,
                    user_id=message.user_id,
                    input_tokens=result.get("tokens_used", {}).get("prompt_tokens", 0),
                    output_tokens=result.get("tokens_used", {}).get("completion_tokens", 0),
                )

                return response

            except asyncio.TimeoutError:
                logger.warning(f"Structured provider '{provider_name}' timed out after {self._request_timeout}s")
                last_error = ProviderError(f"Provider '{provider_name}' timed out after {self._request_timeout}s")
                last_error_provider = provider_name
                continue
            except ProviderError as e:
                error_msg = str(e).lower()
                should_fallback = False

                if "404" in error_msg and ("no endpoints" in error_msg or "guardrail" in error_msg or "privacy" in error_msg):
                    should_fallback = True
                    logger.warning(f"OpenRouter guardrail/404 error in structured, will fallback: {e}")
                elif "429" in error_msg or "rate limit" in error_msg:
                    should_fallback = True
                    logger.warning(f"OpenRouter rate limit hit in structured, will fallback: {e}")
                elif "503" in error_msg or "unavailable" in error_msg:
                    should_fallback = True
                    logger.warning(f"OpenRouter service unavailable in structured, will fallback: {e}")

                if should_fallback and provider_name != fallback_order[-1]:
                    logger.info(f"Falling back to next provider due to: {e}")
                    last_error = e
                    last_error_provider = provider_name
                    continue
                else:
                    logger.error(f"Structured provider '{provider_name}' failed (non-retryable): {e}")
                    last_error = e
                    last_error_provider = provider_name
                    raise
            except Exception as e:
                logger.warning(f"Structured provider '{provider_name}' failed unexpectedly: {str(e)[:100]}")
                last_error = ProviderError(f"Provider '{provider_name}' failed: {e}")
                last_error_provider = provider_name
                continue

        error_msg = f"All structured LLM providers failed. Last error from '{last_error_provider}': {last_error}"
        logger.error("oracle.all_structured_providers_failed", error=error_msg)
        raise ProviderError(error_msg)

    # ── Response Building ────────────────────────────────────────────
    # (Existing methods unchanged)
    def _build_response_message(
        self, original: AegisMessage, response: OracleResponse
    ) -> AegisMessage:
        """Build an AegisMessage envelope for the OracleResponse."""
        payload = response.model_dump()
        # Preserve response_channel from original message so response goes to correct channel
        if "response_channel" in original.payload:
            payload["response_channel"] = original.payload["response_channel"]
        return AegisMessage(
            correlation_id=original.correlation_id or original.message_id,
            source_agent=self.agent_id,
            target_agent=original.source_agent,
            message_type=MessageType.RESPONSE,
            tenant_id=original.tenant_id,
            user_id=original.user_id,
            action=f"{self.agent_id}.response",
            payload=payload,
            priority=Priority.NORMAL,
        )

    def _build_error_message(
        self, original: AegisMessage, error: str, latency_ms: float
    ) -> AegisMessage:
        """Build an error response message."""
        return AegisMessage(
            correlation_id=original.correlation_id or original.message_id,
            source_agent=self.agent_id,
            target_agent=original.source_agent,
            message_type=MessageType.ERROR,
            tenant_id=original.tenant_id,
            user_id=original.user_id,
            action=f"{self.agent_id}.error",
            payload={"error": error},
            priority=Priority.HIGH,
        )

    async def _on_bus_message(self, message: AegisMessage) -> None:
        """Callback for messages received on our bus stream."""
        try:
            response = await self.handle_message(message)
            if response and self._bus_publisher:
                # Use response_channel from original message payload if present
                target_stream = message.payload.get("response_channel", f"aegis:stream:{response.target_agent}")
                await self._bus_publisher.publish_to_stream(target_stream, response)
        except Exception as e:
            logger.error("Error processing bus message: %s", e, exc_info=True)
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
        # Check if we should use ModelRouter (tiered fallback) for this request
        # Use ModelRouter for OpenRouter models
        llm_def = self.llm_registry.select_model(request.llm_preference)

        if llm_def.provider == "openrouter" and self.model_router:
            return await self._handle_query_via_model_router(request, message, llm_def)

        # Original provider-based flow
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
            input_tokens=result.get("tokens_used", {}).get("prompt_tokens", 0),
            output_tokens=result.get("tokens_used", {}).get("completion_tokens", 0),
        )

        return response

    async def _handle_query_via_model_router(
        self, request: OracleRequest, message: AegisMessage, llm_def
    ) -> OracleResponse:
        """
        Handle query via ModelRouter (tiered fallback for OpenRouter).
        """
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

        # Execute via ModelRouter
        from work_tracker.model_router import CompletionRequest
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})
        
        completion_request = CompletionRequest(
            messages=messages,
            model=None,  # Auto-select from tier chain
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            stream=False,
        )
        
        response = await self.model_router.complete(completion_request)
        
        # Track token usage
        self.token_manager.record_usage(
            tenant_id=message.tenant_id,
            user_id=message.user_id,
            input_tokens=response.prompt_tokens,
            output_tokens=response.completion_tokens,
        )
        
        return OracleResponse(
            success=True,
            content=response.content,
            llm_used=response.model,
            tokens_used={
                "prompt_tokens": response.prompt_tokens,
                "completion_tokens": response.completion_tokens,
                "total_tokens": response.total_tokens,
            },
        )

    async def _handle_embed(
        self, request: OracleRequest, message: AegisMessage
    ) -> OracleResponse:
        """
        Handle an EMBED action.
        Implements: Part VI §6.2 — OracleAction.EMBED
        """
        llm_def = self.llm_registry.select_model(request.llm_preference)
        provider = self.llm_registry.get_provider(llm_def.provider)

        result = await provider.embed(
            llm_id=llm_def.llm_id,
            texts=request.texts,
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
        return await self._handle_query(request, message)

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

        # Use ModelRouter for OpenRouter models
        if llm_def.provider == "openrouter" and self.model_router:
            return await self._handle_structured_via_model_router(request, message, llm_def)

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
        )

        response = OracleResponse(
            success=True,
            content=result["content"],
            llm_used=llm_def.llm_id,
            tokens_used=result.get("tokens_used", {}),
        )

        # Track token usage
        self.token_manager.record_usage(
            tenant_id=message.tenant_id,
            user_id=message.user_id,
            input_tokens=result.get("tokens_used", {}).get("prompt_tokens", 0),
            output_tokens=result.get("tokens_used", {}).get("completion_tokens", 0),
        )

        return response

    async def _handle_structured_via_model_router(
        self, request: OracleRequest, message: AegisMessage, llm_def
    ) -> OracleResponse:
        """Handle STRUCTURED via ModelRouter (OpenRouter)."""
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

        from work_tracker.model_router import CompletionRequest
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})
        
        completion_request = CompletionRequest(
            messages=messages,
            model=None,  # Auto-select from tier chain
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            stream=False,
        )
        
        response = await self.model_router.complete(completion_request)

        self.token_manager.record_usage(
            tenant_id=message.tenant_id,
            user_id=message.user_id,
            input_tokens=response.prompt_tokens,
            output_tokens=response.completion_tokens,
        )

        return OracleResponse(
            success=True,
            content=response.content,
            llm_used=response.model,
            tokens_used={
                "prompt_tokens": response.prompt_tokens,
                "completion_tokens": response.completion_tokens,
                "total_tokens": response.total_tokens,
            },
        )

    # ── Response Building ────────────────────────────────────────────

    def _build_response_message(
        self, original: AegisMessage, response: OracleResponse
    ) -> AegisMessage:
        """Build an AegisMessage envelope for the OracleResponse."""
        return AegisMessage(
            correlation_id=original.correlation_id or original.message_id,
            source_agent=self.agent_id,
            target_agent=original.source_agent,
            message_type=MessageType.RESPONSE,
            tenant_id=original.tenant_id,
            user_id=original.user_id,
            action=f"{self.agent_id}.response",
            payload=response.model_dump(),
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
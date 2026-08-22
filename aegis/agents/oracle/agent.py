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
        
        # Close ModelRouter if available
        if self.model_router:
            await self.model_router.close()
        
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
            tokens=result.get("tokens_used", {}),
        )

        return response

    async def _handle_query_via_model_router(
        self, request: OracleRequest, message: AegisMessage, llm_def
    ) -> OracleResponse:
        """
        Handle QUERY action via work-tracker ModelRouter (tiered fallback).
        This provides automatic fallback across free OpenRouter models.
        """
        from aegis.lib.work_tracker import CompletionRequest
        
        # Assemble prompt
        system_prompt, user_prompt = self.prompt_engine.assemble(
            prompt=request.prompt,
            system_prompt=request.system_prompt,
            context_packet=request.context_packet,
        )

        # Validate token budget (using selected model's context window)
        estimated_input = self.token_manager.estimate_tokens(
            system_prompt + user_prompt
        )
        self.token_manager.validate_budget(
            estimated_input=estimated_input,
            max_output=request.max_tokens,
            context_window=llm_def.context_window,
        )

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

        # Build messages for ModelRouter
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        # Create completion request for ModelRouter
        completion_request = CompletionRequest(
            messages=messages,
            model=llm_def.llm_id if llm_def.llm_id != "nvidia/nemotron-3-ultra-550b-a55b:free" else None,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            session_id=message.correlation_id or message.message_id,
            project="aegis",
            agent="aegis",
            metadata={
                "source": "oracle",
                "action": request.action.value,
                "tenant_id": message.tenant_id,
                "user_id": message.user_id,
            },
        )

        # Execute via ModelRouter (handles tiered fallback)
        try:
            router_response = await self.model_router.complete(completion_request)
            
            result = {
                "content": router_response.content,
                "tokens_used": {
                    "prompt": router_response.prompt_tokens,
                    "completion": router_response.completion_tokens,
                    "total": router_response.total_tokens,
                },
                "model": router_response.model,
                "finish_reason": router_response.finish_reason,
            }

        except Exception as e:
            logger.error("oracle.model_router_failed", error=str(e))
            raise ProviderError(f"ModelRouter failed: {e}") from e

        # Cache the response
        response = OracleResponse(
            success=True,
            content=result["content"],
            llm_used=result["model"],
            tokens_used=result.get("tokens_used", {}),
        )
        await self.cache.store(cache_key, response)

        # Track token usage in Aegis token manager
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

    async def _handle_structured_via_model_router(
        self, request: OracleRequest, message: AegisMessage, llm_def
    ) -> OracleResponse:
        """
        Handle STRUCTURED action via work-tracker ModelRouter (tiered fallback).
        """
        from aegis.lib.work_tracker import CompletionRequest
        
        # Assemble prompt
        system_prompt, user_prompt = self.prompt_engine.assemble(
            prompt=request.prompt,
            system_prompt=request.system_prompt,
            context_packet=request.context_packet,
            force_json_instruction=True,
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

        # Build messages for ModelRouter
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        # Create completion request for ModelRouter
        completion_request = CompletionRequest(
            messages=messages,
            model=llm_def.llm_id if llm_def.llm_id != "nvidia/nemotron-3-ultra-550b-a55b:free" else None,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            session_id=message.correlation_id or message.message_id,
            project="aegis",
            agent="aegis",
            metadata={
                "source": "oracle",
                "action": request.action.value,
                "tenant_id": message.tenant_id,
                "user_id": message.user_id,
            },
        )

        # Execute via ModelRouter
        try:
            router_response = await self.model_router.complete(completion_request)
            
            result = {
                "content": router_response.content,
                "tokens_used": {
                    "prompt": router_response.prompt_tokens,
                    "completion": router_response.completion_tokens,
                    "total": router_response.total_tokens,
                },
                "model": router_response.model,
                "finish_reason": router_response.finish_reason,
            }

        except Exception as e:
            logger.error("oracle.model_router_failed", error=str(e))
            raise ProviderError(f"ModelRouter failed: {e}") from e

        # Parse JSON content
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
            llm_used=result["model"],
            tokens_used=result.get("tokens_used", {}),
        )

        # Track token usage
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

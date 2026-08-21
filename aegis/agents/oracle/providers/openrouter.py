# aegis/agents/oracle/providers/openrouter.py
# Implements: Part I — OpenRouter provider with tiered fallback via work-tracker ModelRouter

"""OpenRouter Provider — Cloud provider for Project Aegis.

Integrates with work-tracker's ModelRouter for:
- Tiered fallback across free models
- Circuit breakers per tier
- Daily rate limiting (shared budget)
- Work tracking (requests, tokens, sessions)
"""

from __future__ import annotations

import os
from typing import Any, Optional

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


class OpenRouterProvider(LLMProvider):
    """OpenRouter provider with tiered fallback via work-tracker ModelRouter.

    This provider delegates to the shared ModelRouter which handles:
    - Multiple free model tiers with automatic fallback
    - Circuit breakers for failing tiers
    - Shared daily rate limit (1000 req/day)
    - Automatic work tracking (requests, tokens, sessions)
    """

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        self._router = None
        self._api_key_env = config.api_key_env or "OPENROUTER_API_KEY"
        self._model_id = config.default_model or "nvidia/nemotron-3-ultra:free"

    def _get_router(self):
        """Lazy-load the ModelRouter from work-tracker."""
        if self._router is None:
            try:
                from work_tracker import get_router
                api_key = os.environ.get(self._api_key_env)
                if not api_key:
                    raise ProviderError(
                        f"OpenRouter API key not found in env var {self._api_key_env}"
                    )
                self._router = get_router(api_key=api_key)
            except ImportError:
                raise ProviderError(
                    "work-tracker package not installed. "
                    "Install with: pip install -e /path/to/work-tracker"
                )
        return self._router

    async def generate(
        self,
        llm_id: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        response_format: str | None = None,
    ) -> dict[str, Any]:
        """Generate text via ModelRouter (tiered fallback)."""
        router = self._get_router()

        # Build messages in OpenAI format
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        # Create completion request
        from work_tracker.model_router import CompletionRequest

        request = CompletionRequest(
            messages=messages,
            model=llm_id if llm_id != self._model_id else None,  # None = auto-select
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=1.0,
            stream=False,
            session_id=None,  # Will be auto-created by router
            project="aegis",
            agent="aegis",
            metadata={
                "source": "oracle",
                "action": "generate",
            },
        )

        try:
            response = await router.complete(request)

            return {
                "content": response.content,
                "tokens_used": {
                    "prompt": response.prompt_tokens,
                    "completion": response.completion_tokens,
                    "total": response.total_tokens,
                },
                "model": response.model,
                "finish_reason": response.finish_reason,
            }

        except Exception as e:
            logger.error("openrouter.generate_failed", error=str(e))
            raise ProviderError(f"OpenRouter generation failed: {e}") from e

    async def embed(
        self,
        llm_id: str,
        texts: list[str],
    ) -> dict[str, Any]:
        """Generate embeddings - not supported by OpenRouter free tier models.

        Falls back to local embedding models via Ollama.
        """
        raise ProviderModelError(
            "Embeddings not supported by OpenRouter free tier. "
            "Use local embedding model (nomic-embed-text via Ollama)."
        )

    async def health_check(self) -> bool:
        """Check if OpenRouter is reachable."""
        try:
            router = self._get_router()
            # Simple check - try to get tier status
            status = router.get_tier_status()
            return len(status["tiers"]) > 0
        except Exception as e:
            logger.warning("openrouter.health_failed", error=str(e))
            return False

    async def close(self) -> None:
        """Close the ModelRouter HTTP client."""
        if self._router:
            await self._router.close()
            self._router = None
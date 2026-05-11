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

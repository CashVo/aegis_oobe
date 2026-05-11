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

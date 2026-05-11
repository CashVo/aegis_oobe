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

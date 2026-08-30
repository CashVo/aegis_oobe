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
        tokens: dict | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        """
        Record token usage for a tenant/user pair.

        Args:
            tenant_id: The tenant identifier.
            user_id: The user identifier.
            tokens: Dict with "prompt", "completion", "total" keys (legacy format).
            input_tokens: Number of input/prompt tokens (new format).
            output_tokens: Number of output/completion tokens (new format).
        """
        key = (tenant_id, user_id)
        
        if tokens:
            # Legacy format: tokens dict with prompt/completion/total
            self._usage[key]["prompt"] += tokens.get("prompt", 0)
            self._usage[key]["completion"] += tokens.get("completion", 0)
            self._usage[key]["total"] += tokens.get("total", 0)
        else:
            # New format: input_tokens and output_tokens
            self._usage[key]["prompt"] += input_tokens
            self._usage[key]["completion"] += output_tokens
            self._usage[key]["total"] += input_tokens + output_tokens

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

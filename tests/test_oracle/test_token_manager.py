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

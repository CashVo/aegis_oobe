# tests/test_janus/test_engine.py
"""
Unit tests for the Janus Policy Evaluation Engine.

Tests the safe DSL interpreter for correctness, edge cases, and security.
"""

import pytest
from aegis.agents.janus.engine import PolicyEngine, PolicyEvalError


@pytest.fixture
def engine():
    """Fresh PolicyEngine instance for each test."""
    return PolicyEngine()


class TestBasicComparisons:
    """Test basic comparison operations."""

    def test_equality(self, engine):
        ctx = {"action": "forge.execute_tool", "resource": "tool:file_read"}
        assert engine.evaluate('action == "forge.execute_tool"', ctx) is True
        assert engine.evaluate('action == "something_else"', ctx) is False

    def test_inequality(self, engine):
        ctx = {"role": "member"}
        assert engine.evaluate('role != "root"', ctx) is True
        assert engine.evaluate('role != "member"', ctx) is False

    def test_in_list(self, engine):
        ctx = {"role": "admin"}
        assert engine.evaluate('role in ["admin", "root"]', ctx) is True
        assert engine.evaluate('role in ["member", "observer"]', ctx) is False

    def test_not_in_list(self, engine):
        ctx = {"role": "member"}
        assert engine.evaluate('role not_in ["admin", "root"]', ctx) is True
        assert engine.evaluate('role not_in ["member", "admin"]', ctx) is False

    def test_contains(self, engine):
        ctx = {"command": "git push origin main"}
        assert engine.evaluate('command contains "git"', ctx) is True
        assert engine.evaluate('command contains "sudo"', ctx) is False

    def test_startswith(self, engine):
        ctx = {"action": "forge.execute_tool"}
        assert engine.evaluate('action startswith "forge."', ctx) is True
        assert engine.evaluate('action startswith "oracle."', ctx) is False

    def test_endswith(self, engine):
        ctx = {"file": "report.pdf"}
        assert engine.evaluate('file endswith ".pdf"', ctx) is True
        assert engine.evaluate('file endswith ".txt"', ctx) is False


class TestLogicalOperators:
    """Test logical AND, OR, NOT operators."""

    def test_and(self, engine):
        ctx = {"action": "forge.execute_tool", "resource": "tool:file_write"}
        assert engine.evaluate(
            'action == "forge.execute_tool" and resource == "tool:file_write"', ctx
        ) is True
        assert engine.evaluate(
            'action == "forge.execute_tool" and resource == "tool:file_read"', ctx
        ) is False

    def test_or(self, engine):
        ctx = {"role": "admin"}
        assert engine.evaluate('role == "admin" or role == "root"', ctx) is True
        ctx2 = {"role": "member"}
        assert engine.evaluate('role == "admin" or role == "root"', ctx2) is False

    def test_not(self, engine):
        ctx = {"active": "false"}
        assert engine.evaluate('not active == "true"', ctx) is True

    def test_combined_logic(self, engine):
        ctx = {"action": "forge.execute_tool", "role": "member", "resource": "tool:file_delete"}
        condition = 'action == "forge.execute_tool" and resource == "tool:file_delete" and role != "admin" and role != "root"'
        assert engine.evaluate(condition, ctx) is True

        ctx["role"] = "admin"
        assert engine.evaluate(condition, ctx) is False


class TestParentheses:
    """Test parenthesized grouping."""

    def test_grouped_or(self, engine):
        ctx = {"role": "root", "action": "system.config"}
        condition = 'action == "system.config" and (role == "admin" or role == "root")'
        assert engine.evaluate(condition, ctx) is True

        ctx["role"] = "member"
        assert engine.evaluate(condition, ctx) is False

    def test_nested_parens(self, engine):
        ctx = {"a": "1", "b": "2", "c": "3"}
        condition = '(a == "1" and b == "2") or c == "3"'
        assert engine.evaluate(condition, ctx) is True

        condition2 = '(a == "X" and b == "2") or c == "3"'
        assert engine.evaluate(condition2, ctx) is True  # c == "3" is true


class TestDotNotation:
    """Test nested context field access via dot notation."""

    def test_nested_field(self, engine):
        ctx = {"request": {"action": "delete", "target": "file.txt"}}
        assert engine.evaluate('request.action == "delete"', ctx) is True
        assert engine.evaluate('request.target == "file.txt"', ctx) is True

    def test_missing_nested_field(self, engine):
        ctx = {"request": {"action": "read"}}
        # Missing field resolves to None
        assert engine.evaluate('request.missing == "something"', ctx) is False


class TestLiterals:
    """Test literal value handling."""

    def test_boolean_literals(self, engine):
        ctx = {"enabled": True}
        assert engine.evaluate("enabled == true", ctx) is True
        assert engine.evaluate("enabled == false", ctx) is False

    def test_none_literal(self, engine):
        ctx = {"value": None}
        assert engine.evaluate("value == none", ctx) is True

    def test_numeric_literal(self, engine):
        ctx = {"count": 5}
        assert engine.evaluate("count == 5", ctx) is True
        assert engine.evaluate("count == 10", ctx) is False


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_context(self, engine):
        ctx = {}
        # Missing field resolves to None
        assert engine.evaluate('action == "something"', ctx) is False

    def test_empty_condition_raises(self, engine):
        with pytest.raises(PolicyEvalError):
            engine.evaluate("", {})

    def test_unmatched_paren_raises(self, engine):
        with pytest.raises(PolicyEvalError):
            engine.evaluate('(action == "test"', {"action": "test"})

    def test_truthy_check(self, engine):
        ctx = {"active": True, "disabled": False, "name": "test"}
        assert engine.evaluate("active", ctx) is True
        assert engine.evaluate("disabled", ctx) is False
        assert engine.evaluate("name", ctx) is True

    def test_cache_works(self, engine):
        condition = 'action == "test"'
        ctx = {"action": "test"}
        engine.evaluate(condition, ctx)
        # Second call should use cache
        assert condition in engine._cache
        engine.evaluate(condition, ctx)

    def test_clear_cache(self, engine):
        engine.evaluate('x == "y"', {"x": "y"})
        assert len(engine._cache) > 0
        engine.clear_cache()
        assert len(engine._cache) == 0

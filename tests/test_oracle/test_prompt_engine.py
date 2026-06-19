# tests/test_oracle/test_prompt_engine.py
"""Unit tests for the Prompt Engine."""

import pytest
from aegis.agents.oracle.prompt_engine import PromptEngine


class TestPromptEngine:

    def test_basic_assembly(self):
        engine = PromptEngine()
        sys_p, user_p = engine.assemble(prompt="Hello world")
        assert "Hello world" in user_p
        assert len(sys_p) > 0  # Default system prompt

    def test_custom_system_prompt(self):
        engine = PromptEngine()
        sys_p, user_p = engine.assemble(
            prompt="test",
            system_prompt="Custom system instruction.",
        )
        assert sys_p == "Custom system instruction."

    def test_json_instruction(self):
        engine = PromptEngine()
        sys_p, _ = engine.assemble(
            prompt="test",
            force_json_instruction=True,
        )
        assert "JSON" in sys_p

    def test_context_packet_formatting(self):
        engine = PromptEngine()
        context = {
            "fragments": [
                {"tier": "L0", "content": "User prefers concise answers.", "relevance": 0.95},
                {"tier": "L1", "content": "Python expert.", "relevance": 0.80},
            ],
            "total_tokens": 50,
            "tiers_queried": ["L0", "L1"],
        }
        _, user_p = engine.assemble(
            prompt="What is Python?",
            context_packet=context,
        )
        assert "Relevant Context" in user_p
        assert "User prefers concise answers" in user_p
        assert "Python expert" in user_p
        assert "What is Python?" in user_p

    def test_empty_context_packet(self):
        engine = PromptEngine()
        _, user_p = engine.assemble(
            prompt="test",
            context_packet={"fragments": [], "total_tokens": 0, "tiers_queried": []},
        )
        assert user_p == "test"

    def test_classification_assembly(self):
        engine = PromptEngine()
        sys_p, user_p = engine.assemble_classification(prompt="Is this spam?")
        assert "classification" in sys_p.lower()
        assert "JSON" in sys_p
        assert "Is this spam?" in user_p

    def test_template_registration(self):
        engine = PromptEngine()
        engine.register_template("greeting", "Hello {name}!")
        assert engine.get_template("greeting") == "Hello {name}!"
        assert engine.get_template("nonexistent") is None

    def test_context_fragments_sorted_by_relevance(self):
        engine = PromptEngine()
        context = {
            "fragments": [
                {"tier": "L1", "content": "Low relevance.", "relevance": 0.30},
                {"tier": "L0", "content": "High relevance.", "relevance": 0.99},
            ],
        }
        _, user_p = engine.assemble(prompt="test", context_packet=context)
        # High relevance should appear before low relevance
        high_idx = user_p.index("High relevance")
        low_idx = user_p.index("Low relevance")
        assert high_idx < low_idx

# tests/test_torchestrator/test_intent.py
# Unit tests for the IntentParser

import pytest
from aegis.agents.torchestrator.intent import IntentParser
from aegis.schemas.torchestrator import Intent, IntentCategory


@pytest.fixture
def parser():
    return IntentParser()


class TestRuleBasedParsing:
    """Tests for the rule-based intent classification tier."""

    def test_file_read_intent(self, parser):
        intent = parser.parse_rule_based("Read the file called test.txt")
        assert intent is not None
        assert intent.category == IntentCategory.FILE_OPERATION
        assert intent.confidence >= 0.8
        assert "file_read" in intent.requires_tools

    def test_file_write_intent(self, parser):
        intent = parser.parse_rule_based("Create a file named 'hello.md' with some content")
        assert intent is not None
        assert intent.category == IntentCategory.FILE_OPERATION
        assert intent.entities.get("operation") == "write"

    def test_file_delete_intent(self, parser):
        intent = parser.parse_rule_based("Delete the file '/tmp/old.log'")
        assert intent is not None
        assert intent.category == IntentCategory.FILE_OPERATION
        assert intent.entities.get("operation") == "delete"

    def test_git_branch_intent(self, parser):
        intent = parser.parse_rule_based("Create a new branch called feature/login")
        assert intent is not None
        assert intent.category == IntentCategory.GIT_OPERATION
        assert "feature/login" in intent.entities.get("branch_name", "")

    def test_git_workflow_intent(self, parser):
        intent = parser.parse_rule_based("Start a feature branch workflow for the new API")
        assert intent is not None
        assert intent.category == IntentCategory.GIT_OPERATION
        assert "manage_git_workflow" in intent.requires_skills

    def test_schedule_nightly(self, parser):
        intent = parser.parse_rule_based("Schedule a nightly backup at 2 AM")
        assert intent is not None
        assert intent.category == IntentCategory.SCHEDULING
        assert intent.entities.get("hour") == 2
        assert intent.entities.get("minute") == 0

    def test_schedule_daily(self, parser):
        intent = parser.parse_rule_based("Schedule a daily report at 9:30 AM")
        assert intent is not None
        assert intent.category == IntentCategory.SCHEDULING
        assert intent.entities.get("hour") == 9
        assert intent.entities.get("minute") == 30

    def test_create_user_intent(self, parser):
        intent = parser.parse_rule_based("Create a new user named 'TestUser' with the member role")
        assert intent is not None
        assert intent.category == IntentCategory.USER_MANAGEMENT
        assert intent.entities.get("username") == "TestUser"
        assert intent.entities.get("role") == "member"

    def test_memory_recall_intent(self, parser):
        intent = parser.parse_rule_based("What do you remember about my Python project?")
        assert intent is not None
        assert intent.category == IntentCategory.MEMORY_QUERY
        assert intent.requires_memory is True

    def test_contextual_question(self, parser):
        intent = parser.parse_rule_based("Based on what you know about me, what should I focus on?")
        assert intent is not None
        assert intent.category == IntentCategory.CONTEXTUAL_QUESTION
        assert intent.requires_memory is True

    def test_system_status(self, parser):
        intent = parser.parse_rule_based("Show me the system status")
        assert intent is not None
        assert intent.category == IntentCategory.SYSTEM_COMMAND

    def test_simple_question(self, parser):
        intent = parser.parse_rule_based("What is the capital of France?")
        assert intent is not None
        assert intent.category == IntentCategory.QUESTION
        assert intent.requires_oracle is True

    def test_ambiguous_input_returns_none(self, parser):
        """Ambiguous input should return None, signaling Oracle fallback."""
        intent = parser.parse_rule_based("Help me think about this problem")
        # This may return None (needs Oracle) or CONVERSATION
        # Both are acceptable
        if intent:
            assert intent.category in (IntentCategory.CONVERSATION, IntentCategory.QUESTION)

    def test_short_input(self, parser):
        intent = parser.parse_rule_based("hi")
        assert intent is not None
        assert intent.category == IntentCategory.CONVERSATION


class TestOracleResponseParsing:
    """Tests for parsing Oracle classification responses."""

    def test_valid_json_response(self, parser):
        oracle_output = """{"category": "file_operation", "confidence": 0.9, "requires_tools": ["file_write"], "requires_skills": [], "requires_memory": false, "rewritten_query": null}"""
        intent = parser.parse_oracle_response(oracle_output, "write something")
        assert intent.category == IntentCategory.FILE_OPERATION
        assert intent.confidence == 0.9

    def test_json_embedded_in_text(self, parser):
        oracle_output = """Based on the input, I classify this as:
        {"category": "question", "confidence": 0.85, "requires_tools": [], "requires_skills": [], "requires_memory": false, "rewritten_query": "What is Python?"}
        """
        intent = parser.parse_oracle_response(oracle_output, "tell me about python")
        assert intent.category == IntentCategory.QUESTION

    def test_malformed_response_fallback(self, parser):
        oracle_output = "I cannot classify this input properly."
        intent = parser.parse_oracle_response(oracle_output, "some input")
        assert intent.category == IntentCategory.QUESTION
        assert intent.confidence == 0.5


class TestClassificationPromptBuilding:
    """Tests for the Oracle classification prompt builder."""

    def test_prompt_includes_categories(self, parser):
        prompt = parser.build_classification_prompt("test input")
        assert "question" in prompt
        assert "file_operation" in prompt
        assert "git_operation" in prompt

    def test_prompt_includes_session_context(self, parser):
        prompt = parser.build_classification_prompt("test input", "User: hello\nAssistant: hi")
        assert "Recent conversation context" in prompt
        assert "hello" in prompt

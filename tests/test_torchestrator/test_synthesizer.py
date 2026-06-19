# tests/test_torchestrator/test_synthesizer.py
# Unit tests for the ResponseSynthesizer

import pytest
from aegis.agents.torchestrator.synthesizer import ResponseSynthesizer
from aegis.schemas.torchestrator import (
    Intent,
    IntentCategory,
    TaskPlan,
    TaskStatus,
    TaskStep,
)


@pytest.fixture
def synthesizer():
    return ResponseSynthesizer()


def _make_plan(steps, status=TaskStatus.COMPLETED, raw_input="test input"):
    intent = Intent(category=IntentCategory.QUESTION, raw_input=raw_input)
    plan = TaskPlan(intent=intent, steps=steps, status=status)
    return plan


class TestSingleStepSynthesis:
    """Tests for single-step task plan synthesis."""

    def test_oracle_response_passthrough(self, synthesizer):
        steps = [TaskStep(
            order=1, description="Query Oracle", target_agent="oracle",
            action="oracle.query", status=TaskStatus.COMPLETED,
            result={"content": "Paris is the capital of France."}
        )]
        plan = _make_plan(steps)
        response = synthesizer.synthesize(plan)
        assert "Paris" in response

    def test_tool_response_passthrough(self, synthesizer):
        steps = [TaskStep(
            order=1, description="Read file", target_agent="forge",
            action="forge.execute_tool", status=TaskStatus.COMPLETED,
            result={"data": "File contents here."}
        )]
        plan = _make_plan(steps)
        response = synthesizer.synthesize(plan)
        assert "File contents here" in response


class TestMultiStepSynthesis:
    """Tests for multi-step task plan synthesis."""

    def test_combines_multiple_results(self, synthesizer):
        steps = [
            TaskStep(
                order=1, description="Search memory", target_agent="lexicon",
                action="lexicon.search", status=TaskStatus.COMPLETED,
                result={"content": "User likes Python."}
            ),
            TaskStep(
                order=2, description="Generate answer", target_agent="oracle",
                action="oracle.query", status=TaskStatus.COMPLETED,
                result={"content": "Based on your interests, try FastAPI."}
            ),
        ]
        plan = _make_plan(steps)
        response = synthesizer.synthesize(plan)
        assert "Python" in response or "FastAPI" in response


class TestErrorSynthesis:
    """Tests for error response synthesis."""

    def test_single_failure(self, synthesizer):
        steps = [TaskStep(
            order=1, description="Execute dangerous command", target_agent="forge",
            action="forge.execute_tool", status=TaskStatus.FAILED,
            error="Permission denied by Warden."
        )]
        plan = _make_plan(steps, status=TaskStatus.FAILED)
        response = synthesizer.synthesize(plan)
        assert "Permission denied" in response

    def test_partial_failure(self, synthesizer):
        steps = [
            TaskStep(
                order=1, description="Read file", target_agent="forge",
                action="forge.execute_tool", status=TaskStatus.COMPLETED,
                result={"data": "file content"}
            ),
            TaskStep(
                order=2, description="Delete file", target_agent="forge",
                action="forge.execute_tool", status=TaskStatus.FAILED,
                error="File not found."
            ),
        ]
        plan = _make_plan(steps)
        response = synthesizer.synthesize(plan)
        assert "file content" in response
        assert "File not found" in response

    def test_all_failed(self, synthesizer):
        steps = [
            TaskStep(order=1, description="Step 1", target_agent="forge",
                     action="test", status=TaskStatus.FAILED, error="Error 1"),
            TaskStep(order=2, description="Step 2", target_agent="forge",
                     action="test", status=TaskStatus.FAILED, error="Error 2"),
        ]
        plan = _make_plan(steps, status=TaskStatus.FAILED)
        response = synthesizer.synthesize(plan)
        assert "Error 1" in response
        assert "Error 2" in response


class TestOracleSynthesis:
    """Tests for Oracle-assisted synthesis."""

    def test_oracle_response_with_errors(self, synthesizer):
        steps = [
            TaskStep(order=1, description="Failed step", target_agent="forge",
                     action="test", status=TaskStatus.FAILED, error="timeout"),
        ]
        plan = _make_plan(steps)
        response = synthesizer.synthesize_with_oracle_response(
            "Here is my answer.", plan
        )
        assert "Here is my answer" in response
        assert "timeout" in response

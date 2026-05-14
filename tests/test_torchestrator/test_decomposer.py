# tests/test_torchestrator/test_decomposer.py
# Unit tests for the TaskDecomposer

import pytest
from aegis.agents.torchestrator.decomposer import TaskDecomposer
from aegis.schemas.torchestrator import Intent, IntentCategory, TaskPlan, TaskStatus


@pytest.fixture
def decomposer():
    return TaskDecomposer()


TENANT = "test-tenant"
USER = "test-user"
SESSION = "test-session"


class TestSimpleQuestionDecomposition:
    """UC-1: Simple question decomposition."""

    def test_simple_question_plan(self, decomposer):
        intent = Intent(
            category=IntentCategory.QUESTION,
            raw_input="What is the capital of France?",
            requires_oracle=True,
        )
        plan = decomposer.decompose(intent, TENANT, USER, SESSION)
        assert len(plan.steps) == 1
        assert plan.steps[0].target_agent == "oracle"
        assert plan.steps[0].action == "oracle.query"


class TestContextualQuestionDecomposition:
    """UC-2: Contextual question decomposition."""

    def test_contextual_question_has_lexicon_step(self, decomposer):
        intent = Intent(
            category=IntentCategory.CONTEXTUAL_QUESTION,
            raw_input="Based on what you know about me, what should I focus on?",
            requires_memory=True,
            requires_oracle=True,
        )
        plan = decomposer.decompose(intent, TENANT, USER, SESSION)
        assert len(plan.steps) >= 2
        # First step should be Lexicon context assembly
        assert plan.steps[0].target_agent == "lexicon"
        assert plan.steps[0].action == "lexicon.assemble_context"
        # Last step should be Oracle
        assert plan.steps[-1].target_agent == "oracle"

    def test_contextual_with_current_events(self, decomposer):
        intent = Intent(
            category=IntentCategory.CONTEXTUAL_QUESTION,
            raw_input="Based on what you know and current events, what should I focus on?",
            requires_memory=True,
            requires_oracle=True,
        )
        plan = decomposer.decompose(intent, TENANT, USER, SESSION)
        # Should include web_research step
        agents_used = [s.target_agent for s in plan.steps]
        assert "forge" in agents_used  # web_research via forge


class TestFileOperationDecomposition:
    """UC-3: File operation decomposition."""

    def test_file_write_plan(self, decomposer):
        intent = Intent(
            category=IntentCategory.FILE_OPERATION,
            raw_input="Create a file called test.txt",
            entities={"operation": "write", "file_paths": ["test.txt"]},
            requires_tools=["file_write"],
        )
        plan = decomposer.decompose(intent, TENANT, USER, SESSION)
        assert len(plan.steps) >= 1
        assert plan.steps[0].target_agent == "forge"
        assert "file_write" in plan.steps[0].payload.get("tool_name", "")


class TestGitOperationDecomposition:
    """UC-4: Git operation decomposition."""

    def test_git_workflow_plan(self, decomposer):
        intent = Intent(
            category=IntentCategory.GIT_OPERATION,
            raw_input="Start a feature branch workflow",
            entities={"operation": "workflow", "branch_name": "feature/test"},
            requires_skills=["manage_git_workflow"],
        )
        plan = decomposer.decompose(intent, TENANT, USER, SESSION)
        assert len(plan.steps) == 1
        assert plan.steps[0].action == "forge.execute_skill"
        assert plan.steps[0].payload["skill_name"] == "manage_git_workflow"


class TestSchedulingDecomposition:
    """UC-6: Scheduling decomposition."""

    def test_schedule_nightly_plan(self, decomposer):
        intent = Intent(
            category=IntentCategory.SCHEDULING,
            raw_input="Schedule a nightly memory optimization at 2 AM",
            entities={"schedule_type": "cron", "hour": 2, "minute": 0, "task_description": "nightly memory optimization"},
            requires_tools=["schedule_job"],
        )
        plan = decomposer.decompose(intent, TENANT, USER, SESSION)
        assert len(plan.steps) == 1
        assert plan.steps[0].target_agent == "forge"
        assert plan.steps[0].payload["tool_name"] == "schedule_job"


class TestUserManagementDecomposition:
    """UC-5: User management decomposition."""

    def test_create_user_plan(self, decomposer):
        intent = Intent(
            category=IntentCategory.USER_MANAGEMENT,
            raw_input="Create a new user named TestUser with the member role",
            entities={"operation": "create", "username": "TestUser", "role": "member"},
            requires_skills=["onboard_user"],
        )
        plan = decomposer.decompose(intent, TENANT, USER, SESSION)
        assert len(plan.steps) == 1
        assert plan.steps[0].payload["skill_name"] == "onboard_user"

# tests/test_chunk_011/test_schedule_job_tool.py
# Tests for: Part VIII §8.1 — schedule_job tool
"""
Unit tests for the schedule_job Forge tool.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from aegis.forge.tools.schedule_job import execute, manifest


class TestScheduleJobToolManifest:
    """Tests for the tool manifest definition."""

    def test_manifest_name(self):
        assert manifest.name == "schedule_job"

    def test_manifest_permissions(self):
        assert "scheduler.manage" in manifest.permissions_required

    def test_manifest_has_schema(self):
        schema = manifest.parameters_schema
        assert "properties" in schema
        assert "name" in schema["properties"]
        assert "schedule_type" in schema["properties"]
        assert "action" in schema["properties"]


class TestScheduleJobToolExecute:
    """Tests for the tool execute function."""

    @pytest.mark.asyncio
    async def test_execute_no_scheduler(self):
        """Returns error when scheduler is not running."""
        with patch(
            "aegis.forge.tools.schedule_job.get_scheduler", return_value=None
        ):
            result = await execute({
                "name": "Test",
                "tenant_id": "t1",
                "user_id": "u1",
                "schedule_type": "cron",
                "schedule_config": {"hour": 2},
                "action": "forge.execute_tool",
            })
            assert result.success is False
            assert "not running" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_invalid_params(self):
        """Returns error for invalid parameters."""
        mock_scheduler = AsyncMock()
        mock_scheduler.is_running = True

        with patch(
            "aegis.forge.tools.schedule_job.get_scheduler",
            return_value=mock_scheduler,
        ):
            result = await execute({
                # Missing required fields
                "name": "Incomplete",
            })
            assert result.success is False
            assert "invalid" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_success(self, tmp_path):
        """Successfully registers a job via the tool."""
        from aegis.manager.scheduler import AegisScheduler

        db_path = str(tmp_path / "tool_test.db")
        sched = AegisScheduler(db_path=db_path)
        await sched.start()

        try:
            result = await execute({
                "name": "Nightly Optimization",
                "tenant_id": "t1",
                "user_id": "u1",
                "schedule_type": "cron",
                "schedule_config": {"hour": 2, "minute": 0},
                "action": "forge.execute_skill",
                "action_payload": {"skill_name": "memory_optimize"},
            })
            assert result.success is True
            assert result.data["name"] == "Nightly Optimization"
            assert "job_id" in result.data
        finally:
            await sched.stop()

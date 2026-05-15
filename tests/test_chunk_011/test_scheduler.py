# tests/test_chunk_011/test_scheduler.py
# Tests for: Part XI — Scheduler Protocol
"""
Unit tests for the Aegis Scheduler service and JobStore.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from aegis.schemas.scheduler import (
    JobSummary,
    ScheduledJob,
    ScheduleType,
    SchedulerAction,
    SchedulerRequest,
    SchedulerResponse,
)


# ---------------------------------------------------------------------------
# ScheduledJob Model Tests
# ---------------------------------------------------------------------------

class TestScheduledJobModel:
    """Tests for the ScheduledJob Pydantic model."""

    def test_valid_cron_job(self):
        job = ScheduledJob(
            name="Nightly Backup",
            tenant_id="t1",
            user_id="u1",
            schedule_type=ScheduleType.CRON,
            schedule_config={"hour": 2, "minute": 0},
            action="forge.execute_skill",
            action_payload={"skill_name": "backup"},
        )
        assert job.name == "Nightly Backup"
        assert job.schedule_type == ScheduleType.CRON
        assert job.enabled is True
        assert job.job_id  # Auto-generated

    def test_valid_interval_job(self):
        job = ScheduledJob(
            name="Health Ping",
            tenant_id="t1",
            user_id="u1",
            schedule_type=ScheduleType.INTERVAL,
            schedule_config={"minutes": 5},
            action="forge.execute_tool",
        )
        assert job.schedule_type == ScheduleType.INTERVAL

    def test_valid_date_job(self):
        job = ScheduledJob(
            name="One-Time Task",
            tenant_id="t1",
            user_id="u1",
            schedule_type=ScheduleType.DATE,
            schedule_config={"run_date": "2026-12-25T00:00:00"},
            action="forge.execute_skill",
        )
        assert job.schedule_type == ScheduleType.DATE

    def test_invalid_interval_missing_key(self):
        """Interval jobs must have at least one time key."""
        with pytest.raises(Exception):
            ScheduledJob(
                name="Bad Interval",
                tenant_id="t1",
                user_id="u1",
                schedule_type=ScheduleType.INTERVAL,
                schedule_config={"invalid_key": 5},
                action="forge.execute_tool",
            )

    def test_invalid_date_missing_run_date(self):
        """Date jobs must have run_date."""
        with pytest.raises(Exception):
            ScheduledJob(
                name="Bad Date",
                tenant_id="t1",
                user_id="u1",
                schedule_type=ScheduleType.DATE,
                schedule_config={"other": "value"},
                action="forge.execute_tool",
            )


# ---------------------------------------------------------------------------
# JobStore Tests
# ---------------------------------------------------------------------------

class TestJobStore:
    """Tests for the SQLite-backed JobStore."""

    @pytest.fixture
    def db_path(self, tmp_path):
        return str(tmp_path / "test_jobs.db")

    @pytest.mark.asyncio
    async def test_store_lifecycle(self, db_path):
        """Initialize, save, retrieve, and delete a job."""
        from aegis.manager.scheduler import JobStore

        store = JobStore(db_path)
        await store.initialize()

        job = {
            "job_id": "test-001",
            "name": "Test Job",
            "description": "A test",
            "tenant_id": "t1",
            "user_id": "u1",
            "schedule_type": "cron",
            "schedule_config": {"hour": 3},
            "action": "forge.execute_tool",
            "action_payload": {"tool": "test"},
            "enabled": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        # Save
        await store.save_job(job)

        # Retrieve
        retrieved = await store.get_job("test-001")
        assert retrieved is not None
        assert retrieved["name"] == "Test Job"
        assert retrieved["schedule_config"] == {"hour": 3}

        # List
        jobs = await store.list_jobs(tenant_id="t1")
        assert len(jobs) == 1

        # Delete
        removed = await store.remove_job("test-001")
        assert removed is True

        # Verify deletion
        assert await store.get_job("test-001") is None

        await store.close()

    @pytest.mark.asyncio
    async def test_update_job_field(self, db_path):
        """Can update individual fields on a persisted job."""
        from aegis.manager.scheduler import JobStore

        store = JobStore(db_path)
        await store.initialize()

        job = {
            "job_id": "test-002",
            "name": "Update Test",
            "tenant_id": "t1",
            "user_id": "u1",
            "schedule_type": "interval",
            "schedule_config": {"seconds": 60},
            "action": "forge.execute_tool",
            "enabled": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await store.save_job(job)

        # Disable
        await store.update_job_field("test-002", "enabled", 0)
        updated = await store.get_job("test-002")
        assert updated is not None
        assert updated["enabled"] is False

        await store.close()


# ---------------------------------------------------------------------------
# AegisScheduler Tests
# ---------------------------------------------------------------------------

class TestAegisScheduler:
    """Tests for the AegisScheduler service."""

    @pytest.fixture
    def db_path(self, tmp_path):
        return str(tmp_path / "sched_test.db")

    @pytest.mark.asyncio
    async def test_scheduler_start_stop(self, db_path):
        """Scheduler starts and stops cleanly."""
        from aegis.manager.scheduler import AegisScheduler, get_scheduler

        sched = AegisScheduler(db_path=db_path)
        await sched.start()
        assert sched.is_running
        assert get_scheduler() is sched

        await sched.stop()
        assert not sched.is_running
        assert get_scheduler() is None

    @pytest.mark.asyncio
    async def test_add_and_list_jobs(self, db_path):
        """Can add a job and list it back."""
        from aegis.manager.scheduler import AegisScheduler

        publisher = AsyncMock()
        sched = AegisScheduler(db_path=db_path, bus_publisher=publisher)
        await sched.start()

        job_data = {
            "name": "Test Cron Job",
            "tenant_id": "t1",
            "user_id": "u1",
            "schedule_type": "cron",
            "schedule_config": {"hour": 4, "minute": 30},
            "action": "forge.execute_skill",
            "action_payload": {"skill_name": "test_skill"},
        }

        result = await sched.add_job(job_data)
        assert "job_id" in result
        assert result["name"] == "Test Cron Job"

        jobs = await sched.list_jobs(tenant_id="t1")
        assert len(jobs) == 1
        assert jobs[0]["name"] == "Test Cron Job"

        await sched.stop()

    @pytest.mark.asyncio
    async def test_remove_job(self, db_path):
        """Can remove a job."""
        from aegis.manager.scheduler import AegisScheduler

        sched = AegisScheduler(db_path=db_path)
        await sched.start()

        result = await sched.add_job({
            "name": "To Remove",
            "tenant_id": "t1",
            "user_id": "u1",
            "schedule_type": "interval",
            "schedule_config": {"seconds": 300},
            "action": "forge.execute_tool",
        })

        removed = await sched.remove_job(result["job_id"])
        assert removed is True

        jobs = await sched.list_jobs()
        assert len(jobs) == 0

        await sched.stop()

    @pytest.mark.asyncio
    async def test_pause_resume_job(self, db_path):
        """Can pause and resume a job."""
        from aegis.manager.scheduler import AegisScheduler

        sched = AegisScheduler(db_path=db_path)
        await sched.start()

        result = await sched.add_job({
            "name": "Pausable",
            "tenant_id": "t1",
            "user_id": "u1",
            "schedule_type": "interval",
            "schedule_config": {"minutes": 10},
            "action": "forge.execute_tool",
        })

        job_id = result["job_id"]

        # Pause
        await sched.pause_job(job_id)
        job = await sched.get_job(job_id)
        assert job is not None
        assert job["enabled"] is False

        # Resume
        await sched.resume_job(job_id)
        job = await sched.get_job(job_id)
        assert job is not None
        assert job["enabled"] is True

        await sched.stop()

    @pytest.mark.asyncio
    async def test_on_job_fire_publishes_message(self, db_path):
        """When a job fires, it publishes an AegisMessage to the bus."""
        from aegis.manager.scheduler import AegisScheduler

        publisher = AsyncMock()
        sched = AegisScheduler(db_path=db_path, bus_publisher=publisher)
        await sched.start()

        result = await sched.add_job({
            "name": "Fire Test",
            "tenant_id": "t1",
            "user_id": "u1",
            "schedule_type": "interval",
            "schedule_config": {"seconds": 9999},
            "action": "forge.execute_skill",
            "action_payload": {"skill_name": "backup"},
        })

        # Manually trigger fire
        await sched._on_job_fire(job_id=result["job_id"])

        publisher.assert_called_once()
        message = publisher.call_args[0][0]
        assert message["action"] == "forge.execute_skill"
        assert message["tenant_id"] == "t1"
        assert message["source_agent"] == "scheduler"
        assert message["target_agent"] == "forge"
        assert message["payload"]["skill_name"] == "backup"

        await sched.stop()

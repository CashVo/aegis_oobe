# aegis/manager/scheduler.py
# Implements: Part XI §11.1–§11.3 — Scheduler Protocol
"""
Aegis Scheduler Service.

Wraps APScheduler (v4.x async-native) with an SQLite job store
co-located with Lexicon data. When a job fires, the Scheduler
constructs an ``AegisMessage`` from the job's ``action`` and
``action_payload`` and publishes it to the Redis message bus
for normal agent processing (Warden → Forge → etc.).

Architecture:
    - Managed by SystemManager (not a council agent).
    - Job persistence via SQLAlchemy + SQLite.
    - Exposes add/remove/list/pause/resume operations.
    - Module-level accessor ``get_scheduler()`` for tool integration.

Reference: Part XI, Part III §3.3
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level singleton accessor (used by schedule_job tool)
# ---------------------------------------------------------------------------

_scheduler_instance: Optional["AegisScheduler"] = None


def get_scheduler() -> Optional["AegisScheduler"]:
    """Return the active AegisScheduler instance, or None."""
    return _scheduler_instance


def set_scheduler(instance: Optional["AegisScheduler"]) -> None:
    """Set the module-level scheduler singleton."""
    global _scheduler_instance
    _scheduler_instance = instance


# ---------------------------------------------------------------------------
# Job Store — SQLite-backed persistent storage
# ---------------------------------------------------------------------------

class JobStore:
    """
    Persistent job store using SQLite.

    Stores ScheduledJob definitions as JSON. APScheduler handles its
    own internal schedule state; this store maintains the Aegis job
    metadata (tenant, user, action, payload, etc.) alongside it.
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._conn: Optional[Any] = None

    async def initialize(self) -> None:
        """Create the jobs table if it doesn't exist."""
        import aiosqlite

        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        self._conn = await aiosqlite.connect(self.db_path)
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_jobs (
                job_id      TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                description TEXT DEFAULT '',
                tenant_id   TEXT NOT NULL,
                user_id     TEXT NOT NULL,
                schedule_type TEXT NOT NULL,
                schedule_config TEXT NOT NULL,
                action      TEXT NOT NULL,
                action_payload TEXT DEFAULT '{}',
                enabled     INTEGER DEFAULT 1,
                created_at  TEXT NOT NULL,
                last_run    TEXT,
                next_run    TEXT
            )
        """)
        await self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_jobs_tenant
            ON scheduled_jobs (tenant_id, user_id)
        """)
        await self._conn.commit()
        logger.info("JobStore initialized at %s", self.db_path)

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def save_job(self, job: Dict[str, Any]) -> None:
        """Insert or replace a job definition."""
        if not self._conn:
            raise RuntimeError("JobStore not initialized")
        await self._conn.execute(
            """
            INSERT OR REPLACE INTO scheduled_jobs
                (job_id, name, description, tenant_id, user_id,
                 schedule_type, schedule_config, action, action_payload,
                 enabled, created_at, last_run, next_run)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job["job_id"],
                job["name"],
                job.get("description", ""),
                job["tenant_id"],
                job["user_id"],
                job["schedule_type"],
                json.dumps(job["schedule_config"]),
                job["action"],
                json.dumps(job.get("action_payload", {})),
                1 if job.get("enabled", True) else 0,
                job.get("created_at", datetime.now(timezone.utc).isoformat()),
                job.get("last_run"),
                job.get("next_run"),
            ),
        )
        await self._conn.commit()

    async def remove_job(self, job_id: str) -> bool:
        """Delete a job by ID. Returns True if a row was deleted."""
        if not self._conn:
            raise RuntimeError("JobStore not initialized")
        cursor = await self._conn.execute(
            "DELETE FROM scheduled_jobs WHERE job_id = ?", (job_id,)
        )
        await self._conn.commit()
        return cursor.rowcount > 0

    async def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a single job by ID."""
        if not self._conn:
            raise RuntimeError("JobStore not initialized")
        cursor = await self._conn.execute(
            "SELECT * FROM scheduled_jobs WHERE job_id = ?", (job_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_dict(cursor.description, row)

    async def list_jobs(
        self,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List jobs, optionally filtered by tenant/user."""
        if not self._conn:
            raise RuntimeError("JobStore not initialized")

        query = "SELECT * FROM scheduled_jobs WHERE 1=1"
        params: List[Any] = []
        if tenant_id:
            query += " AND tenant_id = ?"
            params.append(tenant_id)
        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)
        query += " ORDER BY created_at DESC"

        cursor = await self._conn.execute(query, params)
        rows = await cursor.fetchall()
        return [self._row_to_dict(cursor.description, r) for r in rows]

    async def update_job_field(
        self, job_id: str, field: str, value: Any
    ) -> bool:
        """Update a single field on a job."""
        allowed_fields = {
            "enabled", "last_run", "next_run", "name",
            "description", "schedule_config", "action_payload",
        }
        if field not in allowed_fields:
            raise ValueError(f"Cannot update field: {field}")
        if not self._conn:
            raise RuntimeError("JobStore not initialized")

        if field in ("schedule_config", "action_payload") and isinstance(value, dict):
            value = json.dumps(value)

        cursor = await self._conn.execute(
            f"UPDATE scheduled_jobs SET {field} = ? WHERE job_id = ?",
            (value, job_id),
        )
        await self._conn.commit()
        return cursor.rowcount > 0

    @staticmethod
    def _row_to_dict(description, row) -> Dict[str, Any]:
        """Convert a sqlite row + description to a dict."""
        cols = [d[0] for d in description]
        d = dict(zip(cols, row))
        # Parse JSON fields back
        for json_field in ("schedule_config", "action_payload"):
            if json_field in d and isinstance(d[json_field], str):
                try:
                    d[json_field] = json.loads(d[json_field])
                except (json.JSONDecodeError, TypeError):
                    pass
        # Convert enabled back to bool
        if "enabled" in d:
            d["enabled"] = bool(d["enabled"])
        return d


# ---------------------------------------------------------------------------
# Trigger Factory
# ---------------------------------------------------------------------------

def _build_trigger(schedule_type: str, schedule_config: Dict[str, Any]) -> Any:
    """
    Construct an APScheduler trigger from the ScheduledJob specification.

    Falls back to a simple dict representation if APScheduler is not installed.
    """
    try:
        from apscheduler.triggers.cron import CronTrigger
        from apscheduler.triggers.interval import IntervalTrigger
        from apscheduler.triggers.date import DateTrigger

        if schedule_type == "cron":
            return CronTrigger(**schedule_config)
        elif schedule_type == "interval":
            return IntervalTrigger(**schedule_config)
        elif schedule_type == "date":
            return DateTrigger(**schedule_config)
        else:
            raise ValueError(f"Unknown schedule_type: {schedule_type}")
    except ImportError:
        logger.warning(
            "APScheduler not installed — returning raw trigger config"
        )
        return {"type": schedule_type, **schedule_config}


# ---------------------------------------------------------------------------
# The Aegis Scheduler
# ---------------------------------------------------------------------------

class AegisScheduler:
    """
    Aegis Scheduler Service.

    Manages scheduled jobs using APScheduler (v4.x) with SQLite persistence.
    When a job fires, constructs an ``AegisMessage`` and publishes it to the
    Redis message bus for standard agent processing.

    Lifecycle:
        1. ``start()``   — Initialize store, load persisted jobs, start APScheduler.
        2. ``add_job()``  — Register a new ScheduledJob.
        3. ``stop()``     — Gracefully shut down APScheduler, close store.

    Reference: Part XI §11.1–§11.3
    """

    def __init__(
        self,
        db_path: str = "aegis_data/scheduler_jobs.db",
        bus_publisher: Optional[Callable] = None,
    ) -> None:
        """
        Args:
            db_path:       Path to the SQLite job store database.
            bus_publisher: Async callable that accepts an AegisMessage dict
                           and publishes it to the Redis bus. Injected by
                           SystemManager at startup.
        """
        self.db_path = db_path
        self._bus_publisher = bus_publisher
        self._store = JobStore(db_path)
        self._ap_scheduler: Optional[Any] = None
        self._running = False
        self._fire_tasks: Dict[str, asyncio.Task] = {}
        self._fallback_mode = False
        self._fallback_tasks: Dict[str, asyncio.Task] = {}

    @property
    def is_running(self) -> bool:
        return self._running

    # -- Lifecycle -----------------------------------------------------------

    async def start(self) -> None:
        """Initialize the job store and start the APScheduler backend."""
        await self._store.initialize()
        set_scheduler(self)

        # Try APScheduler 4.x
        try:
            from apscheduler import AsyncScheduler
            from apscheduler.datastores.sqlalchemy import SQLAlchemyDataStore

            ds = SQLAlchemyDataStore(
                engine_or_url=f"sqlite+aiosqlite:///{self.db_path.replace('.db', '_aps.db')}"
            )
            self._ap_scheduler = AsyncScheduler(data_store=ds)
            await self._ap_scheduler.__aenter__()
            self._fallback_mode = False
            logger.info("AegisScheduler started with APScheduler 4.x backend")
        except ImportError:
            logger.warning(
                "APScheduler not available — using asyncio fallback scheduler. "
                "Install with: pip install apscheduler>=4.0"
            )
            self._fallback_mode = True

        # Reload persisted jobs
        await self._reload_persisted_jobs()
        self._running = True
        logger.info("AegisScheduler is running (fallback=%s)", self._fallback_mode)

    async def stop(self) -> None:
        """Gracefully stop the scheduler and close the job store."""
        self._running = False

        # Cancel all fallback tasks
        for task in self._fallback_tasks.values():
            task.cancel()
        self._fallback_tasks.clear()

        # Shutdown APScheduler
        if self._ap_scheduler is not None:
            try:
                await self._ap_scheduler.__aexit__(None, None, None)
            except Exception as exc:
                logger.warning("Error shutting down APScheduler: %s", exc)
            self._ap_scheduler = None

        await self._store.close()
        set_scheduler(None)
        logger.info("AegisScheduler stopped")

    # -- Job Operations ------------------------------------------------------

    async def add_job(self, job_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Register a new scheduled job.

        Args:
            job_data: Dict conforming to the ScheduledJob schema.

        Returns:
            The persisted job dict (with job_id populated).

        Implements: Part XI §11.3 steps 4–5
        """
        from aegis.schemas.scheduler import ScheduledJob

        job = ScheduledJob(**job_data)
        job_dict = job.model_dump()
        job_dict["created_at"] = job_dict["created_at"].isoformat()

        # Persist to store
        await self._store.save_job(job_dict)

        # Register with scheduling backend
        if job.enabled:
            await self._register_trigger(job_dict)

        logger.info("Scheduled job added: %s (%s)", job.name, job.job_id)
        return job_dict

    async def remove_job(self, job_id: str) -> bool:
        """
        Remove a scheduled job by ID.

        Returns:
            True if the job was found and removed.
        """
        # Unregister from scheduling backend
        await self._unregister_trigger(job_id)

        removed = await self._store.remove_job(job_id)
        if removed:
            logger.info("Scheduled job removed: %s", job_id)
        else:
            logger.warning("Job not found for removal: %s", job_id)
        return removed

    async def list_jobs(
        self,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List jobs, optionally filtered by tenant/user."""
        return await self._store.list_jobs(tenant_id=tenant_id, user_id=user_id)

    async def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a job by ID."""
        return await self._store.get_job(job_id)

    async def pause_job(self, job_id: str) -> bool:
        """Pause (disable) a job."""
        await self._unregister_trigger(job_id)
        return await self._store.update_job_field(job_id, "enabled", 0)

    async def resume_job(self, job_id: str) -> bool:
        """Resume (enable) a paused job."""
        updated = await self._store.update_job_field(job_id, "enabled", 1)
        if updated:
            job = await self._store.get_job(job_id)
            if job:
                await self._register_trigger(job)
        return updated

    # -- Trigger Management --------------------------------------------------

    async def _register_trigger(self, job_dict: Dict[str, Any]) -> None:
        """Register a job's trigger with the scheduling backend."""
        job_id = job_dict["job_id"]
        schedule_type = job_dict["schedule_type"]
        schedule_config = job_dict["schedule_config"]

        if not self._fallback_mode and self._ap_scheduler is not None:
            try:
                trigger = _build_trigger(schedule_type, schedule_config)
                await self._ap_scheduler.add_schedule(
                    self._on_job_fire,
                    trigger,
                    id=job_id,
                    kwargs={"job_id": job_id},
                    conflict_policy="replace",
                )
                logger.debug("APScheduler trigger registered for job %s", job_id)
            except Exception as exc:
                logger.error(
                    "Failed to register APScheduler trigger for %s: %s — "
                    "falling back to asyncio",
                    job_id,
                    exc,
                )
                self._start_fallback_task(job_dict)
        else:
            self._start_fallback_task(job_dict)

    async def _unregister_trigger(self, job_id: str) -> None:
        """Unregister a job's trigger from the scheduling backend."""
        # Cancel fallback task if any
        task = self._fallback_tasks.pop(job_id, None)
        if task:
            task.cancel()

        # Remove from APScheduler
        if not self._fallback_mode and self._ap_scheduler is not None:
            try:
                await self._ap_scheduler.remove_schedule(job_id)
            except Exception:
                pass  # May not exist

    async def _reload_persisted_jobs(self) -> None:
        """Reload all enabled jobs from the store and register triggers."""
        jobs = await self._store.list_jobs()
        count = 0
        for job in jobs:
            if job.get("enabled"):
                await self._register_trigger(job)
                count += 1
        logger.info("Reloaded %d enabled jobs from store", count)

    # -- Fallback Scheduler (asyncio-based) ----------------------------------

    def _start_fallback_task(self, job_dict: Dict[str, Any]) -> None:
        """Start an asyncio-based fallback schedule loop for a job."""
        job_id = job_dict["job_id"]
        schedule_type = job_dict["schedule_type"]
        schedule_config = job_dict["schedule_config"]

        if schedule_type == "interval":
            interval_seconds = (
                schedule_config.get("seconds", 0)
                + schedule_config.get("minutes", 0) * 60
                + schedule_config.get("hours", 0) * 3600
                + schedule_config.get("days", 0) * 86400
                + schedule_config.get("weeks", 0) * 604800
            )
            if interval_seconds <= 0:
                logger.error("Invalid interval for job %s", job_id)
                return

            task = asyncio.create_task(
                self._fallback_interval_loop(job_id, interval_seconds),
                name=f"scheduler-fallback-{job_id}",
            )
            self._fallback_tasks[job_id] = task

        elif schedule_type == "cron":
            # Simplified cron: check every 60s if we match the cron config
            task = asyncio.create_task(
                self._fallback_cron_loop(job_id, schedule_config),
                name=f"scheduler-fallback-{job_id}",
            )
            self._fallback_tasks[job_id] = task

        elif schedule_type == "date":
            task = asyncio.create_task(
                self._fallback_date_fire(job_id, schedule_config),
                name=f"scheduler-fallback-{job_id}",
            )
            self._fallback_tasks[job_id] = task

    async def _fallback_interval_loop(
        self, job_id: str, interval_seconds: float
    ) -> None:
        """Fire a job at a fixed interval."""
        try:
            while self._running:
                await asyncio.sleep(interval_seconds)
                if self._running:
                    await self._on_job_fire(job_id=job_id)
        except asyncio.CancelledError:
            pass

    async def _fallback_cron_loop(
        self, job_id: str, config: Dict[str, Any]
    ) -> None:
        """Simplified cron: check every 60s if current time matches config."""
        try:
            target_hour = config.get("hour")
            target_minute = config.get("minute", 0)
            last_fire_date: Optional[str] = None

            while self._running:
                await asyncio.sleep(30)  # Check every 30 seconds
                now = datetime.now(timezone.utc)

                if target_hour is not None and (
                    now.hour == int(target_hour)
                    and now.minute == int(target_minute)
                ):
                    today_str = now.strftime("%Y-%m-%d")
                    if last_fire_date != today_str:
                        last_fire_date = today_str
                        await self._on_job_fire(job_id=job_id)
        except asyncio.CancelledError:
            pass

    async def _fallback_date_fire(
        self, job_id: str, config: Dict[str, Any]
    ) -> None:
        """Fire once at a specific date/time."""
        try:
            from datetime import datetime as dt

            run_date_str = config.get("run_date", "")
            if not run_date_str:
                return
            run_date = dt.fromisoformat(run_date_str)
            if run_date.tzinfo is None:
                run_date = run_date.replace(tzinfo=timezone.utc)

            delay = (run_date - datetime.now(timezone.utc)).total_seconds()
            if delay > 0:
                await asyncio.sleep(delay)
                if self._running:
                    await self._on_job_fire(job_id=job_id)
        except asyncio.CancelledError:
            pass

    # -- Job Execution Callback ----------------------------------------------

    async def _on_job_fire(self, job_id: str) -> None:
        """
        Callback invoked when a scheduled job fires.

        Constructs an AegisMessage from the job's action/payload and
        publishes it to the Redis bus for normal agent processing.

        Implements: Part XI §11.3 steps 6–7
        """
        job = await self._store.get_job(job_id)
        if job is None:
            logger.warning("Fired job %s not found in store — skipping", job_id)
            return

        if not job.get("enabled", True):
            logger.debug("Job %s is disabled — skipping fire", job_id)
            return

        logger.info(
            "Job fired: %s (%s) → action=%s",
            job["name"],
            job_id,
            job["action"],
        )

        # Update last_run
        now_iso = datetime.now(timezone.utc).isoformat()
        await self._store.update_job_field(job_id, "last_run", now_iso)

        # Construct AegisMessage envelope
        message = {
            "message_id": str(uuid4()),
            "correlation_id": str(uuid4()),
            "source_agent": "scheduler",
            "target_agent": _resolve_target_agent(job["action"]),
            "message_type": "request",
            "tenant_id": job["tenant_id"],
            "user_id": job["user_id"],
            "action": job["action"],
            "payload": job.get("action_payload", {}),
            "priority": "normal",
            "timestamp": now_iso,
            "ttl_seconds": 300,
            "metadata": {
                "scheduled_job_id": job_id,
                "scheduled_job_name": job["name"],
                "trigger_type": "scheduler",
            },
        }

        # Publish to bus
        if self._bus_publisher:
            try:
                await self._bus_publisher(message)
                logger.info(
                    "Published scheduled message for job %s → %s",
                    job_id,
                    message["target_agent"],
                )
            except Exception as exc:
                logger.error(
                    "Failed to publish scheduled message for job %s: %s",
                    job_id,
                    exc,
                )
        else:
            logger.warning(
                "No bus publisher configured — job %s message not delivered: %s",
                job_id,
                message,
            )


def _resolve_target_agent(action: str) -> str:
    """
    Resolve the target agent from an action string.

    Convention: action is 'agent.operation' (e.g., 'forge.execute_tool').
    Falls back to 'torchestrator' for unrecognized patterns.
    """
    agent_map = {
        "forge": "forge",
        "oracle": "oracle",
        "lexicon": "lexicon",
        "warden": "warden",
        "identity": "identity",
        "janus": "janus",
        "torchestrator": "torchestrator",
    }
    prefix = action.split(".")[0] if "." in action else ""
    return agent_map.get(prefix, "torchestrator")

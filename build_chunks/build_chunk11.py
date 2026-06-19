# build_chunk_011.py
#
# CHUNK-011: System Manager & Scheduler
# Dependencies: CHUNK-002 (Redis Message Bus), CHUNK-005 (Observer), CHUNK-009 (The Forge)
# Implements: Part III §3.3 (System Manager), Part XI (Scheduler Protocol),
#             Part VIII §8.1 (schedule_job tool), Part XIV Build Plan
#
# Run from the root of your project-aegis directory:
#   python build_chunk_011.py

import os
import textwrap

CHUNK_011_FILES = {

    # ──────────────────────────────────────────────────────────────────────
    # 1. SCHEMAS — ScheduledJob & Scheduler Action Models
    # Implements: Part XI §11.2 — Job Definition
    # ──────────────────────────────────────────────────────────────────────
    "aegis/schemas/scheduler.py": '''
# aegis/schemas/scheduler.py
# Implements: Part XI §11.2 — Job Definition
"""
Pydantic models for the Aegis Scheduler subsystem.

Defines the ScheduledJob contract, scheduler actions, and
request/response envelopes for scheduler operations.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """Return timezone-aware UTC now."""
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ScheduleType(str, Enum):
    """Supported schedule trigger types (maps to APScheduler triggers)."""
    CRON = "cron"
    INTERVAL = "interval"
    DATE = "date"


class SchedulerAction(str, Enum):
    """Actions the Scheduler service understands."""
    ADD_JOB = "add_job"
    REMOVE_JOB = "remove_job"
    LIST_JOBS = "list_jobs"
    PAUSE_JOB = "pause_job"
    RESUME_JOB = "resume_job"
    GET_JOB = "get_job"
    UPDATE_JOB = "update_job"


# ---------------------------------------------------------------------------
# Core Model — ScheduledJob (spec §11.2)
# ---------------------------------------------------------------------------

class ScheduledJob(BaseModel):
    """
    Canonical definition of a scheduled job in the Aegis system.

    When a job fires, the Scheduler constructs an ``AegisMessage`` using
    ``action`` and ``action_payload`` and publishes it to the message bus
    for normal agent processing (Warden auth → Forge execution → etc.).

    Reference: Part XI §11.2
    """

    job_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique identifier for this job.",
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="Human-readable job name.",
    )
    description: str = Field(
        default="",
        max_length=1024,
        description="Optional description of what this job does.",
    )
    tenant_id: str = Field(
        ...,
        description="Tenant scope for this job.",
    )
    user_id: str = Field(
        ...,
        description="User who owns this job.",
    )
    schedule_type: ScheduleType = Field(
        ...,
        description="Trigger type: 'cron', 'interval', or 'date'.",
    )
    schedule_config: Dict[str, Any] = Field(
        ...,
        description=(
            "Trigger-specific configuration. "
            "cron: {hour: 2, minute: 0, day_of_week: 'mon-fri'} | "
            "interval: {seconds: 300} | "
            "date: {run_date: '2026-06-01T00:00:00'}"
        ),
    )
    action: str = Field(
        ...,
        description=(
            "The AegisMessage action to dispatch when the job fires. "
            "e.g., 'forge.execute_skill', 'forge.execute_tool'"
        ),
    )
    action_payload: Dict[str, Any] = Field(
        default_factory=dict,
        description="Payload attached to the dispatched AegisMessage.",
    )
    enabled: bool = Field(
        default=True,
        description="Whether the job is currently active.",
    )
    created_at: datetime = Field(
        default_factory=_utcnow,
        description="UTC timestamp of job creation.",
    )
    last_run: Optional[datetime] = Field(
        default=None,
        description="UTC timestamp of the most recent execution.",
    )
    next_run: Optional[datetime] = Field(
        default=None,
        description="UTC timestamp of the next scheduled execution.",
    )

    # -- Validators ----------------------------------------------------------

    @field_validator("schedule_config")
    @classmethod
    def _validate_schedule_config(cls, v: Dict[str, Any], info) -> Dict[str, Any]:
        """Basic sanity checks on schedule_config per schedule_type."""
        stype = info.data.get("schedule_type")
        if stype == ScheduleType.INTERVAL:
            has_interval_key = any(
                k in v for k in ("seconds", "minutes", "hours", "days", "weeks")
            )
            if not has_interval_key:
                raise ValueError(
                    "interval schedule_config must contain at least one of: "
                    "seconds, minutes, hours, days, weeks"
                )
        elif stype == ScheduleType.DATE:
            if "run_date" not in v:
                raise ValueError(
                    "date schedule_config must contain 'run_date'"
                )
        # cron is flexible — APScheduler validates the fields
        return v


# ---------------------------------------------------------------------------
# Request / Response Envelopes
# ---------------------------------------------------------------------------

class SchedulerRequest(BaseModel):
    """Envelope for scheduler operations arriving via the message bus."""
    action: SchedulerAction
    tenant_id: str
    user_id: str
    payload: Dict[str, Any] = Field(default_factory=dict)


class SchedulerResponse(BaseModel):
    """Envelope for scheduler operation results."""
    success: bool
    action: SchedulerAction
    data: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


class JobSummary(BaseModel):
    """Lightweight view of a ScheduledJob for list endpoints."""
    job_id: str
    name: str
    schedule_type: ScheduleType
    enabled: bool
    next_run: Optional[datetime] = None
    last_run: Optional[datetime] = None
''',

    # ──────────────────────────────────────────────────────────────────────
    # 2. MANAGER PACKAGE — __init__.py
    # ──────────────────────────────────────────────────────────────────────
    "aegis/manager/__init__.py": '''
# aegis/manager/__init__.py
# Implements: Part III §3.3 — System Manager Package
"""
Aegis Manager package.

Exports:
    SystemManager  — Full lifecycle manager for all agents and services.
    AegisScheduler — APScheduler-backed job scheduler service.
    AgentEntry     — Registry entry for a managed agent.
    AGENT_REGISTRY — Ordered registry of all council agents.
"""

from aegis.manager.agent_registry import AgentEntry, AGENT_REGISTRY
from aegis.manager.scheduler import AegisScheduler
from aegis.manager.system_manager import SystemManager

__all__ = [
    "SystemManager",
    "AegisScheduler",
    "AgentEntry",
    "AGENT_REGISTRY",
]
''',

    # ──────────────────────────────────────────────────────────────────────
    # 3. AGENT REGISTRY — Discovery & Instantiation Map
    # Implements: Part III §3.3 — Ordered startup
    # ──────────────────────────────────────────────────────────────────────
    "aegis/manager/agent_registry.py": '''
# aegis/manager/agent_registry.py
# Implements: Part III §3.3 — Ordered startup of agents
"""
Agent Registry for the Aegis System Manager.

Provides an ordered manifest of all council agents so the System Manager
can start, stop, and restart them in the correct dependency sequence.

Startup order (from spec §3.3):
    Redis → Observer → Warden → Identity → Lexicon → Janus → Oracle → Forge → TOrchestrator

Note: Redis is infrastructure, not an agent — it is verified separately.
The Observer is a non-council service started first for logging coverage.
"""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type

logger = logging.getLogger(__name__)


@dataclass
class AgentEntry:
    """
    Descriptor for a single managed agent.

    Attributes:
        agent_id:     Unique identifier matching the agent's ``agent_id`` attribute.
        display_name: Human-readable name for logs and UI.
        module_path:  Dotted Python module path containing the agent class.
        class_name:   Name of the agent class within the module.
        priority:     Startup priority (lower = earlier). Shutdown is reverse.
        required:     If True, system cannot proceed without this agent.
        config_key:   Optional key in aegis_config.yaml for agent-specific config.
        restart_max:  Maximum restart attempts before declaring failure.
        tags:         Arbitrary metadata tags (e.g., "council", "service").
    """

    agent_id: str
    display_name: str
    module_path: str
    class_name: str
    priority: int
    required: bool = True
    config_key: Optional[str] = None
    restart_max: int = 3
    tags: List[str] = field(default_factory=list)

    def import_class(self) -> Optional[Type[Any]]:
        """
        Dynamically import and return the agent class.

        Returns:
            The agent class, or None if the module/class cannot be imported.
        """
        try:
            module = importlib.import_module(self.module_path)
            cls = getattr(module, self.class_name)
            logger.debug(
                "Imported agent class: %s.%s", self.module_path, self.class_name
            )
            return cls
        except (ImportError, AttributeError) as exc:
            logger.warning(
                "Failed to import agent '%s' from %s.%s: %s",
                self.agent_id,
                self.module_path,
                self.class_name,
                exc,
            )
            return None


# ---------------------------------------------------------------------------
# Canonical Agent Registry — ordered by startup priority
# Implements: Part III §3.3 startup sequence
# ---------------------------------------------------------------------------

AGENT_REGISTRY: List[AgentEntry] = [
    AgentEntry(
        agent_id="observer",
        display_name="Observer Service",
        module_path="aegis.agents.observer",
        class_name="ObserverAgent",
        priority=10,
        required=False,  # System can run with degraded logging (RT-3)
        config_key="observer",
        restart_max=5,
        tags=["service", "monitoring"],
    ),
    AgentEntry(
        agent_id="warden",
        display_name="Warden (Security)",
        module_path="aegis.agents.warden",
        class_name="WardenAgent",
        priority=20,
        required=True,  # Security is non-negotiable
        config_key="warden",
        restart_max=5,  # Highest restart priority (RT-4)
        tags=["council", "security"],
    ),
    AgentEntry(
        agent_id="identity",
        display_name="Identity Agent",
        module_path="aegis.agents.identity",
        class_name="IdentityAgent",
        priority=30,
        required=True,
        config_key="identity",
        tags=["council", "iam"],
    ),
    AgentEntry(
        agent_id="lexicon",
        display_name="Lexicon (Memory)",
        module_path="aegis.agents.lexicon",
        class_name="LexiconAgent",
        priority=40,
        required=True,
        config_key="lexicon",
        tags=["council", "memory"],
    ),
    AgentEntry(
        agent_id="janus",
        display_name="Janus (Governance)",
        module_path="aegis.agents.janus",
        class_name="JanusAgent",
        priority=50,
        required=True,
        config_key="janus",
        tags=["council", "governance"],
    ),
    AgentEntry(
        agent_id="oracle",
        display_name="Oracle (LLM Gateway)",
        module_path="aegis.agents.oracle",
        class_name="OracleAgent",
        priority=60,
        required=True,
        config_key="oracle",
        tags=["council", "llm"],
    ),
    AgentEntry(
        agent_id="forge",
        display_name="The Forge (Execution)",
        module_path="aegis.agents.forge",
        class_name="ForgeAgent",
        priority=70,
        required=True,
        config_key="forge",
        tags=["council", "execution"],
    ),
    AgentEntry(
        agent_id="torchestrator",
        display_name="TOrchestrator (Council Lead)",
        module_path="aegis.agents.torchestrator",
        class_name="TorchestratorAgent",
        priority=80,
        required=True,
        config_key="torchestrator",
        tags=["council", "orchestration"],
    ),
]


def get_startup_order() -> List[AgentEntry]:
    """Return agents sorted by ascending priority (startup order)."""
    return sorted(AGENT_REGISTRY, key=lambda e: e.priority)


def get_shutdown_order() -> List[AgentEntry]:
    """Return agents sorted by descending priority (reverse startup)."""
    return sorted(AGENT_REGISTRY, key=lambda e: e.priority, reverse=True)


def get_agent_entry(agent_id: str) -> Optional[AgentEntry]:
    """Look up an AgentEntry by agent_id."""
    for entry in AGENT_REGISTRY:
        if entry.agent_id == agent_id:
            return entry
    return None
''',

    # ──────────────────────────────────────────────────────────────────────
    # 4. SCHEDULER SERVICE — APScheduler Integration
    # Implements: Part XI §11.1–§11.3 — Scheduler Protocol
    # ──────────────────────────────────────────────────────────────────────
    "aegis/manager/scheduler.py": '''
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
''',

    # ──────────────────────────────────────────────────────────────────────
    # 5. SYSTEM MANAGER — Agent Lifecycle & Orchestration
    # Implements: Part III §3.3 — System Manager
    # ──────────────────────────────────────────────────────────────────────
    "aegis/manager/system_manager.py": '''
# aegis/manager/system_manager.py
# Implements: Part III §3.3 — System Manager
"""
Aegis System Manager.

The top-level lifecycle controller for the entire Aegis system.
Responsibilities:
    1. Ordered startup:  Redis → Observer → Warden → Identity → Lexicon
                         → Janus → Oracle → Forge → TOrchestrator
    2. Graceful shutdown: Reverse startup order.
    3. Health-check polling with configurable intervals.
    4. Automatic restart of failed agents (with backoff & retry limits).
    5. Scheduler service management (APScheduler integration).

Entry point: ``python -m aegis.main``

Reference: Part III §3.3, Part XI §11.1
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import structlog

from aegis.manager.agent_registry import (
    AGENT_REGISTRY,
    AgentEntry,
    get_shutdown_order,
    get_startup_order,
)
from aegis.manager.scheduler import AegisScheduler

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Configuration Defaults
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "redis": {
        "host": "localhost",
        "port": 6379,
        "db": 0,
    },
    "system_manager": {
        "health_check_interval_seconds": 30,
        "restart_max_retries": 3,
        "restart_backoff_base_seconds": 2.0,
        "restart_backoff_max_seconds": 60.0,
        "startup_timeout_seconds": 30,
        "shutdown_timeout_seconds": 15,
    },
    "scheduler": {
        "enabled": True,
        "job_store_path": "aegis_data/scheduler_jobs.db",
    },
}


def _load_config(config_path: str = "aegis_config.yaml") -> Dict[str, Any]:
    """
    Load system configuration from aegis_config.yaml.

    Falls back to DEFAULT_CONFIG if file is missing.
    Env vars override: AEGIS_REDIS_HOST, AEGIS_REDIS_PORT, etc.
    Precedence: CLI > ENV > YAML > defaults  (RT-2)
    """
    config = dict(DEFAULT_CONFIG)

    if os.path.exists(config_path):
        try:
            import yaml

            with open(config_path, "r") as f:
                file_config = yaml.safe_load(f) or {}
            _deep_merge(config, file_config)
            logger.info("Loaded config from %s", config_path)
        except ImportError:
            logger.warning(
                "PyYAML not installed — using default config. "
                "Install with: pip install pyyaml"
            )
        except Exception as exc:
            logger.warning("Failed to load %s: %s — using defaults", config_path, exc)

    # Env var overrides
    env_overrides = {
        "AEGIS_REDIS_HOST": ("redis", "host"),
        "AEGIS_REDIS_PORT": ("redis", "port"),
        "AEGIS_REDIS_DB": ("redis", "db"),
        "AEGIS_HEALTH_INTERVAL": ("system_manager", "health_check_interval_seconds"),
        "AEGIS_SCHEDULER_ENABLED": ("scheduler", "enabled"),
        "AEGIS_SCHEDULER_DB": ("scheduler", "job_store_path"),
    }
    for env_key, path in env_overrides.items():
        val = os.environ.get(env_key)
        if val is not None:
            section = config.setdefault(path[0], {})
            # Type coercion
            if path[1] in ("port", "db", "health_check_interval_seconds"):
                val = int(val)
            elif path[1] == "enabled":
                val = val.lower() in ("true", "1", "yes")
            section[path[1]] = val

    return config


def _deep_merge(base: dict, override: dict) -> None:
    """Recursively merge override into base."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


# ---------------------------------------------------------------------------
# Agent Health State
# ---------------------------------------------------------------------------

class AgentState:
    """Runtime state tracker for a single managed agent."""

    def __init__(self, entry: AgentEntry) -> None:
        self.entry = entry
        self.instance: Optional[Any] = None
        self.task: Optional[asyncio.Task] = None
        self.status: str = "stopped"  # stopped | starting | running | failed | restarting
        self.restart_count: int = 0
        self.last_heartbeat: Optional[datetime] = None
        self.error: Optional[str] = None

    def reset(self) -> None:
        self.status = "stopped"
        self.restart_count = 0
        self.error = None
        self.instance = None
        self.task = None


# ---------------------------------------------------------------------------
# System Manager
# ---------------------------------------------------------------------------

class SystemManager:
    """
    Orchestrates the full lifecycle of the Aegis system.

    Usage::

        manager = SystemManager()
        await manager.run()  # Blocks until shutdown signal

    Or for programmatic control::

        manager = SystemManager()
        await manager.start()
        # ... system is running ...
        await manager.stop()
    """

    def __init__(
        self,
        config_path: str = "aegis_config.yaml",
        config_override: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._config = _load_config(config_path)
        if config_override:
            _deep_merge(self._config, config_override)

        self._sm_config = self._config.get("system_manager", DEFAULT_CONFIG["system_manager"])
        self._redis_config = self._config.get("redis", DEFAULT_CONFIG["redis"])
        self._sched_config = self._config.get("scheduler", DEFAULT_CONFIG["scheduler"])

        self._agents: Dict[str, AgentState] = {}
        self._scheduler: Optional[AegisScheduler] = None
        self._redis_conn: Optional[Any] = None
        self._health_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()
        self._running = False

        # Initialize agent states from registry
        for entry in AGENT_REGISTRY:
            self._agents[entry.agent_id] = AgentState(entry)

    # -- Properties ----------------------------------------------------------

    @property
    def config(self) -> Dict[str, Any]:
        return dict(self._config)

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def scheduler(self) -> Optional[AegisScheduler]:
        return self._scheduler

    # -- Main Entry Point ----------------------------------------------------

    async def run(self) -> None:
        """
        Start the system and block until a shutdown signal is received.

        This is the primary entry point for ``python -m aegis.main``.
        """
        # Register signal handlers
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._handle_signal, sig)
            except NotImplementedError:
                # Windows doesn't support add_signal_handler
                pass

        try:
            await self.start()
            logger.info("Aegis system is running. Press Ctrl+C to stop.")
            await self._shutdown_event.wait()
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received")
        finally:
            await self.stop()

    def _handle_signal(self, sig: signal.Signals) -> None:
        """Signal handler to initiate graceful shutdown."""
        logger.info("Received signal %s — initiating graceful shutdown", sig.name)
        self._shutdown_event.set()

    # -- Startup Sequence ----------------------------------------------------

    async def start(self) -> None:
        """
        Execute the full startup sequence.

        Order: Redis → Scheduler → Agents (by priority)

        Implements: Part III §3.3 — ordered startup
        """
        logger.info("=" * 60)
        logger.info("  AEGIS SYSTEM MANAGER — STARTUP SEQUENCE")
        logger.info("=" * 60)

        # Step 1: Verify Redis connectivity
        await self._verify_redis()

        # Step 2: Start Scheduler (if enabled)
        if self._sched_config.get("enabled", True):
            await self._start_scheduler()

        # Step 3: Start agents in priority order
        for entry in get_startup_order():
            state = self._agents.get(entry.agent_id)
            if state is None:
                continue
            await self._start_agent(state)

        # Step 4: Start health check loop
        self._health_task = asyncio.create_task(
            self._health_check_loop(),
            name="system-manager-health-check",
        )

        self._running = True
        logger.info("=" * 60)
        logger.info("  AEGIS SYSTEM — ALL AGENTS ONLINE")
        logger.info("=" * 60)

        # Step 5: First-run bootstrap check
        await self._check_first_run()

    async def _verify_redis(self) -> None:
        """
        Verify Redis connectivity before launching any agents.

        Implements: Part III §3.1 — Startup verification
        """
        logger.info("[Redis] Verifying connectivity...")
        try:
            import redis.asyncio as aioredis

            host = self._redis_config.get("host", "localhost")
            port = self._redis_config.get("port", 6379)
            db = self._redis_config.get("db", 0)

            self._redis_conn = aioredis.Redis(host=host, port=port, db=db)
            pong = await self._redis_conn.ping()
            if pong:
                logger.info("[Redis] Connected to %s:%s (db=%s)", host, port, db)
            else:
                raise ConnectionError("Redis PING returned False")
        except ImportError:
            logger.error(
                "[Redis] redis.asyncio not installed. "
                "Install with: pip install redis"
            )
            raise SystemExit(1)
        except Exception as exc:
            logger.error(
                "[Redis] Failed to connect: %s. "
                "Ensure redis-server is running.",
                exc,
            )
            raise SystemExit(1)

    async def _start_scheduler(self) -> None:
        """Initialize and start the Aegis Scheduler service."""
        logger.info("[Scheduler] Starting...")
        db_path = self._sched_config.get(
            "job_store_path", "aegis_data/scheduler_jobs.db"
        )

        # Create bus publisher that writes to Redis Streams
        async def bus_publisher(message: Dict[str, Any]) -> None:
            if self._redis_conn is None:
                raise RuntimeError("Redis not connected")
            target = message.get("target_agent", "torchestrator")
            stream_key = f"aegis:stream:{target}"
            await self._redis_conn.xadd(
                stream_key,
                {"data": json.dumps(message, default=str)},
            )

        self._scheduler = AegisScheduler(
            db_path=db_path,
            bus_publisher=bus_publisher,
        )
        await self._scheduler.start()
        logger.info("[Scheduler] Running (store=%s)", db_path)

    async def _start_agent(self, state: AgentState) -> None:
        """
        Start a single agent: import class → instantiate → call startup().
        """
        entry = state.entry
        log = logger.bind(agent_id=entry.agent_id)
        log.info("[%s] Starting...", entry.display_name)

        state.status = "starting"
        cls = entry.import_class()

        if cls is None:
            if entry.required:
                log.error(
                    "[%s] REQUIRED agent failed to import — system degraded",
                    entry.display_name,
                )
                state.status = "failed"
                state.error = "Import failed"
            else:
                log.warning(
                    "[%s] Optional agent not available — skipping",
                    entry.display_name,
                )
                state.status = "stopped"
            return

        try:
            # Instantiate the agent
            # Agents may accept config, redis_conn, etc.
            agent_config = self._config.get(entry.config_key, {}) if entry.config_key else {}
            try:
                instance = cls(
                    config=agent_config,
                    redis_conn=self._redis_conn,
                )
            except TypeError:
                # Fallback if agent doesn't accept these kwargs
                try:
                    instance = cls(config=agent_config)
                except TypeError:
                    instance = cls()

            state.instance = instance

            # Call startup with timeout
            timeout = self._sm_config.get("startup_timeout_seconds", 30)
            await asyncio.wait_for(instance.startup(), timeout=timeout)

            state.status = "running"
            state.last_heartbeat = datetime.now(timezone.utc)
            log.info("[%s] Started successfully", entry.display_name)

        except asyncio.TimeoutError:
            state.status = "failed"
            state.error = "Startup timed out"
            log.error(
                "[%s] Startup timed out after %ds",
                entry.display_name,
                self._sm_config.get("startup_timeout_seconds", 30),
            )
        except Exception as exc:
            state.status = "failed"
            state.error = str(exc)
            log.error("[%s] Startup failed: %s", entry.display_name, exc)

    # -- Shutdown Sequence ---------------------------------------------------

    async def stop(self) -> None:
        """
        Execute graceful shutdown in reverse startup order.

        Implements: Part III §3.3 — Graceful shutdown in reverse order
        """
        logger.info("=" * 60)
        logger.info("  AEGIS SYSTEM MANAGER — SHUTDOWN SEQUENCE")
        logger.info("=" * 60)

        self._running = False

        # Cancel health check
        if self._health_task and not self._health_task.done():
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass

        # Stop agents in reverse order
        timeout = self._sm_config.get("shutdown_timeout_seconds", 15)
        for entry in get_shutdown_order():
            state = self._agents.get(entry.agent_id)
            if state is None or state.instance is None:
                continue
            await self._stop_agent(state, timeout=timeout)

        # Stop Scheduler
        if self._scheduler and self._scheduler.is_running:
            logger.info("[Scheduler] Stopping...")
            await self._scheduler.stop()
            logger.info("[Scheduler] Stopped")

        # Close Redis
        if self._redis_conn:
            logger.info("[Redis] Closing connection...")
            await self._redis_conn.close()
            self._redis_conn = None
            logger.info("[Redis] Connection closed")

        logger.info("=" * 60)
        logger.info("  AEGIS SYSTEM — SHUTDOWN COMPLETE")
        logger.info("=" * 60)

    async def _stop_agent(self, state: AgentState, timeout: int = 15) -> None:
        """Gracefully stop a single agent."""
        entry = state.entry
        log = logger.bind(agent_id=entry.agent_id)
        log.info("[%s] Stopping...", entry.display_name)

        try:
            if state.instance and hasattr(state.instance, "shutdown"):
                await asyncio.wait_for(state.instance.shutdown(), timeout=timeout)
            state.status = "stopped"
            log.info("[%s] Stopped", entry.display_name)
        except asyncio.TimeoutError:
            log.warning(
                "[%s] Shutdown timed out after %ds — forcing",
                entry.display_name,
                timeout,
            )
            state.status = "stopped"
        except Exception as exc:
            log.error("[%s] Error during shutdown: %s", entry.display_name, exc)
            state.status = "stopped"

    # -- Health Check Loop ---------------------------------------------------

    async def _health_check_loop(self) -> None:
        """
        Periodically poll agent health and restart failed agents.

        Implements: Part III §3.3 — Health-check polling, restart logic
        """
        interval = self._sm_config.get("health_check_interval_seconds", 30)
        logger.info("Health check loop started (interval=%ds)", interval)

        try:
            while self._running:
                await asyncio.sleep(interval)
                if not self._running:
                    break
                await self._run_health_checks()
        except asyncio.CancelledError:
            pass
        finally:
            logger.info("Health check loop stopped")

    async def _run_health_checks(self) -> None:
        """Execute one round of health checks across all agents."""
        for agent_id, state in self._agents.items():
            if state.status == "stopped" and not state.entry.required:
                continue  # Optional agents that aren't running

            if state.status == "running" and state.instance is not None:
                # Check if agent has a health_check method
                if hasattr(state.instance, "health_check"):
                    try:
                        healthy = await asyncio.wait_for(
                            state.instance.health_check(), timeout=10
                        )
                        if healthy:
                            state.last_heartbeat = datetime.now(timezone.utc)
                        else:
                            logger.warning(
                                "[HealthCheck] %s reported unhealthy",
                                state.entry.display_name,
                            )
                            state.status = "failed"
                            state.error = "Health check returned False"
                    except asyncio.TimeoutError:
                        logger.warning(
                            "[HealthCheck] %s health check timed out",
                            state.entry.display_name,
                        )
                        state.status = "failed"
                        state.error = "Health check timed out"
                    except Exception as exc:
                        logger.error(
                            "[HealthCheck] %s health check error: %s",
                            state.entry.display_name,
                            exc,
                        )
                        state.status = "failed"
                        state.error = str(exc)
                else:
                    # No health_check method — assume healthy if running
                    state.last_heartbeat = datetime.now(timezone.utc)

            # Attempt restart for failed agents
            if state.status == "failed":
                await self._attempt_restart(state)

    async def _attempt_restart(self, state: AgentState) -> None:
        """
        Attempt to restart a failed agent with exponential backoff.

        Implements: Part III §3.3 — Restart of failed agents
                    Part XIII RT-3, RT-4 — Observer/Warden restart priority
        """
        entry = state.entry
        max_retries = entry.restart_max or self._sm_config.get("restart_max_retries", 3)
        backoff_base = self._sm_config.get("restart_backoff_base_seconds", 2.0)
        backoff_max = self._sm_config.get("restart_backoff_max_seconds", 60.0)

        if state.restart_count >= max_retries:
            if entry.required:
                logger.critical(
                    "[Restart] REQUIRED agent '%s' exceeded %d restart attempts — "
                    "SYSTEM DEGRADED",
                    entry.display_name,
                    max_retries,
                )
            else:
                logger.error(
                    "[Restart] Optional agent '%s' exceeded %d restart attempts — "
                    "giving up",
                    entry.display_name,
                    max_retries,
                )
            return

        # Exponential backoff
        delay = min(backoff_base * (2 ** state.restart_count), backoff_max)
        state.restart_count += 1
        state.status = "restarting"

        logger.warning(
            "[Restart] Restarting '%s' (attempt %d/%d, backoff=%.1fs)",
            entry.display_name,
            state.restart_count,
            max_retries,
            delay,
        )

        await asyncio.sleep(delay)

        # Attempt clean shutdown first
        if state.instance and hasattr(state.instance, "shutdown"):
            try:
                await asyncio.wait_for(state.instance.shutdown(), timeout=5)
            except Exception:
                pass

        state.instance = None

        # Re-start
        await self._start_agent(state)

        if state.status == "running":
            logger.info(
                "[Restart] '%s' recovered after %d attempts",
                entry.display_name,
                state.restart_count,
            )

    # -- First-Run Bootstrap -------------------------------------------------

    async def _check_first_run(self) -> None:
        """
        Detect first-run condition and trigger bootstrap if needed.

        Implements: Part V §5.4 — Bootstrap / First-Run
        """
        identity_state = self._agents.get("identity")
        if identity_state is None or identity_state.instance is None:
            return

        if hasattr(identity_state.instance, "is_first_run"):
            try:
                is_first = await identity_state.instance.is_first_run()
                if is_first:
                    logger.info(
                        "=" * 60 + "\\n"
                        "  FIRST RUN DETECTED — Bootstrap required.\\n"
                        "  Use 'aegis user create --root' to create\\n"
                        "  the initial root user and default tenant.\\n"
                        + "=" * 60
                    )
            except Exception as exc:
                logger.debug("First-run check skipped: %s", exc)

    # -- Status & Introspection ----------------------------------------------

    def get_system_status(self) -> Dict[str, Any]:
        """
        Return a comprehensive status snapshot of the entire system.

        Used by CLI ``aegis status`` and Mission Control /health endpoint.
        """
        agent_statuses = {}
        for agent_id, state in self._agents.items():
            agent_statuses[agent_id] = {
                "display_name": state.entry.display_name,
                "status": state.status,
                "required": state.entry.required,
                "restart_count": state.restart_count,
                "last_heartbeat": (
                    state.last_heartbeat.isoformat() if state.last_heartbeat else None
                ),
                "error": state.error,
                "tags": state.entry.tags,
            }

        return {
            "system": {
                "running": self._running,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            "redis": {
                "connected": self._redis_conn is not None,
                "host": self._redis_config.get("host"),
                "port": self._redis_config.get("port"),
            },
            "scheduler": {
                "enabled": self._sched_config.get("enabled", True),
                "running": self._scheduler.is_running if self._scheduler else False,
            },
            "agents": agent_statuses,
        }

    def get_agent_status(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """Return status for a single agent."""
        state = self._agents.get(agent_id)
        if state is None:
            return None
        return {
            "agent_id": agent_id,
            "display_name": state.entry.display_name,
            "status": state.status,
            "required": state.entry.required,
            "restart_count": state.restart_count,
            "last_heartbeat": (
                state.last_heartbeat.isoformat() if state.last_heartbeat else None
            ),
            "error": state.error,
        }
''',

    # ──────────────────────────────────────────────────────────────────────
    # 6. SCHEDULE_JOB TOOL — Forge Tool for Job Registration
    # Implements: Part VIII §8.1 — schedule_job tool
    # ──────────────────────────────────────────────────────────────────────
    "aegis/forge/tools/schedule_job.py": '''
# aegis/forge/tools/schedule_job.py
# Implements: Part VIII §8.1 — schedule_job tool
# Implements: Part VII §7.1 — Tool Interface
"""
Forge Tool: schedule_job

Registers a new job with the Aegis Scheduler. This tool is the
programmatic entry point for all scheduled task creation, whether
initiated by the user via chat, CLI, or by other skills/agents.

Flow (Part XI §11.3):
    1. User requests a scheduled task.
    2. TOrchestrator decomposes intent into a ScheduledJob.
    3. TOrchestrator dispatches forge.execute_tool → schedule_job.
    4. This tool validates the job definition and registers it
       with the Scheduler service.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel
from aegis.manager.scheduler import get_scheduler
from aegis.schemas.scheduler import ScheduledJob


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool Manifest (Part VII §7.1)
# ---------------------------------------------------------------------------

class ToolManifest(BaseModel):
    """Standard Aegis tool manifest."""
    name: str
    description: str
    version: str
    parameters_schema: dict
    permissions_required: List[str]
    timeout_seconds: int = 30


class ToolResult(BaseModel):
    """Standard Aegis tool result."""
    success: bool
    data: Any = None
    error: Optional[str] = None


manifest = ToolManifest(
    name="schedule_job",
    description=(
        "Register a new scheduled job with the Aegis Scheduler. "
        "Supports cron, interval, and one-time (date) schedules. "
        "When a job fires, it dispatches an AegisMessage to the bus "
        "for normal agent processing."
    ),
    version="1.0.0",
    parameters_schema={
        "type": "object",
        "required": ["name", "tenant_id", "user_id", "schedule_type",
                      "schedule_config", "action"],
        "properties": {
            "name": {
                "type": "string",
                "description": "Human-readable name for the job.",
            },
            "description": {
                "type": "string",
                "description": "Optional description of what this job does.",
                "default": "",
            },
            "tenant_id": {
                "type": "string",
                "description": "Tenant scope for this job.",
            },
            "user_id": {
                "type": "string",
                "description": "User who owns this job.",
            },
            "schedule_type": {
                "type": "string",
                "enum": ["cron", "interval", "date"],
                "description": "Trigger type.",
            },
            "schedule_config": {
                "type": "object",
                "description": (
                    "Trigger config. "
                    "cron: {hour, minute, ...} | "
                    "interval: {seconds, minutes, hours, ...} | "
                    "date: {run_date: ISO8601}"
                ),
            },
            "action": {
                "type": "string",
                "description": (
                    "AegisMessage action to dispatch. "
                    "e.g., 'forge.execute_skill', 'forge.execute_tool'"
                ),
            },
            "action_payload": {
                "type": "object",
                "description": "Payload for the dispatched message.",
                "default": {},
            },
            "enabled": {
                "type": "boolean",
                "description": "Whether to activate immediately.",
                "default": True,
            },
        },
    },
    permissions_required=["scheduler.manage"],
    timeout_seconds=10,
)


# ---------------------------------------------------------------------------
# Tool Execute Function
# ---------------------------------------------------------------------------

async def execute(params: Dict[str, Any]) -> ToolResult:
    """
    Register a new scheduled job.

    This function validates the parameters, constructs a ScheduledJob,
    and registers it with the active AegisScheduler instance.

    Args:
        params: Dict matching the parameters_schema above.

    Returns:
        ToolResult with the created job data on success.
    """
    from aegis.manager.scheduler import get_scheduler
    from aegis.schemas.scheduler import ScheduledJob

    # 1. Get the scheduler instance
    scheduler = get_scheduler()
    if scheduler is None or not scheduler.is_running:
        return ToolResult(
            success=False,
            error=(
                "Scheduler is not running. Ensure the System Manager is "
                "started with the scheduler enabled."
            ),
        )

    # 2. Validate the job definition via Pydantic
    try:
        job = ScheduledJob(**params)
    except Exception as exc:
        return ToolResult(
            success=False,
            error=f"Invalid job definition: {exc}",
        )

    # 3. Register with the scheduler
    try:
        job_dict = await scheduler.add_job(job.model_dump())
        logger.info(
            "schedule_job tool: registered job '%s' (id=%s, type=%s)",
            job.name,
            job_dict.get("job_id"),
            job.schedule_type,
        )
        return ToolResult(
            success=True,
            data={
                "job_id": job_dict["job_id"],
                "name": job_dict["name"],
                "schedule_type": job_dict["schedule_type"],
                "schedule_config": job_dict["schedule_config"],
                "action": job_dict["action"],
                "enabled": job_dict.get("enabled", True),
                "next_run": job_dict.get("next_run"),
                "message": f"Job '{job.name}' scheduled successfully.",
            },
        )
    except Exception as exc:
        logger.error("schedule_job tool: failed to register job: %s", exc)
        return ToolResult(
            success=False,
            error=f"Failed to register scheduled job: {exc}",
        )
''',

    # ──────────────────────────────────────────────────────────────────────
    # 7. MAIN ENTRY POINT — python -m aegis.main
    # Implements: Part III §3.3 — Entry Point
    # ──────────────────────────────────────────────────────────────────────
    "aegis/main.py": '''
# aegis/main.py
# Implements: Part III §3.3 — Entry Point
"""
Aegis System Entry Point.

Launches the System Manager, which bootstraps Redis, the Scheduler,
and all council agents in the correct dependency order.

Usage::

    python -m aegis.main
    # or
    python -m aegis

Configuration is loaded from ``aegis_config.yaml`` in the current
working directory. Override with env vars (see SystemManager docs).
"""

from __future__ import annotations

import asyncio
import logging
import sys

import structlog


def configure_logging(level: str = "INFO") -> None:
    """
    Configure structured logging for the Aegis system.

    Uses structlog for JSON-formatted, contextual logging as specified
    in Part III §3.2 (Observer Service logging requirements).
    """
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(colors=True),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Also configure stdlib logging for third-party libraries
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        level=getattr(logging, level.upper(), logging.INFO),
        stream=sys.stderr,
    )


def main() -> None:
    """
    Main entry point for the Aegis system.

    Configures logging, creates the SystemManager, and runs it
    until a shutdown signal is received.
    """
    configure_logging()
    log = structlog.get_logger("aegis.main")

    log.info("=" * 60)
    log.info("  PROJECT AEGIS — Initializing")
    log.info("=" * 60)

    from aegis.manager.system_manager import SystemManager

    manager = SystemManager()

    try:
        asyncio.run(manager.run())
    except KeyboardInterrupt:
        log.info("Aegis shutdown via KeyboardInterrupt")
    except Exception as exc:
        log.critical("Aegis fatal error: %s", exc, exc_info=True)
        sys.exit(1)

    log.info("Aegis has exited cleanly.")


if __name__ == "__main__":
    main()
''',

    # ──────────────────────────────────────────────────────────────────────
    # 8. __main__.py — python -m aegis support
    # ──────────────────────────────────────────────────────────────────────
    "aegis/__main__.py": '''
# aegis/__main__.py
"""
Allows running the Aegis system with:

    python -m aegis

Delegates to aegis.main.main().
"""

from aegis.main import main

if __name__ == "__main__":
    main()
''',

    # ──────────────────────────────────────────────────────────────────────
    # 9. TESTS — System Manager
    # ──────────────────────────────────────────────────────────────────────
    "tests/test_chunk_011/__init__.py": '''
# tests/test_chunk_011/__init__.py
''',

    "tests/test_chunk_011/test_system_manager.py": '''
# tests/test_chunk_011/test_system_manager.py
# Tests for: Part III §3.3 — System Manager
"""
Unit and integration tests for the Aegis System Manager.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aegis.manager.agent_registry import (
    AGENT_REGISTRY,
    AgentEntry,
    get_shutdown_order,
    get_startup_order,
)
from aegis.manager.system_manager import (
    AgentState,
    SystemManager,
    _deep_merge,
    _load_config,
)


# ---------------------------------------------------------------------------
# Agent Registry Tests
# ---------------------------------------------------------------------------

class TestAgentRegistry:
    """Tests for agent_registry.py."""

    def test_registry_is_not_empty(self):
        """Registry contains all 8 council agents + services."""
        assert len(AGENT_REGISTRY) >= 7

    def test_startup_order_ascending(self):
        """Startup order has ascending priority values."""
        order = get_startup_order()
        priorities = [e.priority for e in order]
        assert priorities == sorted(priorities)

    def test_shutdown_order_descending(self):
        """Shutdown order is reverse of startup order."""
        startup = get_startup_order()
        shutdown = get_shutdown_order()
        assert [e.agent_id for e in shutdown] == [
            e.agent_id for e in reversed(startup)
        ]

    def test_observer_starts_first(self):
        """Observer has the lowest priority (starts first)."""
        order = get_startup_order()
        assert order[0].agent_id == "observer"

    def test_warden_starts_before_others(self):
        """Warden starts before Identity, Lexicon, etc."""
        order = get_startup_order()
        ids = [e.agent_id for e in order]
        assert ids.index("warden") < ids.index("identity")
        assert ids.index("warden") < ids.index("lexicon")

    def test_torchestrator_starts_last(self):
        """TOrchestrator has the highest priority (starts last)."""
        order = get_startup_order()
        assert order[-1].agent_id == "torchestrator"

    def test_warden_is_required(self):
        """Warden is marked as required (RT-4)."""
        from aegis.manager.agent_registry import get_agent_entry
        warden = get_agent_entry("warden")
        assert warden is not None
        assert warden.required is True

    def test_observer_is_optional(self):
        """Observer is optional — system can run with degraded logging (RT-3)."""
        from aegis.manager.agent_registry import get_agent_entry
        observer = get_agent_entry("observer")
        assert observer is not None
        assert observer.required is False

    def test_warden_has_highest_restart_attempts(self):
        """Warden should have elevated restart attempts (RT-4)."""
        from aegis.manager.agent_registry import get_agent_entry
        warden = get_agent_entry("warden")
        assert warden is not None
        assert warden.restart_max >= 5

    def test_agent_entry_import_nonexistent(self):
        """Importing a nonexistent module returns None."""
        entry = AgentEntry(
            agent_id="fake",
            display_name="Fake",
            module_path="aegis.agents.nonexistent",
            class_name="FakeAgent",
            priority=999,
        )
        assert entry.import_class() is None


# ---------------------------------------------------------------------------
# Config Tests
# ---------------------------------------------------------------------------

class TestConfig:
    """Tests for configuration loading."""

    def test_deep_merge_basic(self):
        base = {"a": 1, "b": {"c": 2, "d": 3}}
        override = {"b": {"c": 99}, "e": 5}
        _deep_merge(base, override)
        assert base == {"a": 1, "b": {"c": 99, "d": 3}, "e": 5}

    def test_load_config_defaults(self):
        """Config loads with sane defaults even without a config file."""
        config = _load_config("nonexistent.yaml")
        assert "redis" in config
        assert "system_manager" in config
        assert "scheduler" in config
        assert config["redis"]["port"] == 6379

    @patch.dict("os.environ", {"AEGIS_REDIS_PORT": "7777"})
    def test_env_var_override(self):
        """Environment variables override config file values."""
        config = _load_config("nonexistent.yaml")
        assert config["redis"]["port"] == 7777


# ---------------------------------------------------------------------------
# Agent State Tests
# ---------------------------------------------------------------------------

class TestAgentState:
    """Tests for AgentState lifecycle tracking."""

    def test_initial_state(self):
        entry = AgentEntry(
            agent_id="test",
            display_name="Test",
            module_path="test.module",
            class_name="TestAgent",
            priority=50,
        )
        state = AgentState(entry)
        assert state.status == "stopped"
        assert state.restart_count == 0
        assert state.instance is None

    def test_reset(self):
        entry = AgentEntry(
            agent_id="test",
            display_name="Test",
            module_path="test.module",
            class_name="TestAgent",
            priority=50,
        )
        state = AgentState(entry)
        state.status = "failed"
        state.restart_count = 5
        state.error = "Something broke"
        state.reset()
        assert state.status == "stopped"
        assert state.restart_count == 0
        assert state.error is None


# ---------------------------------------------------------------------------
# System Manager Tests
# ---------------------------------------------------------------------------

class TestSystemManager:
    """Tests for SystemManager core logic."""

    def test_instantiation(self):
        """SystemManager can be created with default config."""
        with patch.dict("os.environ", {}, clear=False):
            manager = SystemManager(config_path="nonexistent.yaml")
            assert manager.is_running is False
            assert manager.scheduler is None

    def test_get_system_status(self):
        """get_system_status returns expected structure."""
        manager = SystemManager(config_path="nonexistent.yaml")
        status = manager.get_system_status()
        assert "system" in status
        assert "redis" in status
        assert "scheduler" in status
        assert "agents" in status
        assert isinstance(status["agents"], dict)

    def test_agents_initialized(self):
        """All registry agents have corresponding AgentState."""
        manager = SystemManager(config_path="nonexistent.yaml")
        for entry in AGENT_REGISTRY:
            assert entry.agent_id in manager._agents

    def test_get_agent_status_known(self):
        """Can retrieve status for a known agent."""
        manager = SystemManager(config_path="nonexistent.yaml")
        status = manager.get_agent_status("warden")
        assert status is not None
        assert status["agent_id"] == "warden"
        assert status["status"] == "stopped"

    def test_get_agent_status_unknown(self):
        """Unknown agent returns None."""
        manager = SystemManager(config_path="nonexistent.yaml")
        assert manager.get_agent_status("nonexistent") is None
''',

    # ──────────────────────────────────────────────────────────────────────
    # 10. TESTS — Scheduler
    # ──────────────────────────────────────────────────────────────────────
    "tests/test_chunk_011/test_scheduler.py": '''
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
''',

    # ──────────────────────────────────────────────────────────────────────
    # 11. TESTS — schedule_job Tool
    # ──────────────────────────────────────────────────────────────────────
    "tests/test_chunk_011/test_schedule_job_tool.py": '''
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
''',

    # ──────────────────────────────────────────────────────────────────────
    # 12. UPDATED REQUIREMENTS — New Dependencies
    # ──────────────────────────────────────────────────────────────────────
    "requirements_chunk_011.txt": '''
# requirements_chunk_011.txt
# Additional dependencies introduced by CHUNK-011
# Merge these into the project's main requirements.txt

# -- Core (already in project) --
# pydantic>=2.0
# redis>=5.0
# structlog>=23.0

# -- New for CHUNK-011 --
aiosqlite>=0.19.0       # Async SQLite for JobStore
apscheduler>=4.0.0a5    # Async-native job scheduler (v4.x)
pyyaml>=6.0             # Config file parsing (aegis_config.yaml)
''',

    # ──────────────────────────────────────────────────────────────────────
    # 13. CONFIG UPDATE — aegis_config.yaml additions
    # ──────────────────────────────────────────────────────────────────────
    "aegis_config_chunk_011.yaml": '''
# aegis_config_chunk_011.yaml
# Merge these sections into your main aegis_config.yaml
# Implements: Part III §3.3, Part XI §11.1

# System Manager configuration
system_manager:
  # Seconds between health check sweeps
  health_check_interval_seconds: 30
  # Max restart attempts before declaring agent failure
  restart_max_retries: 3
  # Exponential backoff base (seconds) for restarts
  restart_backoff_base_seconds: 2.0
  # Maximum backoff cap (seconds)
  restart_backoff_max_seconds: 60.0
  # Timeout for agent startup() calls
  startup_timeout_seconds: 30
  # Timeout for agent shutdown() calls
  shutdown_timeout_seconds: 15

# Scheduler configuration
scheduler:
  # Enable/disable the scheduler service
  enabled: true
  # Path to the SQLite job store database
  job_store_path: "aegis_data/scheduler_jobs.db"
''',
}


def create_package_init_files(path):
    """Create __init__.py files in parent directories if they don't exist."""
    dir_name = os.path.dirname(path)
    if dir_name and (dir_name.startswith("") or dir_name.startswith("tests/")):
        parts = dir_name.split("/")
        for i in range(2, len(parts) + 1):
            pkg_path = "/".join(parts[:i])
            init_file = os.path.join(pkg_path, "__init__.py")
            if not os.path.exists(init_file):
                os.makedirs(pkg_path, exist_ok=True)
                print(f"  [Created] {init_file} (empty package marker)")
                with open(init_file, "w") as f:
                    pass


def main():
    """Main function to write all files."""
    print("=" * 60)
    print("  ASSEMBLING CHUNK-011: System Manager & Scheduler")
    print("=" * 60)
    print()

    files_written = 0
    for path, content in CHUNK_011_FILES.items():
        # Ensure the directory exists
        dir_name = os.path.dirname(path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)

        create_package_init_files(path)

        print(f"  [Writing] {path}")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(textwrap.dedent(content).strip() + "\n")
        files_written += 1

    print()
    print("=" * 60)
    print(f"  ASSEMBLY COMPLETE — {files_written} files written")
    print("=" * 60)
    print()
    print("  New dependencies (merge into requirements.txt):")
    print("    aiosqlite>=0.19.0")
    print("    apscheduler>=4.0.0a5")
    print("    pyyaml>=6.0")
    print()
    print("  Config additions (merge into aegis_config.yaml):")
    print("    See aegis_config_chunk_011.yaml")
    print()
    print("  Run tests:")
    print("    pytest tests/test_chunk_011/ -v")
    print()
    print("  Launch Aegis:")
    print("    python -m aegis.main")
    print()


if __name__ == "__main__":
    main()

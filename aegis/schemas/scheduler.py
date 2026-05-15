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

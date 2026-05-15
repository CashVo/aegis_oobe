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

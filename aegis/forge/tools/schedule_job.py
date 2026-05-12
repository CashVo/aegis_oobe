# aegis/forge/tools/schedule_job.py
# Implements: Part VIII, §8.1 — schedule_job tool
# Implements: Part XI — Scheduler Protocol
"""
Tool: schedule_job
Register a new job with the Scheduler.
"""

from datetime import datetime, timezone
from uuid import uuid4

from aegis.forge.tools.base import ToolManifest, ToolResult


manifest = ToolManifest(
    name="schedule_job",
    description="Register a new job with the Scheduler.",
    version="1.0.0",
    parameters_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Human-readable job name."},
            "description": {"type": "string", "description": "Job description."},
            "schedule_type": {"type": "string", "enum": ["cron", "interval", "date"], "description": "Scheduling type."},
            "schedule_config": {"type": "object", "description": "Schedule configuration (e.g., {hour: 2, minute: 0})."},
            "action": {"type": "string", "description": "AegisMessage action to dispatch (e.g., 'forge.execute_skill')."},
            "action_payload": {"type": "object", "default": {}, "description": "Payload for the action."},
            "enabled": {"type": "boolean", "default": True, "description": "Whether the job is active."},
        },
        "required": ["name", "schedule_type", "schedule_config", "action"],
    },
    permissions_required=["scheduler.manage"],
    timeout_seconds=10,
)


async def execute(params: dict) -> ToolResult:
    """
    Register a scheduled job.

    This tool creates the job definition and persists it. The actual
    scheduling is handled by the System Manager's Scheduler service (CHUNK-011).

    Args:
        params: ScheduledJob-compatible parameters.

    Returns:
        ToolResult with the created job definition.
    """
    name = params.get("name")
    schedule_type = params.get("schedule_type")
    schedule_config = params.get("schedule_config")
    action = params.get("action")

    if not name:
        return ToolResult(success=False, error="Parameter 'name' is required.")
    if not schedule_type:
        return ToolResult(success=False, error="Parameter 'schedule_type' is required.")
    if schedule_type not in ("cron", "interval", "date"):
        return ToolResult(success=False, error=f"Invalid schedule_type: {schedule_type}. Must be 'cron', 'interval', or 'date'.")
    if not schedule_config:
        return ToolResult(success=False, error="Parameter 'schedule_config' is required.")
    if not action:
        return ToolResult(success=False, error="Parameter 'action' is required.")

    # Build the job definition
    job_id = str(uuid4())
    job_definition = {
        "job_id": job_id,
        "name": name,
        "description": params.get("description", ""),
        "schedule_type": schedule_type,
        "schedule_config": schedule_config,
        "action": action,
        "action_payload": params.get("action_payload", {}),
        "enabled": params.get("enabled", True),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_run": None,
        "next_run": None,
    }

    # NOTE: Actual persistence and APScheduler registration is handled by
    # the Scheduler service in CHUNK-011. This tool creates and returns the
    # validated job definition for the Scheduler to consume.

    return ToolResult(
        success=True,
        data={
            "job": job_definition,
            "message": f"Job '{name}' (ID: {job_id}) created. Pending scheduler registration.",
        },
    )

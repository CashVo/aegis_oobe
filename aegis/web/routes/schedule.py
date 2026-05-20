# aegis/web/routes/schedule.py
# Implements: Part X, §10.2 — Scheduler (/schedule)
"""
Scheduler management: view, add, and manage scheduled jobs.
"""

import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, Request, Form
from aegis.web.app import templates
from aegis.schemas.message import AegisMessage, MessageType

logger = logging.getLogger(__name__)
router = APIRouter()


async def _scheduler_bus_call(bus, action: str, payload: dict) -> dict:
    """Send scheduler request via bus."""
    if not bus:
        return {"success": False, "error": "Bus unavailable"}

    correlation_id = str(uuid.uuid4())
    response_channel = f"aegis:stream:web:sched:{correlation_id}"
    consumer_group = f"web-sched-{correlation_id}"
    try:
        await bus.create_consumer_group(response_channel, consumer_group)
    except Exception:
        pass

    msg = AegisMessage(
        correlation_id=correlation_id,
        source_agent="web",
        target_agent="system_manager",
        message_type=MessageType.REQUEST,
        tenant_id=payload.get("tenant_id", "default"),
        user_id="root",
        action=f"scheduler.{action}",
        payload=payload,
        metadata={"response_channel": response_channel},
    )
    await bus.publish("aegis:stream:system_manager", msg)

    deadline = asyncio.get_event_loop().time() + 10
    result = {"success": False, "error": "timeout"}
    while asyncio.get_event_loop().time() < deadline:
        messages = await bus.consume(
            response_channel, consumer_group, "web",
            count=1, block_ms=500,
        )
        if messages:
            for _, data in messages:
                parsed = AegisMessage.model_validate(data)
                result = parsed.payload
            break
    return result


@router.get("/schedule", include_in_schema=False)
async def schedule_page(request: Request, tenant_id: str = "default"):
    """Render the scheduler management page."""
    bus = request.app.state.bus
    result = await _scheduler_bus_call(bus, "list_jobs", {"tenant_id": tenant_id})
    jobs = result.get("data", {}).get("jobs", [])
    return templates.TemplateResponse(request, "schedule.html", {
        "jobs": jobs,
        "message": None,
    })


@router.post("/schedule/add", include_in_schema=False)
async def add_job(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    schedule_type: str = Form(...),
    schedule_config: str = Form("{}"),
    action: str = Form(...),
    action_payload: str = Form("{}"),
    tenant_id: str = Form("default"),
):
    """Handle add-job form submission."""
    bus = request.app.state.bus
    try:
        sched_cfg = json.loads(schedule_config)
        act_payload = json.loads(action_payload)
    except json.JSONDecodeError as e:
        return templates.TemplateResponse(request, "schedule.html", {
            "jobs": [],
            "message": f"Invalid JSON: {e}",
        })

    result = await _scheduler_bus_call(bus, "add_job", {
        "tenant_id": tenant_id,
        "name": name,
        "description": description,
        "schedule_type": schedule_type,
        "schedule_config": sched_cfg,
        "action": action,
        "action_payload": act_payload,
    })
    message = f"Job '{name}' added." if result.get("success") else result.get("error", "Failed")

    list_result = await _scheduler_bus_call(bus, "list_jobs", {"tenant_id": tenant_id})
    jobs = list_result.get("data", {}).get("jobs", [])

    return templates.TemplateResponse(request, "schedule.html", {
        "jobs": jobs,
        "message": message,
    })


@router.post("/schedule/remove/{job_id}", include_in_schema=False)
async def remove_job(request: Request, job_id: str, tenant_id: str = "default"):
    """Handle job removal."""
    bus = request.app.state.bus
    result = await _scheduler_bus_call(bus, "remove_job", {
        "tenant_id": tenant_id,
        "job_id": job_id,
    })
    message = f"Job {job_id} removed." if result.get("success") else result.get("error", "Failed")

    list_result = await _scheduler_bus_call(bus, "list_jobs", {"tenant_id": tenant_id})
    jobs = list_result.get("data", {}).get("jobs", [])

    return templates.TemplateResponse(request, "schedule.html", {
        "jobs": jobs,
        "message": message,
    })

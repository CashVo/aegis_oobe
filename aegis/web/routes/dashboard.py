# aegis/web/routes/dashboard.py
# Implements: Part X, §10.2 — Dashboard (/)
"""
Dashboard route: system health, agent statuses, recent activity.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from aegis.web.app import templates

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/", include_in_schema=False)
async def dashboard(request: Request):
    """Render the main dashboard page."""
    """Render the main monitoring and control center."""
    bus = getattr(request.app.state, "bus", None)
    agents_status = []
    redis_ok = False
    
    # 1. Provide safe offline mock defaults if the test client has no active bus
    if not bus:
        return templates.TemplateResponse(request, "dashboard.html", {
            "redis_connected": False,
            "agents": agents_status,
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })

    # 2. Normal operational runtime workflow (for your live web server)
    try:
        redis_ok = await bus.health_check()
        
        # Attempt to read heartbeat data
        if redis_ok:
            try:
                r = bus._redis
                keys = await r.keys("aegis:heartbeat:*")
                for key in keys:
                    agent_name = key.decode().split(":")[-1] if isinstance(key, bytes) else key.split(":")[-1]
                    val = await r.get(key)
                    ts_str = val.decode() if isinstance(val, bytes) else str(val) if val else None
                    agents_status.append({
                        "agent_id": agent_name,
                        "status": "running" if val else "unknown",
                        "last_heartbeat": ts_str,
                    })
            except Exception as exc:
                logger.debug(f"Heartbeat read failed: {exc}")

    except Exception:
        redis_ok = False

    
    return templates.TemplateResponse(request, "dashboard.html", {
        "redis_connected": redis_ok,
        "agents": agents_status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

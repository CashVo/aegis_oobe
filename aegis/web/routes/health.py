# aegis/web/routes/health.py
# Implements: Part X, §10.2 — Health API (/health)
"""
Machine-readable health endpoint (JSON).
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health")
async def health(request: Request) -> JSONResponse:
    """
    Machine-readable health endpoint.
    Returns JSON with redis status, agent heartbeats, and system info.
    """
    bus = request.app.state.bus
    redis_ok = False
    agents = {}

    if bus:
        try:
            redis_ok = await bus.ping()
        except Exception:
            redis_ok = False

        if redis_ok:
            try:
                r = bus.client
                keys = await r.keys("aegis:heartbeat:*")
                for key in keys:
                    name = key.decode().split(":")[-1] if isinstance(key, bytes) else key.split(":")[-1]
                    val = await r.get(key)
                    agents[name] = {
                        "status": "running" if val else "unknown",
                        "last_heartbeat": val.decode() if isinstance(val, bytes) and val else None,
                    }
            except Exception:
                pass

    status_code = 200 if redis_ok else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "healthy" if redis_ok else "degraded",
            "redis": "connected" if redis_ok else "disconnected",
            "agents": agents,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )

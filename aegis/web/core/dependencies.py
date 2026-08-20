# aegis/web/core/dependencies.py
# FastAPI dependencies for Mission Control modules

from typing import Any, Optional
from fastapi import Depends, Request, HTTPException
from redis.asyncio import Redis

from aegis.bus.redis_bus import RedisBus
from aegis.config import load_config


async def get_config(request: Request) -> Any:
    """Get the Aegis configuration from app state."""
    config = getattr(request.app.state, "aegis_config", None)
    if config is None:
        config = load_config()
        request.app.state.aegis_config = config
    return config


async def get_bus(request: Request) -> RedisBus:
    """Get the RedisBus instance from app state."""
    bus = getattr(request.app.state, "bus", None)
    if bus is None:
        raise HTTPException(
            status_code=503,
            detail="Redis bus not available. Mission Control running in degraded mode.",
        )
    if not bus.is_connected:
        raise HTTPException(
            status_code=503,
            detail="Redis bus not connected.",
        )
    return bus


async def get_redis_client(request: Request) -> Redis:
    """Get the raw Redis client from the bus."""
    bus = await get_bus(request)
    return bus.client


# Optional: Auth dependency placeholder
async def get_current_user(request: Request) -> Optional[dict]:
    """Get current user from session/auth. Override in auth-enabled deployments."""
    return getattr(request.state, "user", None)


def require_auth(user: Optional[dict] = Depends(get_current_user)) -> dict:
    """Require authenticated user."""
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user
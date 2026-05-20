# aegis/web/app.py
# Implements: Part X, §10.2 — Mission Control Web UI
"""
FastAPI application factory for the Aegis Mission Control Web UI.
Default: localhost:8420
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

logger = logging.getLogger(__name__)

_WEB_DIR = Path(__file__).parent
_TEMPLATES_DIR = _WEB_DIR / "templates"
_STATIC_DIR = _WEB_DIR / "static"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Handles initialization and cleanup routines for the FastAPI system application.
    Replaces deprecated on_event handlers.
    """
    # ── Startup Phase ─────────────────────────────────
    logger.info("Mission Control starting up…")
    try:
        from aegis.config import load_config
        from aegis.bus.redis_bus import RedisBus

        cfg = app.state.aegis_config or load_config()
        app.state.aegis_config = cfg

        bus = RedisBus(cfg)
        await bus.connect()
        app.state.bus = bus
        logger.info("Mission Control connected to Redis bus.")
    except Exception as exc:
        logger.warning(f"Mission Control bus connection failed: {exc}. Running in degraded mode.")

    # Yield control back to the application runtime
    yield

    # ── Shutdown Phase ────────────────────────────────
    logger.info("Mission Control shutting down…")
    if getattr(app.state, "bus", None):
        await app.state.bus.disconnect()


def create_app(config: Any = None) -> FastAPI:
    """Create and configure the Mission Control FastAPI application."""
    app = FastAPI(
        title="Aegis Mission Control",
        description="Project Aegis — Local-First Multi-Agent System Dashboard",
        version="0.12.0",
        lifespan=lifespan,  # 👈 Pass lifespan here
    )

    app.state.aegis_config = config
    app.state.bus = None

    _STATIC_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # ── Register route modules ───────────────────────
    from aegis.web.routes.dashboard import router as dashboard_router
    from aegis.web.routes.chat import router as chat_router
    from aegis.web.routes.memory import router as memory_router
    from aegis.web.routes.users import router as users_router
    from aegis.web.routes.schedule import router as schedule_router
    from aegis.web.routes.logs import router as logs_router
    from aegis.web.routes.health import router as health_router

    app.include_router(dashboard_router)
    app.include_router(chat_router)
    app.include_router(memory_router)
    app.include_router(users_router)
    app.include_router(schedule_router)
    app.include_router(logs_router)
    app.include_router(health_router)

    return app

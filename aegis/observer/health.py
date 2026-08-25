# aegis/observer/health.py
# Implements: Part III, §3.2 — Health Endpoint for Mission Control UI
"""
Lightweight HTTP server exposing a /health endpoint.
Returns JSON-formatted SystemHealthReport for consumption by
Mission Control UI and `aegis status` CLI command.

Uses aiohttp for minimal async HTTP serving.
"""

import asyncio
import json
from typing import Any, Callable, Dict, Optional

from aiohttp import web

from aegis.schemas.observer import SystemHealthReport


class HealthServer:
    """
    Async HTTP server that exposes system health information.

    Endpoints:
        GET /health — Full SystemHealthReport as JSON.
        GET /health/ready — Simple readiness probe (200 if healthy, 503 otherwise).
        GET /health/live — Simple liveness probe (always 200 if server is running).

    Configuration:
        host: Bind address (default: 127.0.0.1 for local-first principle).
        port: Bind port (default: 8421, separate from Mission Control's 8420).
    """

    def __init__(
        self,
        health_provider: Callable[[], SystemHealthReport],
        host: str = "127.0.0.1",
        port: int = 8421,
    ):
        """
        Initialize the HealthServer.

        Args:
            health_provider: Callable that returns the current SystemHealthReport.
            host: Bind address.
            port: Bind port.
        """
        self.health_provider = health_provider
        self.host = host
        self.port = port
        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None

    async def start(self) -> None:
        """Start the health HTTP server."""
        self._app = web.Application()
        self._app.router.add_get("/health", self._handle_health)
        self._app.router.add_get("/health/ready", self._handle_ready)
        self._app.router.add_get("/health/live", self._handle_live)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self.host, self.port)
        await self._site.start()

    async def stop(self) -> None:
        """Stop the health HTTP server gracefully."""
        if self._site:
            await self._site.stop()
        if self._runner:
            await self._runner.cleanup()

    async def _handle_health(self, request: web.Request) -> web.Response:
        """
        GET /health — Return full SystemHealthReport.
        """
        report = self.health_provider()
        # Serialize using Pydantic's model_dump with ISO datetime formatting
        data = report.model_dump(mode="json")
        return web.json_response(data)

    async def _handle_ready(self, request: web.Request) -> web.Response:
        """
        GET /health/ready — Readiness probe.
        Returns 200 if system is healthy/degraded, 503 if unresponsive.
        """
        report = self.health_provider()
        from aegis.schemas.observer import AgentHealth

        if report.system_status in (AgentHealth.HEALTHY, AgentHealth.DEGRADED):
            return web.json_response({"ready": True}, status=200)
        else:
            return web.json_response({"ready": False, "status": report.system_status.value}, status=503)

    async def _handle_live(self, request: web.Request) -> web.Response:
        """
        GET /health/live — Liveness probe.
        Always returns 200 if the server is running.
        """
        return web.json_response({"alive": True}, status=200)

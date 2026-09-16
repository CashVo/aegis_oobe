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
import os
import socket
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
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ):
        """
        Initialize the HealthServer.

        Args:
            health_provider: Callable that returns the current SystemHealthReport.
            host: Bind address.
            port: Bind port.
            max_retries: Maximum number of retry attempts if port is in use.
            retry_delay: Delay between retries in seconds.
        """
        self.health_provider = health_provider
        self.host = host
        self.port = port
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None

    async def start(self) -> None:
        """Start the health HTTP server with port conflict resolution."""
        self._app = web.Application()
        self._app.router.add_get("/health", self._handle_health)
        self._app.router.add_get("/health/ready", self._handle_ready)
        self._app.router.add_get("/health/live", self._handle_live)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        
        # Try to bind with SO_REUSEADDR and handle port conflicts
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                self._site = web.TCPSite(self._runner, self.host, self.port)
                await self._site.start()
                return  # Success
            except OSError as e:
                if e.errno == 98:  # Address already in use
                    last_error = e
                    if attempt < self.max_retries:
                        await asyncio.sleep(self.retry_delay)
                        continue
                raise
        
        # If we got here, all retries failed
        raise OSError(f"Failed to bind to {self.host}:{self.port} after {self.max_retries} retries: {last_error}")

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

# tests/test_observer/test_health_server.py
# Unit tests for the HealthServer HTTP endpoint.
"""
Tests cover:
- /health endpoint returns valid JSON report
- /health/ready returns appropriate status codes
- /health/live always returns 200
"""

import pytest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from aegis.schemas.observer import AgentHealth, SystemHealthReport
from aegis.observer.health import HealthServer


def make_healthy_report() -> SystemHealthReport:
    """Return a mock healthy report."""
    return SystemHealthReport(
        system_status=AgentHealth.HEALTHY,
        observer_uptime_seconds=120.0,
        redis_connected=True,
        total_messages_processed=42,
        total_metrics_collected=100,
    )


def make_unhealthy_report() -> SystemHealthReport:
    """Return a mock unhealthy report."""
    return SystemHealthReport(
        system_status=AgentHealth.UNRESPONSIVE,
        observer_uptime_seconds=120.0,
        redis_connected=False,
        total_messages_processed=10,
    )


@pytest.fixture
async def healthy_server(aiohttp_client):
    """Create a test client for a healthy HealthServer."""
    server = HealthServer(
        health_provider=make_healthy_report,
        host="127.0.0.1",
        port=0,
    )
    # Manually create the app for testing
    app = web.Application()
    app.router.add_get("/health", server._handle_health)
    app.router.add_get("/health/ready", server._handle_ready)
    app.router.add_get("/health/live", server._handle_live)
    return await aiohttp_client(app)


@pytest.fixture
async def unhealthy_server(aiohttp_client):
    """Create a test client for an unhealthy HealthServer."""
    server = HealthServer(
        health_provider=make_unhealthy_report,
        host="127.0.0.1",
        port=0,
    )
    app = web.Application()
    app.router.add_get("/health", server._handle_health)
    app.router.add_get("/health/ready", server._handle_ready)
    app.router.add_get("/health/live", server._handle_live)
    return await aiohttp_client(app)


@pytest.mark.asyncio
async def test_health_endpoint(healthy_server):
    """Test /health returns full report as JSON."""
    resp = await healthy_server.get("/health")
    assert resp.status == 200
    data = await resp.json()
    assert data["system_status"] == "healthy"
    assert data["observer_uptime_seconds"] == 120.0
    assert data["redis_connected"] is True
    assert data["total_messages_processed"] == 42


@pytest.mark.asyncio
async def test_ready_endpoint_healthy(healthy_server):
    """Test /health/ready returns 200 when healthy."""
    resp = await healthy_server.get("/health/ready")
    assert resp.status == 200
    data = await resp.json()
    assert data["ready"] is True


@pytest.mark.asyncio
async def test_ready_endpoint_unhealthy(unhealthy_server):
    """Test /health/ready returns 503 when unresponsive."""
    resp = await unhealthy_server.get("/health/ready")
    assert resp.status == 503
    data = await resp.json()
    assert data["ready"] is False


@pytest.mark.asyncio
async def test_live_endpoint(healthy_server):
    """Test /health/live always returns 200."""
    resp = await healthy_server.get("/health/live")
    assert resp.status == 200
    data = await resp.json()
    assert data["alive"] is True

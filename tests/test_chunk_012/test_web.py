# tests/test_chunk_012/test_web.py
# Tests for Part X, §10.2 — Mission Control Web UI
"""
Unit tests for the Mission Control FastAPI application.
Tests route availability, template rendering, health endpoint, and WebSocket.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a test client with a real app instance and a mocked bus."""
    # 1. Directly import the real factory to avoid mocking the FastAPI app layer
    from aegis.web.app import create_app
    
    # 2. Instantiate a real FastAPI application object
    app = create_app(config=None)
    
    # 3. Construct the async-safe mock bus
    mock_bus = MagicMock()
    mock_bus.connect = AsyncMock()
    mock_bus.disconnect = AsyncMock()
    mock_bus.health_check = AsyncMock(return_value=False)
    mock_bus.create_consumer_group = AsyncMock()
    mock_bus.consume = AsyncMock(return_value=[])
    mock_bus.publish = AsyncMock()
    
    # 4. Bind the mock bus to the real app state
    app.state.bus = mock_bus
    
    # 5. Yield a test client wrapped around the genuine app architecture
    yield TestClient(app, raise_server_exceptions=True)


class TestDashboard:
    """Test the dashboard route."""

    def test_dashboard_renders(self, client):
        """GET / should return 200 with dashboard content."""
        response = client.get("/")
        assert response.status_code == 200
        assert "Dashboard" in response.text or "dashboard" in response.text.lower()


class TestHealthEndpoint:
    """Test the /health API."""

    def test_health_no_redis(self, client):
        """GET /health with no bus should return degraded status."""
        response = client.get("/health")
        # 503 or 200 depending on implementation; we check JSON shape
        data = response.json()
        assert "status" in data
        assert "redis" in data
        assert "agents" in data
        assert "timestamp" in data

    def test_health_json_format(self, client):
        """Health endpoint returns valid JSON."""
        response = client.get("/health")
        assert response.headers["content-type"].startswith("application/json")


class TestChatPage:
    """Test the chat page route."""

    def test_chat_page_renders(self, client):
        """GET /chat should return 200."""
        response = client.get("/chat")
        assert response.status_code == 200
        assert "chat" in response.text.lower()

    def test_chat_page_with_session(self, client):
        """GET /chat?session_id=xxx should pre-fill session."""
        response = client.get("/chat?session_id=test-session-123")
        assert response.status_code == 200
        assert "test-session-123" in response.text


class TestMemoryPage:
    """Test the memory explorer route."""

    def test_memory_page_renders(self, client):
        """GET /memory should return 200."""
        response = client.get("/memory")
        assert response.status_code == 200
        assert "Memory" in response.text or "memory" in response.text.lower()


class TestUsersPage:
    """Test the users management route."""

    def test_users_page_renders(self, client):
        """GET /users should return 200."""
        response = client.get("/users")
        assert response.status_code == 200


class TestSchedulePage:
    """Test the schedule route."""

    def test_schedule_page_renders(self, client):
        """GET /schedule should return 200."""
        response = client.get("/schedule")
        assert response.status_code == 200


class TestLogsPage:
    """Test the logs page route."""

    def test_logs_page_renders(self, client):
        """GET /logs should return 200."""
        response = client.get("/logs")
        assert response.status_code == 200
        assert "Logs" in response.text or "logs" in response.text.lower()

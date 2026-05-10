# tests/test_observer/test_agent.py
# Unit tests for the ObserverAgent.
"""
Tests cover:
- Agent initialization and configuration
- Message handling dispatch (heartbeat, log, metric, health queries)
- Health report generation
- Error handling for unknown actions
"""

import asyncio
import pytest
from datetime import datetime, timezone
from uuid import uuid4

from aegis.schemas.message import AegisMessage, MessageType, Priority
from aegis.schemas.observer import (
    AgentHealth,
    HeartbeatEvent,
    LogEvent,
    MetricEvent,
    ObserverAction,
    LogLevel,
    MetricType,
)
from aegis.observer.agent import ObserverAgent


@pytest.fixture
def observer():
    """Create an ObserverAgent with test configuration."""
    config = {
        "heartbeat_interval": 1.0,
        "missed_threshold": 2,
        "degraded_threshold": 1,
        "health_host": "127.0.0.1",
        "health_port": 0,  # Port 0 = OS assigns (avoids conflicts in tests)
        "metrics_retention_seconds": 60.0,
    }
    return ObserverAgent(config=config)


def make_message(action: str, payload: dict, source: str = "test_agent") -> AegisMessage:
    """Helper to create test AegisMessages."""
    return AegisMessage(
        message_id=str(uuid4()),
        source_agent=source,
        target_agent="observer",
        message_type=MessageType.EVENT,
        tenant_id="test-tenant",
        user_id="test-user",
        action=action,
        payload=payload,
    )


class TestObserverAgent:
    """Tests for ObserverAgent message handling."""

    def test_initialization(self, observer):
        """Test agent initializes with correct defaults."""
        assert observer.agent_id == "observer"
        assert "aegis:stream:observer" in observer.subscriptions
        assert "aegis:stream:broadcast" in observer.subscriptions

    @pytest.mark.asyncio
    async def test_handle_heartbeat(self, observer):
        """Test heartbeat message is processed correctly."""
        heartbeat = HeartbeatEvent(
            agent_id="forge",
            status=AgentHealth.HEALTHY,
            uptime_seconds=100.0,
        )
        msg = make_message(ObserverAction.HEARTBEAT, heartbeat.model_dump(mode="json"))

        result = await observer.handle_message(msg)
        assert result is None  # Heartbeats don't return responses

        # Verify the heartbeat was recorded
        status = observer._heartbeat_monitor.get_agent_status("forge")
        assert status is not None
        assert status.health == AgentHealth.HEALTHY

    @pytest.mark.asyncio
    async def test_handle_log(self, observer):
        """Test log message is buffered."""
        log_event = LogEvent(
            agent_id="oracle",
            level=LogLevel.INFO,
            message="Processing query",
            tenant_id="t1",
            user_id="u1",
        )
        msg = make_message(ObserverAction.LOG, log_event.model_dump(mode="json"))

        await observer.handle_message(msg)

        assert len(observer._log_buffer) == 1
        assert observer._log_buffer[0].message == "Processing query"

    @pytest.mark.asyncio
    async def test_handle_metric(self, observer):
        """Test metric event is recorded."""
        metric = MetricEvent(
            agent_id="forge",
            metric_name="forge.tool.exec_ms",
            metric_type=MetricType.TIMING,
            value=250.0,
            unit="ms",
        )
        msg = make_message(ObserverAction.METRIC, metric.model_dump(mode="json"))

        await observer.handle_message(msg)

        assert observer._metrics_collector.total_collected == 1
        series = observer._metrics_collector.get_metric("forge.tool.exec_ms")
        assert series is not None
        assert series.latest.value == 250.0

    @pytest.mark.asyncio
    async def test_handle_get_health(self, observer):
        """Test health query returns a valid response."""
        msg = make_message(ObserverAction.GET_HEALTH, {})

        response = await observer.handle_message(msg)

        assert response is not None
        assert response.message_type == MessageType.RESPONSE
        assert response.target_agent == "test_agent"
        assert "system_status" in response.payload
        assert "observer_uptime_seconds" in response.payload

    @pytest.mark.asyncio
    async def test_handle_get_agent_status_specific(self, observer):
        """Test querying status of a specific agent."""
        # First register a heartbeat
        hb = HeartbeatEvent(agent_id="warden", status=AgentHealth.HEALTHY, uptime_seconds=50.0)
        hb_msg = make_message(ObserverAction.HEARTBEAT, hb.model_dump(mode="json"))
        await observer.handle_message(hb_msg)

        # Now query
        query_msg = make_message(ObserverAction.GET_AGENT_STATUS, {"agent_id": "warden"})
        response = await observer.handle_message(query_msg)

        assert response is not None
        assert response.payload.get("agent_id") == "warden"
        assert response.payload.get("health") == AgentHealth.HEALTHY.value

    @pytest.mark.asyncio
    async def test_handle_get_agent_status_all(self, observer):
        """Test querying status of all agents."""
        for agent in ["a", "b", "c"]:
            hb = HeartbeatEvent(agent_id=agent, status=AgentHealth.HEALTHY)
            msg = make_message(ObserverAction.HEARTBEAT, hb.model_dump(mode="json"))
            await observer.handle_message(msg)

        query_msg = make_message(ObserverAction.GET_AGENT_STATUS, {})
        response = await observer.handle_message(query_msg)

        assert response is not None
        assert "agents" in response.payload
        assert len(response.payload["agents"]) == 3

    @pytest.mark.asyncio
    async def test_handle_unknown_action(self, observer):
        """Test unknown action is handled gracefully (no crash)."""
        msg = make_message("observer.nonexistent_action", {})
        result = await observer.handle_message(msg)
        assert result is None

    @pytest.mark.asyncio
    async def test_messages_processed_counter(self, observer):
        """Test that message counter increments."""
        msg = make_message(ObserverAction.HEARTBEAT, HeartbeatEvent(agent_id="x").model_dump(mode="json"))

        await observer.handle_message(msg)
        await observer.handle_message(msg)
        await observer.handle_message(msg)

        assert observer._messages_processed == 3

    @pytest.mark.asyncio
    async def test_health_report_structure(self, observer):
        """Test the built health report has all expected fields."""
        report = observer._build_health_report()

        assert report.timestamp is not None
        assert report.system_status in AgentHealth
        assert isinstance(report.agents, list)
        assert isinstance(report.total_messages_processed, int)
        assert isinstance(report.total_metrics_collected, int)
        assert isinstance(report.active_alerts, list)

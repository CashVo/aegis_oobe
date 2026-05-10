# tests/test_observer/test_heartbeat.py
# Unit tests for the HeartbeatMonitor component.
"""
Tests cover:
- Agent registration and unregistration
- Heartbeat recording and health evaluation
- Missed heartbeat detection (degraded + unresponsive)
- System-level health aggregation
- Alert callback firing on state transitions
"""

import asyncio
import pytest
from datetime import datetime, timezone, timedelta

from aegis.schemas.observer import AgentHealth, HeartbeatEvent
from aegis.observer.heartbeat import HeartbeatMonitor


@pytest.fixture
def monitor():
    """Create a HeartbeatMonitor with short intervals for testing."""
    return HeartbeatMonitor(
        heartbeat_interval=1.0,
        missed_threshold=2,
        degraded_threshold=1,
    )


class TestHeartbeatMonitor:
    """Tests for HeartbeatMonitor."""

    def test_register_agent(self, monitor):
        """Test agent registration creates an entry with UNKNOWN health."""
        monitor.register_agent("test_agent")
        assert "test_agent" in monitor.registered_agents
        status = monitor.get_agent_status("test_agent")
        assert status is not None
        assert status.health == AgentHealth.UNKNOWN

    def test_unregister_agent(self, monitor):
        """Test agent unregistration removes the entry."""
        monitor.register_agent("test_agent")
        monitor.unregister_agent("test_agent")
        assert "test_agent" not in monitor.registered_agents

    def test_record_heartbeat(self, monitor):
        """Test recording a heartbeat updates agent status."""
        event = HeartbeatEvent(
            agent_id="forge",
            status=AgentHealth.HEALTHY,
            uptime_seconds=42.0,
        )
        monitor.record_heartbeat(event)

        status = monitor.get_agent_status("forge")
        assert status is not None
        assert status.health == AgentHealth.HEALTHY
        assert status.uptime_seconds == 42.0
        assert status.missed_heartbeats == 0

    def test_auto_register_on_heartbeat(self, monitor):
        """Test that recording a heartbeat auto-registers unknown agents."""
        event = HeartbeatEvent(agent_id="new_agent", status=AgentHealth.HEALTHY)
        monitor.record_heartbeat(event)
        assert "new_agent" in monitor.registered_agents

    def test_system_health_all_healthy(self, monitor):
        """Test system health is HEALTHY when all agents are healthy."""
        for agent_id in ["a", "b", "c"]:
            monitor.record_heartbeat(HeartbeatEvent(agent_id=agent_id, status=AgentHealth.HEALTHY))
        assert monitor.get_system_health() == AgentHealth.HEALTHY

    def test_system_health_degraded(self, monitor):
        """Test system health is DEGRADED when any agent is degraded."""
        monitor.record_heartbeat(HeartbeatEvent(agent_id="a", status=AgentHealth.HEALTHY))
        monitor.record_heartbeat(HeartbeatEvent(agent_id="b", status=AgentHealth.DEGRADED))
        assert monitor.get_system_health() == AgentHealth.DEGRADED

    def test_system_health_unresponsive(self, monitor):
        """Test system health is UNRESPONSIVE when any agent is unresponsive."""
        monitor.record_heartbeat(HeartbeatEvent(agent_id="a", status=AgentHealth.HEALTHY))
        # Manually set one to unresponsive
        status = monitor.get_agent_status("a")
        status.health = AgentHealth.UNRESPONSIVE
        assert monitor.get_system_health() == AgentHealth.UNRESPONSIVE

    def test_system_health_no_agents(self, monitor):
        """Test system health is UNKNOWN when no agents registered."""
        assert monitor.get_system_health() == AgentHealth.UNKNOWN

    @pytest.mark.asyncio
    async def test_missed_heartbeat_detection(self, monitor):
        """Test that stale heartbeats trigger health degradation."""
        # Record a heartbeat with a timestamp in the past
        old_time = datetime.now(timezone.utc) - timedelta(seconds=5)
        event = HeartbeatEvent(agent_id="stale_agent", timestamp=old_time, status=AgentHealth.HEALTHY)
        monitor.record_heartbeat(event)

        # Manually trigger evaluation
        await monitor._evaluate_health()

        status = monitor.get_agent_status("stale_agent")
        # With interval=1.0 and 5 seconds elapsed, that's 5 missed beats
        # which exceeds missed_threshold=2, so should be UNRESPONSIVE
        assert status.health == AgentHealth.UNRESPONSIVE

    @pytest.mark.asyncio
    async def test_alert_callback_fires(self):
        """Test that the alert callback fires on health state change."""
        alerts_received = []

        async def alert_handler(agent_id: str, health: AgentHealth):
            alerts_received.append((agent_id, health))

        monitor = HeartbeatMonitor(
            heartbeat_interval=1.0,
            missed_threshold=2,
            degraded_threshold=1,
            on_agent_alert=alert_handler,
        )

        # Give it a stale heartbeat
        old_time = datetime.now(timezone.utc) - timedelta(seconds=10)
        monitor.record_heartbeat(HeartbeatEvent(agent_id="dying_agent", timestamp=old_time, status=AgentHealth.HEALTHY))

        # Evaluate
        await monitor._evaluate_health()

        assert len(alerts_received) > 0
        assert alerts_received[0][0] == "dying_agent"
        assert alerts_received[0][1] == AgentHealth.UNRESPONSIVE

    def test_get_all_statuses(self, monitor):
        """Test retrieval of all agent statuses."""
        monitor.record_heartbeat(HeartbeatEvent(agent_id="a", status=AgentHealth.HEALTHY))
        monitor.record_heartbeat(HeartbeatEvent(agent_id="b", status=AgentHealth.HEALTHY))
        statuses = monitor.get_all_statuses()
        assert len(statuses) == 2
        agent_ids = [s.agent_id for s in statuses]
        assert "a" in agent_ids
        assert "b" in agent_ids

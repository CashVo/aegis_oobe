# aegis/observer/heartbeat.py
# Implements: Part III, §3.2 — Heartbeat Monitor & Agent Failure Detection
"""
Monitors agent heartbeats, detects missed heartbeats, raises alerts
on agent failure, and reports agent health status.

Self-monitoring via internal heartbeat loop addresses RT-3 (Observer Blind Spot).
"""

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Dict, List, Optional

from aegis.schemas.observer import AgentHealth, AgentStatus, HeartbeatEvent


class HeartbeatMonitor:
    """
    Tracks heartbeats from all registered agents and detects failures.

    Configuration:
        heartbeat_interval: Expected seconds between heartbeats from agents.
        missed_threshold: Number of missed heartbeats before marking UNRESPONSIVE.
        degraded_threshold: Number of missed heartbeats before marking DEGRADED.
    """

    def __init__(
        self,
        heartbeat_interval: float = 10.0,
        missed_threshold: int = 3,
        degraded_threshold: int = 1,
        on_agent_alert: Optional[Callable[[str, AgentHealth], Coroutine[Any, Any, None]]] = None,
    ):
        """
        Initialize the HeartbeatMonitor.

        Args:
            heartbeat_interval: Expected interval between heartbeats (seconds).
            missed_threshold: Missed beats before UNRESPONSIVE status.
            degraded_threshold: Missed beats before DEGRADED status.
            on_agent_alert: Async callback invoked when an agent's health changes.
        """
        self.heartbeat_interval = heartbeat_interval
        self.missed_threshold = missed_threshold
        self.degraded_threshold = degraded_threshold
        self.on_agent_alert = on_agent_alert

        # Internal state
        self._agents: Dict[str, AgentStatus] = {}
        self._running: bool = False
        self._check_task: Optional[asyncio.Task] = None
        self._start_time: float = time.time()

    @property
    def registered_agents(self) -> List[str]:
        """List of agent_ids currently being monitored."""
        return list(self._agents.keys())

    def register_agent(self, agent_id: str) -> None:
        """
        Register an agent for heartbeat monitoring.

        Args:
            agent_id: Unique identifier of the agent to monitor.
        """
        if agent_id not in self._agents:
            self._agents[agent_id] = AgentStatus(
                agent_id=agent_id,
                health=AgentHealth.UNKNOWN,
                last_heartbeat=None,
                uptime_seconds=0.0,
                missed_heartbeats=0,
            )

    def unregister_agent(self, agent_id: str) -> None:
        """Remove an agent from monitoring."""
        self._agents.pop(agent_id, None)

    def record_heartbeat(self, event: HeartbeatEvent) -> None:
        """
        Record a received heartbeat from an agent.

        Args:
            event: The HeartbeatEvent received from the agent.
        """
        agent_id = event.agent_id

        # Auto-register if not already known
        if agent_id not in self._agents:
            self.register_agent(agent_id)

        status = self._agents[agent_id]
        status.last_heartbeat = event.timestamp
        status.health = event.status if event.status == AgentHealth.HEALTHY else event.status
        status.uptime_seconds = event.uptime_seconds
        status.missed_heartbeats = 0
        status.metadata = event.metadata

    def get_agent_status(self, agent_id: str) -> Optional[AgentStatus]:
        """Get the current health status of a specific agent."""
        return self._agents.get(agent_id)

    def get_all_statuses(self) -> List[AgentStatus]:
        """Get health statuses for all monitored agents."""
        return list(self._agents.values())

    def get_system_health(self) -> AgentHealth:
        """
        Determine overall system health based on individual agent states.

        Returns:
            HEALTHY if all agents healthy.
            DEGRADED if any agent is degraded.
            UNRESPONSIVE if any agent is unresponsive.
            UNKNOWN if no agents registered.
        """
        if not self._agents:
            return AgentHealth.UNKNOWN

        healths = [a.health for a in self._agents.values()]

        if AgentHealth.UNRESPONSIVE in healths:
            return AgentHealth.UNRESPONSIVE
        elif AgentHealth.DEGRADED in healths:
            return AgentHealth.DEGRADED
        elif all(h == AgentHealth.HEALTHY for h in healths):
            return AgentHealth.HEALTHY
        else:
            return AgentHealth.UNKNOWN

    async def start(self) -> None:
        """Start the periodic heartbeat check loop."""
        self._running = True
        self._start_time = time.time()
        self._check_task = asyncio.create_task(self._check_loop())

    async def stop(self) -> None:
        """Stop the heartbeat check loop gracefully."""
        self._running = False
        if self._check_task and not self._check_task.done():
            self._check_task.cancel()
            try:
                await self._check_task
            except asyncio.CancelledError:
                pass

    async def _check_loop(self) -> None:
        """
        Periodic loop that evaluates agent health based on heartbeat recency.
        Runs every heartbeat_interval seconds.
        """
        while self._running:
            await asyncio.sleep(self.heartbeat_interval)
            await self._evaluate_health()

    async def _evaluate_health(self) -> None:
        """
        Check all agents for missed heartbeats and update their health status.
        Fires alert callback when health state transitions occur.
        """
        now = datetime.now(timezone.utc)

        for agent_id, status in self._agents.items():
            previous_health = status.health

            if status.last_heartbeat is None:
                # Never received a heartbeat — still unknown
                status.health = AgentHealth.UNKNOWN
                continue

            # Calculate seconds since last heartbeat
            elapsed = (now - status.last_heartbeat).total_seconds()
            expected_beats = int(elapsed / self.heartbeat_interval)

            if expected_beats > self.missed_threshold:
                status.health = AgentHealth.UNRESPONSIVE
                status.missed_heartbeats = expected_beats
            elif expected_beats > self.degraded_threshold:
                status.health = AgentHealth.DEGRADED
                status.missed_heartbeats = expected_beats
            else:
                status.health = AgentHealth.HEALTHY
                status.missed_heartbeats = 0

            # Fire alert on state transition
            if status.health != previous_health and self.on_agent_alert:
                try:
                    await self.on_agent_alert(agent_id, status.health)
                except Exception:
                    pass  # Don't let callback failures break the monitor

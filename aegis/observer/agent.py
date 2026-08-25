# aegis/observer/agent.py
# Implements: Part III, §3.2 — Observer Service (Full Agent Implementation)
"""
The Observer Agent — a dedicated, lightweight non-council agent that provides
system-wide monitoring, structured logging, metrics collection, and health checks.

Subscribes to:
    - aegis:stream:broadcast (system-wide events)
    - aegis:stream:observer (dedicated observer channel)

Capabilities:
    1. Aggregates structured logs from all agents.
    2. Monitors agent heartbeats; raises alerts on agent failure.
    3. Collects performance metrics (message latency, tool execution times).
    4. Exposes a /health endpoint for the Mission Control UI.

Self-Monitoring:
    The Observer monitors its own health via a heartbeat loop.
    If it fails, agents fall back to local stderr logging (RT-3 mitigation).
"""

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from aegis.agents.base import BaseAgent
from aegis.schemas.message import AegisMessage, MessageType, Priority
from aegis.schemas.observer import (
    AgentHealth,
    AgentStatus,
    HeartbeatEvent,
    LogEvent,
    MetricEvent,
    ObserverAction,
    SystemHealthReport,
)
from aegis.observer.heartbeat import HeartbeatMonitor
from aegis.observer.metrics import MetricsCollector
from aegis.observer.health import HealthServer
from aegis.observer.logging import get_logger, FallbackLogger


class ObserverAgent(BaseAgent):
    """
    System-wide observability agent.

    Non-council agent responsible for monitoring all other agents,
    aggregating logs and metrics, and exposing health information.
    """

    agent_id: str = "observer"
    subscriptions: list = ["aegis:stream:observer", "aegis:stream:broadcast"]

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize the Observer Agent.

        Args:
            config: Optional configuration dictionary. Expected keys:
                - heartbeat_interval (float): Seconds between expected heartbeats. Default: 10.0
                - missed_threshold (int): Missed beats before UNRESPONSIVE. Default: 3
                - degraded_threshold (int): Missed beats before DEGRADED. Default: 1
                - health_host (str): Health server bind address. Default: "0.0.0.0"
                - health_port (int): Health server bind port. Default: 8421
                - metrics_retention_seconds (float): Metric retention. Default: 3600.0
                - max_samples_per_metric (int): Max samples per series. Default: 10000
        """
        self._config = config or {}
        self._start_time: float = 0.0
        self._messages_processed: int = 0
        self._alerts: List[str] = []
        self._log_buffer: List[LogEvent] = []
        self._max_log_buffer: int = self._config.get("max_log_buffer", 10000)

        # Initialize subsystems
        self._heartbeat_monitor = HeartbeatMonitor(
            heartbeat_interval=self._config.get("heartbeat_interval", 10.0),
            missed_threshold=self._config.get("missed_threshold", 3),
            degraded_threshold=self._config.get("degraded_threshold", 1),
            on_agent_alert=self._on_agent_alert,
        )

        self._metrics_collector = MetricsCollector(
            max_samples_per_metric=self._config.get("max_samples_per_metric", 10000),
            retention_seconds=self._config.get("metrics_retention_seconds", 3600.0),
        )

        self._health_server = HealthServer(
            health_provider=self._build_health_report,
            host=self._config.get("health_host", "0.0.0.0"),
            port=self._config.get("health_port", 8421),
        )

        # Logger (uses structlog when available, fallback to stderr)
        self._logger = None
        self._fallback_logger = FallbackLogger(agent_id=self.agent_id)

        # Bus references (set by SystemManager)
        self._bus_publisher = None
        self._bus_subscriber = None

        # Self-heartbeat task
        self._self_heartbeat_task: Optional[asyncio.Task] = None
        self._metrics_eviction_task: Optional[asyncio.Task] = None

    async def startup(self) -> None:
        """
        Agent initialization: start subsystems, subscribe to channels.
        Called by System Manager during ordered startup.
        """
        self._start_time = time.time()

        # Initialize structured logger
        try:
            self._logger = get_logger(agent_id=self.agent_id)
            self._logger.info("observer_startup", message="Observer Agent starting up.")
        except Exception:
            self._fallback_logger.info("Observer starting up (fallback logger).")

        # Start heartbeat monitor
        await self._heartbeat_monitor.start()

        # Start health HTTP server
        try:
            await self._health_server.start()
            self._log("info", f"Health endpoint available at http://{self._config.get('health_host', '0.0.0.0')}:{self._config.get('health_port', 8421)}/health")
        except Exception as e:
            self._log("error", f"Failed to start health server: {e}")

        # Start self-monitoring heartbeat loop (RT-3)
        self._self_heartbeat_task = asyncio.create_task(self._self_heartbeat_loop())

        # Start periodic metrics eviction
        self._metrics_eviction_task = asyncio.create_task(self._metrics_eviction_loop())

        self._log("info", "Observer Agent startup complete.")

    async def shutdown(self) -> None:
        """
        Graceful teardown: stop all subsystems.
        Called by System Manager during ordered shutdown.
        """
        self._log("info", "Observer Agent shutting down.")

        # Cancel background tasks
        for task in [self._self_heartbeat_task, self._metrics_eviction_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Stop subsystems
        await self._heartbeat_monitor.stop()
        await self._health_server.stop()

        self._log("info", "Observer Agent shutdown complete.")

    async def handle_message(self, message: AegisMessage) -> Optional[AegisMessage]:
        """
        Process an incoming message on the Observer's channels.

        Routes messages to appropriate handlers based on action field.

        Args:
            message: The incoming AegisMessage.

        Returns:
            Optional response message (for query-type actions).
        """
        self._messages_processed += 1
        action = message.action

        try:
            if action == ObserverAction.HEARTBEAT:
                return await self._handle_heartbeat(message)
            elif action == ObserverAction.LOG:
                return await self._handle_log(message)
            elif action == ObserverAction.METRIC:
                return await self._handle_metric(message)
            elif action == ObserverAction.GET_HEALTH:
                return await self._handle_get_health(message)
            elif action == ObserverAction.GET_AGENT_STATUS:
                return await self._handle_get_agent_status(message)
            elif action == ObserverAction.GET_METRICS:
                return await self._handle_get_metrics(message)
            else:
                # Unknown action — log but don't fail
                self._log("warning", f"Unknown action received: {action}", correlation_id=message.correlation_id)
                return None
        except Exception as e:
            self._log("error", f"Error handling message: {e}", action=action, correlation_id=message.correlation_id)
            return self._error_response(message, str(e))

    # ─── Message Handlers ────────────────────────────────────────────

    async def _handle_heartbeat(self, message: AegisMessage) -> None:
        """Process a heartbeat event from an agent."""
        event = HeartbeatEvent(**message.payload)
        self._heartbeat_monitor.record_heartbeat(event)

    async def _handle_log(self, message: AegisMessage) -> None:
        """Process and store a structured log event."""
        event = LogEvent(**message.payload)

        # Store in buffer (ring buffer behavior)
        if len(self._log_buffer) >= self._max_log_buffer:
            self._log_buffer.pop(0)
        self._log_buffer.append(event)

        # Also emit to structlog for unified output
        self._log(
            event.level.value,
            event.message,
            source_agent=event.agent_id,
            tenant_id=event.tenant_id,
            user_id=event.user_id,
            correlation_id=event.correlation_id,
            **event.context,
        )

    async def _handle_metric(self, message: AegisMessage) -> None:
        """Record a metric event."""
        event = MetricEvent(**message.payload)
        self._metrics_collector.record(event)

    async def _handle_get_health(self, message: AegisMessage) -> AegisMessage:
        """Return the full system health report."""
        report = self._build_health_report()
        return AegisMessage(
            source_agent=self.agent_id,
            target_agent=message.source_agent,
            message_type=MessageType.RESPONSE,
            correlation_id=message.correlation_id or message.message_id,
            tenant_id=message.tenant_id,
            user_id=message.user_id,
            action=ObserverAction.GET_HEALTH,
            payload=report.model_dump(mode="json"),
        )

    async def _handle_get_agent_status(self, message: AegisMessage) -> AegisMessage:
        """Return status for a specific agent or all agents."""
        target_agent_id = message.payload.get("agent_id")

        if target_agent_id:
            status = self._heartbeat_monitor.get_agent_status(target_agent_id)
            data = status.model_dump(mode="json") if status else {"error": f"Agent '{target_agent_id}' not found."}
        else:
            statuses = self._heartbeat_monitor.get_all_statuses()
            data = {"agents": [s.model_dump(mode="json") for s in statuses]}

        return AegisMessage(
            source_agent=self.agent_id,
            target_agent=message.source_agent,
            message_type=MessageType.RESPONSE,
            correlation_id=message.correlation_id or message.message_id,
            tenant_id=message.tenant_id,
            user_id=message.user_id,
            action=ObserverAction.GET_AGENT_STATUS,
            payload=data,
        )

    async def _handle_get_metrics(self, message: AegisMessage) -> AegisMessage:
        """Return metrics data."""
        window = message.payload.get("window_seconds", 300.0)
        metric_name = message.payload.get("metric_name")

        if metric_name:
            data = {"metric": metric_name, "stats": self._metrics_collector.get_stats(metric_name, window)}
        else:
            data = {"all_stats": self._metrics_collector.get_all_stats(window)}

        return AegisMessage(
            source_agent=self.agent_id,
            target_agent=message.source_agent,
            message_type=MessageType.RESPONSE,
            correlation_id=message.correlation_id or message.message_id,
            tenant_id=message.tenant_id,
            user_id=message.user_id,
            action=ObserverAction.GET_METRICS,
            payload=data,
        )

    # ─── Health Report Builder ───────────────────────────────────────

    def _build_health_report(self) -> SystemHealthReport:
        """
        Assemble a complete SystemHealthReport from all subsystem data.
        This is called by the HealthServer and by GET_HEALTH handler.
        """
        uptime = time.time() - self._start_time if self._start_time else 0.0

        # Check Redis connectivity if we have access to the bus
        redis_connected = False
        try:
            # Try to get the bus from the observer's config or attributes
            if hasattr(self, '_bus_publisher') and self._bus_publisher:
                redis_connected = self._bus_publisher.client is not None
            elif hasattr(self, '_bus_subscriber') and self._bus_subscriber:
                redis_connected = self._bus_subscriber.client is not None
        except Exception:
            pass

        return SystemHealthReport(
            system_status=self._heartbeat_monitor.get_system_health(),
            observer_uptime_seconds=uptime,
            agents=self._heartbeat_monitor.get_all_statuses(),
            redis_connected=redis_connected,
            total_messages_processed=self._messages_processed,
            total_metrics_collected=self._metrics_collector.total_collected,
            active_alerts=list(self._alerts[-50:]),  # Last 50 alerts
        )

    # ─── Self-Monitoring (RT-3) ──────────────────────────────────────

    async def _self_heartbeat_loop(self) -> None:
        """
        Self-monitoring loop. The Observer publishes its own heartbeat
        internally. If this loop stops, the System Manager detects
        Observer failure and restarts it.

        Implements RT-3 mitigation (Observer Blind Spot).
        """
        interval = self._config.get("heartbeat_interval", 10.0)
        while True:
            try:
                await asyncio.sleep(interval)
                uptime = time.time() - self._start_time
                # Record own heartbeat internally
                self._heartbeat_monitor.record_heartbeat(
                    HeartbeatEvent(
                        agent_id=self.agent_id,
                        status=AgentHealth.HEALTHY,
                        uptime_seconds=uptime,
                    )
                )
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._fallback_logger.error(f"Self-heartbeat error: {e}")

    async def _metrics_eviction_loop(self) -> None:
        """Periodically evict old metrics to bound memory usage."""
        eviction_interval = self._config.get("metrics_eviction_interval", 600.0)  # 10 minutes
        while True:
            try:
                await asyncio.sleep(eviction_interval)
                evicted = self._metrics_collector.evict_old()
                if evicted > 0:
                    self._log("debug", f"Evicted {evicted} old metric samples.")
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._fallback_logger.error(f"Metrics eviction error: {e}")

    # ─── Alert Callback ──────────────────────────────────────────────

    async def _on_agent_alert(self, agent_id: str, new_health: AgentHealth) -> None:
        """
        Callback fired by HeartbeatMonitor when an agent's health changes.

        Args:
            agent_id: The agent whose health changed.
            new_health: The new health state.
        """
        alert_msg = f"Agent '{agent_id}' health changed to: {new_health.value}"
        self._alerts.append(alert_msg)

        # Cap alerts list
        if len(self._alerts) > 1000:
            self._alerts = self._alerts[-500:]

        self._log("warning", alert_msg, alert_agent=agent_id, new_health=new_health.value)

    # ─── Utility ─────────────────────────────────────────────────────

    def _log(self, level: str, message: str, **context: Any) -> None:
        """
        Emit a log entry using structlog if available, stderr fallback otherwise.
        """
        if self._logger:
            log_fn = getattr(self._logger, level, self._logger.info)
            log_fn(message, **context)
        else:
            fallback_fn = getattr(self._fallback_logger, level, self._fallback_logger.info)
            fallback_fn(message, **context)

    def _error_response(self, original: AegisMessage, error: str) -> AegisMessage:
        """Create a standardized error response message."""
        return AegisMessage(
            source_agent=self.agent_id,
            target_agent=original.source_agent,
            message_type=MessageType.ERROR,
            correlation_id=original.correlation_id or original.message_id,
            tenant_id=original.tenant_id,
            user_id=original.user_id,
            action=original.action,
            payload={"error": error},
        )
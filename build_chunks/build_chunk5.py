# build_chunk_005.py
#
# This script assembles the Aegis CHUNK-005: Observer Service.
# Run it from the root of your project-aegis directory.
# It will create the necessary directories and write the frozen files.
#
# Dependencies: CHUNK-001 (Base Layout & Schemas), CHUNK-002 (Redis Message Bus)
# Delivers: Observer agent, structured logging (structlog), heartbeat monitor,
#           health endpoint, metrics collection, stderr fallback.
# Addresses: Foundation (RT-3 — Observer Blind Spot)

import os
import textwrap


# --- File Manifest ---
CHUNK_005_FILES = {

    # ═══════════════════════════════════════════════════════════════════
    # SCHEMAS
    # ═══════════════════════════════════════════════════════════════════

    "aegis/schemas/observer.py": '''
# aegis/schemas/observer.py
# Implements: Part III, §3.2 — Observer Service Contracts
"""
Pydantic models for Observer Service events and health reporting.
All inter-agent observability communication uses these contracts.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    """Returns current UTC datetime."""
    return datetime.now(timezone.utc)


# ─── Enums ───────────────────────────────────────────────────────────

class LogLevel(str, Enum):
    """Standard log levels for structured logging."""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AgentHealth(str, Enum):
    """Health states for monitored agents."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNRESPONSIVE = "unresponsive"
    UNKNOWN = "unknown"


class MetricType(str, Enum):
    """Types of metrics the Observer collects."""
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    TIMING = "timing"


# ─── Event Models ────────────────────────────────────────────────────

class HeartbeatEvent(BaseModel):
    """
    Published by agents at regular intervals to signal liveness.
    Observer tracks these to detect agent failures.
    """
    agent_id: str = Field(..., description="The unique ID of the reporting agent.")
    timestamp: datetime = Field(default_factory=_utc_now)
    status: AgentHealth = Field(default=AgentHealth.HEALTHY)
    uptime_seconds: float = Field(default=0.0, description="Seconds since agent startup.")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Agent-specific health data.")


class LogEvent(BaseModel):
    """
    Structured log entry published by agents to the Observer for aggregation.
    All fields required for correlation and filtering.
    """
    log_id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = Field(default_factory=_utc_now)
    level: LogLevel = Field(default=LogLevel.INFO)
    agent_id: str = Field(..., description="Source agent.")
    tenant_id: Optional[str] = Field(default=None)
    user_id: Optional[str] = Field(default=None)
    correlation_id: Optional[str] = Field(default=None, description="Links to AegisMessage correlation_id.")
    message: str = Field(..., description="Human-readable log message.")
    context: Dict[str, Any] = Field(default_factory=dict, description="Structured context data.")


class MetricEvent(BaseModel):
    """
    A single metric data point published by any agent.
    Observer aggregates these for performance monitoring.
    """
    metric_id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = Field(default_factory=_utc_now)
    agent_id: str = Field(..., description="Source agent.")
    metric_name: str = Field(..., description="Dot-notation metric name (e.g., 'forge.tool.execution_time').")
    metric_type: MetricType = Field(default=MetricType.GAUGE)
    value: float = Field(..., description="Numeric metric value.")
    unit: str = Field(default="", description="Unit of measurement (ms, bytes, count, etc.).")
    tags: Dict[str, str] = Field(default_factory=dict, description="Dimensional tags for filtering.")


# ─── Health Report Models ────────────────────────────────────────────

class AgentStatus(BaseModel):
    """Health status of a single monitored agent."""
    agent_id: str
    health: AgentHealth = Field(default=AgentHealth.UNKNOWN)
    last_heartbeat: Optional[datetime] = Field(default=None)
    uptime_seconds: float = Field(default=0.0)
    missed_heartbeats: int = Field(default=0)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SystemHealthReport(BaseModel):
    """
    Complete system health snapshot exposed via /health endpoint.
    Consumed by Mission Control UI and CLI `aegis status`.
    """
    timestamp: datetime = Field(default_factory=_utc_now)
    system_status: AgentHealth = Field(default=AgentHealth.UNKNOWN)
    observer_uptime_seconds: float = Field(default=0.0)
    agents: List[AgentStatus] = Field(default_factory=list)
    redis_connected: bool = Field(default=False)
    total_messages_processed: int = Field(default=0)
    total_metrics_collected: int = Field(default=0)
    active_alerts: List[str] = Field(default_factory=list)


# ─── Observer Protocol Actions ───────────────────────────────────────

class ObserverAction(str, Enum):
    """Actions the Observer handles via the message bus."""
    HEARTBEAT = "observer.heartbeat"
    LOG = "observer.log"
    METRIC = "observer.metric"
    GET_HEALTH = "observer.get_health"
    GET_AGENT_STATUS = "observer.get_agent_status"
    GET_METRICS = "observer.get_metrics"
''',

    # ═══════════════════════════════════════════════════════════════════
    # OBSERVER PACKAGE
    # ═══════════════════════════════════════════════════════════════════

    "aegis/observer/__init__.py": '''
# aegis/observer/__init__.py
"""
Aegis Observer Service — System-wide monitoring, structured logging,
metrics collection, and health checks.

Implements: Part III, §3.2
"""

from aegis.observer.agent import ObserverAgent
from aegis.observer.logging import configure_logging, get_logger, FallbackLogger
from aegis.observer.heartbeat import HeartbeatMonitor
from aegis.observer.metrics import MetricsCollector
from aegis.observer.health import HealthServer

__all__ = [
    "ObserverAgent",
    "configure_logging",
    "get_logger",
    "FallbackLogger",
    "HeartbeatMonitor",
    "MetricsCollector",
    "HealthServer",
]
''',

    # ─── Structured Logging ──────────────────────────────────────────

    "aegis/observer/logging.py": '''
# aegis/observer/logging.py
# Implements: Part III, §3.2 — Structured Logging (structlog, JSON-formatted)
"""
Configures structured logging for the entire Aegis system.
Uses structlog for JSON-formatted, contextual logging.
All log entries include tenant_id, user_id, correlation_id, and agent_id.

Provides a FallbackLogger for stderr output when Observer is unavailable (RT-3).
"""

import sys
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import structlog
from structlog.types import EventDict


# ─── Processors ──────────────────────────────────────────────────────

def add_timestamp(logger: Any, method_name: str, event_dict: EventDict) -> EventDict:
    """Add ISO-format UTC timestamp to every log entry."""
    event_dict["timestamp"] = datetime.now(timezone.utc).isoformat()
    return event_dict


def add_log_level(logger: Any, method_name: str, event_dict: EventDict) -> EventDict:
    """Ensure log level is present."""
    event_dict["level"] = method_name
    return event_dict


def sanitize_event_dict(logger: Any, method_name: str, event_dict: EventDict) -> EventDict:
    """Remove None values and ensure serializable output."""
    return {k: v for k, v in event_dict.items() if v is not None}


# ─── Configuration ───────────────────────────────────────────────────

def configure_logging(
    log_level: str = "INFO",
    json_output: bool = True,
    log_file: Optional[str] = None,
) -> None:
    """
    Configure structlog for the Aegis system.

    Args:
        log_level: Minimum log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        json_output: If True, output JSON-formatted logs. Otherwise, console-friendly.
        log_file: Optional file path to write logs to (in addition to stdout).
    """
    # Set up standard library logging as structlog's output
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper(), logging.INFO),
    )

    # Add file handler if specified
    if log_file:
        file_handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
        file_handler.setLevel(getattr(logging, log_level.upper(), logging.INFO))
        logging.getLogger().addHandler(file_handler)

    # Choose renderer based on output format
    if json_output:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    # Configure structlog
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            add_timestamp,
            add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            sanitize_event_dict,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Set the formatter for the root handler
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=[
            structlog.contextvars.merge_contextvars,
            add_timestamp,
            add_log_level,
            structlog.processors.format_exc_info,
        ],
    )
    for handler in logging.getLogger().handlers:
        handler.setFormatter(formatter)


def get_logger(
    agent_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    user_id: Optional[str] = None,
    **initial_context: Any,
) -> structlog.stdlib.BoundLogger:
    """
    Get a bound structured logger with Aegis context fields.

    Args:
        agent_id: The agent requesting the logger.
        tenant_id: Current tenant context.
        user_id: Current user context.
        **initial_context: Additional context to bind.

    Returns:
        A bound structlog logger instance.
    """
    logger = structlog.get_logger()
    bindings: Dict[str, Any] = {}

    if agent_id:
        bindings["agent_id"] = agent_id
    if tenant_id:
        bindings["tenant_id"] = tenant_id
    if user_id:
        bindings["user_id"] = user_id
    bindings.update(initial_context)

    if bindings:
        logger = logger.bind(**bindings)

    return logger


# ─── Fallback Logger (RT-3 Mitigation) ──────────────────────────────

class FallbackLogger:
    """
    Minimal stderr logger used when the Observer service is unavailable.
    Implements RT-3 mitigation: agents fall back to local stderr logging
    if Observer crashes.

    Outputs JSON-formatted log lines to stderr for later collection.
    """

    def __init__(self, agent_id: str):
        self.agent_id = agent_id

    def _emit(self, level: str, message: str, **context: Any) -> None:
        """Write a JSON log line to stderr."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "agent_id": self.agent_id,
            "event": message,
            **context,
        }
        sys.stderr.write(json.dumps(entry) + "\\n")
        sys.stderr.flush()

    def debug(self, message: str, **ctx: Any) -> None:
        self._emit("debug", message, **ctx)

    def info(self, message: str, **ctx: Any) -> None:
        self._emit("info", message, **ctx)

    def warning(self, message: str, **ctx: Any) -> None:
        self._emit("warning", message, **ctx)

    def error(self, message: str, **ctx: Any) -> None:
        self._emit("error", message, **ctx)

    def critical(self, message: str, **ctx: Any) -> None:
        self._emit("critical", message, **ctx)
''',

    # ─── Heartbeat Monitor ───────────────────────────────────────────

    "aegis/observer/heartbeat.py": '''
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
''',

    # ─── Metrics Collector ───────────────────────────────────────────

    "aegis/observer/metrics.py": '''
# aegis/observer/metrics.py
# Implements: Part III, §3.2 — Performance Metrics Collection
"""
Collects and aggregates performance metrics from all agents.
Stores metrics in-memory with a configurable retention window.
Provides query interface for health reporting and Mission Control UI.
"""

import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional

from aegis.schemas.observer import MetricEvent, MetricType


@dataclass
class MetricSample:
    """A single metric data point stored in memory."""
    timestamp: float  # Unix timestamp for efficient comparison
    value: float
    agent_id: str
    tags: Dict[str, str] = field(default_factory=dict)


@dataclass
class MetricSeries:
    """A time-series of samples for a specific metric name."""
    metric_name: str
    metric_type: MetricType
    unit: str
    samples: Deque[MetricSample] = field(default_factory=lambda: deque(maxlen=10000))

    @property
    def count(self) -> int:
        return len(self.samples)

    @property
    def latest(self) -> Optional[MetricSample]:
        return self.samples[-1] if self.samples else None

    def add(self, sample: MetricSample) -> None:
        """Append a sample to the series."""
        self.samples.append(sample)

    def get_values_since(self, since_unix: float) -> List[float]:
        """Get all values since a given unix timestamp."""
        return [s.value for s in self.samples if s.timestamp >= since_unix]

    def compute_stats(self, window_seconds: float = 300.0) -> Dict[str, float]:
        """
        Compute basic statistics over a time window.

        Args:
            window_seconds: Look-back window in seconds (default: 5 minutes).

        Returns:
            Dictionary with count, min, max, avg, sum, latest.
        """
        cutoff = time.time() - window_seconds
        values = self.get_values_since(cutoff)

        if not values:
            return {"count": 0, "min": 0.0, "max": 0.0, "avg": 0.0, "sum": 0.0, "latest": 0.0}

        return {
            "count": len(values),
            "min": min(values),
            "max": max(values),
            "avg": sum(values) / len(values),
            "sum": sum(values),
            "latest": values[-1],
        }


class MetricsCollector:
    """
    In-memory metrics aggregation engine.

    Collects MetricEvents from agents, organizes them into time-series,
    and provides query interfaces for health reporting.

    Configuration:
        max_samples_per_metric: Maximum samples retained per metric series.
        retention_seconds: Metrics older than this are eligible for eviction.
    """

    def __init__(
        self,
        max_samples_per_metric: int = 10000,
        retention_seconds: float = 3600.0,
    ):
        """
        Initialize the MetricsCollector.

        Args:
            max_samples_per_metric: Max samples per metric series (ring buffer).
            retention_seconds: Time window for metric retention (default: 1 hour).
        """
        self.max_samples_per_metric = max_samples_per_metric
        self.retention_seconds = retention_seconds
        self._series: Dict[str, MetricSeries] = {}
        self._total_collected: int = 0

    @property
    def total_collected(self) -> int:
        """Total number of metric events ever recorded."""
        return self._total_collected

    @property
    def active_metrics(self) -> List[str]:
        """List of all active metric names."""
        return list(self._series.keys())

    def record(self, event: MetricEvent) -> None:
        """
        Record a metric event.

        Args:
            event: The MetricEvent to record.
        """
        metric_name = event.metric_name

        # Create series if new
        if metric_name not in self._series:
            self._series[metric_name] = MetricSeries(
                metric_name=metric_name,
                metric_type=event.metric_type,
                unit=event.unit,
                samples=deque(maxlen=self.max_samples_per_metric),
            )

        sample = MetricSample(
            timestamp=event.timestamp.timestamp() if event.timestamp else time.time(),
            value=event.value,
            agent_id=event.agent_id,
            tags=event.tags,
        )

        self._series[metric_name].add(sample)
        self._total_collected += 1

    def get_metric(self, metric_name: str) -> Optional[MetricSeries]:
        """Get a metric series by name."""
        return self._series.get(metric_name)

    def get_stats(
        self,
        metric_name: str,
        window_seconds: float = 300.0,
    ) -> Dict[str, float]:
        """
        Get computed statistics for a metric.

        Args:
            metric_name: The metric to query.
            window_seconds: Look-back window for computation.

        Returns:
            Stats dict or empty dict if metric not found.
        """
        series = self._series.get(metric_name)
        if not series:
            return {}
        return series.compute_stats(window_seconds)

    def get_all_stats(self, window_seconds: float = 300.0) -> Dict[str, Dict[str, float]]:
        """Get stats for all metrics within a window."""
        return {
            name: series.compute_stats(window_seconds)
            for name, series in self._series.items()
        }

    def get_agent_metrics(self, agent_id: str, window_seconds: float = 300.0) -> Dict[str, List[float]]:
        """
        Get all metric values for a specific agent within a time window.

        Args:
            agent_id: The agent to filter by.
            window_seconds: Look-back window.

        Returns:
            Dict of metric_name -> list of values from that agent.
        """
        cutoff = time.time() - window_seconds
        result: Dict[str, List[float]] = {}

        for name, series in self._series.items():
            values = [
                s.value for s in series.samples
                if s.agent_id == agent_id and s.timestamp >= cutoff
            ]
            if values:
                result[name] = values

        return result

    def evict_old(self) -> int:
        """
        Remove samples older than retention_seconds.

        Returns:
            Number of samples evicted.
        """
        cutoff = time.time() - self.retention_seconds
        evicted = 0

        for series in self._series.values():
            original_len = len(series.samples)
            # Deque doesn't support efficient left-trim by condition,
            # so rebuild if necessary
            while series.samples and series.samples[0].timestamp < cutoff:
                series.samples.popleft()
                evicted += 1

        # Remove empty series
        empty_keys = [k for k, v in self._series.items() if v.count == 0]
        for k in empty_keys:
            del self._series[k]

        return evicted

    def reset(self) -> None:
        """Clear all metrics (used for testing)."""
        self._series.clear()
        self._total_collected = 0
''',

    # ─── Health Endpoint Server ──────────────────────────────────────

    "aegis/observer/health.py": '''
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
''',

    # ─── Observer Agent (Main) ───────────────────────────────────────

    "aegis/observer/agent.py": '''
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
                - health_host (str): Health server bind address. Default: "127.0.0.1"
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
            host=self._config.get("health_host", "127.0.0.1"),
            port=self._config.get("health_port", 8421),
        )

        # Logger (uses structlog when available, fallback to stderr)
        self._logger = None
        self._fallback_logger = FallbackLogger(agent_id=self.agent_id)

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
            self._log("info", f"Health endpoint available at http://{self._config.get('health_host', '127.0.0.1')}:{self._config.get('health_port', 8421)}/health")
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

        return SystemHealthReport(
            system_status=self._heartbeat_monitor.get_system_health(),
            observer_uptime_seconds=uptime,
            agents=self._heartbeat_monitor.get_all_statuses(),
            redis_connected=True,  # Will be wired to actual check via bus integration
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
''',

    # ═══════════════════════════════════════════════════════════════════
    # TESTS
    # ═══════════════════════════════════════════════════════════════════

    "tests/test_observer/__init__.py": '''
# tests/test_observer/__init__.py
''',

    "tests/test_observer/test_heartbeat.py": '''
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
''',

    "tests/test_observer/test_metrics.py": '''
# tests/test_observer/test_metrics.py
# Unit tests for the MetricsCollector component.
"""
Tests cover:
- Recording metric events
- Querying individual metrics and stats
- Time-windowed statistics computation
- Agent-scoped metric queries
- Eviction of old samples
- Ring buffer (maxlen) behavior
"""

import time
import pytest
from datetime import datetime, timezone, timedelta

from aegis.schemas.observer import MetricEvent, MetricType
from aegis.observer.metrics import MetricsCollector, MetricSample


@pytest.fixture
def collector():
    """Create a MetricsCollector with small limits for testing."""
    return MetricsCollector(
        max_samples_per_metric=100,
        retention_seconds=60.0,
    )


class TestMetricsCollector:
    """Tests for MetricsCollector."""

    def test_record_event(self, collector):
        """Test recording a single metric event."""
        event = MetricEvent(
            agent_id="forge",
            metric_name="forge.tool.execution_time",
            metric_type=MetricType.TIMING,
            value=150.5,
            unit="ms",
        )
        collector.record(event)

        assert collector.total_collected == 1
        assert "forge.tool.execution_time" in collector.active_metrics

    def test_get_metric_series(self, collector):
        """Test retrieving a metric series."""
        for i in range(5):
            event = MetricEvent(
                agent_id="oracle",
                metric_name="oracle.latency",
                metric_type=MetricType.TIMING,
                value=float(100 + i * 10),
                unit="ms",
            )
            collector.record(event)

        series = collector.get_metric("oracle.latency")
        assert series is not None
        assert series.count == 5
        assert series.latest.value == 140.0

    def test_compute_stats(self, collector):
        """Test statistics computation over a window."""
        for i in range(10):
            event = MetricEvent(
                agent_id="forge",
                metric_name="test.metric",
                value=float(i),
            )
            collector.record(event)

        stats = collector.get_stats("test.metric", window_seconds=300.0)
        assert stats["count"] == 10
        assert stats["min"] == 0.0
        assert stats["max"] == 9.0
        assert stats["avg"] == 4.5
        assert stats["sum"] == 45.0

    def test_get_stats_nonexistent(self, collector):
        """Test stats for non-existent metric returns empty dict."""
        stats = collector.get_stats("nonexistent.metric")
        assert stats == {}

    def test_get_all_stats(self, collector):
        """Test retrieval of stats for all metrics."""
        collector.record(MetricEvent(agent_id="a", metric_name="m1", value=10.0))
        collector.record(MetricEvent(agent_id="b", metric_name="m2", value=20.0))

        all_stats = collector.get_all_stats()
        assert "m1" in all_stats
        assert "m2" in all_stats
        assert all_stats["m1"]["latest"] == 10.0
        assert all_stats["m2"]["latest"] == 20.0

    def test_agent_metrics(self, collector):
        """Test filtering metrics by agent_id."""
        collector.record(MetricEvent(agent_id="forge", metric_name="exec_time", value=100.0))
        collector.record(MetricEvent(agent_id="oracle", metric_name="exec_time", value=200.0))
        collector.record(MetricEvent(agent_id="forge", metric_name="exec_time", value=150.0))

        forge_metrics = collector.get_agent_metrics("forge", window_seconds=300.0)
        assert "exec_time" in forge_metrics
        assert forge_metrics["exec_time"] == [100.0, 150.0]

    def test_eviction(self, collector):
        """Test that eviction removes old samples."""
        # Directly inject old samples
        series = None
        collector.record(MetricEvent(agent_id="a", metric_name="old_metric", value=1.0))
        series = collector.get_metric("old_metric")

        # Manually backdate the sample
        series.samples[0] = MetricSample(
            timestamp=time.time() - 120.0,  # 2 minutes ago, beyond 60s retention
            value=1.0,
            agent_id="a",
        )

        evicted = collector.evict_old()
        assert evicted == 1
        assert series.count == 0

    def test_reset(self, collector):
        """Test reset clears all data."""
        collector.record(MetricEvent(agent_id="a", metric_name="m", value=1.0))
        collector.reset()
        assert collector.total_collected == 0
        assert collector.active_metrics == []

    def test_ring_buffer_max_samples(self):
        """Test that samples are capped at max_samples_per_metric."""
        collector = MetricsCollector(max_samples_per_metric=5, retention_seconds=3600.0)

        for i in range(10):
            collector.record(MetricEvent(agent_id="a", metric_name="bounded", value=float(i)))

        series = collector.get_metric("bounded")
        # Ring buffer retains only last 5
        assert series.count == 5
        assert series.samples[0].value == 5.0
        assert series.samples[-1].value == 9.0
''',

    "tests/test_observer/test_logging.py": '''
# tests/test_observer/test_logging.py
# Unit tests for the structured logging module.
"""
Tests cover:
- Logger creation with bound context
- FallbackLogger stderr output
- configure_logging doesn't raise
"""

import sys
import json
import pytest
from io import StringIO
from unittest.mock import patch

from aegis.observer.logging import (
    configure_logging,
    get_logger,
    FallbackLogger,
)


class TestConfigureLogging:
    """Tests for logging configuration."""

    def test_configure_logging_default(self):
        """Test that configure_logging runs without errors."""
        # Should not raise
        configure_logging(log_level="DEBUG", json_output=True)

    def test_configure_logging_console_mode(self):
        """Test console (non-JSON) mode configuration."""
        configure_logging(log_level="INFO", json_output=False)


class TestGetLogger:
    """Tests for structured logger creation."""

    def test_get_logger_basic(self):
        """Test basic logger creation."""
        configure_logging(log_level="DEBUG", json_output=True)
        logger = get_logger()
        assert logger is not None

    def test_get_logger_with_context(self):
        """Test logger creation with bound context fields."""
        configure_logging(log_level="DEBUG", json_output=True)
        logger = get_logger(
            agent_id="forge",
            tenant_id="tenant-123",
            user_id="user-456",
        )
        assert logger is not None
        # The logger should have bound context (structlog internals)


class TestFallbackLogger:
    """Tests for FallbackLogger (RT-3 stderr fallback)."""

    def test_fallback_logger_output(self):
        """Test that FallbackLogger writes JSON to stderr."""
        logger = FallbackLogger(agent_id="test_agent")

        captured = StringIO()
        with patch("sys.stderr", captured):
            logger.info("Test message", extra_key="extra_value")

        output = captured.getvalue().strip()
        parsed = json.loads(output)

        assert parsed["level"] == "info"
        assert parsed["agent_id"] == "test_agent"
        assert parsed["event"] == "Test message"
        assert parsed["extra_key"] == "extra_value"
        assert "timestamp" in parsed

    def test_fallback_logger_all_levels(self):
        """Test all log levels emit to stderr."""
        logger = FallbackLogger(agent_id="multi_level")

        levels = ["debug", "info", "warning", "error", "critical"]
        captured = StringIO()

        with patch("sys.stderr", captured):
            for level in levels:
                getattr(logger, level)(f"{level} message")

        lines = captured.getvalue().strip().split("\\n")
        assert len(lines) == 5

        for i, level in enumerate(levels):
            parsed = json.loads(lines[i])
            assert parsed["level"] == level
            assert parsed["event"] == f"{level} message"
''',

    "tests/test_observer/test_agent.py": '''
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
''',

    "tests/test_observer/test_health_server.py": '''
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
''',

    # ═══════════════════════════════════════════════════════════════════
    # CONFIGURATION & DEPENDENCY UPDATES
    # ═══════════════════════════════════════════════════════════════════

    "requirements_chunk005.txt": '''
# Additional dependencies for CHUNK-005: Observer Service
# Append these to your existing requirements.txt
structlog>=24.1.0
aiohttp>=3.9.0
''',

}


def create_package_init_files(path):
    """Create __init__.py files in parent directories if they don't exist."""
    dir_name = os.path.dirname(path)
    if dir_name and (dir_name.startswith("") or dir_name.startswith("tests/")):
        parts = dir_name.split("/")
        for i in range(2, len(parts) + 1):
            pkg_path = "/".join(parts[:i])
            init_file = os.path.join(pkg_path, "__init__.py")
            if not os.path.exists(init_file):
                os.makedirs(pkg_path, exist_ok=True)
                print(f"  [Created] {init_file} (empty package marker)")
                with open(init_file, "w") as f:
                    pass


def main():
    """Main function to write all files."""
    print("=" * 60)
    print("  Assembling Aegis CHUNK-005: Observer Service")
    print("=" * 60)
    print()

    files_written = 0
    for path, content in CHUNK_005_FILES.items():
        # Ensure the directory exists
        dir_name = os.path.dirname(path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)

        create_package_init_files(path)
        print(f"  [Writing] {path}")

        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(textwrap.dedent(content.strip()) + "\n")
        files_written += 1

    print()
    print("-" * 60)
    print(f"  Assembly Complete — {files_written} files written.")
    print()
    print("  New dependencies to install:")
    print("    pip install structlog>=24.1.0 aiohttp>=3.9.0")
    print()
    print("  Run tests with:")
    print("    pytest tests/test_observer/ -v")
    print("-" * 60)


if __name__ == "__main__":
    main()

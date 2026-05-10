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

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

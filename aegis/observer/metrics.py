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

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

"""
Tests for the Observability Module — Metrics and Health Checks.
"""

import pytest
import time
from pathlib import Path
import tempfile
import json

from src.observability.metrics import (
    metrics,
    MetricsRegistry,
    Counter,
    Gauge,
    Histogram,
)
from src.observability.health import (
    HealthChecker,
    HealthStatus,
    SystemHealth,
    ComponentHealth,
)


class TestCounter:
    """Tests for Counter metric."""
    
    def test_increment(self):
        """Test counter increment."""
        counter = Counter("test_counter")
        
        counter.inc()
        counter.inc()
        counter.inc(5)
        
        assert counter.get() == 7
    
    def test_increment_with_labels(self):
        """Test counter with labels."""
        counter = Counter("test_counter")
        
        counter.inc(1, labels={"adapter": "email"})
        counter.inc(2, labels={"adapter": "sms"})
        counter.inc(1, labels={"adapter": "email"})
        
        assert counter.get(labels={"adapter": "email"}) == 2
        assert counter.get(labels={"adapter": "sms"}) == 2
    
    def test_export(self):
        """Test counter export."""
        counter = Counter("test_counter")
        counter.inc(3)
        
        points = counter.export()
        
        assert len(points) == 1
        assert points[0].value == 3


class TestGauge:
    """Tests for Gauge metric."""
    
    def test_set(self):
        """Test gauge set."""
        gauge = Gauge("test_gauge")
        
        gauge.set(42)
        
        assert gauge.get() == 42
    
    def test_inc_dec(self):
        """Test gauge increment and decrement."""
        gauge = Gauge("test_gauge")
        
        gauge.set(10)
        gauge.inc(5)
        gauge.dec(3)
        
        assert gauge.get() == 12
    
    def test_set_with_labels(self):
        """Test gauge with labels."""
        gauge = Gauge("test_gauge")
        
        gauge.set(1, labels={"circuit": "email"})
        gauge.set(0, labels={"circuit": "sms"})
        
        assert gauge.get(labels={"circuit": "email"}) == 1
        assert gauge.get(labels={"circuit": "sms"}) == 0


class TestHistogram:
    """Tests for Histogram metric."""
    
    def test_observe(self):
        """Test histogram observe."""
        histogram = Histogram("test_histogram")
        
        histogram.observe(0.1)
        histogram.observe(0.5)
        histogram.observe(1.5)
        
        points = histogram.export()
        
        # Should have bucket points plus sum and count
        assert len(points) > 2
    
    def test_custom_buckets(self):
        """Test histogram with custom buckets."""
        histogram = Histogram(
            "test_histogram",
            buckets=(1, 5, 10, float("inf")),
        )
        
        histogram.observe(3)
        histogram.observe(7)
        
        points = histogram.export()
        
        # Find the sum point
        sum_point = next(p for p in points if "_sum" in p.name)
        assert sum_point.value == 10


class TestMetricsRegistry:
    """Tests for MetricsRegistry."""
    
    def test_counter_creation(self):
        """Test counter creation."""
        registry = MetricsRegistry(prefix="test")
        
        counter = registry.counter("requests")
        counter.inc()
        
        assert counter.get() == 1
    
    def test_gauge_creation(self):
        """Test gauge creation."""
        registry = MetricsRegistry(prefix="test")
        
        gauge = registry.gauge("queue_size")
        gauge.set(5)
        
        assert gauge.get() == 5
    
    def test_histogram_creation(self):
        """Test histogram creation."""
        registry = MetricsRegistry(prefix="test")
        
        histogram = registry.histogram("duration")
        histogram.observe(0.5)
        
        points = histogram.export()
        assert len(points) > 0
    
    def test_convenience_methods(self):
        """Test convenience methods."""
        registry = MetricsRegistry(prefix="test")
        
        registry.increment("counter")
        registry.set_gauge("gauge", 10)
        registry.timing("timing", 0.5)
        
        assert registry.counter("counter").get() == 1
        assert registry.gauge("gauge").get() == 10
    
    def test_export_prometheus(self):
        """Test Prometheus format export."""
        registry = MetricsRegistry(prefix="test")
        registry.increment("requests")
        registry.set_gauge("active", 5)
        
        output = registry.export_prometheus()
        
        assert "test_requests" in output
        assert "test_active" in output
        assert "# TYPE" in output
        assert "# HELP" in output
    
    def test_export_json(self):
        """Test JSON format export."""
        registry = MetricsRegistry(prefix="test")
        registry.increment("requests")
        registry.set_gauge("active", 5)
        
        output = registry.export_json()
        
        assert "timestamp" in output
        assert "counters" in output
        assert "gauges" in output


class TestHealthChecker:
    """Tests for HealthChecker."""
    
    @pytest.fixture
    def temp_state_file(self):
        """Create temporary state file."""
        state = {
            "meta": {
                "schema_version": 1,
                "project": "test",
                "state_id": "S-TEST-001",
                "updated_at_iso": "2026-02-04T12:00:00Z",
                "policy_version": 1,
                "plan_id": "default",
            },
            "mode": {"name": "renewable_countdown", "armed": True},
            "timer": {
                "deadline_iso": "2026-02-05T12:00:00Z",
                "grace_minutes": 0,
                "now_iso": "2026-02-04T12:00:00Z",
                "time_to_deadline_minutes": 1440,
                "overdue_minutes": 0,
            },
            "renewal": {
                "last_renewal_iso": "2026-02-04T12:00:00Z",
                "renewed_this_tick": False,
                "renewal_count": 0,
            },
            "security": {
                "failed_attempts": 0,
                "lockout_active": False,
                "lockout_until_iso": None,
                "max_failed_attempts": 3,
                "lockout_minutes": 60,
            },
            "escalation": {
                "state": "OK",
                "state_entered_at_iso": "2026-02-04T12:00:00Z",
                "last_transition_rule_id": None,
            },
            "actions": {"executed": {}, "last_tick_actions": []},
            "integrations": {
                "enabled_adapters": {},
                "routing": {},
            },
            "pointers": {},
        }
        
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False
        ) as f:
            json.dump(state, f)
            path = Path(f.name)
        
        yield path
        if path.exists():
            path.unlink()
    
    def test_check_returns_health(self, temp_state_file):
        """Test check returns health status."""
        checker = HealthChecker(state_path=temp_state_file)
        
        result = checker.check()
        
        assert isinstance(result, SystemHealth)
        assert result.status in [HealthStatus.HEALTHY, HealthStatus.DEGRADED, HealthStatus.UNHEALTHY]
    
    def test_health_includes_components(self, temp_state_file):
        """Test health includes component checks."""
        checker = HealthChecker(state_path=temp_state_file)
        
        result = checker.check()
        
        component_names = [c.name for c in result.components]
        assert "state_file" in component_names
        assert "audit_log" in component_names
    
    def test_missing_state_unhealthy(self):
        """Test missing state file is unhealthy."""
        checker = HealthChecker(state_path=Path("/nonexistent/state.json"))
        
        result = checker.check()
        
        state_component = next(c for c in result.components if c.name == "state_file")
        assert state_component.status == HealthStatus.UNHEALTHY
    
    def test_to_dict(self, temp_state_file):
        """Test health to_dict conversion."""
        checker = HealthChecker(state_path=temp_state_file)
        
        result = checker.check()
        d = result.to_dict()
        
        assert "status" in d
        assert "timestamp" in d
        assert "components" in d
        assert "healthy" in d


class TestComponentHealth:
    """Tests for ComponentHealth."""
    
    def test_creation(self):
        """Test component health creation."""
        component = ComponentHealth(
            name="test",
            status=HealthStatus.HEALTHY,
            message="All good",
            latency_ms=5.0,
        )
        
        assert component.name == "test"
        assert component.status == HealthStatus.HEALTHY


class TestSystemHealth:
    """Tests for SystemHealth."""
    
    def test_healthy_property(self):
        """Test healthy property."""
        health = SystemHealth(
            status=HealthStatus.HEALTHY,
            timestamp="2026-02-04T12:00:00Z",
            uptime_seconds=100,
            components=[],
        )
        
        assert health.healthy is True
    
    def test_unhealthy_property(self):
        """Test unhealthy property."""
        health = SystemHealth(
            status=HealthStatus.UNHEALTHY,
            timestamp="2026-02-04T12:00:00Z",
            uptime_seconds=100,
            components=[],
        )
        
        assert health.healthy is False

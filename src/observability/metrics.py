"""
Metrics — Collect and expose operational metrics.

Provides a simple metrics collection system compatible with
Prometheus exposition format.

## Usage

    from src.observability.metrics import metrics
    
    metrics.increment("tick.count")
    metrics.timing("tick.duration_ms", 1234)
    metrics.gauge("queue.size", 5)
    
    # Export for Prometheus
    output = metrics.export_prometheus()
"""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class MetricPoint:
    """A single metric data point."""
    
    name: str
    value: float
    timestamp: float
    labels: Dict[str, str] = field(default_factory=dict)


class Counter:
    """A monotonically increasing counter."""
    
    def __init__(self, name: str, help_text: str = ""):
        self.name = name
        self.help_text = help_text
        self._values: Dict[str, float] = defaultdict(float)
        self._lock = Lock()
    
    def inc(self, value: float = 1, labels: Optional[Dict[str, str]] = None) -> None:
        """Increment the counter."""
        key = self._labels_key(labels)
        with self._lock:
            self._values[key] += value
    
    def get(self, labels: Optional[Dict[str, str]] = None) -> float:
        """Get current value."""
        key = self._labels_key(labels)
        return self._values.get(key, 0)
    
    def _labels_key(self, labels: Optional[Dict[str, str]]) -> str:
        if not labels:
            return ""
        return ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
    
    def export(self) -> List[MetricPoint]:
        """Export all values as metric points."""
        points = []
        now = time.time()
        for key, value in self._values.items():
            labels = {}
            if key:
                for pair in key.split(","):
                    k, v = pair.split("=")
                    labels[k] = v
            points.append(MetricPoint(self.name, value, now, labels))
        return points


class Gauge:
    """A gauge that can go up and down."""
    
    def __init__(self, name: str, help_text: str = ""):
        self.name = name
        self.help_text = help_text
        self._values: Dict[str, float] = {}
        self._lock = Lock()
    
    def set(self, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        """Set the gauge value."""
        key = self._labels_key(labels)
        with self._lock:
            self._values[key] = value
    
    def inc(self, value: float = 1, labels: Optional[Dict[str, str]] = None) -> None:
        """Increment the gauge."""
        key = self._labels_key(labels)
        with self._lock:
            self._values[key] = self._values.get(key, 0) + value
    
    def dec(self, value: float = 1, labels: Optional[Dict[str, str]] = None) -> None:
        """Decrement the gauge."""
        self.inc(-value, labels)
    
    def get(self, labels: Optional[Dict[str, str]] = None) -> float:
        """Get current value."""
        key = self._labels_key(labels)
        return self._values.get(key, 0)
    
    def _labels_key(self, labels: Optional[Dict[str, str]]) -> str:
        if not labels:
            return ""
        return ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
    
    def export(self) -> List[MetricPoint]:
        """Export all values as metric points."""
        points = []
        now = time.time()
        for key, value in self._values.items():
            labels = {}
            if key:
                for pair in key.split(","):
                    k, v = pair.split("=")
                    labels[k] = v
            points.append(MetricPoint(self.name, value, now, labels))
        return points


class Histogram:
    """A histogram for timing distributions."""
    
    DEFAULT_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, float("inf"))
    
    def __init__(self, name: str, help_text: str = "", buckets: Optional[tuple] = None):
        self.name = name
        self.help_text = help_text
        self.buckets = buckets or self.DEFAULT_BUCKETS
        self._counts: Dict[str, Dict[float, int]] = defaultdict(lambda: defaultdict(int))
        self._sums: Dict[str, float] = defaultdict(float)
        self._totals: Dict[str, int] = defaultdict(int)
        self._lock = Lock()
    
    def observe(self, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        """Observe a value."""
        key = self._labels_key(labels)
        with self._lock:
            self._sums[key] += value
            self._totals[key] += 1
            for bucket in self.buckets:
                if value <= bucket:
                    self._counts[key][bucket] += 1
    
    def _labels_key(self, labels: Optional[Dict[str, str]]) -> str:
        if not labels:
            return ""
        return ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
    
    def export(self) -> List[MetricPoint]:
        """Export histogram as metric points."""
        points = []
        now = time.time()
        
        for key in set(self._sums.keys()) | set(self._counts.keys()):
            labels = {}
            if key:
                for pair in key.split(","):
                    k, v = pair.split("=")
                    labels[k] = v
            
            # Export buckets
            cumulative = 0
            for bucket in self.buckets:
                cumulative += self._counts[key].get(bucket, 0)
                bucket_labels = {**labels, "le": str(bucket) if bucket != float("inf") else "+Inf"}
                points.append(MetricPoint(f"{self.name}_bucket", cumulative, now, bucket_labels))
            
            # Export sum and count
            points.append(MetricPoint(f"{self.name}_sum", self._sums[key], now, labels))
            points.append(MetricPoint(f"{self.name}_count", self._totals[key], now, labels))
        
        return points


class MetricsRegistry:
    """
    Central registry for all metrics.
    
    Provides simple interface and Prometheus export.
    """
    
    def __init__(self, prefix: str = "continuity"):
        self.prefix = prefix
        self._counters: Dict[str, Counter] = {}
        self._gauges: Dict[str, Gauge] = {}
        self._histograms: Dict[str, Histogram] = {}
        self._lock = Lock()
        
        # Pre-register common metrics
        self._register_common_metrics()
    
    def _register_common_metrics(self) -> None:
        """Register common metrics."""
        # Tick metrics
        self.counter("tick_total", "Total number of ticks executed")
        self.counter("tick_errors_total", "Total tick errors")
        self.histogram("tick_duration_seconds", "Tick execution duration")
        
        # Action metrics
        self.counter("actions_total", "Total actions executed")
        self.counter("actions_success_total", "Successful actions")
        self.counter("actions_failed_total", "Failed actions")
        self.counter("actions_skipped_total", "Skipped actions")
        
        # Adapter metrics
        self.counter("adapter_requests_total", "Total adapter requests")
        self.histogram("adapter_duration_seconds", "Adapter execution duration")
        
        # State metrics
        self.gauge("escalation_stage", "Current escalation stage (0=OK, 5=FULL)")
        self.gauge("time_to_deadline_minutes", "Minutes until deadline")
        self.gauge("retry_queue_size", "Items in retry queue")
        
        # Circuit breaker metrics
        self.gauge("circuit_breaker_state", "Circuit breaker state (0=closed, 1=open, 2=half-open)")
    
    def counter(self, name: str, help_text: str = "") -> Counter:
        """Get or create a counter."""
        full_name = f"{self.prefix}_{name}"
        with self._lock:
            if full_name not in self._counters:
                self._counters[full_name] = Counter(full_name, help_text)
            return self._counters[full_name]
    
    def gauge(self, name: str, help_text: str = "") -> Gauge:
        """Get or create a gauge."""
        full_name = f"{self.prefix}_{name}"
        with self._lock:
            if full_name not in self._gauges:
                self._gauges[full_name] = Gauge(full_name, help_text)
            return self._gauges[full_name]
    
    def histogram(self, name: str, help_text: str = "") -> Histogram:
        """Get or create a histogram."""
        full_name = f"{self.prefix}_{name}"
        with self._lock:
            if full_name not in self._histograms:
                self._histograms[full_name] = Histogram(full_name, help_text)
            return self._histograms[full_name]
    
    # Convenience methods
    def increment(self, name: str, value: float = 1, labels: Optional[Dict[str, str]] = None) -> None:
        """Increment a counter."""
        self.counter(name).inc(value, labels)
    
    def set_gauge(self, name: str, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        """Set a gauge value."""
        self.gauge(name).set(value, labels)
    
    def timing(self, name: str, seconds: float, labels: Optional[Dict[str, str]] = None) -> None:
        """Record a timing."""
        self.histogram(name).observe(seconds, labels)
    
    def export_prometheus(self) -> str:
        """Export metrics in Prometheus text format."""
        lines = []
        
        # Export counters
        for counter in self._counters.values():
            lines.append(f"# HELP {counter.name} {counter.help_text}")
            lines.append(f"# TYPE {counter.name} counter")
            for point in counter.export():
                labels_str = self._format_labels(point.labels)
                lines.append(f"{point.name}{labels_str} {point.value}")
        
        # Export gauges
        for gauge in self._gauges.values():
            lines.append(f"# HELP {gauge.name} {gauge.help_text}")
            lines.append(f"# TYPE {gauge.name} gauge")
            for point in gauge.export():
                labels_str = self._format_labels(point.labels)
                lines.append(f"{point.name}{labels_str} {point.value}")
        
        # Export histograms
        for histogram in self._histograms.values():
            lines.append(f"# HELP {histogram.name} {histogram.help_text}")
            lines.append(f"# TYPE {histogram.name} histogram")
            for point in histogram.export():
                labels_str = self._format_labels(point.labels)
                lines.append(f"{point.name}{labels_str} {point.value}")
        
        return "\n".join(lines)
    
    def export_json(self) -> Dict[str, Any]:
        """Export metrics as JSON."""
        result = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "counters": {},
            "gauges": {},
            "histograms": {},
        }
        
        for name, counter in self._counters.items():
            result["counters"][name] = counter.get()
        
        for name, gauge in self._gauges.items():
            result["gauges"][name] = gauge.get()
        
        for name, histogram in self._histograms.items():
            result["histograms"][name] = {
                "sum": histogram._sums.get("", 0),
                "count": histogram._totals.get("", 0),
            }
        
        return result
    
    def _format_labels(self, labels: Dict[str, str]) -> str:
        """Format labels for Prometheus."""
        if not labels:
            return ""
        pairs = [f'{k}="{v}"' for k, v in sorted(labels.items())]
        return "{" + ",".join(pairs) + "}"


# Global metrics instance
metrics = MetricsRegistry()

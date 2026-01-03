"""Observability metrics for trace compilation.

Provides Prometheus-compatible metrics for monitoring PyAOT performance
and triggering automatic rollback when SLOs are breached.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MetricValue:
    """A single metric value with labels.

    Attributes:
        name: Metric name.
        value: Current value.
        labels: Label key-value pairs.
        timestamp: Last update time.
    """

    name: str
    value: float
    labels: dict[str, str] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class HistogramBucket:
    """Histogram bucket for latency tracking.

    Attributes:
        le: Upper bound (less than or equal).
        count: Number of observations.
    """

    le: float
    count: int = 0


class MetricsCollector:
    """Collects and exposes PyAOT observability metrics.

    Metrics follow the naming convention: py_aot.<subsystem>.<metric>

    Key metrics:
    - py_aot.trace.guard_miss_rate: Guard failures per trace
    - py_aot.trace.deopt_rate: Deopts per second
    - py_aot.trace.compile_latency_ms: Compilation time histogram
    - py_aot.trace.execution_latency_ms: Compiled execution time
    - py_aot.trace.cache_hit_rate: Trace cache hit ratio
    """

    # SLO thresholds (from VISION.md)
    GUARD_MISS_RATE_THRESHOLD = 0.01  # 1%
    DEOPT_RATE_THRESHOLD = 0.001  # 0.1%
    P99_LATENCY_INCREASE_THRESHOLD = 1.05  # 5% increase

    def __init__(self) -> None:
        """Initialize metrics collector."""
        self._lock = threading.Lock()
        self._counters: dict[str, float] = defaultdict(float)
        self._gauges: dict[str, float] = {}
        self._histograms: dict[str, list[HistogramBucket]] = {}
        self._labels: dict[str, dict[str, str]] = {}

        # Default histogram buckets (latency in ms)
        self._latency_buckets = [0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 25.0, 50.0, 100.0]

        # Initialize core metrics
        self._init_metrics()

    def _init_metrics(self) -> None:
        """Initialize default metrics."""
        # Trace counters
        self._counters["py_aot.trace.records_total"] = 0
        self._counters["py_aot.trace.compilations_total"] = 0
        self._counters["py_aot.trace.guard_misses_total"] = 0
        self._counters["py_aot.trace.deopts_total"] = 0
        self._counters["py_aot.trace.cache_hits_total"] = 0
        self._counters["py_aot.trace.cache_misses_total"] = 0

        # Gauges
        self._gauges["py_aot.trace.compiled_routes"] = 0
        self._gauges["py_aot.trace.pending_compilations"] = 0
        self._gauges["py_aot.trace.memory_bytes"] = 0

        # Histograms
        self._init_histogram("py_aot.trace.compile_latency_ms")
        self._init_histogram("py_aot.trace.execution_latency_ms")
        self._init_histogram("py_aot.trace.guard_check_ns")

    def _init_histogram(self, name: str) -> None:
        """Initialize a histogram with default buckets."""
        self._histograms[name] = [
            HistogramBucket(le=b, count=0) for b in self._latency_buckets
        ]
        self._histograms[name].append(HistogramBucket(le=float("inf"), count=0))

    def inc(
        self, name: str, value: float = 1.0, labels: dict[str, str] | None = None
    ) -> None:
        """Increment a counter.

        Args:
            name: Metric name.
            value: Value to add.
            labels: Optional labels.
        """
        with self._lock:
            key = self._make_key(name, labels)
            self._counters[key] += value

    def set_gauge(
        self, name: str, value: float, labels: dict[str, str] | None = None
    ) -> None:
        """Set a gauge value.

        Args:
            name: Metric name.
            value: New value.
            labels: Optional labels.
        """
        with self._lock:
            key = self._make_key(name, labels)
            self._gauges[key] = value

    def observe(
        self, name: str, value: float, labels: dict[str, str] | None = None
    ) -> None:
        """Record a histogram observation.

        Args:
            name: Metric name.
            value: Observed value.
            labels: Optional labels.
        """
        with self._lock:
            if name not in self._histograms:
                self._init_histogram(name)

            for bucket in self._histograms[name]:
                if value <= bucket.le:
                    bucket.count += 1

    def _make_key(self, name: str, labels: dict[str, str] | None) -> str:
        """Create a unique key for metric + labels."""
        if not labels:
            return name
        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"

    def record_trace(self, route_id: str) -> None:
        """Record a trace observation."""
        self.inc("py_aot.trace.records_total", labels={"route": route_id})

    def record_compilation(self, route_id: str, latency_ms: float) -> None:
        """Record a trace compilation."""
        self.inc("py_aot.trace.compilations_total", labels={"route": route_id})
        self.observe("py_aot.trace.compile_latency_ms", latency_ms)

    def record_guard_miss(self, route_id: str, guard_type: str) -> None:
        """Record a guard miss (deopt trigger)."""
        self.inc(
            "py_aot.trace.guard_misses_total",
            labels={"route": route_id, "type": guard_type},
        )

    def record_deopt(self, route_id: str) -> None:
        """Record a deoptimization."""
        self.inc("py_aot.trace.deopts_total", labels={"route": route_id})

    def record_cache_hit(self, route_id: str) -> None:
        """Record a trace cache hit."""
        self.inc("py_aot.trace.cache_hits_total", labels={"route": route_id})

    def record_cache_miss(self, route_id: str) -> None:
        """Record a trace cache miss."""
        self.inc("py_aot.trace.cache_misses_total", labels={"route": route_id})

    def record_execution(self, route_id: str, latency_ms: float) -> None:
        """Record compiled trace execution latency."""
        self.observe(
            "py_aot.trace.execution_latency_ms", latency_ms, labels={"route": route_id}
        )

    def get_guard_miss_rate(self) -> float:
        """Calculate current guard miss rate."""
        with self._lock:
            total = self._counters.get("py_aot.trace.records_total", 0)
            misses = self._counters.get("py_aot.trace.guard_misses_total", 0)
            if total == 0:
                return 0.0
            return misses / total

    def get_deopt_rate(self) -> float:
        """Calculate current deopt rate."""
        with self._lock:
            total = self._counters.get("py_aot.trace.records_total", 0)
            deopts = self._counters.get("py_aot.trace.deopts_total", 0)
            if total == 0:
                return 0.0
            return deopts / total

    def get_cache_hit_rate(self) -> float:
        """Calculate trace cache hit rate."""
        with self._lock:
            hits = self._counters.get("py_aot.trace.cache_hits_total", 0)
            misses = self._counters.get("py_aot.trace.cache_misses_total", 0)
            total = hits + misses
            if total == 0:
                return 0.0
            return hits / total

    def check_slos(self) -> dict[str, bool]:
        """Check if SLOs are being met.

        Returns:
            Dict with SLO name -> pass/fail.
        """
        return {
            "guard_miss_rate": self.get_guard_miss_rate()
            < self.GUARD_MISS_RATE_THRESHOLD,
            "deopt_rate": self.get_deopt_rate() < self.DEOPT_RATE_THRESHOLD,
        }

    def export_prometheus(self) -> str:
        """Export metrics in Prometheus format.

        Returns:
            Prometheus-format metrics string.
        """
        lines = []

        with self._lock:
            # Export counters
            for name, value in self._counters.items():
                lines.append(f"{name} {value}")

            # Export gauges
            for name, value in self._gauges.items():
                lines.append(f"{name} {value}")

            # Export histograms
            for name, buckets in self._histograms.items():
                for bucket in buckets:
                    le_str = "+Inf" if bucket.le == float("inf") else str(bucket.le)
                    lines.append(f'{name}_bucket{{le="{le_str}"}} {bucket.count}')

        return "\n".join(lines)

    def get_summary(self) -> dict[str, Any]:
        """Get metrics summary for debugging.

        Returns:
            Dict with key metrics.
        """
        with self._lock:
            return {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "guard_miss_rate": self.get_guard_miss_rate(),
                "deopt_rate": self.get_deopt_rate(),
                "cache_hit_rate": self.get_cache_hit_rate(),
                "slos": self.check_slos(),
            }

    def reset(self) -> None:
        """Reset all metrics (for testing)."""
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()
            self._init_metrics()


# Global metrics instance
_metrics: MetricsCollector | None = None


def get_metrics() -> MetricsCollector:
    """Get global metrics collector."""
    global _metrics
    if _metrics is None:
        _metrics = MetricsCollector()
    return _metrics


def reset_metrics() -> None:
    """Reset global metrics (for testing)."""
    global _metrics
    if _metrics is not None:
        _metrics.reset()

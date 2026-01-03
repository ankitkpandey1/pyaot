"""Benchmarks for metrics collection.

Measures observability overhead.
"""

from pyaot.web.ops.metrics import MetricsCollector


class TestMetricsBenchmarks:
    """Benchmarks for MetricsCollector performance."""

    def test_counter_inc(self, benchmark) -> None:
        """Benchmark counter increment."""
        metrics = MetricsCollector()

        benchmark(metrics.inc, "py_aot.test.counter")

    def test_counter_inc_with_labels(self, benchmark) -> None:
        """Benchmark counter increment with labels."""
        metrics = MetricsCollector()
        labels = {"route": "test", "method": "GET"}

        benchmark(metrics.inc, "py_aot.test.counter", 1.0, labels)

    def test_gauge_set(self, benchmark) -> None:
        """Benchmark gauge set."""
        metrics = MetricsCollector()

        benchmark(metrics.set_gauge, "py_aot.test.gauge", 42.0)

    def test_histogram_observe(self, benchmark) -> None:
        """Benchmark histogram observation."""
        metrics = MetricsCollector()

        benchmark(metrics.observe, "py_aot.test.latency", 5.5)

    def test_record_trace(self, benchmark) -> None:
        """Benchmark trace recording metric."""
        metrics = MetricsCollector()

        benchmark(metrics.record_trace, "test_route")

    def test_check_slos(self, benchmark) -> None:
        """Benchmark SLO check."""
        metrics = MetricsCollector()

        # Add some data
        for _ in range(100):
            metrics.record_trace("test_route")

        benchmark(metrics.check_slos)

    def test_export_prometheus(self, benchmark) -> None:
        """Benchmark Prometheus export."""
        metrics = MetricsCollector()

        # Add some data
        for i in range(100):
            metrics.record_trace(f"route_{i % 10}")
            metrics.observe("py_aot.trace.execution_latency_ms", i * 0.1)

        benchmark(metrics.export_prometheus)

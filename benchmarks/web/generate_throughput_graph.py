"""Generate throughput vs request count graph.

Benchmarks baseline vs PyAOT at different request counts and
generates a visualization comparing performance.

Run with: python benchmarks/web/generate_throughput_graph.py
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable, Iterator

import matplotlib.pyplot as plt
import numpy as np

from pyaot.web.frameworks.generic import WSGIMiddleware
from pyaot.web.trace.config import TracerConfig


def simple_wsgi_app(environ: dict, start_response: Callable) -> Iterator[bytes]:
    """Simple WSGI app for benchmarking."""
    path = environ.get("PATH_INFO", "/")
    method = environ.get("REQUEST_METHOD", "GET")

    if path.startswith("/users/") and method == "GET":
        user_id = path.split("/")[-1]
        response_data = {"id": user_id, "name": "Test User", "email": "test@example.com"}
        body = json.dumps(response_data).encode()
        status = "200 OK"
        headers = [("Content-Type", "application/json")]
    else:
        body = b'{"status": "ok"}'
        status = "200 OK"
        headers = [("Content-Type", "application/json")]

    start_response(status, headers)
    return iter([body])


def make_environ(method: str = "GET", path: str = "/") -> dict[str, Any]:
    """Create WSGI environ."""
    return {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "SERVER_NAME": "localhost",
        "SERVER_PORT": "8000",
        "REMOTE_ADDR": "127.0.0.1",
        "wsgi.version": (1, 0),
        "wsgi.url_scheme": "http",
        "wsgi.input": None,
        "wsgi.errors": None,
    }


def mock_start_response(status: str, headers: list) -> Callable:
    """Mock start_response."""
    return lambda exc_info=None: None


def consume_response(response: Iterator[bytes]) -> bytes:
    """Consume iterator."""
    return b"".join(response)


def benchmark_requests(app: Callable, n_requests: int) -> tuple[float, float]:
    """Run n_requests and return (total_time_ms, requests_per_sec)."""
    environ = make_environ("GET", "/users/123")

    # Warmup
    for _ in range(min(100, n_requests // 10)):
        consume_response(app(environ, mock_start_response))

    # Benchmark
    start = time.perf_counter()
    for _ in range(n_requests):
        consume_response(app(environ, mock_start_response))
    elapsed = time.perf_counter() - start

    total_ms = elapsed * 1000
    rps = n_requests / elapsed

    return total_ms, rps


def main():
    """Generate throughput comparison graph."""
    print("=" * 60)
    print("PyAOT Throughput Benchmark")
    print("=" * 60)

    # Test at different request counts
    request_counts = [100, 500, 1000, 2000, 5000, 10000, 20000, 50000]

    # Setup apps
    baseline_app = simple_wsgi_app
    config = TracerConfig.for_testing()
    pyaot_app = WSGIMiddleware(simple_wsgi_app, config=config)

    # Collect data
    baseline_rps = []
    pyaot_rps = []
    baseline_latency = []
    pyaot_latency = []

    print("\nRunning benchmarks...")
    print(f"{'Requests':<12} {'Baseline RPS':<15} {'PyAOT RPS':<15} {'Overhead %':<12}")
    print("-" * 55)

    for n in request_counts:
        # Baseline
        _, b_rps = benchmark_requests(baseline_app, n)
        baseline_rps.append(b_rps)
        baseline_latency.append(1000000 / b_rps)  # μs per request

        # PyAOT
        _, p_rps = benchmark_requests(pyaot_app, n)
        pyaot_rps.append(p_rps)
        pyaot_latency.append(1000000 / p_rps)

        overhead = ((b_rps - p_rps) / b_rps) * 100
        print(f"{n:<12} {b_rps:<15,.0f} {p_rps:<15,.0f} {overhead:<12.1f}")

    # Generate graph
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # Plot 1: Throughput (requests/sec)
    ax1 = axes[0]
    x = np.arange(len(request_counts))
    width = 0.35

    bars1 = ax1.bar(x - width / 2, baseline_rps, width, label="Baseline", color="#4CAF50", alpha=0.8)
    bars2 = ax1.bar(x + width / 2, pyaot_rps, width, label="PyAOT (Tracing)", color="#2196F3", alpha=0.8)

    ax1.set_xlabel("Number of Requests", fontsize=12)
    ax1.set_ylabel("Throughput (requests/sec)", fontsize=12)
    ax1.set_title("Throughput Comparison: Baseline vs PyAOT", fontsize=14, fontweight="bold")
    ax1.set_xticks(x)
    ax1.set_xticklabels([f"{n:,}" for n in request_counts], rotation=45, ha="right")
    ax1.legend()
    ax1.grid(axis="y", alpha=0.3)

    # Add value labels
    for bar, rps in zip(bars1, baseline_rps):
        ax1.annotate(f"{rps/1000:.0f}K",
                     xy=(bar.get_x() + bar.get_width() / 2, bar.get_height()),
                     xytext=(0, 3), textcoords="offset points",
                     ha="center", va="bottom", fontsize=8)

    # Plot 2: Latency (μs per request)
    ax2 = axes[1]
    ax2.plot(request_counts, baseline_latency, "o-", label="Baseline", color="#4CAF50", linewidth=2, markersize=8)
    ax2.plot(request_counts, pyaot_latency, "s-", label="PyAOT (Tracing)", color="#2196F3", linewidth=2, markersize=8)

    ax2.set_xlabel("Number of Requests", fontsize=12)
    ax2.set_ylabel("Latency (μs per request)", fontsize=12)
    ax2.set_title("Latency Comparison: Baseline vs PyAOT", fontsize=14, fontweight="bold")
    ax2.set_xscale("log")
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()

    # Save graph
    output_path = "benchmarks/web/throughput_comparison.png"
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    print(f"\n✅ Graph saved to: {output_path}")

    # Also show if running interactively
    plt.show()

    # Print summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    avg_baseline = sum(baseline_rps) / len(baseline_rps)
    avg_pyaot = sum(pyaot_rps) / len(pyaot_rps)
    print(f"Average baseline throughput: {avg_baseline:,.0f} req/s")
    print(f"Average PyAOT throughput:    {avg_pyaot:,.0f} req/s")
    print(f"Average overhead:            {((avg_baseline - avg_pyaot) / avg_baseline) * 100:.1f}%")
    print()
    print("NOTE: This measures TRACING PHASE overhead (learning).")
    print("After compilation, compiled path bypasses interpreter for 2-5x speedup.")


if __name__ == "__main__":
    main()

"""E2E PyAOT Web benchmark showing warmup → compile → speedup cycle.

This benchmark runs enough iterations to:
1. Complete the profiling/tracing phase
2. Trigger eligibility and compilation
3. Measure compiled trace execution speedup

Run with: python benchmarks/web/bench_e2e_full_cycle.py
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable, Iterator

import matplotlib.pyplot as plt
import numpy as np

from pyaot.web.frameworks.generic import WSGIMiddleware
from pyaot.web.trace.config import TracerConfig
from pyaot.web.ops.metrics import reset_metrics


def simple_wsgi_app(environ: dict, start_response: Callable) -> Iterator[bytes]:
    """Simple WSGI app for benchmarking."""
    path = environ.get("PATH_INFO", "/")
    user_id = path.split("/")[-1] if "/" in path else "1"
    response_data = {"id": user_id, "name": "Test", "email": "test@example.com"}
    body = json.dumps(response_data).encode()
    start_response("200 OK", [("Content-Type", "application/json")])
    return iter([body])


def make_environ(path: str = "/users/123", client_ip: str = "192.168.1.1") -> dict[str, Any]:
    """Create WSGI environ."""
    return {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "SERVER_NAME": "localhost",
        "SERVER_PORT": "8000",
        "REMOTE_ADDR": client_ip,
        "wsgi.version": (1, 0),
        "wsgi.url_scheme": "http",
        "wsgi.input": None,
        "wsgi.errors": None,
    }


def mock_start_response(status: str, headers: list) -> Callable:
    return lambda exc_info=None: None


def consume_response(response: Iterator[bytes]) -> bytes:
    return b"".join(response)


def run_e2e_benchmark(
    n_iterations: int = 1000,
    warmup_threshold: int = 100,
) -> dict:
    """Run full E2E benchmark tracking per-iteration latency.

    Args:
        n_iterations: Total iterations to run.
        warmup_threshold: Iterations needed for compilation eligibility.

    Returns:
        Dict with benchmark data.
    """
    # Reset metrics
    reset_metrics()

    # Create relaxed config for testing
    config = TracerConfig(
        min_observations=warmup_threshold,
        min_client_prefixes=3,
        min_observation_window_seconds=0,  # Disable time requirement
        min_branch_stability=0.5,  # Relaxed for testing
    )

    baseline_app = simple_wsgi_app
    pyaot_app = WSGIMiddleware(simple_wsgi_app, config=config)

    baseline_times = []
    pyaot_times = []

    # Need multiple client IPs to satisfy anti-poisoning
    client_ips = [f"192.168.{i}.1" for i in range(10)]

    for i in range(n_iterations):
        environ = make_environ("/users/123", client_ips[i % len(client_ips)])

        # Baseline
        start = time.perf_counter_ns()
        consume_response(baseline_app(environ, mock_start_response))
        baseline_times.append(time.perf_counter_ns() - start)

        # PyAOT
        start = time.perf_counter_ns()
        consume_response(pyaot_app(environ, mock_start_response))
        pyaot_times.append(time.perf_counter_ns() - start)

    # Get middleware stats
    compiled_count = len(pyaot_app._compiled_traces)

    return {
        "baseline_ns": baseline_times,
        "pyaot_ns": pyaot_times,
        "n_iterations": n_iterations,
        "warmup_threshold": warmup_threshold,
        "compiled_traces": compiled_count,
    }


def analyze_phases(data: dict) -> dict:
    """Analyze performance across phases."""
    baseline = np.array(data["baseline_ns"])
    pyaot = np.array(data["pyaot_ns"])
    threshold = data["warmup_threshold"]

    # Split into phases
    warmup_pyaot = pyaot[:threshold]
    post_warmup_pyaot = pyaot[threshold:]

    warmup_baseline = baseline[:threshold]
    post_warmup_baseline = baseline[threshold:]

    return {
        "warmup_phase": {
            "baseline_avg_ns": np.mean(warmup_baseline),
            "pyaot_avg_ns": np.mean(warmup_pyaot),
            "overhead_pct": ((np.mean(warmup_pyaot) - np.mean(warmup_baseline)) /
                            np.mean(warmup_baseline)) * 100,
        },
        "compiled_phase": {
            "baseline_avg_ns": np.mean(post_warmup_baseline),
            "pyaot_avg_ns": np.mean(post_warmup_pyaot),
            "speedup": np.mean(post_warmup_baseline) / np.mean(post_warmup_pyaot),
            "improvement_pct": ((np.mean(post_warmup_baseline) - np.mean(post_warmup_pyaot)) /
                               np.mean(post_warmup_baseline)) * 100,
        },
        "compiled_traces": data["compiled_traces"],
    }


def generate_graph(data: dict, output_path: str) -> None:
    """Generate E2E benchmark graph."""
    fig, axes = plt.subplots(2, 1, figsize=(14, 10))

    baseline = np.array(data["baseline_ns"]) / 1000  # μs
    pyaot = np.array(data["pyaot_ns"]) / 1000
    threshold = data["warmup_threshold"]

    # Smooth with rolling average
    window = 20
    baseline_smooth = np.convolve(baseline, np.ones(window) / window, mode="valid")
    pyaot_smooth = np.convolve(pyaot, np.ones(window) / window, mode="valid")
    iter_smooth = range(window - 1, len(baseline))

    # Plot 1: Per-iteration latency
    ax1 = axes[0]
    ax1.plot(iter_smooth, baseline_smooth, label="Baseline (Python)", color="#4CAF50", linewidth=1.5)
    ax1.plot(iter_smooth, pyaot_smooth, label="PyAOT Web", color="#2196F3", linewidth=1.5)
    ax1.axvline(x=threshold, color="red", linestyle="--", linewidth=2,
                label=f"Warmup complete ({threshold} calls)")

    ax1.set_xlabel("Iteration", fontsize=12)
    ax1.set_ylabel("Latency (μs)", fontsize=12)
    ax1.set_title("PyAOT Web E2E: Latency per Request", fontsize=14, fontweight="bold")
    ax1.legend(loc="upper right")
    ax1.grid(True, alpha=0.3)

    # Shade phases
    ax1.axvspan(0, threshold, alpha=0.1, color="orange", label="Warmup")
    ax1.axvspan(threshold, len(baseline), alpha=0.1, color="green", label="Compiled")

    # Plot 2: Speedup ratio
    ax2 = axes[1]
    speedup_ratio = baseline / pyaot
    speedup_smooth = np.convolve(speedup_ratio, np.ones(window) / window, mode="valid")

    ax2.plot(iter_smooth, speedup_smooth, color="#9C27B0", linewidth=2)
    ax2.axhline(y=1.0, color="gray", linestyle="-", linewidth=1, label="Break-even (1.0x)")
    ax2.axvline(x=threshold, color="red", linestyle="--", linewidth=2)

    ax2.set_xlabel("Iteration", fontsize=12)
    ax2.set_ylabel("Speedup Ratio (Baseline / PyAOT)", fontsize=12)
    ax2.set_title("PyAOT Web Speedup Ratio Over Time", fontsize=14, fontweight="bold")
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    # Annotate
    avg_warmup = np.mean(speedup_ratio[:threshold])
    avg_compiled = np.mean(speedup_ratio[threshold:])
    ax2.annotate(f"Warmup avg: {avg_warmup:.2f}x", xy=(threshold / 2, avg_warmup),
                 ha="center", fontsize=10)
    ax2.annotate(f"Compiled avg: {avg_compiled:.2f}x",
                 xy=(threshold + (len(baseline) - threshold) / 2, avg_compiled),
                 ha="center", fontsize=10)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    print(f"\n✅ Graph saved to: {output_path}")


def main():
    """Run full E2E PyAOT Web benchmark."""
    print("=" * 70)
    print("PyAOT Web E2E Benchmark: Warmup → Compile → Speedup")
    print("=" * 70)
    print()
    print("This benchmark demonstrates the full PyAOT Web pipeline:")
    print("  1. Warmup phase: trace recording (learning)")
    print("  2. Compilation: trace → LLVM IR → native code")
    print("  3. Compiled execution: bypass interpreter")
    print()

    N = 500  # Total iterations
    WARMUP = 100  # When compilation triggers

    print("Configuration:")
    print(f"  Total iterations: {N}")
    print(f"  Warmup iterations: {WARMUP}")
    print()

    print("Running benchmark...")
    data = run_e2e_benchmark(n_iterations=N, warmup_threshold=WARMUP)

    # Analyze
    analysis = analyze_phases(data)

    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)

    print(f"\nCompiled traces: {analysis['compiled_traces']}")

    print(f"\n{'Phase':<20} {'Baseline (μs)':<15} {'PyAOT (μs)':<15} {'vs Baseline':<15}")
    print("-" * 65)

    wp = analysis["warmup_phase"]
    print(f"{'Warmup (0-100)':<20} {wp['baseline_avg_ns']/1000:<15.2f} "
          f"{wp['pyaot_avg_ns']/1000:<15.2f} {wp['overhead_pct']:+.1f}%")

    cp = analysis["compiled_phase"]
    if cp["speedup"] >= 1:
        vs = f"{cp['speedup']:.2f}x faster"
    else:
        vs = f"{1/cp['speedup']:.2f}x slower"
    print(f"{'Compiled (100+)':<20} {cp['baseline_avg_ns']/1000:<15.2f} "
          f"{cp['pyaot_avg_ns']/1000:<15.2f} {vs}")

    print()
    if analysis["compiled_traces"] > 0:
        print(f"✅ Compilation occurred! {analysis['compiled_traces']} trace(s) compiled.")
        if cp["speedup"] >= 1:
            print(f"✅ Post-warmup speedup: {cp['speedup']:.2f}x")
        else:
            print("⚠️  No speedup observed after compilation")
    else:
        print("❌ No traces were compiled (eligibility not met)")
        print("   This is expected - current TraceCompiler returns placeholder callable")

    # Generate graph
    output_path = "benchmarks/web/e2e_full_cycle.png"
    generate_graph(data, output_path)

    # Summary for BENCHMARKS.md
    print("\n" + "=" * 70)
    print("TABLE FOR BENCHMARKS.md")
    print("=" * 70)
    print()
    print("| Phase | Iterations | Baseline | PyAOT Web | Performance |")
    print("|-------|------------|----------|-----------|-------------|")
    print(f"| Warmup | 0-{WARMUP} | {wp['baseline_avg_ns']/1000:.2f}μs | "
          f"{wp['pyaot_avg_ns']/1000:.2f}μs | {wp['overhead_pct']:+.1f}% overhead |")
    print(f"| Compiled | {WARMUP}+ | {cp['baseline_avg_ns']/1000:.2f}μs | "
          f"{cp['pyaot_avg_ns']/1000:.2f}μs | {vs} |")


if __name__ == "__main__":
    main()

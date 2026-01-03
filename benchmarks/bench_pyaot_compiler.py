"""Benchmark for PyAOT core compiler: Python vs @optimize decorator.

This measures the ACTUAL PyAOT optimization - compiling Python
functions to native code using the @optimize decorator.

Run with: python benchmarks/bench_pyaot_compiler.py
"""

from __future__ import annotations

import time
import statistics
from typing import List, Any

# Import PyAOT's actual optimization infrastructure
from pyaot.pipeline import optimize, OptimizedFunction, sum_attrs_optimized


# =============================================================================
# Test Functions - Baseline (Pure Python)
# =============================================================================


def compute_sum_baseline(n: int) -> int:
    """Pure Python sum computation."""
    total = 0
    for i in range(n):
        total += i
    return total


def dot_product_baseline(a: List[float], b: List[float]) -> float:
    """Pure Python dot product."""
    result = 0.0
    for i in range(len(a)):
        result += a[i] * b[i]
    return result


def matrix_trace_baseline(matrix: List[List[float]]) -> float:
    """Pure Python matrix trace (sum of diagonal)."""
    total = 0.0
    for i in range(len(matrix)):
        total += matrix[i][i]
    return total


# =============================================================================
# Test Functions - PyAOT Optimized
# =============================================================================


@optimize(profile_calls=10, stability_threshold=0.9)
def compute_sum_optimized(n: int) -> int:
    """PyAOT optimized sum computation."""
    total = 0
    for i in range(n):
        total += i
    return total


@optimize(profile_calls=10, stability_threshold=0.9)
def dot_product_optimized(a: List[float], b: List[float]) -> float:
    """PyAOT optimized dot product."""
    result = 0.0
    for i in range(len(a)):
        result += a[i] * b[i]
    return result


@optimize(profile_calls=10, stability_threshold=0.9)
def matrix_trace_optimized(matrix: List[List[float]]) -> float:
    """PyAOT optimized matrix trace."""
    total = 0.0
    for i in range(len(matrix)):
        total += matrix[i][i]
    return total


# =============================================================================
# Benchmark Runner
# =============================================================================


def benchmark_function(
    func,
    args: tuple,
    n_iterations: int = 1000,
    warmup: int = 100,
) -> dict:
    """Benchmark a single function.

    Args:
        func: Function to benchmark.
        args: Arguments to pass.
        n_iterations: Number of iterations.
        warmup: Warmup iterations.

    Returns:
        Dict with timing statistics.
    """
    # Warmup
    for _ in range(warmup):
        func(*args)

    # Timed runs
    times = []
    for _ in range(n_iterations):
        start = time.perf_counter_ns()
        func(*args)
        elapsed = time.perf_counter_ns() - start
        times.append(elapsed)

    return {
        "min_ns": min(times),
        "max_ns": max(times),
        "mean_ns": statistics.mean(times),
        "median_ns": statistics.median(times),
        "stdev_ns": statistics.stdev(times) if len(times) > 1 else 0,
        "total_ms": sum(times) / 1_000_000,
        "ops_per_sec": 1_000_000_000 / statistics.mean(times),
    }


def print_comparison(name: str, baseline: dict, optimized: dict) -> None:
    """Print benchmark comparison."""
    speedup = baseline["mean_ns"] / optimized["mean_ns"]
    improvement = ((baseline["mean_ns"] - optimized["mean_ns"]) / baseline["mean_ns"]) * 100

    print(f"\n{name}")
    print("=" * 60)
    print(f"{'Metric':<20} {'Baseline':<20} {'PyAOT':<20}")
    print("-" * 60)
    print(f"{'Mean (ns)':<20} {baseline['mean_ns']:<20,.0f} {optimized['mean_ns']:<20,.0f}")
    print(f"{'Median (ns)':<20} {baseline['median_ns']:<20,.0f} {optimized['median_ns']:<20,.0f}")
    print(f"{'Min (ns)':<20} {baseline['min_ns']:<20,.0f} {optimized['min_ns']:<20,.0f}")
    print(f"{'Ops/sec':<20} {baseline['ops_per_sec']:<20,.0f} {optimized['ops_per_sec']:<20,.0f}")
    print("-" * 60)

    if speedup >= 1:
        print(f"Speedup: {speedup:.2f}x FASTER")
    else:
        print(f"Slowdown: {1/speedup:.2f}x SLOWER")

    print(f"Improvement: {improvement:+.1f}%")


def main():
    """Run PyAOT compiler benchmarks."""
    print("=" * 70)
    print("PyAOT Core Compiler Benchmark: Python vs @optimize")
    print("=" * 70)
    print()
    print("This benchmark compares:")
    print("  - Baseline: Pure Python function execution")
    print("  - PyAOT: @optimize decorated function (profile → compile → native)")
    print()

    # Test 1: Simple sum
    n = 1000
    print(f"\n[1] compute_sum(n={n})")

    baseline1 = benchmark_function(compute_sum_baseline, (n,))
    optimized1 = benchmark_function(compute_sum_optimized, (n,))
    print_comparison("Sum Computation", baseline1, optimized1)

    # Get stats from optimized function
    if hasattr(compute_sum_optimized, "get_stats"):
        stats = compute_sum_optimized.get_stats()
        print(f"\nPyAOT Stats: compiled={stats.is_compiled}, "
              f"native_ratio={stats.native_ratio:.1%}")

    # Test 2: Dot product
    size = 100
    a = [float(i) for i in range(size)]
    b = [float(i * 2) for i in range(size)]
    print(f"\n[2] dot_product(size={size})")

    baseline2 = benchmark_function(dot_product_baseline, (a, b))
    optimized2 = benchmark_function(dot_product_optimized, (a, b))
    print_comparison("Dot Product", baseline2, optimized2)

    if hasattr(dot_product_optimized, "get_stats"):
        stats = dot_product_optimized.get_stats()
        print(f"\nPyAOT Stats: compiled={stats.is_compiled}, "
              f"native_ratio={stats.native_ratio:.1%}")

    # Test 3: Matrix trace
    size = 50
    matrix = [[float(i + j) for j in range(size)] for i in range(size)]
    print(f"\n[3] matrix_trace(size={size}x{size})")

    baseline3 = benchmark_function(matrix_trace_baseline, (matrix,))
    optimized3 = benchmark_function(matrix_trace_optimized, (matrix,))
    print_comparison("Matrix Trace", baseline3, optimized3)

    if hasattr(matrix_trace_optimized, "get_stats"):
        stats = matrix_trace_optimized.get_stats()
        print(f"\nPyAOT Stats: compiled={stats.is_compiled}, "
              f"native_ratio={stats.native_ratio:.1%}")

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    all_speedups = [
        baseline1["mean_ns"] / optimized1["mean_ns"],
        baseline2["mean_ns"] / optimized2["mean_ns"],
        baseline3["mean_ns"] / optimized3["mean_ns"],
    ]

    avg_speedup = statistics.mean(all_speedups)

    print(f"\nAverage Speedup: {avg_speedup:.2f}x")

    if avg_speedup >= 1:
        print(f"PyAOT is {avg_speedup:.2f}x FASTER on average")
    else:
        print(f"PyAOT is {1/avg_speedup:.2f}x SLOWER on average")

    print("\nNote: PyAOT uses type profiling + guard-based compilation.")
    print("First N calls are profiling; subsequent calls use optimized path.")


if __name__ == "__main__":
    main()

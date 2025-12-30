#!/usr/bin/env python3
"""
Frame Elision Benchmarks.

Isolates call overhead to measure the impact of callsite stubs.

Benchmarks:
1. Call overhead isolation - leaf function in loop
2. Nested numeric calls - h→g→f chain
3. Guard failure cost - 1% wrong type
"""

from __future__ import annotations

import time
import statistics
from typing import Callable, List, Tuple


# =============================================================================
# Benchmark 1: Call Overhead Isolation
# =============================================================================

def leaf(a: float, b: float) -> float:
    """Leaf function - minimal work."""
    return a + b


def caller_python(n: int) -> float:
    """Python caller - measures call overhead."""
    s = 0.0
    for _ in range(n):
        s += leaf(1.0, 2.0)
    return s


# =============================================================================
# Benchmark 2: Nested Numeric Calls
# =============================================================================

def f(x: float) -> float:
    return x * 2.0


def g(x: float) -> float:
    return f(x) + 1.0


def h(x: float) -> float:
    return g(x) * 3.0


def nested_caller_python(n: int) -> float:
    """Call h→g→f chain n times."""
    s = 0.0
    for i in range(n):
        s += h(float(i))
    return s


# =============================================================================
# Benchmark 3: Guard Failure Cost
# =============================================================================

def guarded_leaf(a, b):
    """Version that accepts any type."""
    return a + b


def caller_with_failures(n: int, failure_rate: float = 0.01) -> float:
    """Caller that introduces type failures."""
    s = 0.0
    failure_threshold = int(n * failure_rate)
    
    for i in range(n):
        if i < failure_threshold:
            # Wrong type - should trigger fallback (still produces numeric-ish result)
            s += float(len(guarded_leaf("1", "2")))  # "12" -> 2
        else:
            s += guarded_leaf(1.0, 2.0)
    
    return s


# =============================================================================
# Benchmark Runner
# =============================================================================

def time_function(func: Callable, *args, iterations: int = 10) -> Tuple[float, float]:
    """
    Time a function call.
    
    Returns:
        (mean_time_us, std_dev_us)
    """
    times = []
    
    for _ in range(iterations):
        start = time.perf_counter_ns()
        func(*args)
        end = time.perf_counter_ns()
        times.append((end - start) / 1000)  # microseconds
    
    return statistics.mean(times), statistics.stdev(times) if len(times) > 1 else 0


def run_benchmarks():
    """Run all frame elision benchmarks."""
    print("=" * 70)
    print("FRAME ELISION BENCHMARKS")
    print("=" * 70)
    print()
    
    n = 10000
    
    # Benchmark 1: Call overhead
    print("1. CALL OVERHEAD ISOLATION")
    print("-" * 50)
    mean, std = time_function(caller_python, n)
    per_call_ns = (mean * 1000) / n
    print(f"   Python caller({n})")
    print(f"   Total: {mean:.2f} ± {std:.2f} μs")
    print(f"   Per call: {per_call_ns:.1f} ns")
    print()
    
    # Benchmark 2: Nested calls
    print("2. NESTED NUMERIC CALLS (h→g→f)")
    print("-" * 50)
    mean, std = time_function(nested_caller_python, n)
    per_call_ns = (mean * 1000) / n
    print(f"   nested_caller({n})")
    print(f"   Total: {mean:.2f} ± {std:.2f} μs")
    print(f"   Per call: {per_call_ns:.1f} ns")
    print()
    
    # Benchmark 3: Guard failures
    print("3. GUARD FAILURE COST (1% wrong type)")
    print("-" * 50)
    
    # 0% failure
    mean_0, std_0 = time_function(caller_with_failures, n, 0.0)
    print(f"   0% failures: {mean_0:.2f} ± {std_0:.2f} μs")
    
    # 1% failure
    mean_1, std_1 = time_function(caller_with_failures, n, 0.01)
    print(f"   1% failures: {mean_1:.2f} ± {std_1:.2f} μs")
    
    # 10% failure
    mean_10, std_10 = time_function(caller_with_failures, n, 0.10)
    print(f"   10% failures: {mean_10:.2f} ± {std_10:.2f} μs")
    
    overhead_1 = ((mean_1 - mean_0) / mean_0) * 100 if mean_0 > 0 else 0
    overhead_10 = ((mean_10 - mean_0) / mean_0) * 100 if mean_0 > 0 else 0
    print(f"   Overhead 1%: {overhead_1:.1f}%")
    print(f"   Overhead 10%: {overhead_10:.1f}%")
    print()
    
    print("=" * 70)
    print("BASELINE COMPLETE")
    print("=" * 70)
    print()
    print("Next: Compare with PyAOT callsite stubs")


if __name__ == "__main__":
    run_benchmarks()

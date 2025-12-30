#!/usr/bin/env python3
"""
Stub Performance Benchmark.

Compares:
1. Pure Python calls
2. Stub with fallback (guards pass, no native)
3. Stub with native (guards pass, native available)
"""

from __future__ import annotations

import time
import statistics
from typing import Callable, Tuple


# =============================================================================
# Test Functions
# =============================================================================

def leaf_add(a: float, b: float) -> float:
    """Simple leaf function."""
    return a + b


def leaf_mul(x: float) -> float:
    """Multiply by 2."""
    return x * 2.0


# =============================================================================
# Benchmark Harness
# =============================================================================

def time_calls(func: Callable, n: int, *args) -> Tuple[float, float]:
    """
    Time n calls to func.
    
    Returns:
        (total_us, per_call_ns)
    """
    times = []
    
    for _ in range(10):  # 10 iterations
        start = time.perf_counter_ns()
        for _ in range(n):
            func(*args)
        end = time.perf_counter_ns()
        times.append((end - start) / 1000)  # microseconds
    
    mean = statistics.mean(times)
    per_call = (mean * 1000) / n  # nanoseconds
    
    return mean, per_call


def run_stub_benchmark():
    """Run benchmark comparing Python vs Stub execution."""
    print("=" * 70)
    print("CALLSITE STUB PERFORMANCE BENCHMARK")
    print("=" * 70)
    print()
    
    n = 100000
    
    # 1. Pure Python
    print("1. PURE PYTHON CALLS")
    print("-" * 50)
    total, per_call = time_calls(leaf_add, n, 1.0, 2.0)
    print(f"   leaf_add x {n:,}")
    print(f"   Total: {total:.2f} μs")
    print(f"   Per call: {per_call:.1f} ns")
    baseline_ns = per_call
    print()
    
    # 2. Stub with fallback
    print("2. STUB WITH FALLBACK")
    print("-" * 50)
    
    from pyaot.callsite.stub import create_stub
    
    stub = create_stub(
        callsite_id="bench:leaf_add:0",
        callee=leaf_add,
        arg_types=(float, float),
        native_callable=None,  # No native - will use fallback
    )
    
    total, per_call = time_calls(stub.execute, n, 1.0, 2.0)
    print(f"   stub.execute x {n:,}")
    print(f"   Total: {total:.2f} μs")
    print(f"   Per call: {per_call:.1f} ns")
    print(f"   Overhead vs Python: {per_call - baseline_ns:.1f} ns ({((per_call/baseline_ns)-1)*100:.1f}%)")
    print(f"   Stats: native={stub.native_calls}, fallback={stub.fallback_calls}")
    print()
    
    # 3. Stub with native (simulated - uses Python for now)
    print("3. STUB WITH NATIVE (SIMULATED)")
    print("-" * 50)
    
    # Create a "native" version (just uses the same function for now)
    native_stub = create_stub(
        callsite_id="bench:leaf_add:1",
        callee=leaf_add,
        arg_types=(float, float),
        native_callable=leaf_add,  # Use same function as "native"
    )
    
    total, per_call = time_calls(native_stub.execute, n, 1.0, 2.0)
    print(f"   native_stub.execute x {n:,}")
    print(f"   Total: {total:.2f} μs")
    print(f"   Per call: {per_call:.1f} ns")
    print(f"   Stats: native={native_stub.native_calls}, fallback={native_stub.fallback_calls}")
    print()
    
    # 4. Summary
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print()
    print("The stub infrastructure adds guard checking overhead.")
    print("Real gains come from native code that eliminates Python frames,")
    print("which requires LLVM compilation of the callee.")
    print()
    print("Next: Integrate with LLVM codegen for actual native execution.")


if __name__ == "__main__":
    run_stub_benchmark()

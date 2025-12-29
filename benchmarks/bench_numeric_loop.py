"""
Numeric loop benchmark for PyAOT.

Tests the core use case: speeding up numeric computations.

Target: ≥2× speedup on eligible CPU-bound kernels.
"""

import time
import statistics
from typing import List, Callable, Tuple


def sum_array_python(arr) -> float:
    """Pure Python sum implementation."""
    total = 0.0
    for x in arr:
        total += x
    return total


def dot_product_python(a, b) -> float:
    """Pure Python dot product."""
    total = 0.0
    for x, y in zip(a, b):
        total += x * y
    return total


def matrix_vector_python(matrix, vector) -> list:
    """Pure Python matrix-vector multiplication."""
    result = []
    for row in matrix:
        total = 0.0
        for x, y in zip(row, vector):
            total += x * y
        result.append(total)
    return result


def benchmark_function(
    func: Callable,
    args: tuple,
    warmup: int = 3,
    iterations: int = 10,
) -> Tuple[float, float, float]:
    """Benchmark a function.
    
    Returns:
        Tuple of (mean_ms, min_ms, max_ms).
    """
    # Warmup
    for _ in range(warmup):
        func(*args)
    
    # Benchmark
    times = []
    for _ in range(iterations):
        start = time.perf_counter_ns()
        func(*args)
        elapsed = (time.perf_counter_ns() - start) / 1_000_000  # ms
        times.append(elapsed)
    
    return (
        statistics.mean(times),
        min(times),
        max(times),
    )


def run_benchmarks():
    """Run all numeric benchmarks."""
    try:
        import numpy as np
        HAS_NUMPY = True
    except ImportError:
        HAS_NUMPY = False
        print("NumPy not available, using pure Python lists")
    
    print("=" * 60)
    print("PyAOT Numeric Loop Benchmarks")
    print("=" * 60)
    print()
    
    # Test sizes
    sizes = [1_000, 10_000, 100_000, 1_000_000]
    
    for size in sizes:
        print(f"\n--- Size: {size:,} elements ---\n")
        
        # Create test data
        if HAS_NUMPY:
            arr = np.random.random(size)
            arr_list = arr.tolist()
        else:
            import random
            arr_list = [random.random() for _ in range(size)]
            arr = arr_list
        
        # Benchmark sum_array
        mean, min_t, max_t = benchmark_function(sum_array_python, (arr_list,))
        print(f"sum_array (Python): {mean:.3f} ms (min={min_t:.3f}, max={max_t:.3f})")
        
        if HAS_NUMPY:
            mean_np, min_np, max_np = benchmark_function(np.sum, (arr,))
            print(f"sum_array (NumPy):  {mean_np:.3f} ms (min={min_np:.3f}, max={max_np:.3f})")
            speedup = mean / mean_np
            print(f"NumPy speedup: {speedup:.1f}×")
        
        # Dot product (for smaller sizes)
        if size <= 100_000:
            if HAS_NUMPY:
                arr2 = np.random.random(size)
                arr2_list = arr2.tolist()
            else:
                arr2_list = [random.random() for _ in range(size)]
                arr2 = arr2_list
            
            mean, _, _ = benchmark_function(dot_product_python, (arr_list, arr2_list))
            print(f"dot_product (Python): {mean:.3f} ms")
            
            if HAS_NUMPY:
                mean_np, _, _ = benchmark_function(np.dot, (arr, arr2))
                print(f"dot_product (NumPy):  {mean_np:.3f} ms")
                speedup = mean / mean_np
                print(f"NumPy speedup: {speedup:.1f}×")
    
    print()
    print("=" * 60)
    print("Benchmark complete")
    print("=" * 60)


if __name__ == "__main__":
    run_benchmarks()

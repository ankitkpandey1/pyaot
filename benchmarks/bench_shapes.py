"""
Benchmark for shape-guarded attribute access.

This benchmark compares:
1. Baseline Python attribute access (p.x, p.y)
2. PyAOT shape-guarded fast attribute access

Target outcomes (per Phase 2 specification):
- 2.5-4× reduction in attribute access overhead
- ~3× overall loop speedup without compilation
"""

import time
import statistics
from typing import List, Tuple, Callable, Any


class Point:
    """Simple class for benchmarking attribute access."""
    
    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y


class Point3D:
    """3D point for more attributes."""
    
    def __init__(self, x: float, y: float, z: float):
        self.x = x
        self.y = y
        self.z = z


# =============================================================================
# Baseline implementations (standard Python)
# =============================================================================

def sum_points_baseline(points: List[Point]) -> float:
    """Baseline: Standard Python attribute access."""
    total = 0.0
    for p in points:
        total += p.x + p.y
    return total


def sum_points_getattr(points: List[Point]) -> float:
    """Using explicit getattr (slower)."""
    total = 0.0
    for p in points:
        total += getattr(p, 'x') + getattr(p, 'y')
    return total


def sum_points_dict_direct(points: List[Point]) -> float:
    """Direct __dict__ access (no guards)."""
    total = 0.0
    for p in points:
        d = p.__dict__
        total += d['x'] + d['y']
    return total


# =============================================================================
# PyAOT fast path implementations
# =============================================================================

def sum_points_pyaot_guarded(points: List[Point], expected_type: type) -> float:
    """PyAOT: Shape-guarded attribute access."""
    from pyaot.shapes.fast_attr import guarded_attr_access
    
    total = 0.0
    for p in points:
        total += guarded_attr_access(p, 'x', expected_type)
        total += guarded_attr_access(p, 'y', expected_type)
    return total


def sum_points_pyaot_fast_only(points: List[Point], expected_type: type) -> float:
    """PyAOT: Fast path only (assumes guards pass)."""
    from pyaot.shapes.fast_attr import fast_getattr_guarded, GuardFailedError
    
    total = 0.0
    for p in points:
        try:
            total += fast_getattr_guarded(p, 'x', expected_type)
            total += fast_getattr_guarded(p, 'y', expected_type)
        except (GuardFailedError, AttributeError):
            # Fallback on failure
            total += p.x + p.y
    return total


# =============================================================================
# Benchmarking utilities
# =============================================================================

def benchmark_function(
    func: Callable,
    args: tuple,
    warmup: int = 5,
    iterations: int = 20,
) -> Tuple[float, float, float, float]:
    """
    Benchmark a function.
    
    Returns:
        Tuple of (mean_ms, std_ms, min_ms, max_ms).
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
        statistics.stdev(times) if len(times) > 1 else 0.0,
        min(times),
        max(times),
    )


def print_result(name: str, mean: float, std: float, min_t: float, max_t: float):
    """Print benchmark result."""
    print(f"  {name:40s} {mean:8.3f} ± {std:6.3f} ms  (min={min_t:.3f}, max={max_t:.3f})")


def train_shape_tracker(points: List[Point], sample_size: int = 1000) -> None:
    """Train the shape tracker with sample objects."""
    from pyaot.shapes.tracker import get_global_tracker
    
    tracker = get_global_tracker()
    for p in points[:sample_size]:
        tracker.observe_object(p)


# =============================================================================
# Main benchmark suite
# =============================================================================

def benchmark_attribute_access():
    """Benchmark attribute access patterns."""
    print("=" * 70)
    print("PyAOT Phase 2: Shape-Guarded Attribute Access Benchmark")
    print("=" * 70)
    print()
    
    # Test sizes
    sizes = [10_000, 50_000, 100_000]
    
    for size in sizes:
        print(f"\n{'─' * 70}")
        print(f"  Size: {size:,} Point objects")
        print(f"{'─' * 70}\n")
        
        # Create test data
        points = [Point(float(i), float(i + 1)) for i in range(size)]
        
        # Train shape tracker
        print("  Training shape tracker...")
        train_shape_tracker(points)
        
        # Verify correctness
        baseline_result = sum_points_baseline(points)
        pyaot_result = sum_points_pyaot_guarded(points, Point)
        assert abs(baseline_result - pyaot_result) < 1e-6, "Results differ!"
        print(f"  Correctness verified: sum = {baseline_result:,.1f}\n")
        
        # Run benchmarks
        print("  Benchmarks:")
        
        # Baseline (p.x, p.y)
        mean, std, min_t, max_t = benchmark_function(
            sum_points_baseline, (points,)
        )
        print_result("Baseline (p.x, p.y)", mean, std, min_t, max_t)
        baseline_mean = mean
        
        # getattr()
        mean, std, min_t, max_t = benchmark_function(
            sum_points_getattr, (points,)
        )
        print_result("getattr(p, 'x')", mean, std, min_t, max_t)
        
        # Direct __dict__ (no guards)
        mean, std, min_t, max_t = benchmark_function(
            sum_points_dict_direct, (points,)
        )
        print_result("p.__dict__['x'] (no guards)", mean, std, min_t, max_t)
        dict_mean = mean
        
        # PyAOT guarded (with fallback)
        mean, std, min_t, max_t = benchmark_function(
            sum_points_pyaot_guarded, (points, Point)
        )
        print_result("PyAOT guarded_attr_access", mean, std, min_t, max_t)
        pyaot_mean = mean
        
        # PyAOT fast only
        mean, std, min_t, max_t = benchmark_function(
            sum_points_pyaot_fast_only, (points, Point)
        )
        print_result("PyAOT fast_getattr_guarded", mean, std, min_t, max_t)
        
        # Calculate speedups
        print()
        print(f"  Speedup vs baseline: {baseline_mean / pyaot_mean:.2f}×")
        print(f"  Speedup vs getattr:  (see above)")
        print(f"  Dict direct vs baseline: {baseline_mean / dict_mean:.2f}×")
    
    print()
    print("=" * 70)
    print("Benchmark complete")
    print("=" * 70)


def benchmark_individual_access():
    """Micro-benchmark individual attribute access."""
    print()
    print("=" * 70)
    print("Micro-benchmark: Individual Attribute Access")
    print("=" * 70)
    print()
    
    # Create single object
    p = Point(1.0, 2.0)
    
    # Train tracker
    from pyaot.shapes.tracker import get_global_tracker
    tracker = get_global_tracker()
    for _ in range(100):
        tracker.observe_object(p)
    
    N = 1_000_000
    
    # Baseline
    start = time.perf_counter_ns()
    for _ in range(N):
        x = p.x
    elapsed = (time.perf_counter_ns() - start) / 1_000_000
    print(f"  p.x ({N:,} times):                    {elapsed:.3f} ms")
    baseline_per_access = elapsed / N * 1_000_000  # ns
    
    # getattr
    start = time.perf_counter_ns()
    for _ in range(N):
        x = getattr(p, 'x')
    elapsed = (time.perf_counter_ns() - start) / 1_000_000
    print(f"  getattr(p, 'x') ({N:,} times):       {elapsed:.3f} ms")
    
    # __dict__
    start = time.perf_counter_ns()
    for _ in range(N):
        x = p.__dict__['x']
    elapsed = (time.perf_counter_ns() - start) / 1_000_000
    print(f"  p.__dict__['x'] ({N:,} times):       {elapsed:.3f} ms")
    
    # PyAOT guarded
    from pyaot.shapes.fast_attr import guarded_attr_access
    start = time.perf_counter_ns()
    for _ in range(N):
        x = guarded_attr_access(p, 'x', Point)
    elapsed = (time.perf_counter_ns() - start) / 1_000_000
    print(f"  guarded_attr_access ({N:,} times):   {elapsed:.3f} ms")
    pyaot_per_access = elapsed / N * 1_000_000  # ns
    
    print()
    print(f"  Per-access overhead:")
    print(f"    Baseline:     {baseline_per_access:.1f} ns")
    print(f"    PyAOT:        {pyaot_per_access:.1f} ns")
    print(f"    Ratio:        {pyaot_per_access / baseline_per_access:.2f}×")
    print()


def check_c_extension():
    """Report C extension status."""
    from pyaot.shapes.fast_attr import has_c_extension
    print()
    if has_c_extension():
        print("✓ C extension is available (using optimized path)")
    else:
        print("✗ C extension not available (using pure Python fallback)")
    print()


if __name__ == "__main__":
    check_c_extension()
    benchmark_attribute_access()
    benchmark_individual_access()

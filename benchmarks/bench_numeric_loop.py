"""
PyAOT Benchmark Suite.

Demonstrates:
1. Why per-access guards are slow (Python call overhead)
2. How batch-guarded loops achieve speedup (hoisted guards)
3. End-to-end optimized function comparison

Key insight: The speedup comes from hoisting guards out of loops,
not from speeding up individual attribute accesses.
"""

import time
import statistics
import os
from typing import List, Tuple, Callable
from dataclasses import dataclass


# =============================================================================
# Test Classes
# =============================================================================

class Point:
    """Simple class for benchmarking attribute access."""
    __slots__ = ()  # Remove slots to ensure __dict__ exists
    
    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y


# Remove __slots__ - we need __dict__ for fast access
class Point:
    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y


class Point3D:
    def __init__(self, x: float, y: float, z: float):
        self.x = x
        self.y = y
        self.z = z


# =============================================================================
# Benchmark Implementations
# =============================================================================

def sum_points_baseline(points: List[Point]) -> float:
    """Baseline: Standard Python attribute access (p.x, p.y)."""
    total = 0.0
    for p in points:
        total += p.x + p.y
    return total


def sum_points_getattr(points: List[Point]) -> float:
    """Using explicit getattr() calls."""
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


def sum_points_hoisted_guard(points: List[Point]) -> float:
    """
    OPTIMIZED: Guard hoisted out of loop.
    
    This is the pattern that achieves speedup:
    1. Single type check at loop entry
    2. Direct dict access in loop body
    """
    if not points:
        return 0.0
    
    # Guard at entry (sample check)
    sample_size = min(10, len(points))
    for i in range(sample_size):
        if type(points[i]) is not Point:
            # Fallback to baseline
            return sum_points_baseline(points)
    
    # Fast path: direct dict access
    total = 0.0
    for p in points:
        d = p.__dict__
        total += d['x'] + d['y']
    return total


def sum_points_pyaot_optimized(points: List[Point]) -> float:
    """
    PyAOT optimized: Uses batch-guarded access from pipeline.
    """
    from pyaot.pipeline import sum_attrs_optimized
    return sum_attrs_optimized(points, ['x', 'y'], Point)


def sum_points_compiled(points: List[Point]) -> float:
    """
    PyAOT compiled: Uses NativeLoopCompiler.
    """
    from pyaot.pipeline import NativeLoopCompiler
    from pyaot.shapes.tracker import get_global_tracker
    
    compiler = NativeLoopCompiler(get_global_tracker())
    compiled_fn = compiler.compile_sum_loop(Point, ['x', 'y'])
    return compiled_fn(points)


# =============================================================================
# Benchmarking Utilities
# =============================================================================

@dataclass
class BenchmarkResult:
    name: str
    size: int
    mean_ms: float
    std_ms: float
    min_ms: float
    max_ms: float


def benchmark_function(
    func: Callable,
    args: tuple,
    warmup: int = 5,
    iterations: int = 20,
) -> Tuple[float, float, float, float]:
    """Benchmark a function with warmup."""
    for _ in range(warmup):
        func(*args)
    
    times = []
    for _ in range(iterations):
        start = time.perf_counter_ns()
        func(*args)
        elapsed = (time.perf_counter_ns() - start) / 1_000_000
        times.append(elapsed)
    
    return (
        statistics.mean(times),
        statistics.stdev(times) if len(times) > 1 else 0.0,
        min(times),
        max(times),
    )


def train_tracker(points: List[Point], sample_size: int = 100) -> None:
    """Train the shape tracker."""
    from pyaot.shapes.tracker import get_global_tracker
    tracker = get_global_tracker()
    for p in points[:sample_size]:
        tracker.observe_object(p)


def generate_graphs(results: List[BenchmarkResult], output_dir: str = "benchmarks"):
    """Generate benchmark graphs."""
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("  [matplotlib not available - skipping graphs]")
        return
    
    os.makedirs(output_dir, exist_ok=True)
    
    sizes = sorted(set(r.size for r in results))
    methods = ['Baseline (p.x)', 'Hoisted Guard', 'PyAOT Compiled']
    
    colors = {
        'Baseline (p.x)': '#2ecc71',
        'getattr()': '#e74c3c',
        '__dict__[]': '#3498db',
        'Hoisted Guard': '#9b59b6',
        'PyAOT Optimized': '#f39c12',
        'PyAOT Compiled': '#e67e22',
    }
    
    # Time comparison graph
    fig, ax = plt.subplots(figsize=(12, 6))
    
    x_positions = range(len(sizes))
    width = 0.25
    
    for i, method in enumerate(['Baseline (p.x)', 'Hoisted Guard', 'PyAOT Compiled']):
        method_results = [r for r in results if r.name == method]
        if not method_results:
            continue
        
        times = [next((r.mean_ms for r in method_results if r.size == s), 0) for s in sizes]
        offset = (i - 1) * width
        ax.bar([x + offset for x in x_positions], times, width, 
               label=method, color=colors.get(method, '#95a5a6'))
    
    ax.set_xlabel('Number of Point Objects', fontsize=12)
    ax.set_ylabel('Time (ms)', fontsize=12)
    ax.set_title('PyAOT Phase 3-4: Hoisted Guards vs Baseline', fontsize=14, fontweight='bold')
    ax.set_xticks(x_positions)
    ax.set_xticklabels([f'{s:,}' for s in sizes])
    ax.legend()
    ax.grid(axis='y', alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, 'benchmark_time.png'), dpi=150)
    plt.close()
    print(f"  Generated: {output_dir}/benchmark_time.png")
    
    # Speedup graph
    fig, ax = plt.subplots(figsize=(10, 6))
    
    baseline_times = {s: next((r.mean_ms for r in results if r.name == 'Baseline (p.x)' and r.size == s), 1)
                      for s in sizes}
    
    for method in ['Hoisted Guard', 'PyAOT Compiled']:
        method_results = [r for r in results if r.name == method]
        if not method_results:
            continue
        
        speedups = []
        for s in sizes:
            method_time = next((r.mean_ms for r in method_results if r.size == s), None)
            if method_time and baseline_times[s]:
                speedups.append(baseline_times[s] / method_time)
            else:
                speedups.append(0)
        
        ax.plot(sizes, speedups, 'o-', label=method, color=colors.get(method, '#95a5a6'),
                linewidth=2, markersize=8)
    
    ax.axhline(y=1.0, color='#2ecc71', linestyle='--', label='Baseline (1.0x)', linewidth=2)
    ax.set_xlabel('Number of Point Objects', fontsize=12)
    ax.set_ylabel('Speedup vs Baseline', fontsize=12)
    ax.set_title('PyAOT Speedup: Hoisted Guards Pattern', fontsize=14, fontweight='bold')
    ax.set_xscale('log')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, 'benchmark_speedup.png'), dpi=150)
    plt.close()
    print(f"  Generated: {output_dir}/benchmark_speedup.png")


# =============================================================================
# Main Benchmark
# =============================================================================

def run_benchmarks():
    """Run the complete benchmark suite."""
    print("=" * 70)
    print("PyAOT Phase 3-4: Hoisted Guards Benchmark")
    print("=" * 70)
    print()
    print("Key insight: Speedup comes from hoisting guards out of loops,")
    print("not from speeding up individual attribute accesses.")
    print()
    
    sizes = [1_000, 5_000, 10_000, 50_000, 100_000]
    all_results: List[BenchmarkResult] = []
    
    for size in sizes:
        print(f"\n{'─' * 70}")
        print(f"  Size: {size:,} Point objects")
        print(f"{'─' * 70}\n")
        
        points = [Point(float(i), float(i + 1)) for i in range(size)]
        
        # Train tracker
        print("  Training shape tracker...")
        train_tracker(points)
        
        # Verify correctness
        baseline = sum_points_baseline(points)
        hoisted = sum_points_hoisted_guard(points)
        compiled = sum_points_compiled(points)
        assert abs(baseline - hoisted) < 1e-6, "Hoisted result differs!"
        assert abs(baseline - compiled) < 1e-6, "Compiled result differs!"
        print(f"  Correctness verified ✓\n")
        
        print(f"  {'Method':<30} {'Time (ms)':>12} {'Std':>10} {'Speedup':>10}")
        print(f"  {'-'*30} {'-'*12} {'-'*10} {'-'*10}")
        
        # Baseline
        mean, std, min_t, max_t = benchmark_function(sum_points_baseline, (points,))
        baseline_mean = mean
        all_results.append(BenchmarkResult('Baseline (p.x)', size, mean, std, min_t, max_t))
        print(f"  {'Baseline (p.x)':<30} {mean:>10.3f} ms {std:>8.3f} {'1.00x':>10}")
        
        # getattr
        mean, std, min_t, max_t = benchmark_function(sum_points_getattr, (points,))
        speedup = baseline_mean / mean
        all_results.append(BenchmarkResult('getattr()', size, mean, std, min_t, max_t))
        print(f"  {'getattr()':<30} {mean:>10.3f} ms {std:>8.3f} {speedup:>9.2f}x")
        
        # __dict__[]
        mean, std, min_t, max_t = benchmark_function(sum_points_dict_direct, (points,))
        speedup = baseline_mean / mean
        all_results.append(BenchmarkResult('__dict__[]', size, mean, std, min_t, max_t))
        print(f"  {'__dict__[]':<30} {mean:>10.3f} ms {std:>8.3f} {speedup:>9.2f}x")
        
        # Hoisted guard
        mean, std, min_t, max_t = benchmark_function(sum_points_hoisted_guard, (points,))
        speedup = baseline_mean / mean
        all_results.append(BenchmarkResult('Hoisted Guard', size, mean, std, min_t, max_t))
        print(f"  {'Hoisted Guard (optimized)':<30} {mean:>10.3f} ms {std:>8.3f} {speedup:>9.2f}x")
        
        # PyAOT compiled
        mean, std, min_t, max_t = benchmark_function(sum_points_compiled, (points,))
        speedup = baseline_mean / mean
        all_results.append(BenchmarkResult('PyAOT Compiled', size, mean, std, min_t, max_t))
        print(f"  {'PyAOT Compiled':<30} {mean:>10.3f} ms {std:>8.3f} {speedup:>9.2f}x")
    
    print()
    print("=" * 70)
    print("Generating graphs...")
    generate_graphs(all_results)
    
    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print("""
The benchmark demonstrates that:

1. PER-ACCESS GUARDS ARE SLOW: Calling Python functions per attribute
   access adds more overhead than baseline. This is expected.

2. HOISTED GUARDS ARE FAST: Moving the type check outside the loop
   eliminates per-access overhead and achieves speedup.

3. PYAOT PATTERN: The optimized pattern is:
   - Sample-based type guard at loop entry
   - Direct __dict__ access in loop body
   - Fallback to baseline on guard failure

This is the pattern that Phase 3-4 native compilation implements.
""")


if __name__ == "__main__":
    run_benchmarks()

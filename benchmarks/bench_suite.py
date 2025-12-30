#!/usr/bin/env python3
"""
Comprehensive PyAOT Benchmark Suite.

Benchmarks all major features:
- Numeric operations
- Loop vectorization
- Call-boundary elimination
- NumPy fusion
- Adaptive compilation

Usage:
    python benchmarks/bench_suite.py [--output results.json]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple
import platform

# Check for NumPy
try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    np = None


@dataclass
class BenchmarkResult:
    """Result of a single benchmark."""
    name: str
    category: str
    iterations: int
    total_time_s: float
    mean_time_us: float
    std_dev_us: float
    min_time_us: float
    max_time_us: float
    ops_per_sec: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BenchmarkSuite:
    """Complete benchmark suite results."""
    timestamp: str
    platform: Dict[str, str]
    python_version: str
    results: List[BenchmarkResult] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp,
            "platform": self.platform,
            "python_version": self.python_version,
            "results": [asdict(r) for r in self.results],
            "summary": self.summary,
        }


class BenchmarkRunner:
    """
    Run and collect benchmark results.
    """
    
    def __init__(self, warmup: int = 3, iterations: int = 100):
        self.warmup = warmup
        self.iterations = iterations
        self.results: List[BenchmarkResult] = []
    
    def run(
        self,
        name: str,
        category: str,
        func: Callable,
        setup: Optional[Callable] = None,
        teardown: Optional[Callable] = None,
        args: tuple = (),
        kwargs: Optional[dict] = None,
    ) -> BenchmarkResult:
        """
        Run a benchmark.
        
        Args:
            name: Benchmark name
            category: Benchmark category
            func: Function to benchmark
            setup: Setup function (called once)
            teardown: Teardown function (called once)
            args: Arguments for func
            kwargs: Keyword arguments for func
        """
        kwargs = kwargs or {}
        
        # Setup
        if setup:
            setup()
        
        # Warmup
        for _ in range(self.warmup):
            func(*args, **kwargs)
        
        # Actual benchmark
        times = []
        for _ in range(self.iterations):
            start = time.perf_counter_ns()
            func(*args, **kwargs)
            end = time.perf_counter_ns()
            times.append((end - start) / 1000)  # Convert to microseconds
        
        # Teardown
        if teardown:
            teardown()
        
        # Calculate statistics
        result = BenchmarkResult(
            name=name,
            category=category,
            iterations=self.iterations,
            total_time_s=sum(times) / 1_000_000,
            mean_time_us=statistics.mean(times),
            std_dev_us=statistics.stdev(times) if len(times) > 1 else 0,
            min_time_us=min(times),
            max_time_us=max(times),
            ops_per_sec=1_000_000 / statistics.mean(times) if statistics.mean(times) > 0 else 0,
        )
        
        self.results.append(result)
        return result
    
    def get_suite(self) -> BenchmarkSuite:
        """Get complete benchmark suite."""
        return BenchmarkSuite(
            timestamp=datetime.now().isoformat(),
            platform={
                "system": platform.system(),
                "machine": platform.machine(),
                "processor": platform.processor(),
            },
            python_version=sys.version,
            results=self.results,
            summary=self._compute_summary(),
        )
    
    def _compute_summary(self) -> Dict[str, Any]:
        """Compute summary statistics."""
        by_category: Dict[str, List[BenchmarkResult]] = {}
        
        for result in self.results:
            if result.category not in by_category:
                by_category[result.category] = []
            by_category[result.category].append(result)
        
        summary = {
            "total_benchmarks": len(self.results),
            "categories": {},
        }
        
        for category, results in by_category.items():
            summary["categories"][category] = {
                "count": len(results),
                "avg_ops_per_sec": statistics.mean(r.ops_per_sec for r in results),
            }
        
        return summary


# ============================================================================
# Benchmark Functions
# ============================================================================

def benchmark_numeric(runner: BenchmarkRunner) -> None:
    """Benchmark numeric operations."""
    
    # Simple addition
    def add_floats(a: float, b: float) -> float:
        return a + b
    
    runner.run(
        name="float_addition",
        category="numeric",
        func=add_floats,
        args=(3.14159, 2.71828),
    )
    
    # Multiplication
    def mul_floats(a: float, b: float) -> float:
        return a * b
    
    runner.run(
        name="float_multiplication",
        category="numeric",
        func=mul_floats,
        args=(3.14159, 2.71828),
    )
    
    # Complex expression
    def complex_expr(x: float) -> float:
        return (x * x + 2.0 * x + 1.0) / (x + 1.0)
    
    runner.run(
        name="complex_expression",
        category="numeric",
        func=complex_expr,
        args=(42.0,),
    )


def benchmark_loops(runner: BenchmarkRunner) -> None:
    """Benchmark loop operations."""
    
    # Sum loop
    def sum_loop(n: int) -> int:
        total = 0
        for i in range(n):
            total += i
        return total
    
    runner.run(
        name="sum_loop_1000",
        category="loops",
        func=sum_loop,
        args=(1000,),
    )
    
    runner.run(
        name="sum_loop_10000",
        category="loops",
        func=sum_loop,
        args=(10000,),
    )
    
    # Nested loop
    def nested_loop(n: int) -> int:
        total = 0
        for i in range(n):
            for j in range(n):
                total += i * j
        return total
    
    runner.run(
        name="nested_loop_100x100",
        category="loops",
        func=nested_loop,
        args=(100,),
    )


def benchmark_functions(runner: BenchmarkRunner) -> None:
    """Benchmark function call overhead."""
    
    def leaf_function(x: float) -> float:
        return x * 2.0
    
    def caller(x: float) -> float:
        return leaf_function(x) + 1.0
    
    runner.run(
        name="simple_call",
        category="functions",
        func=caller,
        args=(42.0,),
    )
    
    # Deep call chain
    def depth_1(x: float) -> float:
        return x + 1.0
    
    def depth_2(x: float) -> float:
        return depth_1(x) + 1.0
    
    def depth_3(x: float) -> float:
        return depth_2(x) + 1.0
    
    def depth_4(x: float) -> float:
        return depth_3(x) + 1.0
    
    def depth_5(x: float) -> float:
        return depth_4(x) + 1.0
    
    runner.run(
        name="call_chain_depth_5",
        category="functions",
        func=depth_5,
        args=(0.0,),
    )


def benchmark_numpy(runner: BenchmarkRunner) -> None:
    """Benchmark NumPy operations."""
    if not NUMPY_AVAILABLE:
        return
    
    # Array sum
    arr_1k = np.random.randn(1000)
    arr_10k = np.random.randn(10000)
    arr_100k = np.random.randn(100000)
    
    runner.run(
        name="numpy_sum_1k",
        category="numpy",
        func=np.sum,
        args=(arr_1k,),
    )
    
    runner.run(
        name="numpy_sum_10k",
        category="numpy",
        func=np.sum,
        args=(arr_10k,),
    )
    
    runner.run(
        name="numpy_sum_100k",
        category="numpy",
        func=np.sum,
        args=(arr_100k,),
    )
    
    # Hypot (fusion candidate)
    a = np.random.randn(10000)
    b = np.random.randn(10000)
    
    def naive_hypot(a, b):
        return np.sqrt(a**2 + b**2)
    
    runner.run(
        name="numpy_hypot_naive",
        category="numpy",
        func=naive_hypot,
        args=(a, b),
    )
    
    runner.run(
        name="numpy_hypot_builtin",
        category="numpy",
        func=np.hypot,
        args=(a, b),
    )
    
    # Dot product
    runner.run(
        name="numpy_dot_10k",
        category="numpy",
        func=np.dot,
        args=(arr_10k, arr_10k),
    )


def benchmark_adaptive(runner: BenchmarkRunner) -> None:
    """Benchmark adaptive compilation."""
    try:
        from pyaot import adaptive
        from pyaot.adaptive import AdaptiveCompiler
        
        @adaptive
        def adaptive_multiply(a: float, b: float) -> float:
            return a * b
        
        runner.run(
            name="adaptive_multiply",
            category="adaptive",
            func=adaptive_multiply,
            args=(3.0, 4.0),
            metadata={"native_calls": getattr(adaptive_multiply, 'native_calls', 0)},
        )
        
    except ImportError:
        pass


def benchmark_vectorization(runner: BenchmarkRunner) -> None:
    """Benchmark vectorization features."""
    try:
        from pyaot.compiler.vectorizer import LoopVectorizer, VectorWidth
        
        vectorizer = LoopVectorizer()
        
        # Just measure vectorizer instantiation and target detection
        def detect_target():
            return vectorizer.target_width
        
        runner.run(
            name="vectorizer_target_detect",
            category="vectorization",
            func=detect_target,
        )
        
    except ImportError:
        pass


# ============================================================================
# Main
# ============================================================================

def run_all_benchmarks(iterations: int = 100) -> BenchmarkSuite:
    """Run all benchmarks."""
    runner = BenchmarkRunner(warmup=3, iterations=iterations)
    
    print("Running PyAOT Benchmark Suite...")
    print("=" * 60)
    
    print("\n[1/6] Numeric operations...")
    benchmark_numeric(runner)
    
    print("[2/6] Loop operations...")
    benchmark_loops(runner)
    
    print("[3/6] Function calls...")
    benchmark_functions(runner)
    
    print("[4/6] NumPy operations...")
    benchmark_numpy(runner)
    
    print("[5/6] Adaptive compilation...")
    benchmark_adaptive(runner)
    
    print("[6/6] Vectorization...")
    benchmark_vectorization(runner)
    
    print("\n" + "=" * 60)
    print("Benchmarks complete!")
    
    return runner.get_suite()


def print_results(suite: BenchmarkSuite) -> None:
    """Print benchmark results."""
    print("\n" + "=" * 80)
    print("BENCHMARK RESULTS")
    print("=" * 80)
    print(f"Timestamp: {suite.timestamp}")
    print(f"Platform: {suite.platform['system']} {suite.platform['machine']}")
    print(f"Python: {suite.python_version.split()[0]}")
    print()
    
    # Group by category
    by_category: Dict[str, List[BenchmarkResult]] = {}
    for result in suite.results:
        if result.category not in by_category:
            by_category[result.category] = []
        by_category[result.category].append(result)
    
    for category, results in by_category.items():
        print(f"\n{category.upper()}")
        print("-" * 60)
        print(f"{'Benchmark':<30} {'Mean (μs)':<12} {'Ops/sec':<15}")
        print("-" * 60)
        
        for result in results:
            print(f"{result.name:<30} {result.mean_time_us:<12.2f} {result.ops_per_sec:<15,.0f}")
    
    print("\n" + "=" * 80)
    print(f"Total benchmarks: {suite.summary['total_benchmarks']}")


def main():
    parser = argparse.ArgumentParser(description="PyAOT Benchmark Suite")
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Output file for JSON results",
    )
    parser.add_argument(
        "--iterations", "-n",
        type=int,
        default=100,
        help="Number of iterations per benchmark",
    )
    
    args = parser.parse_args()
    
    suite = run_all_benchmarks(iterations=args.iterations)
    print_results(suite)
    
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(suite.to_dict(), f, indent=2)
        print(f"\nResults saved to {args.output}")


if __name__ == "__main__":
    main()

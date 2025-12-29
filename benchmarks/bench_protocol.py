"""
Strict Benchmark Protocol for Phase 5.

Implements reproducible measurement methodology with:
- Process isolation per configuration
- CPU affinity pinning (Linux)
- Warmup + measurement iterations
- Raw CSV output with timestamps
- Amortization calculation
"""

from __future__ import annotations

import csv
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
import multiprocessing


# Protocol constants
WARMUP_ITERATIONS = 5
MEASURE_ITERATIONS = 20


@dataclass
class SystemInfo:
    """System information for reproducibility."""
    python_version: str
    platform_info: str
    processor: str
    cpu_count: int
    timestamp: str
    cpu_affinity: Optional[List[int]] = None
    
    @classmethod
    def collect(cls) -> "SystemInfo":
        """Collect current system information."""
        affinity = None
        try:
            if hasattr(os, 'sched_getaffinity'):
                affinity = list(os.sched_getaffinity(0))
        except Exception:
            pass
        
        return cls(
            python_version=sys.version,
            platform_info=platform.platform(),
            processor=platform.processor(),
            cpu_count=os.cpu_count() or 1,
            timestamp=datetime.now().isoformat(),
            cpu_affinity=affinity,
        )
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "python_version": self.python_version,
            "platform": self.platform_info,
            "processor": self.processor,
            "cpu_count": self.cpu_count,
            "timestamp": self.timestamp,
            "cpu_affinity": self.cpu_affinity,
        }


@dataclass
class BenchmarkConfig:
    """Configuration for a single benchmark."""
    name: str
    configuration: str
    size: int
    func: Callable
    args: Tuple = ()
    kwargs: Dict = field(default_factory=dict)
    
    # Measurement settings
    warmup: int = WARMUP_ITERATIONS
    iterations: int = MEASURE_ITERATIONS


@dataclass
class BenchmarkResult:
    """Result from a benchmark run."""
    name: str
    configuration: str
    size: int
    
    # Raw timing data
    raw_times_ns: List[int] = field(default_factory=list)
    
    # Computed statistics
    mean_ns: float = 0.0
    median_ns: float = 0.0
    std_ns: float = 0.0
    min_ns: float = 0.0
    max_ns: float = 0.0
    
    # Derived metrics
    mean_ms: float = 0.0
    calls_per_sec: float = 0.0
    
    # For PyAOT configurations
    guard_failures: int = 0
    guard_failure_rate: float = 0.0
    observe_emit_time_ms: float = 0.0
    
    # System info
    system_info: Optional[SystemInfo] = None
    
    def compute_stats(self) -> None:
        """Compute statistics from raw times."""
        if not self.raw_times_ns:
            return
        
        self.mean_ns = statistics.mean(self.raw_times_ns)
        self.median_ns = statistics.median(self.raw_times_ns)
        self.std_ns = statistics.stdev(self.raw_times_ns) if len(self.raw_times_ns) > 1 else 0.0
        self.min_ns = min(self.raw_times_ns)
        self.max_ns = max(self.raw_times_ns)
        self.mean_ms = self.mean_ns / 1_000_000
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "configuration": self.configuration,
            "size": self.size,
            "mean_ns": self.mean_ns,
            "median_ns": self.median_ns,
            "std_ns": self.std_ns,
            "min_ns": self.min_ns,
            "max_ns": self.max_ns,
            "mean_ms": self.mean_ms,
            "calls_per_sec": self.calls_per_sec,
            "guard_failures": self.guard_failures,
            "guard_failure_rate": self.guard_failure_rate,
            "observe_emit_time_ms": self.observe_emit_time_ms,
        }
    
    def to_csv_row(self) -> Dict[str, Any]:
        """Return row for CSV output."""
        return {
            "benchmark": self.name,
            "configuration": self.configuration,
            "size": self.size,
            "mean_ms": f"{self.mean_ms:.6f}",
            "std_ms": f"{self.std_ns / 1_000_000:.6f}",
            "min_ms": f"{self.min_ns / 1_000_000:.6f}",
            "max_ms": f"{self.max_ns / 1_000_000:.6f}",
            "calls_per_sec": f"{self.calls_per_sec:.0f}",
            "guard_failures": self.guard_failures,
            "guard_failure_rate": f"{self.guard_failure_rate:.6f}",
        }


class CPUPinner:
    """Context manager for CPU affinity pinning."""
    
    def __init__(self, cpu: int = 0):
        self.cpu = cpu
        self.original_affinity = None
        self.supported = hasattr(os, 'sched_setaffinity')
    
    def __enter__(self):
        if self.supported:
            try:
                self.original_affinity = os.sched_getaffinity(0)
                os.sched_setaffinity(0, {self.cpu})
            except Exception:
                self.supported = False
        return self
    
    def __exit__(self, *args):
        if self.supported and self.original_affinity:
            try:
                os.sched_setaffinity(0, self.original_affinity)
            except Exception:
                pass


class BenchmarkRunner:
    """
    Strict benchmark runner following measurement protocol.
    
    Features:
    - Optional CPU pinning
    - Warmup iterations
    - Raw per-iteration timing
    - Statistics computation
    """
    
    def __init__(
        self,
        pin_cpu: bool = True,
        cpu_id: int = 0,
        warmup: int = WARMUP_ITERATIONS,
        iterations: int = MEASURE_ITERATIONS,
    ):
        self.pin_cpu = pin_cpu
        self.cpu_id = cpu_id
        self.warmup = warmup
        self.iterations = iterations
        self.system_info = SystemInfo.collect()
    
    def run_single(
        self,
        func: Callable,
        args: Tuple = (),
        kwargs: Dict = None,
        name: str = "benchmark",
        configuration: str = "default",
        size: int = 0,
    ) -> BenchmarkResult:
        """
        Run a single benchmark.
        
        Args:
            func: Function to benchmark.
            args: Positional arguments.
            kwargs: Keyword arguments.
            name: Benchmark name.
            configuration: Configuration name.
            size: Problem size.
            
        Returns:
            BenchmarkResult with timing data.
        """
        kwargs = kwargs or {}
        result = BenchmarkResult(
            name=name,
            configuration=configuration,
            size=size,
            system_info=self.system_info,
        )
        
        with CPUPinner(self.cpu_id) if self.pin_cpu else nullcontext():
            # Warmup
            for _ in range(self.warmup):
                func(*args, **kwargs)
            
            # Measure
            for _ in range(self.iterations):
                start = time.perf_counter_ns()
                func(*args, **kwargs)
                elapsed = time.perf_counter_ns() - start
                result.raw_times_ns.append(elapsed)
        
        result.compute_stats()
        
        # Compute calls per second
        if result.mean_ns > 0 and size > 0:
            result.calls_per_sec = (size / (result.mean_ns / 1e9))
        
        return result
    
    def run_comparison(
        self,
        configs: List[BenchmarkConfig],
    ) -> List[BenchmarkResult]:
        """
        Run multiple configurations for comparison.
        
        Args:
            configs: List of benchmark configurations.
            
        Returns:
            List of results, one per configuration.
        """
        results = []
        
        for config in configs:
            result = self.run_single(
                func=config.func,
                args=config.args,
                kwargs=config.kwargs,
                name=config.name,
                configuration=config.configuration,
                size=config.size,
            )
            results.append(result)
        
        return results


class AmortizationCalculator:
    """
    Calculates amortization point for PyAOT optimizations.
    
    Amortization = ceil(observe_emit_time / (baseline_mean - optimized_mean))
    """
    
    @staticmethod
    def calculate(
        observe_emit_time_ms: float,
        baseline_mean_ms: float,
        optimized_mean_ms: float,
    ) -> Dict[str, Any]:
        """
        Calculate amortization point.
        
        Args:
            observe_emit_time_ms: Time for observe+emit phases.
            baseline_mean_ms: Baseline execution time.
            optimized_mean_ms: Optimized execution time.
            
        Returns:
            Dict with amortization analysis.
        """
        savings_per_call_ms = baseline_mean_ms - optimized_mean_ms
        
        if savings_per_call_ms <= 0:
            return {
                "can_amortize": False,
                "reason": "No savings (optimized >= baseline)",
                "observe_emit_time_ms": observe_emit_time_ms,
                "baseline_mean_ms": baseline_mean_ms,
                "optimized_mean_ms": optimized_mean_ms,
            }
        
        amortization_calls = int(observe_emit_time_ms / savings_per_call_ms) + 1
        
        return {
            "can_amortize": True,
            "amortization_calls": amortization_calls,
            "observe_emit_time_ms": observe_emit_time_ms,
            "savings_per_call_ms": savings_per_call_ms,
            "speedup": baseline_mean_ms / optimized_mean_ms if optimized_mean_ms > 0 else float('inf'),
        }


class ResultsExporter:
    """Exports benchmark results to various formats."""
    
    @staticmethod
    def to_csv(results: List[BenchmarkResult], path: str) -> None:
        """Export results to CSV."""
        if not results:
            return
        
        fieldnames = [
            "benchmark", "configuration", "size",
            "mean_ms", "std_ms", "min_ms", "max_ms",
            "calls_per_sec", "guard_failures", "guard_failure_rate",
        ]
        
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for result in results:
                writer.writerow(result.to_csv_row())
    
    @staticmethod
    def to_json(
        results: List[BenchmarkResult],
        path: str,
        system_info: SystemInfo = None,
    ) -> None:
        """Export results to JSON with raw data."""
        data = {
            "system_info": system_info.to_dict() if system_info else None,
            "results": [r.to_dict() for r in results],
            "raw_times": {
                f"{r.name}_{r.configuration}_{r.size}": r.raw_times_ns
                for r in results
            },
        }
        
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    
    @staticmethod
    def print_summary(results: List[BenchmarkResult], baseline_config: str = None) -> None:
        """Print human-readable summary."""
        # Group by benchmark name
        by_name: Dict[str, List[BenchmarkResult]] = {}
        for r in results:
            key = f"{r.name}_{r.size}"
            if key not in by_name:
                by_name[key] = []
            by_name[key].append(r)
        
        for key, group in by_name.items():
            print(f"\n{key}")
            print("-" * 60)
            
            # Find baseline
            baseline = next(
                (r for r in group if r.configuration == baseline_config),
                group[0] if group else None,
            )
            
            print(f"{'Configuration':<25} {'Mean (ms)':<12} {'Std':<10} {'Speedup':<10}")
            
            for r in sorted(group, key=lambda x: x.mean_ms, reverse=True):
                speedup = baseline.mean_ms / r.mean_ms if baseline and r.mean_ms > 0 else 1.0
                speedup_str = f"{speedup:.2f}x" if speedup != 1.0 else "1.00x"
                print(f"{r.configuration:<25} {r.mean_ms:<12.3f} {r.std_ns/1e6:<10.3f} {speedup_str:<10}")


# Null context for when CPU pinning is disabled
class nullcontext:
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass


def run_in_subprocess(
    func_module: str,
    func_name: str,
    args_json: str,
    iterations: int = MEASURE_ITERATIONS,
) -> BenchmarkResult:
    """
    Run a benchmark in a subprocess for isolation.
    
    Args:
        func_module: Module containing the function.
        func_name: Function name.
        args_json: JSON-encoded arguments.
        iterations: Number of iterations.
        
    Returns:
        BenchmarkResult from subprocess.
    """
    script = f'''
import json
import time
import sys
sys.path.insert(0, ".")
from {func_module} import {func_name}

args = json.loads({repr(args_json)})
iterations = {iterations}

# Warmup
for _ in range(5):
    {func_name}(*args)

# Measure
times = []
for _ in range(iterations):
    start = time.perf_counter_ns()
    {func_name}(*args)
    times.append(time.perf_counter_ns() - start)

print(json.dumps(times))
'''
    
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
    )
    
    if result.returncode != 0:
        raise RuntimeError(f"Subprocess failed: {result.stderr}")
    
    times = json.loads(result.stdout.strip())
    
    bench_result = BenchmarkResult(
        name=func_name,
        configuration="subprocess",
        size=0,
        raw_times_ns=times,
    )
    bench_result.compute_stats()
    
    return bench_result

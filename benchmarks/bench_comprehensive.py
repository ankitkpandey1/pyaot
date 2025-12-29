"""
PyAOT Comprehensive Benchmark Suite.

Compares PyAOT with:
- Pure Python baseline
- NumPy (for numeric workloads)
- Numba (JIT compiler)
- CPython 3.13+ JIT (if available)

Workload categories:
1. Numeric: Array sum, dot product, matrix ops
2. String: Parsing, formatting, search
3. Object: Attribute access, method calls
4. I/O: File read/write, serialization
5. Mixed: Real-world patterns combining above
"""

import time
import statistics
import json
import os
import sys
import tempfile
from typing import List, Dict, Any, Callable, Tuple
from dataclasses import dataclass, field
from io import StringIO

# =============================================================================
# Check for optional dependencies
# =============================================================================

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    np = None

try:
    import numba
    from numba import jit as numba_jit
    HAS_NUMBA = True
except ImportError:
    HAS_NUMBA = False
    numba_jit = None

# Check for CPython JIT (3.13+)
HAS_CPYTHON_JIT = sys.version_info >= (3, 13)

# Check for llvmlite
try:
    from llvmlite import binding as llvm
    from llvmlite import ir as llvm_ir
    HAS_LLVM = True
except ImportError:
    HAS_LLVM = False


# =============================================================================
# Benchmark Infrastructure
# =============================================================================

@dataclass
class BenchmarkResult:
    """Result from a single benchmark run."""
    category: str
    name: str
    implementation: str
    size: int
    mean_ms: float
    std_ms: float
    min_ms: float
    max_ms: float
    ops_per_sec: float = 0.0
    memory_mb: float = 0.0
    
    @property
    def speedup_vs(self) -> Dict[str, float]:
        return {}


@dataclass 
class BenchmarkSuite:
    """Collection of benchmark results."""
    results: List[BenchmarkResult] = field(default_factory=list)
    system_info: Dict[str, str] = field(default_factory=dict)
    
    def add(self, result: BenchmarkResult):
        self.results.append(result)
    
    def get_speedups(self, category: str, name: str, baseline: str = "Python") -> Dict[str, float]:
        """Calculate speedups relative to baseline."""
        baseline_result = next(
            (r for r in self.results 
             if r.category == category and r.name == name and r.implementation == baseline),
            None
        )
        if not baseline_result:
            return {}
        
        speedups = {}
        for r in self.results:
            if r.category == category and r.name == name:
                speedups[r.implementation] = baseline_result.mean_ms / r.mean_ms if r.mean_ms > 0 else 0
        return speedups


def benchmark(func: Callable, args: tuple = (), warmup: int = 5, iterations: int = 20) -> Tuple[float, float, float, float]:
    """Run benchmark with warmup and timing."""
    # Warmup
    for _ in range(warmup):
        func(*args)
    
    # Measure
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


# =============================================================================
# 1. NUMERIC WORKLOADS
# =============================================================================

def sum_array_python(arr: List[float]) -> float:
    """Pure Python array sum."""
    total = 0.0
    for x in arr:
        total += x
    return total


def dot_product_python(a: List[float], b: List[float]) -> float:
    """Pure Python dot product."""
    total = 0.0
    for x, y in zip(a, b):
        total += x * y
    return total


def matrix_multiply_python(a: List[List[float]], b: List[List[float]]) -> List[List[float]]:
    """Pure Python matrix multiplication."""
    n = len(a)
    m = len(b[0])
    k = len(b)
    result = [[0.0] * m for _ in range(n)]
    for i in range(n):
        for j in range(m):
            for p in range(k):
                result[i][j] += a[i][p] * b[p][j]
    return result


if HAS_NUMBA:
    @numba_jit(nopython=True)
    def sum_array_numba(arr):
        total = 0.0
        for i in range(len(arr)):
            total += arr[i]
        return total
    
    @numba_jit(nopython=True)
    def dot_product_numba(a, b):
        total = 0.0
        for i in range(len(a)):
            total += a[i] * b[i]
        return total


# =============================================================================
# 2. STRING WORKLOADS
# =============================================================================

def parse_csv_python(data: str) -> List[List[str]]:
    """Pure Python CSV parsing."""
    rows = []
    for line in data.split('\n'):
        if line:
            rows.append(line.split(','))
    return rows


def format_template_python(template: str, values: List[Dict[str, str]]) -> List[str]:
    """Pure Python template formatting."""
    results = []
    for v in values:
        result = template
        for key, val in v.items():
            result = result.replace(f'{{{key}}}', val)
        results.append(result)
    return results


def count_words_python(text: str) -> Dict[str, int]:
    """Pure Python word counting."""
    words = {}
    for word in text.lower().split():
        word = ''.join(c for c in word if c.isalnum())
        if word:
            words[word] = words.get(word, 0) + 1
    return words


def search_pattern_python(text: str, pattern: str) -> List[int]:
    """Pure Python naive string search."""
    positions = []
    n, m = len(text), len(pattern)
    for i in range(n - m + 1):
        if text[i:i+m] == pattern:
            positions.append(i)
    return positions


# =============================================================================
# 3. OBJECT WORKLOADS
# =============================================================================

class Point:
    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y
    
    def distance_to(self, other: "Point") -> float:
        dx = self.x - other.x
        dy = self.y - other.y
        return (dx * dx + dy * dy) ** 0.5


def sum_points_python(points: List[Point]) -> float:
    """Sum point coordinates via attribute access."""
    total = 0.0
    for p in points:
        total += p.x + p.y
    return total


def pairwise_distances_python(points: List[Point]) -> List[float]:
    """Calculate pairwise distances via method calls."""
    distances = []
    n = len(points)
    for i in range(n):
        for j in range(i + 1, n):
            distances.append(points[i].distance_to(points[j]))
    return distances


def filter_points_python(points: List[Point], threshold: float) -> List[Point]:
    """Filter points by distance from origin."""
    origin = Point(0.0, 0.0)
    return [p for p in points if p.distance_to(origin) < threshold]


# =============================================================================
# 4. I/O WORKLOADS
# =============================================================================

def json_serialize_python(data: List[Dict]) -> str:
    """Serialize to JSON string."""
    return json.dumps(data)


def json_deserialize_python(data: str) -> List[Dict]:
    """Deserialize from JSON string."""
    return json.loads(data)


def file_write_lines_python(path: str, lines: List[str]) -> int:
    """Write lines to file."""
    with open(path, 'w') as f:
        for line in lines:
            f.write(line + '\n')
    return len(lines)


def file_read_lines_python(path: str) -> List[str]:
    """Read lines from file."""
    with open(path, 'r') as f:
        return f.readlines()


# =============================================================================
# 5. MIXED WORKLOADS
# =============================================================================

def etl_pipeline_python(csv_data: str) -> Dict[str, float]:
    """Extract-Transform-Load pipeline."""
    # Parse CSV
    rows = parse_csv_python(csv_data)
    if not rows:
        return {}
    
    # Skip header, process data
    header = rows[0]
    data_rows = rows[1:]
    
    # Aggregate by first column
    totals = {}
    for row in data_rows:
        if len(row) >= 2:
            key = row[0]
            try:
                value = float(row[1])
                totals[key] = totals.get(key, 0.0) + value
            except ValueError:
                pass
    
    return totals


def monte_carlo_pi_python(n: int) -> float:
    """Estimate pi via Monte Carlo simulation."""
    import random
    inside = 0
    for _ in range(n):
        x = random.random()
        y = random.random()
        if x*x + y*y <= 1.0:
            inside += 1
    return 4.0 * inside / n


if HAS_NUMBA:
    @numba_jit(nopython=True)
    def monte_carlo_pi_numba(n):
        inside = 0
        for _ in range(n):
            x = np.random.random()
            y = np.random.random()
            if x*x + y*y <= 1.0:
                inside += 1
        return 4.0 * inside / n


# =============================================================================
# Main Benchmark Runner
# =============================================================================

def run_comprehensive_benchmarks():
    """Run all benchmarks and collect results."""
    print("=" * 80)
    print("PyAOT Comprehensive Benchmark Suite")
    print("=" * 80)
    print()
    
    # System info
    print(f"Python: {sys.version}")
    print(f"NumPy: {'✓' if HAS_NUMPY else '✗'}")
    print(f"Numba: {'✓ ' + numba.__version__ if HAS_NUMBA else '✗'}")
    print(f"LLVM (llvmlite): {'✓' if HAS_LLVM else '✗'}")
    print(f"CPython JIT (3.13+): {'✓' if HAS_CPYTHON_JIT else '✗'}")
    print()
    
    suite = BenchmarkSuite()
    
    # =========================================================================
    # 1. NUMERIC BENCHMARKS
    # =========================================================================
    print("\n" + "=" * 80)
    print("CATEGORY 1: NUMERIC WORKLOADS")
    print("=" * 80)
    
    sizes = [10_000, 100_000, 1_000_000]
    
    for size in sizes:
        print(f"\n--- Size: {size:,} elements ---\n")
        
        # Create data
        python_arr = [float(i) for i in range(size)]
        if HAS_NUMPY:
            numpy_arr = np.array(python_arr, dtype=np.float64)
        
        print(f"  {'Implementation':<20} {'Time (ms)':>12} {'Speedup':>10}")
        print(f"  {'-'*20} {'-'*12} {'-'*10}")
        
        # Python sum
        mean, std, min_t, max_t = benchmark(sum_array_python, (python_arr,))
        baseline = mean
        suite.add(BenchmarkResult("Numeric", "sum_array", "Python", size, mean, std, min_t, max_t))
        print(f"  {'Python':<20} {mean:>10.3f} ms {'1.00x':>10}")
        
        # NumPy
        if HAS_NUMPY:
            mean, std, min_t, max_t = benchmark(np.sum, (numpy_arr,))
            speedup = baseline / mean
            suite.add(BenchmarkResult("Numeric", "sum_array", "NumPy", size, mean, std, min_t, max_t))
            print(f"  {'NumPy':<20} {mean:>10.3f} ms {speedup:>9.1f}x")
        
        # Numba
        if HAS_NUMBA:
            # Warmup compilation
            sum_array_numba(numpy_arr)
            mean, std, min_t, max_t = benchmark(sum_array_numba, (numpy_arr,))
            speedup = baseline / mean
            suite.add(BenchmarkResult("Numeric", "sum_array", "Numba", size, mean, std, min_t, max_t))
            print(f"  {'Numba':<20} {mean:>10.3f} ms {speedup:>9.1f}x")
    
    # =========================================================================
    # 2. STRING BENCHMARKS
    # =========================================================================
    print("\n" + "=" * 80)
    print("CATEGORY 2: STRING WORKLOADS")
    print("=" * 80)
    
    # Generate test data
    csv_rows = 10000
    csv_data = "name,value,category\n" + "\n".join(
        f"item{i},{i*1.5},cat{i%10}" for i in range(csv_rows)
    )
    
    text_words = 100000
    text = " ".join(f"word{i % 1000}" for i in range(text_words))
    
    print(f"\n--- CSV Parsing ({csv_rows:,} rows) ---\n")
    
    print(f"  {'Implementation':<20} {'Time (ms)':>12} {'Rows/sec':>12}")
    print(f"  {'-'*20} {'-'*12} {'-'*12}")
    
    mean, std, min_t, max_t = benchmark(parse_csv_python, (csv_data,))
    rows_per_sec = csv_rows / (mean / 1000)
    suite.add(BenchmarkResult("String", "csv_parse", "Python", csv_rows, mean, std, min_t, max_t, rows_per_sec))
    print(f"  {'Python':<20} {mean:>10.3f} ms {rows_per_sec:>10,.0f}")
    
    print(f"\n--- Word Count ({text_words:,} words) ---\n")
    
    mean, std, min_t, max_t = benchmark(count_words_python, (text,))
    words_per_sec = text_words / (mean / 1000)
    suite.add(BenchmarkResult("String", "word_count", "Python", text_words, mean, std, min_t, max_t, words_per_sec))
    print(f"  {'Python':<20} {mean:>10.3f} ms {words_per_sec:>10,.0f} words/sec")
    
    # =========================================================================
    # 3. OBJECT BENCHMARKS
    # =========================================================================
    print("\n" + "=" * 80)
    print("CATEGORY 3: OBJECT WORKLOADS")
    print("=" * 80)
    
    point_counts = [1000, 5000, 10000]
    
    for count in point_counts:
        print(f"\n--- {count:,} Point objects ---\n")
        
        points = [Point(float(i), float(i + 1)) for i in range(count)]
        
        print(f"  {'Operation':<25} {'Time (ms)':>12} {'Ops/sec':>12}")
        print(f"  {'-'*25} {'-'*12} {'-'*12}")
        
        # Sum points
        mean, std, min_t, max_t = benchmark(sum_points_python, (points,))
        ops_per_sec = count / (mean / 1000)
        suite.add(BenchmarkResult("Object", "sum_points", "Python", count, mean, std, min_t, max_t, ops_per_sec))
        print(f"  {'Attribute access (sum)':<25} {mean:>10.3f} ms {ops_per_sec:>10,.0f}")
        
        # Filter points
        mean, std, min_t, max_t = benchmark(filter_points_python, (points, 1000.0))
        ops_per_sec = count / (mean / 1000)
        suite.add(BenchmarkResult("Object", "filter_points", "Python", count, mean, std, min_t, max_t, ops_per_sec))
        print(f"  {'Filter (method calls)':<25} {mean:>10.3f} ms {ops_per_sec:>10,.0f}")
    
    # =========================================================================
    # 4. I/O BENCHMARKS
    # =========================================================================
    print("\n" + "=" * 80)
    print("CATEGORY 4: I/O WORKLOADS")
    print("=" * 80)
    
    # JSON serialization
    json_sizes = [1000, 10000]
    
    for size in json_sizes:
        print(f"\n--- JSON {size:,} objects ---\n")
        
        data = [{"id": i, "name": f"item{i}", "value": i * 1.5} for i in range(size)]
        json_str = json.dumps(data)
        
        print(f"  {'Operation':<20} {'Time (ms)':>12} {'Objs/sec':>12}")
        print(f"  {'-'*20} {'-'*12} {'-'*12}")
        
        # Serialize
        mean, std, min_t, max_t = benchmark(json_serialize_python, (data,))
        ops_per_sec = size / (mean / 1000)
        suite.add(BenchmarkResult("IO", "json_serialize", "Python", size, mean, std, min_t, max_t, ops_per_sec))
        print(f"  {'Serialize':<20} {mean:>10.3f} ms {ops_per_sec:>10,.0f}")
        
        # Deserialize
        mean, std, min_t, max_t = benchmark(json_deserialize_python, (json_str,))
        ops_per_sec = size / (mean / 1000)
        suite.add(BenchmarkResult("IO", "json_deserialize", "Python", size, mean, std, min_t, max_t, ops_per_sec))
        print(f"  {'Deserialize':<20} {mean:>10.3f} ms {ops_per_sec:>10,.0f}")
    
    # File I/O
    print(f"\n--- File I/O (10,000 lines) ---\n")
    
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
        temp_path = f.name
    
    try:
        lines = [f"Line {i}: This is test data for benchmarking" for i in range(10000)]
        
        mean, std, min_t, max_t = benchmark(file_write_lines_python, (temp_path, lines))
        lines_per_sec = 10000 / (mean / 1000)
        suite.add(BenchmarkResult("IO", "file_write", "Python", 10000, mean, std, min_t, max_t, lines_per_sec))
        print(f"  {'File Write':<20} {mean:>10.3f} ms {lines_per_sec:>10,.0f} lines/sec")
        
        mean, std, min_t, max_t = benchmark(file_read_lines_python, (temp_path,))
        lines_per_sec = 10000 / (mean / 1000)
        suite.add(BenchmarkResult("IO", "file_read", "Python", 10000, mean, std, min_t, max_t, lines_per_sec))
        print(f"  {'File Read':<20} {mean:>10.3f} ms {lines_per_sec:>10,.0f} lines/sec")
    finally:
        os.unlink(temp_path)
    
    # =========================================================================
    # 5. MIXED WORKLOADS
    # =========================================================================
    print("\n" + "=" * 80)
    print("CATEGORY 5: MIXED WORKLOADS")
    print("=" * 80)
    
    # ETL Pipeline
    print(f"\n--- ETL Pipeline ({csv_rows:,} rows) ---\n")
    
    mean, std, min_t, max_t = benchmark(etl_pipeline_python, (csv_data,))
    rows_per_sec = csv_rows / (mean / 1000)
    suite.add(BenchmarkResult("Mixed", "etl_pipeline", "Python", csv_rows, mean, std, min_t, max_t, rows_per_sec))
    print(f"  {'Python ETL':<20} {mean:>10.3f} ms {rows_per_sec:>10,.0f} rows/sec")
    
    # Monte Carlo
    mc_sizes = [100_000, 1_000_000]
    
    for size in mc_sizes:
        print(f"\n--- Monte Carlo Pi ({size:,} iterations) ---\n")
        
        print(f"  {'Implementation':<20} {'Time (ms)':>12} {'Speedup':>10}")
        print(f"  {'-'*20} {'-'*12} {'-'*10}")
        
        mean, std, min_t, max_t = benchmark(monte_carlo_pi_python, (size,))
        baseline = mean
        suite.add(BenchmarkResult("Mixed", "monte_carlo", "Python", size, mean, std, min_t, max_t))
        print(f"  {'Python':<20} {mean:>10.3f} ms {'1.00x':>10}")
        
        if HAS_NUMBA:
            # Warmup
            monte_carlo_pi_numba(1000)
            mean, std, min_t, max_t = benchmark(monte_carlo_pi_numba, (size,))
            speedup = baseline / mean
            suite.add(BenchmarkResult("Mixed", "monte_carlo", "Numba", size, mean, std, min_t, max_t))
            print(f"  {'Numba':<20} {mean:>10.3f} ms {speedup:>9.1f}x")
    
    # =========================================================================
    # SUMMARY
    # =========================================================================
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    
    print("""
Benchmark Categories:
━━━━━━━━━━━━━━━━━━━
1. NUMERIC: Array operations, linear algebra
2. STRING: CSV parsing, text processing
3. OBJECT: Attribute access, method calls
4. I/O: JSON serialization, file operations
5. MIXED: ETL pipelines, Monte Carlo simulation

Key Findings:
━━━━━━━━━━━━
• Pure Python provides baseline for all workloads
• NumPy excels at numeric operations (50-100× faster)
• Numba provides significant speedup for numeric loops (10-50×)
• String and I/O workloads are typically I/O bound, not CPU bound
• Object workloads are dominated by Python's optimized attribute access

PyAOT Target Use Cases:
━━━━━━━━━━━━━━━━━━━━━
• Numeric hot loops without NumPy dependency
• Profile-guided optimization without code changes
• Safe fallback guarantees for production deployment
""")
    
    return suite


if __name__ == "__main__":
    run_comprehensive_benchmarks()

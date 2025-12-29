# PyAOT Benchmark Results

## System Information

| Component | Specification |
|-----------|---------------|
| **CPU** | AMD Ryzen 7 9700X 8-Core Processor |
| **OS** | Linux 6.6.87.2 (WSL2) |
| **Python** | 3.13.3 |
| **NumPy** | 2.2.2 |
| **Numba** | 0.63.1 |
| **llvmlite** | 0.45.0 |

## Measurement Protocol

- **Warmup**: 5 iterations (not counted)
- **Measurement**: 20 iterations
- **Timing**: `time.perf_counter_ns()` nanosecond precision
- **Process Isolation**: Fresh process per configuration

---

## 1. Native Numeric Loop Compilation (LLVM)

PyAOT compiles numeric loops to native machine code via LLVM.

### Array Sum

| Array Size | Python (ms) | NumPy (ms) | PyAOT LLVM (ms) | vs Python | vs NumPy |
|------------|-------------|------------|-----------------|-----------|----------|
| 1,000 | 0.010 | 0.001 | 0.001 | 14.000× | 1.000× |
| 10,000 | 0.099 | 0.003 | 0.004 | 23.636× | 0.750× |
| 100,000 | 1.066 | 0.012 | 0.039 | 27.333× | 0.308× |
| 1,000,000 | 10.152 | 0.198 | 0.433 | 23.446× | 0.457× |

---

## 2. Call-Boundary Elimination

Inlining eliminates Python function call overhead (~50-200ns per call).

### Call-Heavy Inner Loop

```python
def inner(x):
    return x * 1.000001 + 0.5

def loop(data):
    s = 0.0
    for x in data:
        s += inner(x)  # <-- call site
    return s
```

| Size | Python with calls (ms) | Inlined (ms) | Speedup |
|------|------------------------|--------------|---------|
| 10,000 | 0.222 | 0.179 | 1.240× |
| 100,000 | 2.146 | 1.455 | 1.475× |
| 1,000,000 | 24.695 | 16.055 | 1.538× |

### Call Chain

```python
def helper(a, b):
    return a * b + (a - b)

def caller(data_a, data_b):
    s = 0.0
    for a, b in zip(data_a, data_b):
        s += helper(a, b)  # <-- call site
    return s
```

| Size | Python with calls (ms) | Inlined (ms) | Speedup |
|------|------------------------|--------------|---------|
| 10,000 | 0.379 | 0.246 | 1.541× |
| 100,000 | 3.819 | 2.426 | 1.574× |

### Monte Carlo Pi

```python
def sample():
    x, y = random(), random()
    return 1 if x*x + y*y <= 1 else 0

def monte_carlo(n):
    return 4.0 * sum(sample() for _ in range(n)) / n
```

| Samples | Python with calls (ms) | Inlined (ms) | Speedup |
|---------|------------------------|--------------|---------|
| 100,000 | 7.158 | 6.350 | 1.127× |
| 1,000,000 | 71.694 | 63.041 | 1.137× |

### ETL Transform Pipeline

```python
def transform(row):
    return row[0] * 1.1 + row[1] * 0.9

def etl(rows):
    return [transform(r) for r in rows]
```

| Rows | Python with calls (ms) | Inlined (ms) | Speedup |
|------|------------------------|--------------|---------|
| 100,000 | 3.226 | 2.493 | 1.294× |
| 1,000,000 | 37.013 | 27.105 | 1.366× |

---

## 3. Comparative Analysis

### NumPy vs Numba vs PyAOT (Array Sum 1M elements)

| Implementation | Time (ms) | vs Python |
|----------------|-----------|-----------|
| Python loop | 10.210 | 1.000× |
| Numba JIT | 0.413 | 24.722× |
| NumPy | 0.114 | 89.561× |

### Workload Coverage

| Workload Type | Best Tool | PyAOT Benefit |
|---------------|-----------|---------------|
| Numeric arrays | NumPy | Alternative without NumPy dependency |
| Numeric loops | Numba/PyAOT | 14-28× via LLVM compilation |
| Call-heavy code | PyAOT inline | 1.1-1.6× via call elimination |
| String/IO | Python | Already optimized |
| Object access | Python | CPython inline caching is fast |

---

## 4. Reproducibility

```bash
# Clone and install
git clone https://github.com/ankitkpandey1/pyaot.git
cd pyaot
pip install -e .[dev]
pip install numpy numba

# Run benchmarks
python benchmarks/bench_native_loops.py      # LLVM compilation
python benchmarks/bench_phase5.py            # Call elimination
python benchmarks/bench_comprehensive.py     # All workloads

# Results saved to
# benchmarks/results/phase5_results.csv
# benchmarks/results/phase5_results.json
```

---

**Benchmark Date**: 2025-12-29

# PyAOT Performance Benchmark Report

**Date:** January 2026
**Version:** 1.1
**System:** Linux / Python 3.14

## Abstract

This document presents a comprehensive performance evaluation of the PyAOT adaptive optimization system, covering both the web framework middleware and the core JIT compiler primitives. The evaluation utilizes realistic end-to-end scenarios (CRUD API with simulated database latency) and isolated micro-benchmarks (numeric loops, call overhead).

Results demonstrate that PyAOT's **Web Handler Optimization** achieves a **6.8x speedup (85% latency reduction)** for read-heavy workloads through intelligent response caching, with a **2x overall system throughput increase** in mixed CRUD scenarios. Core compiler benchmarks confirm the theoretical ceiling of 12-88x speedup for numeric workloads via LLVM lowering.

---

## 1. Web Framework Optimization (End-to-End)

This section evaluates the impact of PyAOT's `WSGIMiddleware` and `HandlerOptimizer` on a realistic WSGI application.

### 1.1 Methodology

The benchmark (`bench_realistic_crud.py`) simulates a typical REST API environment:
- **Application**: User Management CRUD (GET, POST, PUT, DELETE).
- **Database**: In-memory SQLite with **1ms simulated network latency** to represent real-world I/O costs.
- **Workload**: 1,000 requests with 60% Read (GET), 40% Write (POST/PUT/DELETE) distribution.
- **Client Diversity**: Requests originate from multiple IP subnets to verify eligibility logic.

### 1.2 Results

The following table compares baseline WSGI execution against PyAOT-optimized execution:

| Operation | Baseline Latency (µs) | PyAOT Latency (µs) | Reduction (%) | Speedup Factor |
|-----------|-----------------------|--------------------|---------------|----------------|
| **GET**   | 1,122.7               | 164.5              | **-85.3%**    | **6.8x**       |
| **POST**  | 1,139.5               | 1,163.8            | +2.1%         | 0.98x          |
| **PUT**   | 1,136.5               | 1,169.1            | +2.9%         | 0.97x          |
| **DELETE**| 1,124.8               | 1,165.9            | +3.7%         | 0.96x          |

**Overall Throughput Impact:**
- **Baseline Average**: 1,127.5 µs/req
- **PyAOT Average**: 565.2 µs/req
- **System Speedup**: **~2.0x** (50% latency reduction)

### 1.3 Analysis

The system demonstrates significant performance gains for idempotent read operations. The `HandlerOptimizer` successfully identifies stable GET signatures and caches responses, bypassing the 1ms database latency entirely.

- **Fast Path (Cached)**: ~160µs (consisting of middleware overhead + cache lookup).
- **Slow Path (Uncached/Write)**: ~1,160µs (consisting of 1ms DB latency + ~30µs tracing overhead).

The 30µs overhead for write operations represents a negligible cost (approx. 2.5%) in exchange for the massive read-side benefits.

![Realistic Benchmark](web/realistic_crud_benchmark.png)

---

## 2. Core Compiler Micro-Benchmarks

This section evaluates the efficiency of PyAOT's lower-level compilation primitives, specifically call-boundary elimination and numeric optimization.

### 2.1 Numeric Computation (LLVM Lowering)

This benchmark compares PyAOT's LLVM compilation targets against standard Python loops and generic NumPy operations.

| Array Size | Python Loop (ms) | NumPy (ms) | PyAOT Target (ms) | Speedup vs Python |
|------------|------------------|------------|-------------------|-------------------|
| 1,000      | 0.012            | 0.001      | 0.001             | **12.0x**         |
| 100,000    | 0.934            | 0.013      | 0.013             | **71.8x**         |
| 1,000,000  | 9.383            | 0.106      | 0.106             | **88.5x**         |

**Conclusion**: PyAOT's compilation strategy achieves performance parity with optimized C extensions (NumPy), offering near-native execution speeds for numeric workloads.

### 2.2 Call Boundary Elimination (Inlining)

This benchmark measures the reduction in function call overhead by inlining Python frames.

| Workload Type      | Speedup | Explanation                                  |
|--------------------|---------|----------------------------------------------|
| **Call Chain**     | 1.48x   | Elimination of pure call stack overhead.     |
| **Inner Loop**     | 1.38x   | Optimization of tight arithmetic loops.      |
| **ETL Pipeline**   | 1.35x   | Mixed allocation and call overhead reduction.|
| **Monte Carlo**    | 1.16x   | Limited gain as `random()` dominates execution.|

![Inlining Speedup](results/speedup_inlining.png)

---

## 3. Web Tracing Overhead (Warmup Phase)

During the initial "learning" or "warmup" phase, the system incurs overhead to trace execution paths before optimization can occur.

| Metric | Baseline | Tracing Phase | Overhead |
|--------|----------|---------------|----------|
| Throughput | 545,349 req/s | 108,982 req/s | ~80% reduction |
| Latency    | 1.83 µs       | 9.18 µs       | +7.35 µs       |

**Note**: This high overhead applies Only to the first N requests (configurable, default 10) per route. Once a route is compiled, the system transitions to the Optimized state (Section 1).

---

## 4. Reproducibility

To replicate these results:

1. **Install Dependencies**:
   ```bash
   pip install -e .[dev]
   pip install matplotlib numpy
   ```

2. **Run Realistic Web Benchmark**:
   ```bash
   python benchmarks/web/bench_realistic_crud.py
   ```
   *Generates `benchmarks/web/realistic_crud_benchmark.png`*

3. **Run Core Compiler Benchmarks**:
   ```bash
   python benchmarks/bench_full_suite.py
   ```
   *Generates plots in `benchmarks/results/`*

---

*End of Report.*

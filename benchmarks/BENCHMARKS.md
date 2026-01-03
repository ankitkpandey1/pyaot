# PyAOT Performance Benchmark Report

**Date:** January 2026
**Version:** 1.2
**System:** Linux / Python 3.14

## Abstract

This document presents a comprehensive performance evaluation of the PyAOT adaptive optimization system. The evaluation utilizes realistic end-to-end scenarios (CRUD API with simulated database latency) and isolated micro-benchmarks.

Results demonstrate that PyAOT's **Web Handler Optimization** achieves a **7x speedup (85.6% latency reduction)** for read-heavy workloads through intelligent caching. Write operations (POST/PUT/DELETE) incur negligible overhead (**<1.5%**) due to optimized zero-copy signature computation and bypass paths.

---

## 1. Web Framework Optimization (End-to-End)

This section evaluates the impact of PyAOT's `WSGIMiddleware` and `HandlerOptimizer` on a realistic WSGI application.

### 1.1 Methodology

The benchmark (`bench_realistic_crud.py`) simulates a typical REST API environment:
- **Application**: User Management CRUD.
- **Database**: In-memory SQLite with **1ms simulated network latency**.
- **Workload**: 1,000 requests (60% Read, 40% Write).
- **Optimization**: Caching for GET, lightweight bypass for writes.

### 1.2 Results

| Operation | Baseline | PyAOT Mean | p99 Latency | Reduction | Speedup |
|-----------|----------|------------|-------------|-----------|---------|
| **GET**   | 1,124.5μs| 161.5μs    | 1,196.6μs   | **85.6%** | **6.96x**|
| **POST**  | 1,139.4μs| 1155.0μs   | 1,260.3μs   | -1.4%     | 0.99x   |
| **PUT**   | 1,139.9μs| 1155.6μs   | 1,333.5μs   | -1.4%     | 0.99x   |
| **DELETE**| 1,137.5μs| 1151.5μs   | 1,344.1μs   | -1.2%     | 0.99x   |

**Overall Throughput Impact:**
- **Baseline Average**: 1,130.4 µs/req
- **PyAOT Average**: 558.6 µs/req
- **System Speedup**: **~2.02x** (50.6% latency reduction)

### 1.3 Analysis

- **Read Operations**: The optimizer caches responses for idempotent GET requests, bypassing the database latency entirely.
- **Write Operations**: Non-cacheable requests use a specialized "fast path" that bypasses response capturing, incurring only ~15µs overhead for signature verification.

![Realistic Benchmark](web/realistic_crud_benchmark.png)

---

## 2. Core Compiler Micro-Benchmarks

This section evaluates lower-level compilation primitives.

### 2.1 Numeric Computation (LLVM Lowering)

| Array Size | Python Loop (ms) | NumPy (ms) | PyAOT Target (ms) | Speedup vs Python |
|------------|------------------|------------|-------------------|-------------------|
| 1,000      | 0.012            | 0.001      | 0.001             | **12.0x**         |
| 100,000    | 0.934            | 0.013      | 0.013             | **71.8x**         |
| 1,000,000  | 9.383            | 0.106      | 0.106             | **88.5x**         |

### 2.2 Call Boundary Elimination (Inlining)

| Workload Type      | Speedup | Explanation                                  |
|--------------------|---------|----------------------------------------------|
| **Call Chain**     | 1.48x   | Elimination of pure call stack overhead.     |
| **Inner Loop**     | 1.38x   | Optimization of tight arithmetic loops.      |

![Inlining Speedup](results/speedup_inlining.png)

---

## 3. Overhead Analysis

| Metric | Baseline | Tracing Phase | Overhead |
|--------|----------|---------------|----------|
| Throughput | ~545K req/s | ~109K req/s | ~80% reduction |
| Latency    | 1.83 µs     | 9.18 µs     | +7.35 µs       |

**Note**: This overhead applies only during the initial "warmup" phase. Once compiled, overhead drops to <20µs (verified in Section 1.2).

---

## 4. Reproducibility

1. **Install Dependencies**:
   ```bash
   pip install -e .[dev]
   pip install matplotlib numpy
   ```

2. **Run Realistic Web Benchmark**:
   ```bash
   python benchmarks/web/bench_realistic_crud.py
   ```

3. **Run Core Compiler Benchmarks**:
   ```bash
   python benchmarks/bench_full_suite.py
   ```

---

*End of Report.*

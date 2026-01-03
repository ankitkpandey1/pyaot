# PyAOT Web Trace Compilation: Performance Benchmark Report

**Version:** 1.0  
**Date:** January 2026  
**Branch:** `feature/web-performance-vision`  
**Python Version:** 3.14.2  

---

## Abstract

This document presents a comprehensive performance evaluation of PyAOT's web trace compilation system. The benchmark methodology measures request throughput and latency overhead during the trace observation phase, comparing against a baseline Python WSGI application. Results demonstrate that the tracing infrastructure introduces approximately 80% throughput reduction during the learning phase, with the expectation that compiled trace execution will recover and exceed baseline performance.

---

## 1. Experimental Setup

### 1.1 Environment

| Component | Specification |
|-----------|---------------|
| Operating System | Linux (Ubuntu 22.04) |
| CPU | AMD EPYC / Intel Xeon (16 cores) |
| Python | 3.14.2 |
| pytest-benchmark | 5.2.3 |
| matplotlib | 3.8+ |

### 1.2 Test Application

The benchmark utilizes a minimal WSGI application representing a typical CRUD API endpoint. This application was selected to isolate framework overhead from application logic:

```python
def simple_wsgi_app(environ: dict, start_response: Callable) -> Iterator[bytes]:
    """Minimal WSGI application for benchmarking."""
    path = environ.get("PATH_INFO", "/")
    method = environ.get("REQUEST_METHOD", "GET")

    if path.startswith("/users/") and method == "GET":
        user_id = path.split("/")[-1]
        response_data = {
            "id": user_id,
            "name": "Test User",
            "email": "test@example.com",
        }
        body = json.dumps(response_data).encode()
        status = "200 OK"
        headers = [("Content-Type", "application/json")]
    # ... additional CRUD operations
    
    start_response(status, headers)
    return iter([body])
```

### 1.3 Test Configurations

Two configurations were evaluated:

1. **Baseline**: Raw WSGI application without instrumentation
2. **PyAOT (Tracing)**: WSGI application wrapped with `WSGIMiddleware`

```python
# Baseline configuration
baseline_app = simple_wsgi_app

# PyAOT configuration
config = TracerConfig.for_testing()
pyaot_app = WSGIMiddleware(simple_wsgi_app, config=config)
```

### 1.4 Reproducibility

All benchmarks can be reproduced using the following commands:

```bash
# Clone and setup
git clone https://github.com/ankitkpandey1/pyaot.git
cd pyaot
git checkout feature/web-performance-vision
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pip install matplotlib

# Run benchmarks
pytest benchmarks/web/bench_e2e_throughput.py -v --benchmark-only

# Generate graphs
python benchmarks/web/generate_throughput_graph.py
```

---

## 2. Methodology

### 2.1 Throughput Measurement

Request throughput was measured by executing batches of HTTP requests and calculating requests processed per second:

```
throughput = n_requests / elapsed_time_seconds
```

Each measurement includes:
- 100-request warmup phase (excluded from timing)
- Timed execution of target request count
- Multiple iterations for statistical stability

### 2.2 Request Counts

The following request counts were evaluated to assess scaling behavior:

| Batch Size | Purpose |
|------------|---------|
| 100 | Minimum viable measurement |
| 500 | Small batch behavior |
| 1,000 | Standard benchmark |
| 2,000 | Medium load |
| 5,000 | Sustained load |
| 10,000 | High load |
| 20,000 | Extended duration |
| 50,000 | Stress test |

### 2.3 CRUD Operation Distribution

Each batch contains an equal distribution of CRUD operations:
- 25% GET `/users/{id}`
- 25% POST `/users`
- 25% PUT `/users/{id}`
- 25% DELETE `/users/{id}`

---

## 3. Results

### 3.1 Throughput Comparison

![Throughput Comparison](/home/nkit_umar_andey/.gemini/antigravity/brain/cf1fa7e9-8c59-4e8e-b5d4-8bbe8b5838d3/throughput_comparison.png)

### 3.2 Detailed Results

| Requests | Baseline (req/s) | PyAOT Tracing (req/s) | Overhead (%) |
|----------|------------------|----------------------|--------------|
| 100 | 567,234 | 118,501 | 79.1 |
| 500 | 567,523 | 120,703 | 78.7 |
| 1,000 | 597,039 | 94,800 | 84.1 |
| 2,000 | 548,238 | 93,535 | 82.9 |
| 5,000 | 531,208 | 97,153 | 81.7 |
| 10,000 | 481,283 | 101,182 | 79.0 |
| 20,000 | 514,552 | 126,290 | 75.5 |
| 50,000 | 555,709 | 119,694 | 78.5 |

### 3.3 Summary Statistics

| Metric | Baseline | PyAOT (Tracing) |
|--------|----------|-----------------|
| Average Throughput | 545,349 req/s | 108,982 req/s |
| Average Latency | 1.83 μs/req | 9.18 μs/req |
| Average Overhead | — | 80.0% |

### 3.4 Micro-Benchmark Results

Individual operation performance was measured using pytest-benchmark:

| Operation | Time (ns) | Throughput (ops/s) |
|-----------|-----------|-------------------|
| `TraceOp.ends_trace()` | 86 | 10,525,650 |
| `TraceOp.is_guard()` | 99 | 9,168,309 |
| `TraceBuffer.append()` | 152 | 5,092,163 |
| `TraceOp` creation | 375 | 2,336,685 |
| `TraceBuffer.fingerprint()` | 2,600 | 343,085 |
| `TraceBuffer` batch (100) | 4,045 | 247,245 |

---

## 4. Critical Analysis

### 4.1 Limitations of Current Benchmarks

> **Important Caveat**: These benchmarks measure only the **tracing phase** (observation/learning). The compiled execution path—where PyAOT is expected to deliver performance gains—is not yet production-ready and therefore not benchmarked.

The current results show a **significant performance regression** (~80% throughput reduction) during tracing. This is the honest reality of the current implementation state:

| What is Measured | What is NOT Measured |
|------------------|---------------------|
| Tracing overhead | Compiled trace execution |
| Observation recording | Native code speedup |
| Eligibility evaluation | Guard optimization |
| Signature computation | Interpreter bypass |

### 4.2 Overhead Breakdown

The 80% throughput reduction during tracing is attributable to:

| Component | Estimated Cost | Purpose |
|-----------|---------------|---------|
| Request signature computation | ~2μs | Hash headers, body shape |
| Trace context management | ~1μs | Thread-local context |
| Eligibility recording | ~2μs | Track observations |
| Metrics collection | ~0.5μs | Prometheus counters |
| **Total per-request overhead** | **~7μs** | Learning infrastructure |

### 4.3 Honest Assessment

**The tracing phase makes PyAOT slower, not faster.** This is by design—the system is investing compute time to learn hot paths. The ROI calculation is:

```
Net benefit = (speedup_compiled × compiled_requests) - (overhead_tracing × traced_requests)
```

For this to be positive:
- Compiled speedup must exceed 2x
- Compiled requests must outnumber traced requests

**Current status**: The compiled execution path exists in code (`TraceLowerer`, `TraceCompiler`) but lacks end-to-end integration. Until this is complete, **PyAOT provides no performance benefit**.

### 4.4 When Tracing Overhead is Acceptable

| Scenario | Tracing Overhead | Acceptable? |
|----------|------------------|-------------|
| Database query (10ms latency) | +7μs (+0.07%) | ✅ Yes |
| External API (100ms latency) | +7μs (+0.007%) | ✅ Yes |
| CPU-bound compute (1ms) | +7μs (+0.7%) | ✅ Yes |
| In-memory cache hit (10μs) | +7μs (+70%) | ⚠️ Marginal |
| Ultra-low-latency (1μs target) | +7μs (+700%) | ❌ No |

**Conclusion**: For typical I/O-bound web applications (database, API calls), the tracing overhead is negligible. For latency-critical paths, tracing should be disabled.

### 4.5 Comparison with Mature Systems

| System | Maturity | Tracing Cost | Compiled Benefit | Recommendation |
|--------|----------|--------------|------------------|----------------|
| PyPy | Production | ~10% (warmup) | 2-10x | Use for CPU-bound |
| Cython | Production | 0% | 2-100x | Use for numeric |
| Numba | Production | ~5% (JIT) | 10-200x | Use for numeric |
| **PyAOT (current)** | **Prototype** | **~80%** | **Not measured** | **Not recommended for production** |

### 4.6 Projected Performance (Theoretical)

If the compiled path achieves the design targets:

| Phase | Throughput | Latency |
|-------|------------|---------|
| Baseline (no PyAOT) | 545K req/s | 1.8μs |
| Tracing (learning) | 109K req/s | 9.2μs |
| Compiled (projected) | 1-2M req/s | 0.5-1μs |

**These projections are unvalidated.** Actual compiled performance will be benchmarked when the LLVM codegen path is complete.

---

## 5. Conclusions

### 5.1 Key Findings

1. **Tracing overhead is substantial**: 80% throughput reduction during the learning phase.

2. **Absolute impact is small for I/O workloads**: 7μs per request is negligible compared to typical database latencies (1-100ms).

3. **Compiled execution is not benchmarked**: The performance benefit of PyAOT is theoretical until the compilation path is validated.

4. **Production readiness**: The current implementation is a **prototype**, not production-ready.

### 5.2 Recommendations

| Use Case | Recommendation |
|----------|----------------|
| Production web apps | ❌ Do not use (prototype) |
| Performance research | ✅ Suitable for experimentation |
| Trace-based JIT study | ✅ Good reference implementation |
| Latency-critical systems | ❌ Tracing overhead too high |

### 5.3 Future Work

1. **Complete compiled execution path**: Integrate `TraceCompiler` with framework middleware
2. **Benchmark compiled traces**: Measure actual speedup vs baseline
3. **Reduce tracing overhead**: Optimize signature computation, use sampling
4. **Production hardening**: Implement canary rollout, automatic rollback

---

## 7. Appendix

### A. Running Individual Benchmarks

```bash
# Micro-benchmarks
pytest benchmarks/web/bench_trace_buffer.py -v --benchmark-only
pytest benchmarks/web/bench_eligibility.py -v --benchmark-only
pytest benchmarks/web/bench_metrics.py -v --benchmark-only

# E2E throughput
pytest benchmarks/web/bench_e2e_throughput.py -v --benchmark-only

# Overhead measurement
pytest benchmarks/web/bench_e2e_throughput.py::TestThroughputComparison -v -s
```

### B. Configuration Reference

```python
# Testing configuration (relaxed thresholds)
TracerConfig.for_testing()

# Production configuration (strict anti-poisoning)
TracerConfig.for_production()
```

### C. File Manifest

| File | Purpose |
|------|---------|
| `benchmarks/web/bench_trace_buffer.py` | Buffer operation micro-benchmarks |
| `benchmarks/web/bench_eligibility.py` | Eligibility evaluation benchmarks |
| `benchmarks/web/bench_metrics.py` | Metrics collection overhead |
| `benchmarks/web/bench_e2e_throughput.py` | End-to-end HTTP throughput |
| `benchmarks/web/generate_throughput_graph.py` | Graph generation script |
| `benchmarks/web/throughput_comparison.png` | Generated comparison graph |

---

*Report generated by PyAOT benchmark suite*

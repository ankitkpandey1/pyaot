# PyAOT-Web Vision: Trace-Based Compilation

> **Mission**: Compile *observed request execution traces*, not Python code, turning real production traffic into guarded native pipelines with zero semantic risk.

PyAOT-Web compiles observed request traces (with guards and deopt), not arbitrary Python code — prioritizing correctness and gradual rollout while delivering native hot-path latency improvements.

---

## The Key Insight

### ❌ Wrong Approach
> "Compile Python web handlers to native code"

### ✅ Correct Approach  
> "Compile **observed execution traces** of request handlers into guarded native micro-pipelines"

This is the same conceptual leap that made HotSpot, LuaJIT, V8, and CPython PEP 659 effective.

---

## Problem Statement

### The Python Web Performance Gap

| Metric | Python | Native | Gap |
|--------|--------|--------|-----|
| Requests/sec | 1-5K | 100-500K | 20-100x |
| P99 latency | 5-50ms | 0.1-1ms | 10-50x |
| Memory/request | 10-50KB | 1-5KB | 10x |

### Root Cause

```
Per-request interpreter overhead:
├── Function calls (50-100 × 150ns)     = 10-15μs
├── Object allocations (20-50 × 50ns)   = 1-5μs  
├── Attribute lookups (100+ × 30ns)     = 3-10μs
└── TOTAL                               = 15-35μs
```

**Target**: ~1μs **handler CPU work** for hot-path code (excludes network/DB I/O). Treat as aspirational — validate on target hardware.

---

## Goals & Non-Goals

| Goal | Target |
|------|--------|
| Throughput | 10-100x improvement |
| Latency | 5-10x reduction |
| Compatibility | 100% Python semantics |
| Code changes | Zero |

**Non-Goals**: Replacing CPython, compiling all Python code, matching Rust/Go exactly.

---

## Constraints

### Resource Limits

| Resource | Limit | Notes |
|----------|-------|-------|
| Guard microbudget | 200–500ns per check | validate on target hardware |
| Guard miss handling | single-digit µs | primary lever: keep miss rate low |
| Trace compilation (lightweight) | < 500ms | runtime mode |
| Trace compilation (full PGO) | < 5s | CI mode |
| Memory overhead | < 20% | |

### Trace Size Limits

| Limit | Value | Rationale |
|-------|-------|-----------|
| Max inline depth | 5 | prevent unbounded inlining |
| Max trace instructions | 200 | bound compilation time |
| Code size per route | 512KB | prevent binary bloat |
| Max traces per route | 8 | bound memory footprint |

---

## Why This Is Not LuaJIT

PyAOT-Web learns from LuaJIT's successes but explicitly addresses its production pain points:

| Issue | LuaJIT | PyAOT-Web |
|-------|--------|-----------|
| **Compilation model** | Runtime-only JIT | AOT-first: CI precompile for stable routes; runtime compilation bounded |
| **Equivalence testing** | No formal difftest | Every trace passes deterministic equivalence test vs CPython |
| **Semantic safety** | Speculative rewrites | No speculative elision of I/O, side effects, exceptions |
| **Guard poisoning** | Unbounded | Require N observations across M client prefixes + TTL |
| **Code bloat** | Unbounded inlining | Explicit code budgets and cost model |
| **Rollout** | Ship or don't | Signed artifacts, canary rollout, metric-based auto-rollback |

---

## Architecture: Trace-Based Compilation

```
┌──────────────┐
│ HTTP Request │
└──────┬───────┘
       ▼
┌──────────────────────────┐
│ Trace Selector (guards)  │
└──────┬───────────────────┘
       ▼
┌──────────────────────────────────────────┐
│ Guarded Native Trace                     │
│  - linearized execution path             │
│  - branch-weighted, allocation-free      │
└──────┬───────────────────────────────────┘
       │ pass              │ fail
       ▼                   ▼
┌──────────────┐   ┌──────────────────┐
│ Native Exit  │   │ CPython Fallback │
└──────────────┘   └──────────────────┘
```

### What is a Trace?

A linearized execution path with guards on: branch directions, object shapes, attribute offsets, call targets, exception absence.

---

## Trace Safety & Validation

### Difftest Harness (Required)

Every compiled trace must pass deterministic equivalence:
- Execute trace on both compiled path and CPython interpreter
- Compare: status code, headers, body (byte-for-byte)
- Fuzz mode: mutate inputs to find divergence
- Run on every CI build and before canary promotion

### Replay Format (Versioned)

```protobuf
message TraceRecord {
  uint32 version = 1;
  string route_id = 2;
  bytes request_body_hash = 3;
  repeated BranchDecision branches = 4;
  repeated AttrOffset attrs = 5;
  repeated CallTarget calls = 6;
  uint64 timestamp_ns = 7;
  bytes checksum = 8;
}
```

### Anti-Poisoning Requirements

| Rule | Value |
|------|-------|
| Min observations before compile | 100 |
| Min distinct client IP prefixes | 3 |
| Observation window | 1 hour minimum |
| Trace TTL | 24 hours (re-validate) |
| Reject single-shot traces | Always |

### Side-Effect Safety

Traces must NOT speculatively reorder or elide:
- Database writes
- Time/randomness reads
- External API calls
- Logging with observable effects

Mark side-effecting operations in Trace IR. Paths with side effects stay interpreted or use strict ordering guards.

---

## Compilation Modes

### Mode A: CI Precompile (Stable Routes)

- Full LLVM optimization + PGO
- Compile time: up to 5s per trace
- Produces signed, versioned artifacts
- Deployed via feature flags

### Mode B: Runtime Lightweight AOT (Emergent Traces)

- Minimal optimization, fast codegen
- Compile time: < 500ms
- Background promotion to full optimization
- Auto-disabled on high guard miss rate

---

## Compiler Heuristics

| Heuristic | Threshold |
|-----------|-----------|
| Inline callees | call_count > 1000 AND callee_size < 50 ops AND miss_rate < 2% |
| Max inline depth | 5 |
| Max trace instructions | 200 |
| Scalar replacement | fields < 5 AND does not escape |
| Dict → tuple | ≤3 string keys |
| Code size per route | 512KB |

---

## Observability & SLOs

| Metric | Alert Threshold |
|--------|-----------------|
| `py_aot.trace.guard_miss_rate` | > 5% → retrace; > 15% → auto-rollback |
| `py_aot.trace.compiled_hit_rate` | < 80% → investigate coverage |
| `py_aot.trace.compilation_error_rate` | > 1% → pause compilation |
| `py_aot.trace.fallback_rate` | > 50% → review trace quality |
| `py_aot.perf.hotpath_cpu_ns` | histogram, P99 target |

**Guard-miss rate is the first-class rollback signal.**

---

## Trace Lifecycle

| Trigger | Action |
|---------|--------|
| Code deploy | Invalidate traces for changed routes |
| guard_miss_rate > threshold | Retrace |
| New shape above support count | Extend/replace trace |
| TTL (24h) | Re-validate |

---

## Testing Checklist

- [ ] **Difftest**: 100% deterministic equivalence on recorded traces
- [ ] **Microbench**: TechEmpower-style (branch, alloc, attr heavy)
- [ ] **Real-app**: FastAPI + DB, Django list, Flask form
- [ ] **Chaos**: Guard-miss spikes → verify safe fallback
- [ ] **Performance**: Measure guard overhead on target hardware

---

## Implementation Phases (12 Weeks)

| Week | Deliverable |
|------|-------------|
| 0-2 | TraceRecorder prototype, storage schema |
| 2-6 | Trace IR, naive LLVM lowering, guard stubs |
| 6-10 | Difftest harness, equivalence tests, microbench |
| 10-12 | Scalar replacement, inlining, canary deploy |

---

## Success Metrics

| Metric | Baseline | Goal | Validated |
|--------|----------|------|-----------|
| Hot path CPU | 500μs | 50μs | TBD |
| Guard miss rate | N/A | < 5% | TBD |
| Compiled hit rate | 0% | > 80% | TBD |

---

## References

- [LuaJIT](http://luajit.org/)
- [HotSpot](https://openjdk.org/groups/hotspot/)
- [CPython PEP 659](https://peps.python.org/pep-0659/)
- [Meta Cinder](https://github.com/facebookincubator/cinder)

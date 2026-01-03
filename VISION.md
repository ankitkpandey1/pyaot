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

## Research Contributions

This work does not claim novelty in trace-based compilation itself. Instead, it makes new contributions in making tracing **sound, practical, and production-safe** for Python web workloads — a domain where prior tracing systems have largely failed or deliberately avoided deployment.

### 1. Request-Level Trace Compilation (New Granularity)

We introduce **request-execution traces** as a compilation unit, shifting tracing from intra-program repetition (loops) to population-level repetition (similar requests across users).

**Why this is new**: Prior trace-based systems (LuaJIT, PyPy, HotSpot C1) assume hot loops and optimize long-running code paths. Web handlers often contain no loops, are short-lived, and exhibit repetition *across requests*, not within one request.

This work formalizes tracing under a **statistical repetition model**: if a request shape repeats across users with high probability, its execution path can be safely specialized.

### 2. Trace Safety Under Side Effects (Unsolved in Prior Work)

We define **trace cut rules** and **guard placement constraints** that preserve Python semantics in the presence of I/O, ORM/database access, authentication state, exceptions, and mutable global objects.

**Key insight**: In web workloads, side effects dominate. Traces must be linear, side-effect respecting. No speculative reordering or elision is permitted. We treat side effects as **trace boundaries**, not optimizable instructions.

### 3. Zero-Risk Speculation via Deterministic Fallback

We propose a **zero semantic risk model** for speculative compilation:
- Guarded execution
- Deterministic interpreter fallback
- Transactional trace boundaries

Every compiled trace satisfies: for all inputs satisfying its guards, native execution is observationally equivalent to CPython execution. If any guard fails, execution transfers to the interpreter without partial side effects or state corruption.

### 4. Adversarial Trace Resilience (New Problem Space)

We identify and address **trace poisoning** as a first-class problem. Unlike classic JITs, web workloads are untrusted, input-controlled, and potentially adversarial.

We introduce:
- Multi-observation trace eligibility thresholds
- Provenance tracking (route, signature, environment)
- Guard-miss–driven invalidation
- Time-based trace TTLs

This prevents attackers from inducing pathological traces via crafted requests — a problem not considered in earlier tracing literature.

### 5. Trace IR for Semantic-Preserving Lowering

We introduce a **Trace Intermediate Representation (Trace IR)** that captures observed control flow, guard predicates, object shape access, and allocation intent (elidable vs materialized).

Trace IR is linear, side-effect aware, and explicitly guarded. This avoids lifting Python AST or bytecode directly to LLVM, enabling precise scalar replacement, guard coalescing, controlled inlining, and deterministic lowering.

### 6. CPython-Compatible Trace Compilation (Legacy-Constrained Design)

We demonstrate that trace-based native execution is possible **without modifying CPython** while preserving C-extension interoperability, reference counting semantics, exception behavior, and interpreter invariants.

Unlike PyPy or LuaJIT, this system does not own the VM, cannot alter the object model, and must interoperate with opaque C extensions. This explores **compiler–runtime co-design under strict legacy constraints**.

### 7. Allocation Elimination in Allocation-Dominated Workloads

We show that most web handler allocations are **logical, not semantic**, and can be eliminated via scalar replacement, stack allocation, and direct serialization from registers.

Unlike numeric workloads, these allocations are short-lived, do not escape, and exist primarily for convenience. We formalize allocation elimination rules specific to web handlers.

### 8. Production-Safe Deployment Model

We propose a deployment model combining:
- Observation-first compilation
- Deterministic difftesting
- Canary rollout
- Guard-miss–driven rollback

This closes the gap between research JITs and real-world deployment requirements, addressing why many prior systems failed operationally despite technical success.

### 9. Empirical Characterization of Web Trace Viability

We provide empirical characterization of:
- Which web handler patterns are traceable
- Guard-miss behavior under real traffic
- Trace stability over time
- Cost/benefit of specialization

This answers an open question: *Is trace-based compilation viable for Python web workloads at all?* We show it is — under the constraints defined in this work.

### Summary of Novelty

This work does not invent tracing. It redefines **where tracing is viable**, **how it must be constrained**, and **how it can be made safe** for Python web systems.

| Contribution | Domain |
|--------------|--------|
| Request-level tracing | New granularity |
| Side-effect safety | New correctness constraints |
| Anti-poisoning | New adversarial considerations |
| Difftest + canary | New deployment guarantees |

---

## References

- [LuaJIT](http://luajit.org/)
- [HotSpot](https://openjdk.org/groups/hotspot/)
- [CPython PEP 659](https://peps.python.org/pep-0659/)
- [Meta Cinder](https://github.com/facebookincubator/cinder)


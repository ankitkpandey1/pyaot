# PyAOT-Web Vision: Trace-Based Compilation

> **Mission**: Compile *observed request execution traces*, not Python code, turning real production traffic into guarded native pipelines with zero semantic risk.

PyAOT-Web compiles observed request traces (with guards and deopt), not arbitrary Python code — prioritizing correctness and gradual rollout while delivering native hot-path latency improvements.

The tracer never emits LLVM or native code. Native code is emitted only by the existing PyAOT compiler, after traces become eligible and are converted into guard and deoptimization annotations.

---

## The Key Insight

### ❌ Wrong Approach
> "Compile Python web handlers to native code"

### ✅ Correct Approach  
> "Compile **observed execution traces** of request handlers into guarded native micro-pipelines"

This is the same conceptual leap that made HotSpot, LuaJIT, V8, and CPython PEP 659 effective.

## Responsibility Split

### Tracer
Observes execution and emits metadata only:
execution-path fingerprints, guard conditions, and deoptimization metadata.

### PyAOT Compiler (existing)
Owns all lowering and code generation:
Python → LLVM → native code, inserting guards and deopt calls using tracer metadata.

### LLVM
Performs optimization and native code emission.

No new IR is introduced.

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

**Target**: ~1μs **handler CPU work** for hot-path code (excludes network/DB I/O). Treat as aspirational — validate on target hardware — report the hardware config used (CPU family, clocks, NUMA, kernel).

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
| Guard microbudget | target 200–500ns per check | **measure and validate on target hardware**; treat as goal not guarantee |
| Guard miss handling | expected single-digit µs to transfer control | materialization costs may add µs — keep miss-rate low |
| Trace compilation (lightweight) | target < 500ms | specify worst-case and median from telemetry |
| Trace compilation (full PGO) | < 5s | CI mode |
| Memory overhead | < 20% | |

### Trace Size Limits

| Limit | Value | Rationale |
|-------|-------|-----------|
| Max inline depth | 5 | prevent unbounded inlining |
| Max trace instructions | 200 | bound compilation time |
| Code size per route | 512KB | prevent binary bloat |
| Max traces per route | 8 | bound memory footprint |

### Inlining Cost Model

```
benefit_score = call_count * estimated_cycles_saved - code_size_penalty
```

Inline if `benefit_score > threshold`. Use as compile heuristic to prevent code bloat.

---

## Why This Is Not LuaJIT

| Issue | LuaJIT | PyAOT-Web |
|-------|--------|-----------|
| **Compilation model** | Runtime-only JIT | AOT-first: CI precompile for stable routes |
| **Equivalence testing** | No formal difftest | Every trace passes deterministic equivalence test |
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

**Difftest policy**: All recorded canonical traces must pass 100% byte-for-byte equivalence on CI. Fuzzed trace checks require no divergences for a sampled set of N=1000. Any divergence fails the build; divergences must be triaged as either a compiler bug or a necessary semantic restriction.

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
| Min observations before compile | 100 (recommend tuning via telemetry; require observations from ≥3 distinct subnets) |
| Min distinct client IP prefixes | 3 |
| Observation window | 1 hour minimum |
| Trace TTL | 24 hours (re-validate) |
| Reject single-shot traces | Always |

**Rationale**: These thresholds prevent single-attacker poisoning while allowing legitimate hot paths to compile. Tune from telemetry during canary phase.

### Side-Effect Safety

Traces must NOT speculatively reorder or elide:
- Database writes
- Time/randomness reads
- External API calls
- Logging with observable effects

Mark side-effecting operations in Trace IR. Paths with side effects stay interpreted or use strict ordering guards.

**Transactional Deopt**: Compiled traces must not commit partial external side effects. If a compiled path would reach a point that commits externally (DB write, external API call), it must either (a) include a guard ensuring the path is safe for commit, or (b) transfer control back to the interpreter before commit. Deopt must be transactional: either complete native path or transfer to interpreter before any external commit.

---

## Compilation Modes

### Mode A: CI Precompile (Stable Routes)

- Full LLVM optimization + PGO
- Compile time: up to 5s per trace
- Produces signed, versioned artifacts
- Deployed via feature flags

### Mode B: Runtime Lightweight AOT (Emergent Traces)

- Minimal optimization, fast codegen
- Compile time: target < 500ms
- Background promotion to full optimization
- Auto-disabled on high guard miss rate

**Note**: Runtime lightweight code is intended as short-lived; background promotion to full PGO artifacts must be opt-in and rate-limited to prevent resource exhaustion.

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

| Metric | Type | Alert Threshold |
|--------|------|-----------------|
| `py_aot.trace.guard_miss_rate` | gauge | > 5% → retrace; > 15% → auto-rollback |
| `py_aot.trace.compiled_hit_rate` | gauge | < 80% → investigate coverage |
| `py_aot.trace.compilation_error_rate` | gauge | > 1% → pause compilation |
| `py_aot.trace.fallback_rate` | gauge | > 50% → review trace quality |
| `py_aot.perf.hotpath_cpu_ns` | histogram (p50/p95/p99) | track regression |

**Guard-miss rate is the first-class rollback signal.**

---

## Testing & Rollout Checklist

### CI Gating

- [ ] Difftest pass for all recorded traces → artifact signed
- [ ] No artifact may be promoted to canary without passing difftest and static safety checks

### Canary Deployment

- [ ] Deploy artifacts to 1–5% traffic
- [ ] Watch `guard_miss_rate`, latency, error-rate for 15 minutes

### Auto-Rollback Rules

- [ ] If `guard_miss_rate > 15%` for 5 minutes → rollback
- [ ] If p95 latency regresses > 10% → rollback
- [ ] Auto-disable compiled traces for affected route

### Telemetry Tuning

- [ ] After 1 week, use observed miss rates to tune min-observations and TTL

---

## Trace Lifecycle

| Trigger | Action |
|---------|--------|
| Code deploy | Invalidate traces for changed routes |
| guard_miss_rate > threshold | Retrace |
| New shape above support count | Extend/replace trace |
| TTL (24h) | Re-validate |

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
| Hot path CPU | 500μs | 50μs | TBD (measure on target hardware) |
| Guard miss rate | N/A | < 5% | TBD |
| Compiled hit rate | 0% | > 80% | TBD |

---

## Research Contributions

This work does not claim novelty in trace-based compilation itself. Instead, it makes new contributions in making tracing **sound, practical, and production-safe** for Python web workloads — a domain where prior tracing systems have largely failed or deliberately avoided deployment.

### 1. Request-Level Trace Compilation (New Granularity)

We introduce **request-execution traces** as a compilation unit, shifting tracing from intra-program repetition (loops) to population-level repetition (similar requests across users).

**Why this is new**: Prior trace-based systems (LuaJIT, PyPy, HotSpot C1) assume hot loops. Web handlers exhibit repetition *across requests*, not within one request. This work formalizes tracing under a **statistical repetition model**.

### 2. Trace Safety Under Side Effects

We define **trace cut rules** and **guard placement constraints** that preserve Python semantics in the presence of I/O, ORM access, authentication state, exceptions, and mutable globals. We treat side effects as **trace boundaries**, not optimizable instructions.

### 3. Zero-Risk Speculation via Deterministic Fallback

We propose a **zero semantic risk model**: guarded execution, deterministic interpreter fallback, transactional trace boundaries. If any guard fails, execution transfers to the interpreter without partial side effects.

### 4. Adversarial Trace Resilience

We address **trace poisoning** as a first-class problem via multi-observation thresholds, provenance tracking, guard-miss–driven invalidation, and time-based TTLs.

### 5. Trace IR for Semantic-Preserving Lowering

We introduce **Trace IR** — linear, side-effect aware, explicitly guarded — avoiding direct Python AST → LLVM lowering.

### 6. CPython-Compatible Trace Compilation

Trace-based native execution **without modifying CPython**, preserving C-extension interop, refcounting, and exception behavior.

### 7. Allocation Elimination in Web Workloads

Most web handler allocations are **logical, not semantic**, and can be eliminated via scalar replacement and stack allocation.

### 8. Production-Safe Deployment Model

Observation-first compilation, deterministic difftesting, canary rollout, guard-miss–driven rollback.

### 9. Empirical Characterization

We characterize which web handler patterns are traceable, guard-miss behavior, trace stability, and cost/benefit of specialization.

### Summary of Novelty

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

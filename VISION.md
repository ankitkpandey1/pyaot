# PyAOT-Web Vision: Trace-Based Compilation

> **Mission**: Compile *observed request execution traces*, not Python code, turning real production traffic into guarded native pipelines with zero semantic risk.

PyAOT-Web compiles observed request traces (with guards and deopt), not arbitrary Python code — prioritizing correctness and gradual rollout while delivering native hot-path latency improvements.

---

## The Key Insight

### ❌ Wrong Approach
> "Compile Python web handlers to native code"

### ✅ Correct Approach  
> "Compile **observed execution traces** of request handlers into guarded native micro-pipelines"

This is the same conceptual leap that made:
- JVM HotSpot viable
- LuaJIT successful  
- V8 TurboFan effective
- CPython adaptive interpreter (PEP 659) workable

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
├── Branch dispatch overhead            = 2-5μs
└── TOTAL                               = 15-35μs
```

**Target**: ~1μs **handler CPU work** for hot-path code (excludes network/DB I/O). End-to-end P99 depends on I/O and network.

---

## What We Are Trying to Achieve

### Goals

| Goal | Target |
|------|--------|
| Throughput | 10-100x improvement |
| Latency | 5-10x reduction |
| Compatibility | 100% Python semantics |
| Code changes | Zero |
| Production safety | Zero crashes |

### Non-Goals

- Replacing CPython
- Compiling all Python code
- Matching Rust/Go exactly (target: 80% performance, 100% Python)

---

## Constraints

### Must Have

| Constraint | Rationale |
|------------|-----------|
| CPython compatibility | Standard interpreter, no forks |
| Safe fallback | Any failure → Python execution |
| Profile-first | No compilation without observation |
| Semantic preservation | Identical results to Python |

### Resource Limits

| Resource | Limit | Notes |
|----------|-------|-------|
| Guard microbudget | target <200–500ns per guard check | validate on hardware |
| Guard miss handling | expected single-digit µs to transfer to interpreter | minimize by lowering miss rate |
| Compilation overhead | < 5% startup time | |
| Memory overhead | < 20% | |
| Trace compilation time | < 100ms (goal/optimistic) | requires measured CI validation |

---

## Architecture: Trace-Based Compilation

### Core Concept

Instead of compiling entire handlers, compile **trace segments**:

```
┌──────────────┐
│ HTTP Request │
└──────┬───────┘
       ▼
┌──────────────────────────┐
│ Route Dispatcher         │  (Python, guard-checked)
└──────┬───────────────────┘
       ▼
┌──────────────────────────┐
│ Trace Selector           │
│  - request signature     │
│  - route + auth + shape  │
└──────┬───────────────────┘
       ▼
┌──────────────────────────────────────────┐
│ Guarded Native Trace                     │
│  - linearized execution path             │
│  - branch-weighted                       │
│  - allocation-free (scalar replacement)  │
│  - no Python objects unless required     │
└──────┬───────────────────────────────────┘
       │                          │
       │ guards pass              │ guards fail
       ▼                          ▼
┌──────────────┐         ┌──────────────────┐
│ Native Exit  │         │ CPython Fallback │
└──────────────┘         └──────────────────┘
```

### What is a Trace?

A **trace segment** is:
- A linearized execution path through a handler
- Observed during profiling
- With explicit guards on:
  - Branch directions taken
  - Object shapes encountered
  - Attribute offsets accessed
  - Call targets resolved
  - Exception absence (no try/except triggered)

This avoids full control flow graph explosion.

---

## Example: Multi-Trace Compilation

### Original Handler

```python
def get_user(id):
    if not current_user.is_authenticated:
        return {'error': 'Unauthorized'}, 401
    user = User.query.get(id)
    if not user:
        return {'error': 'Not found'}, 404
    return {'id': user.id, 'name': user.name}
```

### Compiled as Multiple Traces

**Trace A (hot, 90% of requests)**
```
GUARDS:
  - current_user.is_authenticated == True
  - User.query.get returns non-null
  - user.__dict__ layout == Shape#42
  
TRACE:
  load_attr current_user.is_authenticated offset=48
  branch_taken  
  call db_fast_path(id)
  guard_nonnull result
  load_attr user.id offset=16
  load_attr user.name offset=24
  serialize_fast
  return 200
```

**Trace B (cold, 5%)**: auth failed → fallback to Python

**Trace C (cold, 5%)**: user not found → fallback to Python

**Result**: Hot path is native, cold paths stay Python. Safety intact.

---

## New Subsystems (Delta from Current PyAOT)

### 1. Trace Recorder ⭐ (Most Important)

**Not a profiler. A tracer.**

Records during observation:
- Bytecode instructions executed
- Branch decisions (taken/not taken)
- Call targets (resolved function pointers)
- Attribute offsets (dict key positions)
- Allocation sites (for elimination candidates)

Bounded by route + request signature.

```python
TraceRecord(
    route='/api/user/<id>',
    signature=('int',),
    branches=[(12, True, 0.95), (18, True, 0.90)],
    attrs=[('user', 'id', 16), ('user', 'name', 24)],
    calls=[('User.query.get', 0x7f...)],
)
```

### 2. Trace IR (New Layer)

**Do not lift Python AST directly to LLVM.**

Introduce intermediate Trace IR:

```
GUARD_TYPE r0, User
GUARD_SHAPE r0, Shape#42
LOAD_ATTR_FAST r1, r0, offset=16    ; user.id
LOAD_ATTR_FAST r2, r0, offset=24    ; user.name
BRANCH_LIKELY label_success, prob=0.95
ALLOC_ELIDED r3, dict
CALL_DIRECT serialize_user, r1, r2
RETURN r3
```

Then lower Trace IR → LLVM IR.

Trace IR should be serializable and versioned. Include a canonicalizer pass to coalesce equivalent guards across traces.

This enables:
- Branch weighting
- Allocation removal (scalar replacement)
- Call inlining
- Guard coalescing

### 3. Guarded Entry Stub

Every compiled trace begins with guard checks:

```llvm
entry:
  %g1 = call i1 @guard_type(%arg0, @User)
  br i1 %g1, label %g2_check, label %fallback
g2_check:
  %g2 = call i1 @guard_shape(%arg0, 42)
  br i1 %g2, label %hot_path, label %fallback
hot_path:
  ; native trace execution
fallback:
  tail call @python_interpreter(...)
```

Requirements:
- Stub must be < 20 instructions
- Predictable branch layout
- Guard coalescing optimization: merge initial guard sets across traces to reduce stub overhead

### 4. Allocation Strategy (Priority Order)

1. **Scalar replacement** — Split objects into registers
2. **Stack allocation** — Short-lived, non-escaping objects
3. **Arena allocation** — Only when escape analysis fails

Most web handlers allocate *logically*, not *physically*. Scalar replacement handles 80% of cases.

### 5. Compiler Heuristics

| Heuristic | Threshold |
|-----------|-----------|
| Inline callees | call_count > 1000 AND callee_size < 50 IR ops AND guard_miss_rate < 2% |
| Max inline depth | 4 levels to avoid code bloat |
| Scalar replacement | object fields used < 5 times AND does not escape |
| Dict → tuple conversion | ≤3 keys, all string literals |
| Memory pools | emit for common shapes; fallback to PyObjects on miss |

---

## Engineering Controls

### Trace Validity Testing (Difftest)

Automated equivalence runner:
- Execute N recorded traces on both interpreter and compiled code
- Compare outputs byte-for-byte (JSON body + status code + headers)
- Fuzz-mode: mutate inputs to find edge cases
- Run on every CI build

### Deterministic Recording Format

Trace record format (protobuf or flatbuffers):
- Route ID
- Input bytes (headers, body hash)
- Branch map with taken/not-taken
- Attribute offsets accessed
- Resolved call addresses
- Timestamps
- Sampled stack trace
- Checksum + format version

### Safe Rollout / Canary Model

- Compiled artifacts must be signed and versioned
- Runtime supports percentage rollout (e.g., 1% → 10% → 100%)
- Per-route enable flags
- Auto-disable if guard_miss_rate or error_rate spike above threshold
- Metrics-driven rollback

### Security Considerations

Threat model:
- Attacker submits malicious headers/inputs to trigger abnormal traces
- Trace poisoning could cause wrong guards to be compiled

Mitigations:
- Only compile traces above high confidence threshold (e.g., >1000 observations)
- Require multiple independent observations matching same pattern
- Hash inputs and reject outlier signatures
- Sign compiled artifacts

---

## Trace Lifecycle & Invalidation

**Guard-miss rate is the primary control knob.**

| Trigger | Action |
|---------|--------|
| Code deploy (CI artifact bump) | Invalidate all traces for changed routes |
| guard_miss_rate > 5% for 5 minutes | Trigger re-profiling |
| New shape observed (new attr offset, new call target) above support count | Extend or replace trace |
| TTL (24-72 hours) | Re-evaluate trace validity |
| Manual flag | Force retrace via admin API |

---

## Observability Metrics

First-class metrics (wire to dashboards and SLOs):

| Metric Name | Type | Description |
|-------------|------|-------------|
| `py_aot.trace.executions` | counter | Total trace executions |
| `py_aot.trace.guard_misses` | counter | Guard check failures |
| `py_aot.trace.guard_miss_rate` | gauge | guard_misses / executions |
| `py_aot.trace.compilation_time_ms` | histogram | Time to compile trace |
| `py_aot.trace.compiled_hit_rate` | gauge | Requests served by native traces |
| `py_aot.trace.fallback_rate` | gauge | Requests that fell back to Python |
| `py_aot.perf.cpu_ns_per_request_hotpath` | histogram | CPU time in native hot path |
| `py_aot.memory.arena_alloc_bytes_per_request` | histogram | Arena memory per request |

**Alert thresholds**:
- `guard_miss_rate > 5%` → trigger retrace
- `guard_miss_rate > 15%` → auto-disable trace, rollback to Python
- `fallback_rate > 50%` → investigate trace coverage

---

## Deployment Model

- **Stable routes**: Prefer simple precompilation in CI for routes that rarely change
- **Dynamic workloads**: Live AOT compilation based on runtime observation
- **Developer hint API** (optional): `@py_aot.hint(stable=True)` to mark high-confidence code for eager compilation

---

## Testing & Validation Checklist

| Category | Requirement |
|----------|-------------|
| Microbench | TechEmpower-style benchmark: branch-heavy, allocation-heavy, attr-heavy handlers |
| Real-app | Run on 3 apps: FastAPI hello+db, Django list endpoint, Flask form validation |
| Equivalence | 100% deterministic difftest on N most common routes |
| Chaos | Inject guard-miss spikes, verify safe fallback, no data loss |
| Performance | Measure guard check overhead on target hardware |

---

## Implementation Phases (0-12 Weeks)

### Week 0–2: Trace Recorder Prototype
- [ ] Implement minimal TraceRecorder (per-route, record branch & attr offsets)
- [ ] Define storage schema (protobuf)
- [ ] Add ingest pipeline

### Week 2–6: Trace IR + Naive Lowering
- [ ] Define Trace IR opcodes
- [ ] Implement TraceIR → naive LLVM lowering (no optimizations)
- [ ] Add guard stub generator
- [ ] Basic end-to-end: record → compile → execute

### Week 6–10: Difftest + Benchmarks
- [ ] Integrate difftest harness
- [ ] Add equivalence tests for recorded traces
- [ ] Run TechEmpower-style microbenchmark
- [ ] Measure baseline guard overhead

### Week 10–12: Optimizations + Canary
- [ ] Implement scalar replacement
- [ ] Add simple inlining heuristics
- [ ] Measure guard miss rates and compiled hit rates
- [ ] Deploy canary with 1% traffic

---

## Success Metrics

| Metric | Baseline | Target (Goal) | Target (Validated) |
|--------|----------|---------------|-------------------|
| Hot path CPU time | 500μs | 50μs | TBD (measure) |
| Guard miss rate | N/A | < 5% | TBD (measure) |
| Trace compilation time | N/A | < 100ms | TBD (measure) |
| Guard check overhead | N/A | < 500ns | TBD (measure) |
| Compiled hit rate | 0% | > 80% | TBD (measure) |
| Requests/sec | 5K | 50K | TBD (measure) |

---

## Open Questions

1. **Trace recording granularity**: Per-route? Per-signature? Per-branch-path?
2. **Trace invalidation policy**: How aggressive on code changes?
3. **Framework integration**: Hooks for Flask/FastAPI/Django?
4. **Guard coalescing**: Best strategy for multi-trace routes?

---

## References

- LuaJIT: http://luajit.org/
- HotSpot: https://openjdk.org/groups/hotspot/
- CPython PEP 659: https://peps.python.org/pep-0659/
- Meta Cinder: https://github.com/facebookincubator/cinder

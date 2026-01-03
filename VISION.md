# PyAOT-Web Vision: Trace-Based Compilation

> **Mission**: Compile *observed request execution traces*, not Python code, turning real production traffic into guarded native pipelines with zero semantic risk.

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

**Target**: 1μs per request (1M req/sec)

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

| Resource | Limit |
|----------|-------|
| Guard overhead | < 100ns per trace entry |
| Compilation overhead | < 5% startup time |
| Memory overhead | < 20% |
| Guard miss handling | < 500ns fallback |

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

**Trace B (cold, 5%)**
```
auth failed → fallback to Python
```

**Trace C (cold, 5%)**  
```
user not found → fallback to Python
```

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
# Produces:
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
- Guard miss cost < 100ns

### 4. Allocation Strategy (Corrected)

**Priority order:**

1. **Scalar replacement** — Split objects into registers
2. **Stack allocation** — Short-lived, non-escaping objects
3. **Arena allocation** — Only when escape analysis fails

Most web handlers allocate *logically*, not *physically*. Scalar replacement handles 80% of cases.

```python
# Before: allocates dict
return {'id': user.id, 'name': user.name}

# After scalar replacement: no allocation
# id and name are in registers, serialized directly
```

### 5. Guard Miss Tracking

Guard miss rate is a **first-class metric**:

```python
@dataclass
class TraceStats:
    trace_id: str
    executions: int
    guard_misses: int
    miss_rate: float  # If > 5%, consider retracing
```

If miss rate exceeds threshold → trigger re-profiling and recompilation.

---

## GIL Strategy (Realistic)

### Phase 1: Hold GIL, Reduce Traffic

Native trace runs **while holding GIL**, but:
- No Python API calls in hot path
- No refcount operations (scalar replacement)
- No object allocations

This reduces contention dramatically without GIL bypass complexity.

### Phase 2: Sub-Interpreter Isolation (Future)

Move traces to per-interpreter model (PEP 684):
- Each worker gets own interpreter
- No shared GIL
- True parallelism

This is realistic and SOTA-2026.

---

## I/O Reality Check

### Cannot Compile

- Full database access end-to-end
- Network I/O
- File system operations

### Can Compile

- **Result decoding**: row → object → dict
- **Serialization**: object → JSON bytes
- **Validation**: request → validated params

These alone yield large wins (50-100% improvement).

---

## Comparison: Before and After

### Current PyAOT (v0.x)

```
Scope: Leaf numerical functions only
Model: Compile function → LLVM
Guard: Type guards on arguments
```

### PyAOT-Web (v1.0)

```
Scope: Request execution traces
Model: Record trace → Trace IR → LLVM
Guard: Type + Shape + Branch + Call guards
Multi-trace: Hot/cold path separation
```

---

## Implementation Phases

| Phase | Subsystem | Impact |
|-------|-----------|--------|
| 1 | Trace Recorder | Foundation |
| 2 | Trace IR + Lowering | Core compilation |
| 3 | Guard generation | Safety |
| 4 | Scalar replacement | Allocation elimination |
| 5 | Branch weighting | Prediction optimization |
| 6 | Result decoding specialization | I/O edge gains |

---

## Success Metrics

| Metric | Baseline | Target |
|--------|----------|--------|
| Hot path latency | 500μs | 50μs |
| Guard miss rate | N/A | < 5% |
| Trace compilation time | N/A | < 100ms |
| Fallback cost | N/A | < 500ns |
| Requests/sec | 5K | 50K |

---

## Why This Architecture is Credible

Aligns with proven systems:
- **HotSpot**: Tiered compilation, trace-based optimization
- **LuaJIT**: Trace recording, guard-based execution
- **V8 TurboFan**: Speculative optimization with deopt
- **CPython PEP 659**: Adaptive specialization

Avoids common mistakes:
- ❌ "Compile all Python" fantasy
- ❌ Unsound static typing assumptions
- ❌ Framework-specific hacks
- ❌ GIL bypass before basic optimization

---

## Open Questions

1. **Trace recording granularity**: Per-route? Per-signature? Per-branch-path?
2. **Trace invalidation**: When to re-record after code changes?
3. **Framework integration**: Hooks for Flask/FastAPI/Django?
4. **Observability**: How to expose trace stats to developers?

---

## References

- LuaJIT: http://luajit.org/
- HotSpot: https://openjdk.org/groups/hotspot/
- CPython PEP 659: https://peps.python.org/pep-0659/
- Meta Cinder: https://github.com/facebookincubator/cinder

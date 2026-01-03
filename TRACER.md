# PyAOT-Web Tracer

**Final Design Specification v1.0**

> **Goal**: Record *sound, stable, replayable request execution traces* suitable for guarded native compilation, with zero semantic risk, bounded cost, and adversarial resilience.

---

## 0. Design Axioms (Non-Negotiable)

1. **Tracing is observational, never speculative**
   The tracer records *what actually happened*. It does not predict, infer, or rewrite behavior.

2. **Tracing must be side-effect safe**
   Traces must not reorder, elide, or partially observe side effects.

3. **Tracing must be adversarially robust**
   Untrusted inputs must not poison traces.

4. **Tracing cost must be bounded**
   Tracing must not exceed a small, predictable overhead and must never cause unbounded memory growth.

5. **Every trace must be replayable and difftestable**
   If it cannot be replayed against CPython, it is invalid.

---

## 1. What the Tracer Does (Scope)

The tracer records **request-execution traces**:

- Entry at framework boundary (route handler)
- Linearized execution path
- Only *executed* instructions
- Only *observed* control flow
- Only *actual* call targets
- Only *actual* object shapes / offsets

It explicitly does **not**:

- Infer types beyond observation
- Record unexecuted branches
- Trace across side-effect commits
- Follow asynchronous continuations

---

## 2. Tracing Granularity

### Unit of Tracing

```
(route_id, request_signature, execution_path_id)
```

Where:
- `route_id`: framework-level route (string or numeric ID)
- `request_signature`: stable abstraction of request (types + shape)
- `execution_path_id`: branch path fingerprint

### Request Signature Definition

A request signature is a **coarse, stable abstraction**, not raw input:

```python
(
  HTTP_method,
  path_template,
  auth_state,
  param_types,
  header_shape_hash,
  body_shape_hash
)
```

**Never include raw values**. Only shapes.

---

## 3. Trace Lifecycle (State Machine)

```
DISABLED
   ↓ (route becomes hot)
OBSERVING
   ↓ (stable & safe)
ELIGIBLE
   ↓ (compiled)
ACTIVE
   ↓ (guard miss / TTL / code change)
INVALIDATED
```

### State Transitions

| From | To | Condition |
|------|----|-----------| 
| OBSERVING | ELIGIBLE | meets eligibility rules |
| ELIGIBLE | ACTIVE | compilation successful |
| ACTIVE | INVALIDATED | guard miss spike, TTL, code change |
| INVALIDATED | OBSERVING | re-observe |

---

## 4. Eligibility Rules (Anti-Poisoning Core)

A trace is **eligible** only if **all** hold:

| Rule | Value |
|------|-------|
| Minimum executions | ≥ 100 |
| Distinct client prefixes | ≥ 3 |
| Observation window | ≥ 1 hour |
| Branch stability | ≥ 95% identical |
| Shape stability | no new shapes in last 20% |
| Side-effect safety | no unsafe commits |
| Trace length | ≤ 200 instructions |

If *any* rule fails → trace is **discarded**.

This is the single most important defense against poisoning.

---

## 5. What Exactly Is Recorded

### 5.1 Control Flow

- Branch taken/not taken
- Branch frequency
- Branch order

### 5.2 Data Flow

- Local variable loads
- Attribute reads with resolved offsets
- Constant loads
- Primitive operations

### 5.3 Calls

Call targets are identified by a **stable content hash**, not raw pointers:

```python
call_target_id = hash(
    function.__code__.co_code,
    function.__code__.co_consts,
    function.__code__.co_names,
    qualified_name,
    defining_module_version
)
```

- Runtime pointers may be used transiently during observation
- Persisted traces always store the hash
- Code deploy → hash mismatch → trace invalidated

Also recorded:
- Call arity
- Return shape (nullable / non-null)

### 5.4 Allocations

- Allocation site ID
- Type hint
- Escape status (does value escape trace?)

### 5.5 Side-Effects (Critical)

Each instruction is marked as:

- `PURE`
- `LOCAL_MUTATION`
- `EXTERNAL_COMMIT` (DB write, I/O, etc.)

`EXTERNAL_COMMIT` **ends trace** unless explicitly allowed.

---

## 6. Trace Boundaries (Hard Stops)

The tracer must **stop** (and discard tail) when encountering:

- External I/O commit
- Non-deterministic operation (time, randomness)
- Exception thrown (unless trace explicitly guards `no-exception`)
- Async boundary (`await`)
- Yield / generator
- C-extension call without purity annotation
- Dynamic code execution (`eval`, `exec`)
- Thread interaction

This is what makes the tracer *sound*.

---

## 7. Trace Recording Mechanism

### Instrumentation Strategy

**Hybrid CPython bytecode instrumentation + runtime hooks**

Why:
- Bytecode gives precise semantics
- Runtime hooks give shape/call resolution
- No CPython fork required

### Hooks Installed At:

- Function entry (route handler)
- Bytecode dispatch loop (select opcodes only)
- Attribute access resolution
- Call dispatch
- Exception check
- Allocation

Only **whitelisted opcodes** are traced.

---

## 8. Trace Buffer Design (Bounded & Safe)

### Per-Request Trace Buffer

- Fixed-size ring buffer (initial size: 256 ops; tunable via telemetry)
- Overflow → tracing stops for this request, trace discarded

Rationale:
- 256 covers >99% of observed web handler paths
- Overflow → trace discarded, never truncated

### Entry Format (Compact)

```c
struct TraceOp {
  opcode_id;
  operand_ids;
  metadata_id;
}
```

Metadata tables (deduplicated):
- Shape table
- Call target table
- Constant table

This keeps per-request overhead predictable.

---

## 9. Trace IR Emission

Tracer emits trace annotations over the existing PyAOT IR.

### Emission Rules

- One Trace IR instruction per recorded op
- Insert `GUARD_*` instructions from observed invariants
- Attach `deopt_id` to every guardable instruction
- Insert `TRACE_END` on boundary

The tracer **does not optimize**. It only records.

---

## 10. Trace IR Specification (v1.0 — Frozen)

This is the canonical Trace IR. Compiler, deopt, difftest, and tracer all target this.

### Design Constraints

- Linear, SSA-like virtual registers (`r0`, `r1`, …)
- Single entry, multiple guarded exits
- All guards are explicit
- All deopt points are explicit
- No hidden control flow

### Guards (No Side Effects)

```
GUARD_TYPE         reg, type_id, deopt_id
GUARD_SHAPE        reg, shape_id, deopt_id
GUARD_NONNULL      reg, deopt_id
GUARD_BRANCH_TAKEN cond_reg, expected_bool, deopt_id
GUARD_CALL_TARGET  call_id, deopt_id
GUARD_NO_EXCEPTION deopt_id
```

### Loads / Stores

```
LOAD_CONST         dst, const_id
LOAD_LOCAL         dst, local_id
STORE_LOCAL        local_id, src
LOAD_ATTR          dst, obj, offset
```

### Computation

```
BINOP              dst, left, right, op   ; + - * / == < etc
UNARYOP            dst, src, op
```

### Calls

```
CALL_DIRECT        dst, call_id, arg_regs...
CALL_INDIRECT      dst, func_reg, arg_regs...
```

Rules:
- `CALL_DIRECT` only if target hash stable
- `CALL_INDIRECT` is traceable but non-inlineable

### Allocation

```
ALLOC              dst, type_id, escape_flag
```

- `escape_flag = NOESCAPE | MAY_ESCAPE`
- `NOESCAPE` → scalar replacement candidate

### Control / Exit

```
BRANCH             cond_reg, true_label, false_label
RETURN             value_reg
RAISE              exception_reg
DEOPT              deopt_id
TRACE_END
```

---

## 11. Deopt Semantics (Locked)

Every guard failure jumps to `DEOPT(deopt_id)`.

Each `deopt_id` maps to:
- Bytecode resume PC
- Live locals
- Operand stack snapshot
- Materialization plan

Interpreter sees a fully consistent frame as if execution had continued normally to that PC.

**No partial side effects are visible.**

---

## 12. Deopt Metadata Generation

For every potential deopt point, the tracer emits:

- Resume bytecode PC
- Live locals at that PC
- Stack depth
- Mapping from virtual regs → Python locals/stack

This is essential: **compiler cannot invent this later**.

---

## 13. Trace Canonicalization

Before storage, traces are canonicalized:

- Normalize register numbering
- Normalize constant IDs
- Canonical branch ordering
- Strip debug-only metadata

Equivalent traces collapse to one.

---

## 14. Trace Storage & Versioning

Each trace stored with:

```
TraceHeader {
  trace_id
  route_id
  signature_hash
  code_version
  tracer_version
  checksum
}
```

Changing code, tracer, or Trace IR spec → invalidates all traces.

---

## 15. Difftest Contract (Hard Requirement)

For every eligible trace:

1. Replay canonical input on:
   - CPython interpreter
   - Compiled trace
2. Compare:
   - Status code
   - Headers
   - Body bytes
   - Side-effect log
3. Any divergence → trace rejected

Tracer must guarantee replayability.

---

## 16. Guard Synthesis Rules

Guards are generated only from **observed invariants**:

| Observation | Guard |
|-------------|-------|
| Type constant | `GUARD_TYPE` |
| Shape stable | `GUARD_SHAPE` |
| Branch always taken | `GUARD_BRANCH_TAKEN` |
| No exception observed | `GUARD_NO_EXCEPTION` |
| Call target fixed | `GUARD_CALL_TARGET` |

Never infer beyond observation.

---

## 17. Failure Modes & Handling

| Failure | Action |
|---------|--------|
| Trace buffer overflow | Discard trace |
| Shape instability | Reset OBSERVING |
| Guard miss spike | Invalidate |
| Replay mismatch | Reject trace |
| Poison suspicion | Blacklist signature |

---

## 18. Performance Budget

| Component | Budget |
|-----------|--------|
| Tracing overhead | ≤5% request latency (measured on FastAPI + ORM + JSON baseline) |
| Memory per trace | ≤ 10KB |
| Trace store growth | bounded per route |
| CPU per trace | linear in trace length |

---

## 19. Design Rationale Summary

This tracer satisfies soundness, boundedness, and adversarial resilience constraints while remaining implementable on unmodified CPython.

Key properties:
- **Separates observation from optimization**
- **Has explicit soundness boundaries**
- **Handles adversarial inputs**
- **Produces replayable artifacts**
- **Is bounded in cost**
- **Integrates cleanly with deopt semantics**
- **Works with CPython unmodified**

This is production-grade trace capture under hostile conditions.

---

## Appendix A: Instrumentation Whitelist

Tracing only records the following CPython bytecodes:

### Allowed

```
LOAD_FAST, STORE_FAST
LOAD_CONST
LOAD_ATTR
COMPARE_OP
BINARY_*, UNARY_*
CALL_FUNCTION, CALL_METHOD
POP_JUMP_IF_*
RETURN_VALUE
```

### Immediate Trace Stop

```
YIELD_*, AWAIT
SETUP_EXCEPT, RAISE_VARARGS
IMPORT_*
EXEC_STMT, EVAL
WITH_*
```

Any opcode invoking frame switching or async scheduling.

This whitelist is intentionally conservative.

---

## Appendix B: Frozen vs Tunable

### Frozen (Implementation May Proceed)

- Trace IR opcode set
- Guard semantics
- Deopt contract
- Trace boundaries
- Call target identity rules
- Side-effect rules

### Tunable (Via Telemetry)

- Trace buffer size (256 initial)
- Eligibility thresholds
- Inline depth
- Trace length limits
- Guard miss thresholds

---

## Implementation Checklist

- [ ] Bytecode + runtime hook instrumentation
- [ ] Per-request bounded trace buffer
- [ ] Side-effect classifier
- [ ] Trace eligibility evaluator
- [ ] Trace IR emitter
- [ ] Deopt metadata generator
- [ ] Canonicalizer
- [ ] Trace store + versioning
- [ ] Difftest harness
- [ ] Guard-miss feedback loop

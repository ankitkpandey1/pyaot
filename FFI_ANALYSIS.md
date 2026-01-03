# PyAOT Performance Analysis: The FFI Overhead Problem

## Executive Summary

After thorough testing, we discovered that while PyAOT's compilation pipeline works correctly:
- ✅ Tracing/IR lowering produces correct IR
- ✅ LLVM IR generation is correct
- ✅ Native code executes correctly (produces correct results)

**However, the ctypes FFI crossing overhead (~280ns per call) makes native execution SLOWER than Python for most functions.**

## Evidence

### Test Results

```
Simple function (x * y + x):
  Python:  45.8 ns/call
  Native: 404.6 ns/call  
  Speedup: 0.11x (9x SLOWER)

Heavy function (20+ operations):
  Python:  273.3 ns/call
  Native:  288.0 ns/call
  Speedup: 0.95x (still slower)

Pure FFI overhead measurement:
  ctypes call to libc.lround(): 311.2 ns
  Python function call:          30.8 ns
  FFI overhead:                 280.3 ns
```

### Root Cause

The ctypes FFI crossing from Python to native code costs ~280ns. This overhead is fixed per call, regardless of how much work the native function does.

For native to be faster:
```
native_execution_time + FFI_overhead < python_execution_time
native_execution_time + 280ns < python_execution_time
```

This means a function must save more than 280ns of Python interpreter overhead to break even.

## Current Architecture Problem

```
┌─────────────────┐
│   Python Code   │
└────────┬────────┘
         │ ctypes FFI (~280ns overhead)
         ▼
┌─────────────────┐
│  Native Code    │ (executes in ~5-50ns)
└─────────────────┘
```

The FFI boundary is crossed for EVERY call. Even if native code is 10x faster, the 280ns crossing cost dominates.

## Solution: Rust-Based Native Extension

### Why Rust?

1. **PyO3**: Rust has excellent Python bindings that minimize FFI overhead
2. **Zero-cost abstractions**: Rust matches C performance
3. **Memory safety**: No GC pauses, no buffer overflows
4. **Existing ecosystem**: PyO3 is mature and well-tested

### Proposed Architecture

```
┌─────────────────────────────────────────┐
│           Python Application            │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│     Rust Extension (pyaot_native)       │
│  ┌─────────────────────────────────┐    │
│  │   Trace Compiler (Cranelift)    │    │ 
│  │         or LLVM via inkwell     │    │
│  └─────────────────────────────────┘    │
│  ┌─────────────────────────────────┐    │
│  │   Runtime Dispatcher            │    │
│  │   - Guard checking              │    │
│  │   - Native execution            │    │
│  │   - Deoptimization              │    │
│  └─────────────────────────────────┘    │
└─────────────────────────────────────────┘
```

### Key Design Principles

1. **Single FFI crossing**: Python calls Rust once, Rust handles the rest
2. **Batch operations**: Execute many operations in single Rust call  
3. **Keep hot paths in Rust**: Don't cross back to Python unnecessarily
4. **Cranelift for speed**: Faster compilation than LLVM, good enough codegen

### Implementation Phases

#### Phase 1: Rust Foundation
- Create `pyaot-native` Rust crate with PyO3
- Implement basic trace execution loop in Rust
- Benchmark FFI overhead with PyO3

#### Phase 2: Cranelift JIT
- Integrate Cranelift for JIT compilation
- Compile traces to native in Rust
- Execute compiled traces without crossing to Python

#### Phase 3: Guard System
- Implement guards in Rust
- Deoptimization path back to Python
- Shape/type guard caching

#### Phase 4: Integration
- Replace ctypes-based execution with Rust extension
- Maintain backward compatibility
- Comprehensive benchmarking

## Expected Performance

With Rust + PyO3:
- FFI overhead: ~50-100ns (vs 280ns with ctypes)
- Hot path stays in Rust (no repeated crossings)
- Batch operations amortize FFI cost

Target speedups:
- Simple numeric functions: 2-5x
- Complex traces (10+ ops): 5-20x
- Tight loops: 10-50x

## Alternative Approaches Considered

### 1. CPython C Extension
- Pros: Minimal FFI overhead
- Cons: Complex, memory safety issues, harder to maintain

### 2. Cython
- Pros: Easy Python-like syntax
- Cons: Still has Python runtime overhead, not true native

### 3. Numba
- Pros: Works well for numeric code
- Cons: Limited to NumPy operations, not general-purpose

### 4. cffi
- Pros: Slightly faster than ctypes
- Cons: Still ~200ns overhead, same fundamental problem

**Rust + PyO3 is the best balance of performance, safety, and maintainability.**

## Immediate Next Steps

1. Create regression tests for current functionality
2. Set up Rust workspace alongside Python
3. Implement minimal PyO3 extension
4. Benchmark PyO3 vs ctypes overhead
5. If PyO3 overhead is acceptable, proceed with Cranelift integration

## References

- PyO3: https://pyo3.rs
- Cranelift: https://cranelift.dev
- inkwell (LLVM bindings for Rust): https://github.com/TheDan64/inkwell

---

## Proposed Solution: Rust Native Extension with Cranelift

### The Core Insight

The FFI overhead is per-call. To eliminate it:
1. **Move the entire execution loop to Rust** - Python calls Rust once, Rust runs the entire trace
2. **Use Cranelift for JIT** - Fast compilation, good enough codegen
3. **Only cross back to Python for deopt** - Guards fail? Deopt to Python interpreter

### Architecture

```
Python                          Rust Extension (pyaot-native)
──────                          ─────────────────────────────
                                
 request ──────FFI (once)─────▶ ┌─────────────────────────────┐
                                │  Dispatch Loop              │
                                │  ├─ Check guards (fast)     │
                                │  ├─ Execute native trace    │
                                │  └─ Return result           │
                                └──────────────┬──────────────┘
                                               │
 result ◀────────────────────────────────────┘
```

### Key Components

1. **pyaot-native crate**
   - PyO3 for Python bindings
   - Cranelift for JIT compilation
   - Guard checking in Rust (type checks via PyO3)

2. **Trace Representation**
   - Serialize IR to bytes
   - Send to Rust once during compilation
   - Cranelift compiles to native

3. **Execution Model**
   - Python: `result = pyaot_native.execute(trace_id, args)`
   - Rust: look up compiled trace, execute, return result
   - Single FFI crossing per trace execution

### Expected Performance

```
Current (ctypes):
  FFI overhead: ~280ns per call
  Native execution: ~5-50ns
  Total: ~300-330ns (slower than Python)

Proposed (Rust + PyO3):
  FFI overhead: ~50ns per call (PyO3 is faster)
  Native execution: ~5-50ns (same)
  Total: ~55-100ns
  
  Python baseline: ~50-300ns depending on function
  
  Result: 2-5x speedup for typical functions
```

### Implementation Roadmap

```
Week 1: Foundation
  - Set up pyaot-native Rust crate
  - PyO3 bindings for basic function
  - Benchmark PyO3 overhead

Week 2: Trace Execution
  - Trace serialization format
  - Rust-side trace interpreter
  - Basic ops (add, mul, load, store)

Week 3: Cranelift JIT
  - Integrate Cranelift
  - Compile traces to native
  - Cache compiled code

Week 4: Guards & Deopt
  - Type guards in Rust
  - Deoptimization path
  - Integration with Python

Week 5: Integration & Testing
  - Replace ctypes backend
  - Performance benchmarks
  - Regression tests
```

### Success Criteria

1. Simple numeric functions: **2x faster than Python**
2. Complex traces (20+ ops): **5x faster than Python**
3. Guard checking: **<50ns overhead**
4. Compilation time: **<100ms per trace**

### Alternative: Stay with Python, Accept Limitations

If Rust is not feasible:
1. Accept that single-call native is slower
2. Focus on **batched execution** - compile loops, not individual calls
3. Use NumPy/vectorization for numeric hot paths
4. PyAOT becomes a "trace analyzer" not a "trace compiler"

This is a valid approach but limits the vision significantly.


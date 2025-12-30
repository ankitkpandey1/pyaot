# Changelog

All notable changes to PyAOT will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2025-12-30

### Added

#### Loop Vectorization
- `LoopVectorizer` class for automatic SIMD transformation
- Support for AVX2, AVX-512, and ARM NEON targets
- SIMD opcodes in IR: `SIMD_LOAD`, `SIMD_FADD`, `SIMD_REDUCE_ADD`, etc.
- `IRLoop` class for loop representation

#### Multi-Function Compilation
- `CallGraphAnalyzer` for call chain detection
- `InterproceduralOptimizer` for inlining call chains
- Call chain benefit estimation

#### NumPy Fusion
- `NumPyFusionPass` for fusing NumPy operations
- Common patterns: hypot, normalize, dot, euclidean distance
- Eliminates intermediate array allocations

#### Exception Handling
- Exception opcodes: `TRY_BEGIN`, `TRY_END`, `EXCEPT`, `RAISE`
- `ExceptionCompiler` for try/except compilation
- `ExceptionRuntime` for exception state management

#### GPU Targeting
- `pyaot/gpu/` module for CUDA support
- `CUDACodegen` for kernel generation
- `GPURuntime` for memory management
- `GPUArray` with NumPy-like API

#### Production Hardening
- `DiagnosticReporter` with rich error messages
- `ProfilingDashboard` for terminal visualization
- CLI commands: `pyaot dashboard`, `pyaot diagnose`, `pyaot info`

#### Benchmark Suite
- `benchmarks/bench_suite.py` with comprehensive benchmarks
- JSON output for CI integration

### Changed
- Updated documentation (README.md, ARCHITECTURE.md)
- Improved CLI with new commands

## [0.1.0] - 2025-12-29

### Added

#### Core System
- Profile-guided AOT compilation pipeline
- Sampled profiling with <5% overhead
- Hotness scoring and eligibility checking
- LLVM-based native code generation

#### Type System
- `TypeInferencer` for runtime type observation
- Type stability tracking
- Guard generation for type assumptions

#### Shape System
- `ShapeRegistry` for object layout tracking
- Fast attribute access optimization
- Shape guards for structural assumptions

#### Adaptive Compilation
- `@adaptive` decorator for type-hint-based compilation
- Continuous PGO with drift detection
- Source hash tracking for cache invalidation

#### Call-Boundary Elimination
- Profile-guided inlining
- Guard checking with Python fallback
- ~50-200ns call overhead elimination

#### Caching
- Content-addressed artifact storage
- ABI validation
- LRU eviction

#### CLI
- `pyaot profile` - Profile a script
- `pyaot compile` - Compile profiles
- `pyaot run` - Run with AOT optimization
- `pyaot cache` - Cache management

### Documentation
- Comprehensive README.md
- ARCHITECTURE.md with design details
- BENCHMARK.md with methodology

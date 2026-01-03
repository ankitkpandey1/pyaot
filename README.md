# PyAOT

**Region-Based Native Accelerator for Python**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/License-Apache_2.0-green.svg)](LICENSE)

PyAOT is an experimental region-based accelerator that attempts to speed up hot Python execution paths by compiling them to native machine code. It uses a decorator-based approach to define "regions" of code that are observed, traced, and then compiled to C, loaded via a Rust-based native runner.

> **Current Status**: The Region Accelerator (Path A) has been implemented and benchmarked.
> **Performance finding**: For extremely small, fast-executing functions (sub-100ns), the overhead of the Python wrapper and FFI boundary (~1700ns) currently outweighs the benefits of native execution. Future work may focus on larger, more computationally intensive regions to amortize this cost.

---

## Table of Contents

- [Introduction](#introduction)
- [How It Works](#how-it-works)
- [Installation](#installation)
- [Usage](#usage)
- [Architecture](#architecture)
- [Performance](#performance)
- [Development](#development)
- [License](#license)

---

## Introduction

PyAOT allows you to mark specific functions as "regions" using the `@pyaot.region` decorator. The system then:
1.  **Observes** execution to gather type and shape information.
2.  **Compiles** the region to C code tailored to the observed types.
3.  **Executes** the compiled native code via a high-performance Rust extension.
4.  **Falls back** to strict Python execution if types change (guards fail) or compilation is not possible.

This approach targets side-effect-free, compute-bound sections of code where the overhead of the Python interpreter is the primary bottleneck.

---

## How It Works

### The Region Concept

A **Region** is a function responsible for a specific calculation or logic flow. It must be:
- **Side-effect free** (no I/O, no global state mutation, except allowed logging).
- **Deterministic** (same inputs -> same outputs).
- **Restartable** (safe to re-execute if the native guard fails).

### Execution Flow

1.  **Warmup**: The function runs in standard Python mode. PyAOT traces arguments, attribute accesses, and control flow.
2.  **Compilation**: Once sufficient stable traces are collected, PyAOT generates C source code representing the function's logic using the Python C API.
3.  **Native Load**: The C code is compiled to a shared object (`.so`) and loaded by the `pyaot_native` Rust extension.
4.  **Native Execution**: Subsequent calls are routed to the native implementation.
5.  **Guards**: The native code checks input types. If a mismatch is detected, it returns a signal to fall back to Python, ensuring correctness.

---

## Installation

### Prerequisites
- Python 3.10+
- Rust (for the native runner)
- GCC or Clang (for compiling generated C code)

### Steps

```bash
# Clone the repository
git clone https://github.com/pyaot/pyaot.git
cd pyaot

# Install Python dependencies and build the Rust extension
pip install .
```

---

## Usage

### Basic Usage

Decorate your pure functions with `@pyaot.region`:

```python
import pyaot

@pyaot.region
def calculate_score(data, factor):
    if data.active:
        return data.val * factor + 10
    return 0

class Item:
    def __init__(self, val, active):
        self.val = val
        self.active = active

# PyAOT observes the first few calls
item = Item(100, True)
for _ in range(100):
    calculate_score(item, 1.5)

# After warmup, calculate_score runs natively!
```

### Configuration

You can configure the JIT behavior:

```python
from pyaot.region import RegionConfig

# Configure via global settings or per-decorator (coming soon)
# Current defaults:
# min_observations = 10 (executions before compilation)
# max_failures = 3 (fallback attempts before disabling native)
```

---

## Architecture

PyAOT consists of three main components:

1.  **Python Frontend (`pyaot/region/`)**:
    -   `wrapper.py`: Handles the decorator logic, dispatching, and fallback.
    -   `tracer.py`: Records runtime values, types, and attribute offsets.
    -   `compiler.py`: Generates optimized C code from Python AST and traces.

2.  **Native Runner (`native/` - Rust)**:
    -   A Python extension written in Rust using `PyO3`.
    -   Manages loading of compiled `.so` libraries.
    -   Provides a low-overhead entry point for executing native regions.

3.  **Compiler Backend**:
    -   Uses `gcc` (or compatible system compiler) to transform generated C code into shared objects.

See [ARCHITECTURE.md](ARCHITECTURE.md) for deeper details.

---

## Performance

The goal of PyAOT is to reduce interpreter overhead.

### Current Benchmarks

Target: `get_user` handler (minimal logic: dict creation, attribute access).
-   **Method**: `@pyaot.region` compilation.
-   **Result**: 0.05x speedup (20x slowdown) for very small functions (~88ns in Python vs ~1700ns Native).
-   **Analysis**: The overhead of entering the native region (argument marshalling, FFI boundary) currently dominates execution time for micro-benchmarks. The accelerator is expected to perform better on computationally heavier tasks where the instruction count reduction outweighs the fixed entry cost.

---

## Development

### Running Tests

```bash
pytest tests/
```

### Running Benchmarks

```bash
python tests/bench_target_handler.py
```

---

## License

Apache License 2.0. See [LICENSE](LICENSE) for details.
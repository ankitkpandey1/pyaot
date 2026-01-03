# Introduction to PyAOT Regions

PyAOT provides a decorator-based mechanism to accelerate specific, hot regions of your Python code.

## How it works

Unlike whole-program JITs (like PyPy) or function-level JITs (like Numba), PyAOT focuses on **control-flow regions** that are computationally expensive but side-effect free.

### The Problem

Python is slow at elementary operations (addition, attribute access) because everything is dynamic. Every `a + b` involves:
1.  Check `a`'s type.
2.  Check `b`'s type.
3.  Dispatch to `__add__`.
4.  Allocate a new object for the result.

### The Solution

If we know that `a` and `b` are always integers, `a + b` is a single CPU instruction.

PyAOT's `@label` does the following:

1.  **Observes**: It watches your function run a few times ("warmup").
    ```python
    calculate(10, 20)  # Observed: int, int
    calculate(5, 5)    # Observed: int, int
    ```
2.  **Locks Assumptions**: It concludes "They are always ints".
3.  **Compiles**: It generates C code that assumes they are ints, but inserts a **Guard** at the top.
    ```c
    if (!PyLong_Check(arg0) || !PyLong_Check(arg1)) return NULL; // Guard
    long a = PyLong_AsLong(arg0);
    long b = PyLong_AsLong(arg1);
    return PyLong_FromLong(a + b);
    ```
4.  **Runs**: The next time you call it, the wrapper hands off execution to this compiled C function.

### Fallback

If you suddenly call `calculate("a", "b")`, the Guard fails (returns NULL). The wrapper catches this signal and immediately runs the original Python function. Your program never crashes due to optimization assumptions; it just gets slower (back to normal speed) for that call.

This hybrid approach allows safe, incremental optimization of Python applications.

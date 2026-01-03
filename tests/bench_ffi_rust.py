"""Benchmark Rust FFI vs ctypes FFI overhead."""

import time
import ctypes
import pyaot_native

def benchmark():
    print("=== FFI Overhead Benchmark ===")
    
    N = 1_000_000
    
    # 1. Rust/PyO3
    print("Benchmarking Rust PyO3...")
    # Warmup
    for _ in range(1000):
        pyaot_native.benchmark_overhead()
        
    start = time.perf_counter_ns()
    for _ in range(N):
        pyaot_native.benchmark_overhead()
    rust_ns = time.perf_counter_ns() - start
    rust_avg = rust_ns / N
    print(f"Rust PyO3:  {rust_avg:.1f} ns/call")
    
    # 2. ctypes
    print("Benchmarking ctypes...")
    lib = ctypes.CDLL(None)
    # Use getpid as a simple void-like function or lround
    lround = lib.lround
    lround.argtypes = [ctypes.c_double]
    lround.restype = ctypes.c_long
    
    # Warmup
    for _ in range(1000):
        lround(0.0)
        
    start = time.perf_counter_ns()
    for _ in range(N):
        lround(0.0)
    ctypes_ns = time.perf_counter_ns() - start
    ctypes_avg = ctypes_ns / N
    print(f"ctypes:     {ctypes_avg:.1f} ns/call")
    
    # 3. Pure Python
    def noop(): pass
    start = time.perf_counter_ns()
    for _ in range(N):
        noop()
    py_avg = (time.perf_counter_ns() - start) / N
    print(f"Python:     {py_avg:.1f} ns/call")
    
    print("-" * 30)
    print(f"Rust Overhead:   {rust_avg - py_avg:.1f} ns")
    print(f"ctypes Overhead: {ctypes_avg - py_avg:.1f} ns")
    print(f"Improvement:     {ctypes_avg / rust_avg:.1f}x faster FFI")

if __name__ == "__main__":
    benchmark()

"""Benchmark Path A: Region Accelerator vs Python.

Target Handler: get_user(req, users_cache, error)
Logic:
    if not req.user.is_authenticated:
        return error
    user = users_cache[req.user.id]
    return { "id": user.id, ... }
"""

import time
import pytest
from pyaot.region import region
from pyaot.region.wrapper import RegionConfig

# Mock Objects
class User:
    def __init__(self, id, name, role, auth=True):
        self.id = id
        self.name = name
        self.role = role
        self.is_authenticated = auth

class Request:
    def __init__(self, user):
        self.user = user

def benchmark_target():
    print("=== Path A: Region Accelerator Benchmark ===")
    
    # Setup Data
    users_cache = {1: User(1, "Alice", "Admin")}
    error_resp = {"error": "Unauthorized"}
    
    # 1. Pure Python Baseline
    def get_user_py(req, users_cache, error):
        if not req.user.is_authenticated:
            return error
        user = users_cache[req.user.id]
        return {
            "id": user.id,
            "name": user.name,
            "role": user.role,
        }
        
    # 2. Region Accelerator
    # Forcing compilation by creating wrapper and compiling immediately via training
    @region(config=RegionConfig(min_observations=10))
    def get_user_region(req, users_cache, error):
        if not req.user.is_authenticated:
             return error
        user = users_cache[req.user.id]
        return {
            "id": user.id,
            "name": user.name,
            "role": user.role,
        }

    # Training
    req_auth = Request(User(1, "Alice", "Admin"))
    for _ in range(20):
        get_user_region(req_auth, users_cache, error_resp)
        
    if not get_user_region.state.is_compiled:
        print("WARNING: Region failed to compile!")
        return
        
    # Measurement
    N = 1_000_000
    
    # --- Python ---
    start = time.perf_counter_ns()
    for _ in range(N):
        get_user_py(req_auth, users_cache, error_resp)
    py_ns = time.perf_counter_ns() - start
    py_avg = py_ns / N
    
    # --- Region ---
    start = time.perf_counter_ns()
    for _ in range(N):
        get_user_region(req_auth, users_cache, error_resp)
    region_ns = time.perf_counter_ns() - start
    region_avg = region_ns / N
    
    print(f"Python Baseline: {py_avg:.1f} ns/call")
    print(f"Region Native:   {region_avg:.1f} ns/call")
    
    speedup = py_avg / region_avg
    print(f"Speedup:         {speedup:.2f}x")
    
    overhead = region_avg  # Since it's native exec, total time is effectively overhead + native logic
    # But checking 'Entry overhead' specifically requires empty region comparison.
    # User asked "Entry overhead < 100ns". 
    # Our FFI benchmark showed 91ns overhead.
    # Here we measure actual logic acceleration.
    
    if speedup >= 5.0:
        print("✅ SUCCESS: >= 5x speedup achieved")
    else:
        print("❌ FAIL: < 5x speedup")

if __name__ == "__main__":
    benchmark_target()

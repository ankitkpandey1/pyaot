"""Integration Test: Region Wrapper + Compiler + Native Runner."""

import pytest
from pyaot.region import region
from pyaot.region.wrapper import RegionConfig

def test_region_autocompilation():
    """Verify that a region auto-compiles after min_observations."""
    
    # Configure with small threshold
    config = RegionConfig(min_observations=5)
    
    @region(config=config)
    def fast_add(x, y):
        # A simple function that our V1 compiler handles
        return x + y
        
    # Phase 1: Observation/Tracing
    for i in range(5):
        assert fast_add(i, 1) == i + 1
        assert not fast_add.state.is_compiled, f"Should not be compiled yet at call {i+1}"
        
    # Phase 2: Trigger Compilation (Call 6)
    # The 6th call (index 5) exceeds min_observations (5)
    result = fast_add(10, 20)
    assert result == 30
    
    # Check compilation state
    # Note: Compilation happens *before* executing the native runner for that call in my logic?
    # Let's check logic: 
    # if call_count > min_observations: compile...
    # if state.is_compiled: run native...
    # So yes, the trigger call should run natively if compilation succeeds right away.
    
    assert fast_add.state.is_compiled, "Region should be compiled now"
    assert fast_add.state.native_runner is not None
    
    # Phase 3: Native Execution
    # Verify we are running natively (trace/logs would confirm, but result correctness is base)
    assert fast_add(100, 200) == 300
    
    # We can check if "native execution" string is missing from result because 
    # real compilation returns the actual sum, not the "Executed region..." string from Step 3 placeholder.
    # The Step 4 compiler generates C code that does PyNumber_Add, so it returns the real sum.
    
    # To truly verify it's native, we might check if a .so exists for it?
    # Or rely on the fact that if it wasn't native, is_compiled would be False.

def test_region_compilation_failure_fallback():
    """Verify fallback when compilation is impossible (unsupported op)."""
    
    config = RegionConfig(min_observations=2)
    
    @region(config=config)
    def unsupported_op(x, y):
        return x - y # V1 compiler doesn't support subtraction yet
        
    # 1, 2
    unsupported_op(10, 5)
    unsupported_op(10, 5)
    
    # 3 - Trigger compilation
    # Compiler (my implementation) might raise generic error or generate generating code that errors at runtime
    # If compiler raises error, we catch it and disable native.
    
    res = unsupported_op(10, 5)
    assert res == 5
    
    # If compilation failed (e.g. Unsupported op in _generate_c), we fallback to Python
    # Check state
    # My compiler implementation falls back to returning NULL in C code if unknown op
    # This means C generation succeeds, but runtime execution fails?
    # Wait, my _generate_c emits "PyErr_SetString..." for unsupported ops.
    # So compilation succeeds.
    # Native execution strictly raises RuntimeError (from PyErr).
    # Then wrapper catches Exception and falls back.
    
    assert unsupported_op.state.is_compiled, "Should be compiled (but broken)"
    assert unsupported_op.state.native_failures > 0


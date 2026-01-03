"""Integration Test: Guards and Fallback."""

import pytest
from pyaot.region import region
from pyaot.region.wrapper import RegionConfig

def test_region_guard_fallback():
    """Verify that type mismatch triggers backoff to Python."""
    
    config = RegionConfig(min_observations=5)
    
    @region(config=config)
    def typed_add(x, y):
        # Python handles polymorphic dispatch
        return x + y
        
    # Phase 1: Train on Integers
    for i in range(5):
        assert typed_add(10, 20) == 30
    
    # Phase 2: Trigger Compilation (with Int guards)
    assert typed_add(10, 20) == 30
    assert typed_add.state.is_compiled
    
    # Phase 3: Happy path (Int execution)
    assert typed_add(100, 200) == 300
    
    # Phase 4: Guard Failure (Pass Floats)
    # The native code (generated for Int) should check PyLong_Check(arg)
    # It should fail for float, raise TypeError (internally) or return NULL
    # Wrapper should catch this and fallback to Python
    
    # Note: 10.5 + 20.5 = 31.0
    res = typed_add(10.5, 20.5)
    assert res == 31.0
    
    # Check stats
    # native_failures should increment
    assert typed_add.state.native_failures > 0

def test_region_guard_fallback_str():
    """Verify fallback for Strings (unsupported op in native but valid in Python)."""
    
    config = RegionConfig(min_observations=5)
    
    @region(config=config)
    def typed_mul(x, y):
        return x * y
        
    # Train on Ints
    for _ in range(6):
        typed_mul(2, 3)
        
    assert typed_mul.state.is_compiled
    
    # Pass String (Guard failure check type)
    # "a" * 3 = "aaa"
    res = typed_mul("a", 3)
    assert res == "aaa"
    
    assert typed_mul.state.native_failures > 0

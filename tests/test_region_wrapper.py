"""Tests for Region Wrapper (Step 1)."""

import pytest
from pyaot.region import region
from pyaot.region.wrapper import Region

def test_region_decorator_basic():
    """Test basic usage of @region decorator."""
    
    @region
    def add_one(x):
        return x + 1
        
    assert isinstance(add_one, Region)
    assert add_one(5) == 6
    assert add_one.state.call_count == 1
    assert add_one.state.is_compiled is False

def test_region_decorator_with_config():
    """Test @region decorator with configuration."""
    from pyaot.region.wrapper import RegionConfig
    
    @region(config=RegionConfig(min_observations=10))
    def mul_two(x):
        return x * 2
        
    assert isinstance(mul_two, Region)
    assert mul_two(5) == 10
    assert mul_two.state.config.min_observations == 10

def test_region_fallback_mechanism():
    """Test that region falls back to Python if native fails (simulated)."""
    
    @region
    def risky_func(x):
        return x * x

    # Simulate a compiled state with a broken runner
    def broken_runner(*args, **kwargs):
        raise RuntimeError("Native crash!")
        
    risky_func.state.is_compiled = True
    risky_func.state.native_runner = broken_runner
    
    # Should fall back to Python execution
    assert risky_func(5) == 25
    
    # Verify fallback tracking
    assert risky_func.state.native_failures == 1
    assert risky_func.state.is_compiled is True  # Still compiled (failures < limit)
    
    # Fail enough times to disable
    for _ in range(5):
        risky_func(5)
        
    assert risky_func.state.native_failures >= 5
    assert risky_func.state.is_compiled is False # Logic disabled after max failures

def test_execution_transparency():
    """Test that region wrapper is transparent to arguments and exceptions."""
    
    @region
    def complex_logic(a, b, op="add"):
        if op == "add":
            return a + b
        elif op == "fail":
            raise ValueError("Intentional failure")
        return a - b
        
    assert complex_logic(10, 5) == 15
    assert complex_logic(10, 5, op="sub") == 5
    
    with pytest.raises(ValueError, match="Intentional failure"):
        complex_logic(10, 5, op="fail")

def test_target_handler_signature():
    """Verify the target handler works with the region wrapper."""
    
    # Mock request object
    class User:
        def __init__(self, id, name, role):
            self.id = id
            self.name = name
            self.role = role
            self.is_authenticated = True

    class Request:
        def __init__(self, user):
            self.user = user
            
    users_cache = {1: User(1, "Alice", "Admin")}
    error = {"error": "Unauthorized"}
    
    @region
    def get_user(req):
        if not hasattr(req.user, 'is_authenticated') or not req.user.is_authenticated:
            return error
        user = users_cache[req.user.id]
        return {
            "id": user.id,
            "name": user.name,
            "role": user.role,
        }
    
    # Test authorized
    req = Request(User(1, "Alice", "Admin"))
    result = get_user(req)
    assert result == {"id": 1, "name": "Alice", "role": "Admin"}
    
    # Test unauthorized
    req_unauth = Request(User(2, "Bob", "User"))
    req_unauth.user.is_authenticated = False
    result = get_user(req_unauth)
    assert result == error

def test_trace_capturing():
    """Test that tracing captures inputs during observation phase."""
    from pyaot.region.tracer import Guard
    
    @region
    def traced_func(x, y):
        return x + y
        
    # First call - should trace
    traced_func(10, 20)
    
    assert len(traced_func.state.traces) == 1
    trace = traced_func.state.traces[0]
    
    # Should have captured guards for inputs
    arg_guards = [g for g in trace.guards if g.kind == 'type']
    assert len(arg_guards) >= 2
    assert any(g.target == 'x' and g.expected == int for g in arg_guards)
    assert any(g.target == 'y' and g.expected == int for g in arg_guards)


"""Unit tests for HandlerOptimizer."""

import time
from typing import Iterator
from unittest.mock import Mock

import pytest
from pyaot.web.codegen.optimizer import HandlerOptimizer
from pyaot.web.trace.signature import RequestSignature


def mock_handler(environ, start_response) -> Iterator[bytes]:
    """Slow handler to simulate work."""
    time.sleep(0.01)  # 10ms work
    start_response("200 OK", [("Content-Type", "text/plain")])
    return iter([b"Hello World"])


def test_optimization_speedup():
    """Test that optimizer actually speeds up repeated calls."""
    optimizer = HandlerOptimizer()
    
    # Create signature
    sig = RequestSignature(
        http_method="GET",
        path_template="/users/<id>",
        auth_state="authenticated",
        param_types=(),
        header_shape_hash="abc",
        body_shape_hash="",
    )
    
    # 1. Measure baseline
    environ = {"REQUEST_METHOD": "GET", "PATH_INFO": "/users/1"}
    
    start = time.perf_counter()
    mock_handler(environ, Mock())
    baseline_time = time.perf_counter() - start
    
    # 2. Optimize
    optimized = optimizer.optimize(sig, mock_handler)
    
    # 3. First call (cache miss + capture)
    start = time.perf_counter()
    list(optimized(environ, Mock()))
    first_call_time = time.perf_counter() - start
    
    # 4. Second call (cache hit)
    start = time.perf_counter()
    list(optimized(environ, Mock()))
    second_call_time = time.perf_counter() - start
    
    print(f"\nBaseline: {baseline_time*1000:.2f}ms")
    print(f"First call (capture): {first_call_time*1000:.2f}ms")
    print(f"Second call (cached): {second_call_time*1000:.2f}ms")
    
    # Speedup validation
    assert second_call_time < baseline_time
    assert second_call_time < 0.001  # Should be sub-1ms (cache hit)
    
    speedup = baseline_time / second_call_time
    print(f"Speedup: {speedup:.2f}x")
    assert speedup > 10  # Expect massive speedup due to sleep removal


def test_non_cacheable_method():
    """Test that POST requests are NOT cached."""
    optimizer = HandlerOptimizer()
    
    sig = RequestSignature(
        http_method="POST",  # POST is not cacheable
        path_template="/users",
        auth_state="authenticated",
        param_types=(),
        header_shape_hash="abc",
        body_shape_hash="",
    )
    
    optimized = optimizer.optimize(sig, mock_handler)
    
    # First call
    start = time.perf_counter()
    list(optimized({}, Mock()))
    t1 = time.perf_counter() - start
    
    # Second call
    start = time.perf_counter()
    list(optimized({}, Mock()))
    t2 = time.perf_counter() - start
    
    # Both should include sleep
    assert t1 >= 0.01
    assert t2 >= 0.01

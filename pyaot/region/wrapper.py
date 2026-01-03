"""Region wrapper and administration."""

from __future__ import annotations

import functools
import inspect
from dataclasses import dataclass
from typing import Any, Callable, Generic, TypeVar, Optional
from pyaot.region.tracer import get_tracer, TraceData
from pyaot.region.compiler import compile_function
import pyaot_native

T = TypeVar("T")


@dataclass
class RegionConfig:
    """Configuration for a compiled region."""
    
    # Minimum observations before attempting compilation
    min_observations: int = 100
    
    # Maximum failures before disabling native path
    max_failures: int = 5


class RegionState:
    """Runtime state of a region."""
    
    def __init__(self, func: Callable, config: RegionConfig):
        self.func = func
        self.config = config
        self.call_count = 0
        self.native_failures = 0
        self.is_compiled = False
        self.traces: list[TraceData] = []
        # Placeholder for native runner (Step 3)
        self.native_runner: Optional[Callable] = None


class Region(Generic[T]):
    """A managed execution region."""

    def __init__(self, func: Callable[..., T], config: Optional[RegionConfig] = None):
        if not inspect.isfunction(func):
             raise TypeError("@region can only be used on functions")
             
        self._func = func
        self._config = config or RegionConfig()
        self._state = RegionState(func, self._config)
        
        # Preserve metadata
        functools.update_wrapper(self, func)

    def __call__(self, *args: Any, **kwargs: Any) -> T:
        """Execute the region.
        
        Dispatches to native runner if available and eligible,
        otherwise falls back to Python execution.
        """
        self._state.call_count += 1
        tracer = get_tracer()
        
        # Phase 1: Tracing
        if not self._state.is_compiled and self._state.call_count <= self._config.min_observations:
            # simple trace of types for inputs
            tracer.start_trace(str(id(self)))
            # Match args to names using signature
            sig = inspect.signature(self._func)
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            
            for name, value in bound.arguments.items():
                tracer.record_type(name, value)
                
            # Execute
            try:
                result = self._func(*args, **kwargs)
            finally:
                trace_data = tracer.end_trace()
                if trace_data:
                    self._state.traces.append(trace_data)
                    
            return result
        
        # Trigger Compilation?
        if not self._state.is_compiled and self._state.call_count > self._config.min_observations:
            try:
                region_id = f"region_{id(self)}"
                # Compile and load into pyaot_native
                # Note: compile_function does both
                handle = compile_function(self._func, region_id, self._state.traces)
                self._state.is_compiled = True
                self._state.native_runner = lambda *a, **k: pyaot_native.run_region(handle, a, k)
            except Exception as e:
                # Compilation failed, stick to Python
                # In prod, log this failure
                print(f"Compilation/Load failed: {e}")
                self._state.native_failures += 1
                # Prevent retry spam
                if self._state.native_failures >= self._config.max_failures:
                     # For now, just bump min_observations to retry later or never
                     self._config.min_observations *= 10

        # Phase 2: Native Execution (Dispatch)
        # Helper method for dispatch logic to separate mechanics from policy
        if self._state.is_compiled and self._state.native_runner:
            try:
                # Optimized native path (simulation for now)
                return self._state.native_runner(*args, **kwargs)
            except Exception: # Guard failure or native error
                # Fallback path
                self._state.native_failures += 1
                if self._state.native_failures >= self._config.max_failures:
                     # Disable native after too many failures
                     self._state.is_compiled = False
                
                return self._func(*args, **kwargs)
        
        # Default Python path
        return self._func(*args, **kwargs)

    @property
    def state(self) -> RegionState:
        """Access region state for inspection/metrics."""
        return self._state


def region(config: Optional[RegionConfig] = None):
    """Decorator to mark a function as a compilation region.
    
    Usage:
        @region
        def my_function(x):
            return x + 1
            
        @region(config=RegionConfig(min_observations=50))
        def configured_func(x):
            pass
    """
    if callable(config):
        # Decorator used without arguments: @region
        return Region(config)
        
    def decorator(func: Callable[..., T]) -> Region[T]:
        return Region(func, config)
    return decorator

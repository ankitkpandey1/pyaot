"""
Guarded dispatcher for AOT compiled functions.

Wraps compiled functions with guard checks and provides
automatic fallback to Python execution on guard failure.
"""

from dataclasses import dataclass
from typing import Any, Callable, Optional
import functools
import time

from pyaot.types.guards import GuardSet
from pyaot.logging import log_fallback, log_guard_failure
from pyaot.config import get_config


@dataclass
class DispatchStats:
    """Statistics for a guarded dispatcher."""
    native_calls: int = 0
    fallback_calls: int = 0
    guard_failures: int = 0
    total_native_time_ns: int = 0
    total_fallback_time_ns: int = 0
    
    @property
    def native_ratio(self) -> float:
        """Ratio of native vs total calls."""
        total = self.native_calls + self.fallback_calls
        if total == 0:
            return 0.0
        return self.native_calls / total


class GuardedDispatcher:
    """Dispatcher that routes between native and Python execution.
    
    When guards pass, calls the native implementation.
    When guards fail, falls back to the original Python function.
    
    Guard failures never crash and never corrupt state.
    """
    
    def __init__(
        self,
        native_impl: Callable,
        fallback: Callable,
        guards: GuardSet,
        function_name: str = "",
        collect_stats: bool = False,
    ):
        """Initialize the dispatcher.
        
        Args:
            native_impl: The compiled native implementation.
            fallback: The original Python function.
            guards: Guard set for this function.
            function_name: Name for logging/debugging.
            collect_stats: Whether to collect dispatch statistics.
        """
        self.native_impl = native_impl
        self.fallback = fallback
        self.guards = guards
        self.function_name = function_name or fallback.__name__
        self.collect_stats = collect_stats
        self.stats = DispatchStats()
        
        # Copy function metadata
        functools.update_wrapper(self, fallback)
    
    def __call__(self, *args, **kwargs) -> Any:
        """Dispatch to native or fallback based on guards."""
        # Check if AOT is disabled globally
        config = get_config()
        if not config.enabled:
            return self.fallback(*args, **kwargs)
        
        # Check guards
        if self.guards.check_all(args):
            # Guards passed - use native implementation
            try:
                if self.collect_stats:
                    start = time.perf_counter_ns()
                    result = self.native_impl(*args, **kwargs)
                    self.stats.native_calls += 1
                    self.stats.total_native_time_ns += time.perf_counter_ns() - start
                    return result
                else:
                    return self.native_impl(*args, **kwargs)
            except Exception as e:
                # Native execution failed - fall back to Python
                log_fallback(self.function_name, f"native exception: {e}")
                return self.fallback(*args, **kwargs)
        else:
            # Guards failed - use fallback
            log_fallback(self.function_name, "guard failure")
            if self.collect_stats:
                start = time.perf_counter_ns()
                result = self.fallback(*args, **kwargs)
                self.stats.fallback_calls += 1
                self.stats.guard_failures += 1
                self.stats.total_fallback_time_ns += time.perf_counter_ns() - start
                return result
            else:
                return self.fallback(*args, **kwargs)
    
    def get_stats(self) -> DispatchStats:
        """Get dispatch statistics."""
        return self.stats
    
    def reset_stats(self) -> None:
        """Reset dispatch statistics."""
        self.stats = DispatchStats()
    
    def force_native(self, *args, **kwargs) -> Any:
        """Force native execution (for testing)."""
        return self.native_impl(*args, **kwargs)
    
    def force_fallback(self, *args, **kwargs) -> Any:
        """Force fallback execution (for testing)."""
        return self.fallback(*args, **kwargs)


def create_dispatcher(
    native_impl: Callable,
    fallback: Callable,
    guards: GuardSet,
    function_name: str = "",
) -> GuardedDispatcher:
    """Create a guarded dispatcher for a compiled function.
    
    This is the main entry point for wrapping compiled functions.
    
    Args:
        native_impl: The compiled native implementation.
        fallback: The original Python function.
        guards: Guard set for this function.
        function_name: Name for logging/debugging.
        
    Returns:
        A GuardedDispatcher that can be called like the original function.
    """
    config = get_config()
    return GuardedDispatcher(
        native_impl=native_impl,
        fallback=fallback,
        guards=guards,
        function_name=function_name,
        collect_stats=config.metrics_enabled,
    )


def dispatch(
    func: Callable,
    native_impl: Callable,
    guards: GuardSet,
) -> Callable:
    """Decorator-style dispatcher creation.
    
    Usage:
        @dispatch(native_impl=compiled_sum, guards=my_guards)
        def sum_array(arr):
            return sum(arr)
    """
    return create_dispatcher(
        native_impl=native_impl,
        fallback=func,
        guards=guards,
        function_name=func.__name__,
    )

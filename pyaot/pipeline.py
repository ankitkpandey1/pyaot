"""
Optimized pipeline for PyAOT.

Provides the @optimize decorator that automatically profiles,
compiles, and hot-swaps to native implementations.
"""

from __future__ import annotations

import functools
import inspect
from typing import Any, Callable, Dict, List, Optional, Type, TypeVar
from dataclasses import dataclass

from pyaot.shapes.tracker import get_global_tracker, ShapeTracker
from pyaot.shapes.shape import Shape


F = TypeVar('F', bound=Callable[..., Any])


@dataclass
class OptimizationStats:
    """Statistics for an optimized function."""
    profile_calls: int = 0
    native_calls: int = 0
    fallback_calls: int = 0
    is_compiled: bool = False
    stable_types: List[str] = None
    
    def __post_init__(self):
        if self.stable_types is None:
            self.stable_types = []
    
    @property
    def total_calls(self) -> int:
        return self.profile_calls + self.native_calls + self.fallback_calls
    
    @property
    def native_ratio(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return self.native_calls / self.total_calls


class OptimizedFunction:
    """
    Wrapper for an optimized function.
    
    Phases:
    1. Profile: Observe types for first N calls
    2. Analyze: Check type stability when threshold reached
    3. Compile: Generate native code if stable
    4. Execute: Use native with guards, fallback on failure
    """
    
    def __init__(
        self,
        func: Callable,
        profile_calls: int = 100,
        stability_threshold: float = 0.95,
    ):
        self.func = func
        self.profile_calls = profile_calls
        self.stability_threshold = stability_threshold
        
        self._tracker = get_global_tracker()
        self._stats = OptimizationStats()
        self._observed_types: Dict[int, Type] = {}  # arg_idx -> observed type
        self._is_profiling = True
        self._native_impl: Optional[Callable] = None
        
        # Copy function metadata
        functools.update_wrapper(self, func)
    
    def __call__(self, *args, **kwargs) -> Any:
        """Execute the function."""
        if self._is_profiling:
            return self._profile_and_execute(*args, **kwargs)
        elif self._native_impl is not None:
            return self._guarded_execute(*args, **kwargs)
        else:
            return self.func(*args, **kwargs)
    
    def _profile_and_execute(self, *args, **kwargs) -> Any:
        """Profile types and execute."""
        self._stats.profile_calls += 1
        
        # Observe argument types
        for i, arg in enumerate(args):
            if hasattr(arg, '__dict__'):
                self._tracker.observe_object(arg)
                self._observed_types[i] = type(arg)
            elif hasattr(arg, '__iter__') and not isinstance(arg, (str, bytes)):
                # Observe elements of iterables
                try:
                    for item in list(arg)[:10]:  # Sample first 10
                        if hasattr(item, '__dict__'):
                            self._tracker.observe_object(item)
                            self._observed_types[i] = type(item)
                            break
                except (TypeError, StopIteration):
                    pass
        
        # Check if profiling phase complete
        if self._stats.profile_calls >= self.profile_calls:
            self._is_profiling = False
            self._try_compile()
        
        return self.func(*args, **kwargs)
    
    def _try_compile(self) -> None:
        """Try to compile if types are stable."""
        stable_types = []
        
        for arg_idx, observed_type in self._observed_types.items():
            type_id = id(observed_type)
            if self._tracker.is_type_stable(type_id):
                stable_types.append(observed_type.__name__)
                self._stats.stable_types.append(observed_type.__name__)
        
        if stable_types:
            # Types are stable - create optimized version
            self._create_native_impl()
            self._stats.is_compiled = True
    
    def _create_native_impl(self) -> None:
        """Create native implementation using shape-aware access."""
        # For now, create an optimized Python version that uses batch checking
        # Real implementation would generate LLVM code
        
        observed_types = dict(self._observed_types)
        tracker = self._tracker
        original = self.func
        
        def optimized(*args, **kwargs):
            # Batch type check at entry
            for i, expected_type in observed_types.items():
                if i < len(args):
                    arg = args[i]
                    # For iterables, check first element
                    if hasattr(arg, '__iter__') and not isinstance(arg, (str, bytes)):
                        try:
                            first = next(iter(arg))
                            if type(first) is not expected_type:
                                return original(*args, **kwargs)
                        except StopIteration:
                            pass
                    elif type(arg) is not expected_type:
                        return original(*args, **kwargs)
            
            # Types match - execute with optimized access
            return original(*args, **kwargs)
        
        self._native_impl = optimized
    
    def _guarded_execute(self, *args, **kwargs) -> Any:
        """Execute with guards."""
        try:
            result = self._native_impl(*args, **kwargs)
            self._stats.native_calls += 1
            return result
        except Exception:
            self._stats.fallback_calls += 1
            return self.func(*args, **kwargs)
    
    def get_stats(self) -> OptimizationStats:
        """Get optimization statistics."""
        return self._stats
    
    def reset(self) -> None:
        """Reset to profiling mode."""
        self._is_profiling = True
        self._native_impl = None
        self._stats = OptimizationStats()
        self._observed_types.clear()


def optimize(
    func: Optional[F] = None,
    *,
    profile_calls: int = 100,
    stability_threshold: float = 0.95,
) -> F:
    """
    Decorator to automatically optimize a function.
    
    The function goes through three phases:
    1. Profile: Observe types for first `profile_calls` invocations
    2. Compile: Generate optimized code if types are stable
    3. Execute: Use optimized code with guards, fallback on failure
    
    Usage:
        @optimize
        def sum_points(points):
            total = 0.0
            for p in points:
                total += p.x + p.y
            return total
    
    Args:
        func: The function to optimize.
        profile_calls: Number of calls to profile before compiling.
        stability_threshold: Required type stability ratio (0-1).
        
    Returns:
        Optimized wrapper function.
    """
    def decorator(f: F) -> F:
        return OptimizedFunction(
            f,
            profile_calls=profile_calls,
            stability_threshold=stability_threshold,
        )
    
    if func is not None:
        return decorator(func)
    return decorator


# =============================================================================
# Batch-optimized attribute access for lists of objects
# =============================================================================

def sum_attrs_optimized(
    objects: List[Any],
    attr_names: List[str],
    expected_type: Type,
) -> float:
    """
    Optimized sum of attributes from a list of objects.
    
    This function demonstrates the pattern that achieves speedup:
    1. Single type check at entry (not per-object)
    2. Direct __dict__ access (bypasses getattr)
    3. Native arithmetic
    
    Args:
        objects: List of objects to sum.
        attr_names: Attribute names to sum.
        expected_type: Expected type of all objects.
        
    Returns:
        Sum of all specified attributes.
    """
    if not objects:
        return 0.0
    
    # Single guard check at entry (sample first few objects)
    sample_size = min(10, len(objects))
    for obj in objects[:sample_size]:
        if type(obj) is not expected_type:
            # Fallback to standard access
            return _sum_attrs_fallback(objects, attr_names)
    
    # Fast path: direct dict access
    total = 0.0
    for obj in objects:
        obj_dict = obj.__dict__
        for attr in attr_names:
            total += obj_dict[attr]
    
    return total


def _sum_attrs_fallback(objects: List[Any], attr_names: List[str]) -> float:
    """Fallback using standard getattr."""
    total = 0.0
    for obj in objects:
        for attr in attr_names:
            total += getattr(obj, attr)
    return total


# =============================================================================
# Native loop compilation (simplified demonstration)
# =============================================================================

class NativeLoopCompiler:
    """
    Compiles object iteration loops to optimized code.
    
    This demonstrates the pattern for Phase 3 native compilation:
    - Hoist type checks out of loop
    - Inline dict access
    - Execute native arithmetic
    """
    
    def __init__(self, tracker: Optional[ShapeTracker] = None):
        self._tracker = tracker or get_global_tracker()
    
    def compile_sum_loop(
        self,
        expected_type: Type,
        attr_names: List[str],
    ) -> Callable[[List[Any]], float]:
        """
        Compile a sum loop for objects of expected_type.
        
        The compiled function:
        1. Guards on type at entry
        2. Uses direct dict access
        3. Falls back on guard failure
        
        Args:
            expected_type: The expected type of list elements.
            attr_names: Attributes to sum.
            
        Returns:
            Optimized sum function.
        """
        tracker = self._tracker
        type_id = id(expected_type)
        interned_attrs = [attr for attr in attr_names]  # Pre-intern
        
        def compiled_sum(objects: List[Any]) -> float:
            # Prologue: batch type guard
            if not objects:
                return 0.0
            
            # Sample-based guard (check first N objects)
            sample = min(10, len(objects))
            for i in range(sample):
                if type(objects[i]) is not expected_type:
                    # Guard failed - fallback
                    return _sum_attrs_fallback(objects, attr_names)
            
            # Shape stability check (one-time)
            if not tracker.is_type_stable(type_id):
                return _sum_attrs_fallback(objects, attr_names)
            
            # Fast path: direct dict access with inline arithmetic
            total = 0.0
            for obj in objects:
                d = obj.__dict__
                for attr in interned_attrs:
                    total += d[attr]
            
            return total
        
        return compiled_sum
    
    def compile_map_loop(
        self,
        expected_type: Type,
        attr_name: str,
    ) -> Callable[[List[Any]], List[Any]]:
        """
        Compile a map loop that extracts an attribute from all objects.
        
        Args:
            expected_type: The expected type of list elements.
            attr_name: Attribute to extract.
            
        Returns:
            Optimized extraction function.
        """
        type_id = id(expected_type)
        tracker = self._tracker
        
        def compiled_map(objects: List[Any]) -> List[Any]:
            if not objects:
                return []
            
            # Sample-based guard
            sample = min(10, len(objects))
            for i in range(sample):
                if type(objects[i]) is not expected_type:
                    return [getattr(obj, attr_name) for obj in objects]
            
            if not tracker.is_type_stable(type_id):
                return [getattr(obj, attr_name) for obj in objects]
            
            # Fast path
            return [obj.__dict__[attr_name] for obj in objects]
        
        return compiled_map

"""
Guard generation for inlined call sites.

Creates guard sets that verify assumptions at runtime,
enabling safe fallback to Python when guards fail.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, Tuple, Type
import sys

from pyaot.shapes.shape import Shape


@dataclass
class ShapeGuard:
    """Guard for array/object shape."""
    arg_index: int
    expected_shape: Optional[Tuple[int, ...]]
    expected_dtype: Optional[str] = None


@dataclass
class InlineGuardSet:
    """
    Set of guards for an inlined call site.
    
    All guards must pass for the native inlined path to be taken.
    On any guard failure, control falls back to Python.
    """
    
    # Function identity guard
    expected_callee_id: int
    expected_callee_name: str = ""
    
    # For bound methods: receiver type guard
    expected_receiver_type_id: Optional[int] = None
    expected_receiver_type_name: Optional[str] = None
    
    # Argument type guards
    expected_arg_types: Tuple[type, ...] = ()
    
    # Shape guards for arrays
    shape_guards: List[ShapeGuard] = field(default_factory=list)
    
    # Global/module version (for detecting module reloads)
    global_version: int = 0
    
    # Statistics
    check_count: int = field(default=0, repr=False)
    failure_count: int = field(default=0, repr=False)
    
    def check_callee(self, callee: Callable) -> bool:
        """Check if callee matches expected."""
        return id(callee) == self.expected_callee_id
    
    def check_receiver_type(self, receiver: Any) -> bool:
        """Check if receiver type matches expected."""
        if self.expected_receiver_type_id is None:
            return True
        return id(type(receiver)) == self.expected_receiver_type_id
    
    def check_arg_types(self, args: Tuple[Any, ...]) -> bool:
        """Check if argument types match expected."""
        if not self.expected_arg_types:
            return True
        if len(args) != len(self.expected_arg_types):
            return False
        for arg, expected_type in zip(args, self.expected_arg_types):
            if type(arg) is not expected_type:
                return False
        return True
    
    def check_shapes(self, args: Tuple[Any, ...]) -> bool:
        """Check if array shapes match expected."""
        for guard in self.shape_guards:
            if guard.arg_index >= len(args):
                return False
            arg = args[guard.arg_index]
            
            # Check shape
            if hasattr(arg, 'shape'):
                if guard.expected_shape is not None:
                    if arg.shape != guard.expected_shape:
                        return False
            
            # Check dtype
            if hasattr(arg, 'dtype'):
                if guard.expected_dtype is not None:
                    if str(arg.dtype) != guard.expected_dtype:
                        return False
        
        return True
    
    def check_all(
        self,
        callee: Callable,
        args: Tuple[Any, ...],
        receiver: Any = None,
    ) -> bool:
        """
        Check all guards.
        
        Returns True only if all guards pass.
        Updates statistics.
        """
        self.check_count += 1
        
        if not self.check_callee(callee):
            self.failure_count += 1
            return False
        
        if not self.check_receiver_type(receiver):
            self.failure_count += 1
            return False
        
        if not self.check_arg_types(args):
            self.failure_count += 1
            return False
        
        if not self.check_shapes(args):
            self.failure_count += 1
            return False
        
        return True
    
    @property
    def failure_rate(self) -> float:
        """Get the guard failure rate."""
        if self.check_count == 0:
            return 0.0
        return self.failure_count / self.check_count
    
    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "expected_callee_id": self.expected_callee_id,
            "expected_callee_name": self.expected_callee_name,
            "expected_receiver_type_id": self.expected_receiver_type_id,
            "expected_receiver_type_name": self.expected_receiver_type_name,
            "expected_arg_types": [t.__name__ for t in self.expected_arg_types],
            "shape_guards": [
                {
                    "arg_index": g.arg_index,
                    "expected_shape": g.expected_shape,
                    "expected_dtype": g.expected_dtype,
                }
                for g in self.shape_guards
            ],
            "global_version": self.global_version,
            "check_count": self.check_count,
            "failure_count": self.failure_count,
        }


def create_inline_guards(
    callee: Callable,
    receiver: Any = None,
    sample_args: Tuple[Any, ...] = (),
) -> InlineGuardSet:
    """
    Create guards for an inline candidate.
    
    Args:
        callee: The callee function.
        receiver: For bound methods, the receiver object.
        sample_args: Sample arguments to infer types.
        
    Returns:
        Guard set for the inlined call.
    """
    guards = InlineGuardSet(
        expected_callee_id=id(callee),
        expected_callee_name=getattr(callee, '__name__', str(callee)),
    )
    
    # Add receiver type guard for bound methods
    if receiver is not None:
        receiver_type = type(receiver)
        guards.expected_receiver_type_id = id(receiver_type)
        guards.expected_receiver_type_name = receiver_type.__name__
    
    # Add argument type guards
    if sample_args:
        guards.expected_arg_types = tuple(type(arg) for arg in sample_args)
    
    # Add shape guards for array arguments
    for i, arg in enumerate(sample_args):
        if hasattr(arg, 'shape') and hasattr(arg, 'dtype'):
            guards.shape_guards.append(ShapeGuard(
                arg_index=i,
                expected_shape=tuple(arg.shape),
                expected_dtype=str(arg.dtype),
            ))
    
    return guards


class GuardedInlineDispatcher:
    """
    Dispatcher that routes between inlined native and Python fallback.
    
    When guards pass, calls the inlined native implementation.
    When guards fail, falls back to the original Python call.
    """
    
    def __init__(
        self,
        native_impl: Callable,
        fallback: Callable,
        guards: InlineGuardSet,
    ):
        self.native_impl = native_impl
        self.fallback = fallback
        self.guards = guards
        self.native_calls = 0
        self.fallback_calls = 0
    
    def __call__(self, *args, **kwargs) -> Any:
        """Dispatch based on guard checks."""
        # For inlining, we don't support kwargs
        if kwargs:
            self.fallback_calls += 1
            return self.fallback(*args, **kwargs)
        
        # Check guards
        if self.guards.check_all(self.fallback, args):
            self.native_calls += 1
            return self.native_impl(*args)
        else:
            self.fallback_calls += 1
            return self.fallback(*args, **kwargs)
    
    @property
    def native_ratio(self) -> float:
        """Ratio of native vs total calls."""
        total = self.native_calls + self.fallback_calls
        if total == 0:
            return 0.0
        return self.native_calls / total
    
    def get_stats(self) -> dict:
        """Get dispatcher statistics."""
        return {
            "native_calls": self.native_calls,
            "fallback_calls": self.fallback_calls,
            "native_ratio": self.native_ratio,
            "guard_failure_rate": self.guards.failure_rate,
        }

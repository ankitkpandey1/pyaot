"""
Callsite Stub Implementation.

A CallsiteStub represents a specialized entry point for a hot callsite
that bypasses Python frame creation.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, List, Optional, Tuple


class GuardType(Enum):
    """Types of guards in a stub."""
    CALLEE_IDENTITY = auto()  # Check callee is expected function
    ARG_TYPE = auto()         # Check argument type
    ARG_VALUE = auto()        # Check argument value (for constants)
    SHAPE_STABLE = auto()     # Check object shape stability


@dataclass
class StubGuard:
    """A single guard in the stub sequence."""
    guard_type: GuardType
    arg_index: int = -1       # Which argument (-1 for callee)
    expected_type: Optional[type] = None
    expected_id: Optional[int] = None  # id() of expected object
    
    def check(self, callee: Callable, args: Tuple) -> bool:
        """Execute this guard check."""
        if self.guard_type == GuardType.CALLEE_IDENTITY:
            return id(callee) == self.expected_id
        
        elif self.guard_type == GuardType.ARG_TYPE:
            if self.arg_index >= len(args):
                return False
            return type(args[self.arg_index]) is self.expected_type
        
        elif self.guard_type == GuardType.ARG_VALUE:
            if self.arg_index >= len(args):
                return False
            return id(args[self.arg_index]) == self.expected_id
        
        return True


@dataclass
class CallsiteStub:
    """
    Callsite-specialized entry stub.
    
    Bypasses Python frame creation for hot monomorphic callsites.
    
    Flow:
        1. Check guard sequence
        2. PASS → jump to native entry (no frame)
        3. FAIL → call fallback (PyObject_Call)
    """
    callsite_id: str
    callee: Callable
    callee_id: int
    
    # Guard sequence
    guards: List[StubGuard] = field(default_factory=list)
    
    # Native entry (function pointer from LLVM)
    native_entry: Optional[int] = None
    native_callable: Optional[Callable] = None
    
    # Fallback
    fallback: Optional[Callable] = None
    
    # Statistics
    native_calls: int = 0
    fallback_calls: int = 0
    guard_failures: int = 0
    
    def __post_init__(self):
        if self.fallback is None:
            self.fallback = self.callee
    
    def execute(self, *args, **kwargs) -> Any:
        """
        Execute the stub.
        
        Checks guards and dispatches to native or fallback.
        """
        # Check all guards
        if self._check_guards(args):
            # Guards passed - use native path
            if self.native_callable is not None:
                self.native_calls += 1
                return self.native_callable(*args)
        
        # Guards failed or no native - use fallback
        self.fallback_calls += 1
        self.guard_failures += 1
        return self.fallback(*args, **kwargs)
    
    def _check_guards(self, args: Tuple) -> bool:
        """Check all guards in sequence."""
        for guard in self.guards:
            if not guard.check(self.callee, args):
                return False
        return True
    
    def add_callee_guard(self) -> None:
        """Add guard for callee identity."""
        self.guards.append(StubGuard(
            guard_type=GuardType.CALLEE_IDENTITY,
            expected_id=self.callee_id,
        ))
    
    def add_type_guard(self, arg_index: int, expected_type: type) -> None:
        """Add guard for argument type."""
        self.guards.append(StubGuard(
            guard_type=GuardType.ARG_TYPE,
            arg_index=arg_index,
            expected_type=expected_type,
        ))
    
    @property
    def guard_failure_rate(self) -> float:
        """Calculate guard failure rate."""
        total = self.native_calls + self.fallback_calls
        if total == 0:
            return 0.0
        return self.guard_failures / total
    
    def get_stats(self) -> dict:
        """Get stub statistics."""
        return {
            "callsite_id": self.callsite_id,
            "native_calls": self.native_calls,
            "fallback_calls": self.fallback_calls,
            "guard_failures": self.guard_failures,
            "guard_failure_rate": self.guard_failure_rate,
        }


def create_stub(
    callsite_id: str,
    callee: Callable,
    arg_types: Tuple[type, ...],
    native_callable: Optional[Callable] = None,
) -> CallsiteStub:
    """
    Create a callsite stub with standard guards.
    
    Args:
        callsite_id: Unique callsite identifier
        callee: The callee function
        arg_types: Expected argument types
        native_callable: Native compiled version
        
    Returns:
        Configured CallsiteStub
    """
    stub = CallsiteStub(
        callsite_id=callsite_id,
        callee=callee,
        callee_id=id(callee),
        native_callable=native_callable,
    )
    
    # Add callee identity guard
    stub.add_callee_guard()
    
    # Add type guards for each argument
    for i, t in enumerate(arg_types):
        stub.add_type_guard(i, t)
    
    return stub

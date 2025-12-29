"""
Trampoline generation for guarded inline calls.

Creates C ABI compatible trampolines that:
1. Check guards
2. Call native inlined path if guards pass
3. Fall back to PyObject_Call if guards fail
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
from typing import Any, Callable, Optional, Tuple

from pyaot.inline.guards import InlineGuardSet


@dataclass
class InlineTrampoline:
    """
    Trampoline for a single inlined call site.
    
    Routes between native and fallback based on guards.
    """
    
    # The inlined native implementation
    native_impl: Callable
    
    # Guard set
    guards: InlineGuardSet
    
    # Original fallback
    fallback: Callable
    
    # Statistics
    native_calls: int = 0
    fallback_calls: int = 0
    guard_check_time_ns: int = 0
    
    def __call__(self, *args) -> Any:
        """
        Execute through trampoline.
        
        Checks guards and routes to native or fallback.
        """
        # Fast path: check guards
        callee = self.fallback
        
        if self.guards.check_all(callee, args):
            # Guards passed - use native
            self.native_calls += 1
            return self.native_impl(*args)
        else:
            # Guards failed - fallback
            self.fallback_calls += 1
            return self.fallback(*args)
    
    @property
    def native_ratio(self) -> float:
        """Ratio of native to total calls."""
        total = self.native_calls + self.fallback_calls
        if total == 0:
            return 0.0
        return self.native_calls / total
    
    @property
    def total_calls(self) -> int:
        """Total calls through trampoline."""
        return self.native_calls + self.fallback_calls
    
    def get_stats(self) -> dict:
        """Get trampoline statistics."""
        return {
            "native_calls": self.native_calls,
            "fallback_calls": self.fallback_calls,
            "native_ratio": self.native_ratio,
            "guard_failure_rate": self.guards.failure_rate,
            "total_calls": self.total_calls,
        }
    
    def reset_stats(self) -> None:
        """Reset statistics."""
        self.native_calls = 0
        self.fallback_calls = 0
        self.guard_check_time_ns = 0
        self.guards.check_count = 0
        self.guards.failure_count = 0


def create_trampoline(
    native_impl: Callable,
    fallback: Callable,
    guards: InlineGuardSet,
) -> InlineTrampoline:
    """
    Create a trampoline for an inlined call site.
    
    Args:
        native_impl: The inlined native implementation.
        fallback: The original Python function.
        guards: Guard set for this inline.
        
    Returns:
        InlineTrampoline instance.
    """
    return InlineTrampoline(
        native_impl=native_impl,
        guards=guards,
        fallback=fallback,
    )


class TrampolineRegistry:
    """
    Registry of all trampolines for a module/function.
    
    Manages the collection of inline trampolines and provides
    lookup by callsite ID.
    """
    
    def __init__(self):
        self._trampolines: dict[str, InlineTrampoline] = {}
    
    def register(
        self,
        callsite_id: str,
        trampoline: InlineTrampoline,
    ) -> None:
        """Register a trampoline for a callsite."""
        self._trampolines[callsite_id] = trampoline
    
    def get(self, callsite_id: str) -> Optional[InlineTrampoline]:
        """Get trampoline for a callsite."""
        return self._trampolines.get(callsite_id)
    
    def get_all_stats(self) -> dict:
        """Get statistics for all trampolines."""
        total_native = sum(t.native_calls for t in self._trampolines.values())
        total_fallback = sum(t.fallback_calls for t in self._trampolines.values())
        total = total_native + total_fallback
        
        return {
            "trampoline_count": len(self._trampolines),
            "total_native_calls": total_native,
            "total_fallback_calls": total_fallback,
            "overall_native_ratio": total_native / total if total > 0 else 0.0,
            "per_trampoline": {
                k: v.get_stats() for k, v in self._trampolines.items()
            },
        }
    
    def clear(self) -> None:
        """Clear all trampolines."""
        self._trampolines.clear()


# Global trampoline registry
_global_registry: Optional[TrampolineRegistry] = None


def get_trampoline_registry() -> TrampolineRegistry:
    """Get the global trampoline registry."""
    global _global_registry
    if _global_registry is None:
        _global_registry = TrampolineRegistry()
    return _global_registry


def inline_call(
    callsite_id: str,
    callee: Callable,
    args: Tuple[Any, ...],
) -> Any:
    """
    Execute a call through the inline trampoline if available.
    
    This is the main entry point for inlined calls at runtime.
    
    Args:
        callsite_id: The callsite identifier.
        callee: The function being called.
        args: Arguments to the call.
        
    Returns:
        Result of the call (native or fallback).
    """
    registry = get_trampoline_registry()
    trampoline = registry.get(callsite_id)
    
    if trampoline is not None:
        return trampoline(*args)
    else:
        # No trampoline registered - direct call
        return callee(*args)

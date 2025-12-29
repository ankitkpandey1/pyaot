"""
Fast attribute access with shape guards for PyAOT.

Provides guarded attribute access that uses side-table shape information
to optimize lookups while maintaining correctness via runtime guards.

The fast path:
1. Guard on type identity
2. Guard on shape stability
3. Direct __dict__ lookup

Any guard failure falls back to standard getattr().
"""

import sys
from typing import Any, Optional, Type

# Try to import C extension, fall back to pure Python
try:
    from pyaot.shapes._fast_attr import (
        fast_getattr as _c_fast_getattr,
        GUARD_FAILED as _C_GUARD_FAILED,
    )
    _HAS_C_EXTENSION = True
except ImportError:
    _HAS_C_EXTENSION = False
    _c_fast_getattr = None
    _C_GUARD_FAILED = None

# Pure Python sentinel for guard failure
class _GuardFailedSentinel:
    """Sentinel object indicating guard failure."""
    __slots__ = ()
    
    def __repr__(self) -> str:
        return "GUARD_FAILED"
    
    def __bool__(self) -> bool:
        # Ensure it's falsy to catch if result: patterns
        return False

GUARD_FAILED = _GuardFailedSentinel()


# Lazy import to avoid circular dependency
_tracker = None


def _get_tracker():
    """Get the global tracker (lazy import)."""
    global _tracker
    if _tracker is None:
        from pyaot.shapes.tracker import get_global_tracker
        _tracker = get_global_tracker()
    return _tracker


def _reset_cached_tracker():
    """Reset the cached tracker reference (for testing)."""
    global _tracker
    _tracker = None


def fast_getattr_guarded(
    obj: object,
    attr_name: str,
    expected_type: Type,
    use_c_extension: bool = True,
) -> Any:
    """
    Perform fast attribute access with guards.
    
    This function attempts a fast-path attribute lookup that bypasses
    some of the overhead of standard getattr(). It uses runtime guards
    to ensure correctness.
    
    Args:
        obj: The object to access.
        attr_name: Name of the attribute.
        expected_type: The expected type of obj.
        use_c_extension: Whether to try C extension (default True).
        
    Returns:
        The attribute value on success.
        
    Raises:
        GuardFailedError: If any guard fails.
        AttributeError: If attribute not found after guards pass.
    """
    # Guard 1: Type identity check
    if type(obj) is not expected_type:
        raise GuardFailedError(
            f"Type mismatch: expected {expected_type.__name__}, "
            f"got {type(obj).__name__}"
        )
    
    # Guard 2: Type is shape-stable
    tracker = _get_tracker()
    type_id = id(expected_type)
    
    if not tracker.is_type_stable(type_id):
        raise GuardFailedError(
            f"Type {expected_type.__name__} is not shape-stable"
        )
    
    # Fast attribute access
    if use_c_extension and _HAS_C_EXTENSION and _c_fast_getattr is not None:
        # Use C extension
        interned_name = sys.intern(attr_name)
        result = _c_fast_getattr(obj, expected_type, interned_name)
        if result is _C_GUARD_FAILED:
            raise GuardFailedError(f"C fast_getattr failed for '{attr_name}'")
        return result
    else:
        # Pure Python fast path
        obj_dict = getattr(obj, '__dict__', None)
        if obj_dict is None:
            raise GuardFailedError(
                f"Object has no __dict__"
            )
        
        try:
            return obj_dict[attr_name]
        except KeyError:
            raise AttributeError(
                f"'{expected_type.__name__}' object has no attribute '{attr_name}'"
            )


def guarded_attr_access(
    obj: object,
    attr_name: str,
    expected_type: Type,
) -> Any:
    """
    High-level guarded attribute access with automatic fallback.
    
    This is the main integration surface for code generators.
    It attempts the fast path and silently falls back to getattr()
    on any failure.
    
    Semantics:
        - On fast path success: returns attribute value
        - On guard failure: returns getattr(obj, attr_name)
        - On attribute error: raises AttributeError (same as getattr)
    
    Args:
        obj: The object to access.
        attr_name: Name of the attribute.
        expected_type: The expected type of obj.
        
    Returns:
        The attribute value.
        
    Raises:
        AttributeError: If attribute doesn't exist (same as getattr).
    """
    try:
        return fast_getattr_guarded(obj, attr_name, expected_type)
    except GuardFailedError:
        # Silent fallback to standard Python
        return getattr(obj, attr_name)


def guarded_attr_access_with_stats(
    obj: object,
    attr_name: str,
    expected_type: Type,
    stats: Optional["FastAttrStats"] = None,
) -> Any:
    """
    Guarded attribute access that tracks statistics.
    
    Same as guarded_attr_access but records fast path vs fallback usage.
    
    Args:
        obj: The object to access.
        attr_name: Name of the attribute.
        expected_type: The expected type of obj.
        stats: Optional FastAttrStats to record statistics.
        
    Returns:
        The attribute value.
    """
    try:
        result = fast_getattr_guarded(obj, attr_name, expected_type)
        if stats is not None:
            stats.fast_path_hits += 1
        return result
    except GuardFailedError:
        if stats is not None:
            stats.fallback_calls += 1
        return getattr(obj, attr_name)


class GuardFailedError(Exception):
    """Exception raised when a guard check fails."""
    pass


class FastAttrStats:
    """Statistics for fast attribute access."""
    __slots__ = ('fast_path_hits', 'fallback_calls')
    
    def __init__(self):
        self.fast_path_hits = 0
        self.fallback_calls = 0
    
    @property
    def total_calls(self) -> int:
        return self.fast_path_hits + self.fallback_calls
    
    @property
    def fast_path_ratio(self) -> float:
        total = self.total_calls
        if total == 0:
            return 0.0
        return self.fast_path_hits / total
    
    def reset(self) -> None:
        self.fast_path_hits = 0
        self.fallback_calls = 0
    
    def __repr__(self) -> str:
        return (
            f"FastAttrStats(hits={self.fast_path_hits}, "
            f"fallbacks={self.fallback_calls}, "
            f"ratio={self.fast_path_ratio:.2%})"
        )


# Convenience function to check if C extension is available
def has_c_extension() -> bool:
    """Check if the C extension is available."""
    return _HAS_C_EXTENSION

"""
Side-table object shape system for PyAOT.

This module provides shape tracking and fast attribute access
without modifying CPython object layout.

Key components:
- Shape: Immutable shape descriptor (type_id, dict_keys)
- ShapeRegistry: Global thread-safe shape registration
- ShapeTracker: Type-level shape stability tracking
- fast_getattr: Guarded fast attribute access
"""

from pyaot.shapes.shape import Shape, ShapeID
from pyaot.shapes.registry import ShapeRegistry, get_global_registry
from pyaot.shapes.tracker import ShapeTracker, TypeShapeInfo, get_global_tracker
from pyaot.shapes.fast_attr import (
    guarded_attr_access,
    fast_getattr_guarded,
    GUARD_FAILED,
)

__all__ = [
    # Core types
    "Shape",
    "ShapeID",
    # Registry
    "ShapeRegistry",
    "get_global_registry",
    # Tracker
    "ShapeTracker",
    "TypeShapeInfo",
    "get_global_tracker",
    # Fast access
    "guarded_attr_access",
    "fast_getattr_guarded",
    "GUARD_FAILED",
]

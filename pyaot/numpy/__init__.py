"""
PyAOT NumPy Module.

Provides NumPy-specific optimizations:
- Operation fusion to eliminate intermediate arrays
- Pattern recognition for common idioms
- Vectorized code generation
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyaot.numpy.fusion import NumPyFusionPass
    from pyaot.numpy.patterns import FusionPattern


__all__ = [
    "NumPyFusionPass",
    "FusionPattern",
    "fuse_operations",
]


def fuse_operations(func):
    """
    Decorator to enable NumPy operation fusion.
    
    Example:
        @fuse_operations
        def compute(a, b):
            return np.sqrt(a**2 + b**2)
    """
    from pyaot.numpy.fusion import NumPyFusionPass
    
    fusion = NumPyFusionPass()
    return fusion.optimize(func)

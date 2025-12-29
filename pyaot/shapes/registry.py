"""
Thread-safe shape registry for PyAOT.

The ShapeRegistry provides global registration and lookup of shapes,
assigning unique ShapeIDs to each distinct shape.
"""

import threading
from typing import Dict, Optional

from pyaot.shapes.shape import Shape, ShapeID


class ShapeRegistry:
    """
    Thread-safe global registry for shape management.
    
    Each unique Shape is assigned a ShapeID (integer) for efficient
    comparison and storage. The registry is append-only - shapes are
    never removed or modified.
    
    Thread Safety:
        All public methods are thread-safe via internal locking.
        
    Example:
        >>> registry = ShapeRegistry()
        >>> shape = Shape(type_id=123, dict_keys=('x', 'y'))
        >>> shape_id = registry.register(shape)
        >>> registry.get_shape(shape_id) == shape
        True
    """
    
    def __init__(self):
        """Initialize an empty registry."""
        self._lock = threading.Lock()
        self._shapes: Dict[Shape, ShapeID] = {}
        self._id_to_shape: Dict[ShapeID, Shape] = {}
        self._next_id: ShapeID = 0
    
    def register(self, shape: Shape) -> ShapeID:
        """
        Register a shape and return its ID.
        
        If the shape is already registered, returns the existing ID.
        Otherwise, assigns a new ID.
        
        Args:
            shape: The shape to register.
            
        Returns:
            The ShapeID for this shape.
        """
        with self._lock:
            # Check if already registered
            existing_id = self._shapes.get(shape)
            if existing_id is not None:
                return existing_id
            
            # Assign new ID
            shape_id = self._next_id
            self._next_id += 1
            self._shapes[shape] = shape_id
            self._id_to_shape[shape_id] = shape
            return shape_id
    
    def get_id(self, shape: Shape) -> Optional[ShapeID]:
        """
        Get ID for an existing shape.
        
        Args:
            shape: The shape to look up.
            
        Returns:
            The ShapeID if registered, None otherwise.
        """
        with self._lock:
            return self._shapes.get(shape)
    
    def get_shape(self, shape_id: ShapeID) -> Optional[Shape]:
        """
        Get shape by ID.
        
        Args:
            shape_id: The shape ID to look up.
            
        Returns:
            The Shape if found, None otherwise.
        """
        with self._lock:
            return self._id_to_shape.get(shape_id)
    
    def register_from_object(self, obj: object) -> ShapeID:
        """
        Convenience method to register shape from an object.
        
        Args:
            obj: Object to extract shape from.
            
        Returns:
            The ShapeID for this object's shape.
        """
        shape = Shape.from_object(obj)
        return self.register(shape)
    
    def __len__(self) -> int:
        """Return number of registered shapes."""
        with self._lock:
            return len(self._shapes)
    
    def clear(self) -> None:
        """
        Clear all registered shapes.
        
        WARNING: This invalidates all existing ShapeIDs.
        Only use for testing or reset scenarios.
        """
        with self._lock:
            self._shapes.clear()
            self._id_to_shape.clear()
            self._next_id = 0
    
    def get_stats(self) -> Dict[str, int]:
        """
        Get registry statistics.
        
        Returns:
            Dict with 'total_shapes' and 'next_id'.
        """
        with self._lock:
            return {
                "total_shapes": len(self._shapes),
                "next_id": self._next_id,
            }


# Global registry instance
_global_registry: Optional[ShapeRegistry] = None
_global_registry_lock = threading.Lock()


def get_global_registry() -> ShapeRegistry:
    """
    Get the global ShapeRegistry instance.
    
    Creates one if it doesn't exist (thread-safe).
    
    Returns:
        The global ShapeRegistry.
    """
    global _global_registry
    if _global_registry is None:
        with _global_registry_lock:
            if _global_registry is None:
                _global_registry = ShapeRegistry()
    return _global_registry


def reset_global_registry() -> None:
    """
    Reset the global registry.
    
    WARNING: Invalidates all existing ShapeIDs.
    Only use for testing.
    """
    global _global_registry
    with _global_registry_lock:
        if _global_registry is not None:
            _global_registry.clear()
        _global_registry = None

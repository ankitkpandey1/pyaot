"""
Shape tracker for PyAOT.

Tracks shape stability at the type level to determine which types
have consistent attribute layouts suitable for fast access optimization.
"""

import threading
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, Optional, List, Tuple

from pyaot.shapes.shape import Shape, ShapeID
from pyaot.shapes.registry import ShapeRegistry, get_global_registry


@dataclass
class TypeShapeInfo:
    """
    Per-type shape tracking information.
    
    Tracks which shapes have been observed for instances of a type
    and whether the type is "shape-stable" (all instances share
    the same shape).
    
    Attributes:
        type_id: The id() of the type being tracked.
        type_ref: Weak reference to the actual type object.
        observed_shapes: Counter of shape frequencies.
        is_stable: Whether this type is shape-stable.
        common_shape_id: The most common ShapeID (if stable).
        observation_count: Total observations.
    """
    type_id: int
    type_name: str = ""
    observed_shapes: Counter = field(default_factory=Counter)
    is_stable: bool = True
    common_shape_id: Optional[ShapeID] = None
    observation_count: int = 0
    
    def get_stability_ratio(self) -> float:
        """
        Get the ratio of the most common shape.
        
        Returns:
            Ratio in [0.0, 1.0], or 1.0 if no observations.
        """
        if self.observation_count == 0:
            return 1.0
        
        if not self.observed_shapes:
            return 1.0
        
        most_common = self.observed_shapes.most_common(1)
        if not most_common:
            return 1.0
        
        _, count = most_common[0]
        return count / self.observation_count
    
    def get_shape_count(self) -> int:
        """Return number of distinct shapes observed."""
        return len(self.observed_shapes)


class ShapeTracker:
    """
    Tracks shape stability across types.
    
    The ShapeTracker observes objects during profiling and determines
    which types have "stable" shapes (i.e., all or nearly all instances
    share the same attribute layout).
    
    A type is considered stable if >= stability_threshold of observed
    instances share the same shape.
    
    Thread Safety:
        All public methods are thread-safe via internal locking.
        
    Example:
        >>> tracker = ShapeTracker()
        >>> class Point:
        ...     def __init__(self, x, y):
        ...         self.x = x
        ...         self.y = y
        >>> for i in range(100):
        ...     tracker.observe_object(Point(i, i+1))
        >>> tracker.is_type_stable(id(Point))
        True
    """
    
    def __init__(
        self,
        stability_threshold: float = 0.95,
        min_observations: int = 10,
        registry: Optional[ShapeRegistry] = None,
    ):
        """
        Initialize the tracker.
        
        Args:
            stability_threshold: Minimum ratio for stability (default 0.95).
            min_observations: Minimum observations before declaring stability.
            registry: ShapeRegistry to use (default: global registry).
        """
        self._lock = threading.Lock()
        self._registry = registry or get_global_registry()
        self._type_info: Dict[int, TypeShapeInfo] = {}
        self._stability_threshold = stability_threshold
        self._min_observations = min_observations
    
    @property
    def stability_threshold(self) -> float:
        """Get the stability threshold."""
        return self._stability_threshold
    
    @property
    def registry(self) -> ShapeRegistry:
        """Get the associated ShapeRegistry."""
        return self._registry
    
    def observe_object(self, obj: object) -> ShapeID:
        """
        Observe an object's shape and update tracking.
        
        Args:
            obj: The object to observe.
            
        Returns:
            The ShapeID for this object's shape.
        """
        shape = Shape.from_object(obj)
        shape_id = self._registry.register(shape)
        type_id = shape.type_id
        
        with self._lock:
            # Get or create type info
            info = self._type_info.get(type_id)
            if info is None:
                info = TypeShapeInfo(
                    type_id=type_id,
                    type_name=type(obj).__name__,
                )
                self._type_info[type_id] = info
            
            # Update observations
            info.observed_shapes[shape_id] += 1
            info.observation_count += 1
            
            # Recompute stability
            self._update_stability(info)
        
        return shape_id
    
    def observe_objects(self, objects: List[object]) -> List[ShapeID]:
        """
        Observe multiple objects (batch operation).
        
        Args:
            objects: List of objects to observe.
            
        Returns:
            List of ShapeIDs.
        """
        return [self.observe_object(obj) for obj in objects]
    
    def is_type_stable(self, type_id: int) -> bool:
        """
        Check if a type has stable shape.
        
        Args:
            type_id: The id() of the type to check.
            
        Returns:
            True if the type is shape-stable, False otherwise.
        """
        with self._lock:
            info = self._type_info.get(type_id)
            if info is None:
                return False
            return info.is_stable
    
    def is_type_stable_by_type(self, obj_type: type) -> bool:
        """
        Check if a type has stable shape (by type object).
        
        Args:
            obj_type: The type object to check.
            
        Returns:
            True if the type is shape-stable.
        """
        return self.is_type_stable(id(obj_type))
    
    def get_common_shape(self, type_id: int) -> Optional[ShapeID]:
        """
        Get the common shape ID for a type.
        
        Args:
            type_id: The id() of the type.
            
        Returns:
            The most common ShapeID, or None if type not tracked.
        """
        with self._lock:
            info = self._type_info.get(type_id)
            return info.common_shape_id if info else None
    
    def get_common_shape_by_type(self, obj_type: type) -> Optional[ShapeID]:
        """
        Get the common shape ID for a type (by type object).
        
        Args:
            obj_type: The type object.
            
        Returns:
            The most common ShapeID.
        """
        return self.get_common_shape(id(obj_type))
    
    def get_type_info(self, type_id: int) -> Optional[TypeShapeInfo]:
        """
        Get tracking info for a type.
        
        Args:
            type_id: The id() of the type.
            
        Returns:
            TypeShapeInfo or None if not tracked.
        """
        with self._lock:
            info = self._type_info.get(type_id)
            if info is None:
                return None
            # Return a copy to avoid external mutation
            return TypeShapeInfo(
                type_id=info.type_id,
                type_name=info.type_name,
                observed_shapes=Counter(info.observed_shapes),
                is_stable=info.is_stable,
                common_shape_id=info.common_shape_id,
                observation_count=info.observation_count,
            )
    
    def get_stable_types(self) -> List[Tuple[int, str, ShapeID]]:
        """
        Get all stable types.
        
        Returns:
            List of (type_id, type_name, common_shape_id) tuples.
        """
        with self._lock:
            result = []
            for type_id, info in self._type_info.items():
                if info.is_stable and info.common_shape_id is not None:
                    result.append((type_id, info.type_name, info.common_shape_id))
            return result
    
    def _update_stability(self, info: TypeShapeInfo) -> None:
        """
        Recompute stability for a type after observation.
        
        Must be called with lock held.
        """
        # Not enough observations yet
        if info.observation_count < self._min_observations:
            info.is_stable = True  # Assume stable until proven otherwise
            if info.observed_shapes:
                most_common = info.observed_shapes.most_common(1)[0]
                info.common_shape_id = most_common[0]
            return
        
        # Compute stability ratio
        most_common = info.observed_shapes.most_common(1)
        if not most_common:
            info.is_stable = False
            info.common_shape_id = None
            return
        
        most_common_id, count = most_common[0]
        ratio = count / info.observation_count
        
        info.is_stable = ratio >= self._stability_threshold
        if info.is_stable:
            info.common_shape_id = most_common_id
        else:
            # Still track common shape even if unstable
            info.common_shape_id = most_common_id
    
    def get_stats(self) -> Dict[str, int]:
        """
        Get tracker statistics.
        
        Returns:
            Dict with counts.
        """
        with self._lock:
            stable_count = sum(1 for info in self._type_info.values() if info.is_stable)
            return {
                "total_types_tracked": len(self._type_info),
                "stable_types": stable_count,
                "unstable_types": len(self._type_info) - stable_count,
                "total_observations": sum(
                    info.observation_count for info in self._type_info.values()
                ),
            }
    
    def clear(self) -> None:
        """
        Clear all tracking data.
        
        WARNING: Only use for testing or reset scenarios.
        """
        with self._lock:
            self._type_info.clear()


# Global tracker instance
_global_tracker: Optional[ShapeTracker] = None
_global_tracker_lock = threading.Lock()


def get_global_tracker() -> ShapeTracker:
    """
    Get the global ShapeTracker instance.
    
    Creates one if it doesn't exist (thread-safe).
    
    Returns:
        The global ShapeTracker.
    """
    global _global_tracker
    if _global_tracker is None:
        with _global_tracker_lock:
            if _global_tracker is None:
                _global_tracker = ShapeTracker()
    return _global_tracker


def reset_global_tracker() -> None:
    """
    Reset the global tracker.
    
    WARNING: Invalidates all tracking data.
    Only use for testing.
    """
    global _global_tracker
    with _global_tracker_lock:
        if _global_tracker is not None:
            _global_tracker.clear()
        _global_tracker = None

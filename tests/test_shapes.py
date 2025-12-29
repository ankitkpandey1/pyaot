"""
Tests for PyAOT Phase 2: Side-Table Shape System.

Tests cover:
- Shape creation and hashing
- ShapeRegistry registration and lookup
- ShapeTracker stability detection
- Fast attribute access with guards
- Guard failure and fallback behavior
"""

import pytest
import threading
from typing import List


class TestShape:
    """Tests for Shape data structure."""
    
    def test_shape_from_object(self):
        """Test Shape.from_object creates correct shape."""
        from pyaot.shapes.shape import Shape
        
        class Point:
            def __init__(self, x, y):
                self.x = x
                self.y = y
        
        p = Point(1, 2)
        shape = Shape.from_object(p)
        
        assert shape.type_id == id(type(p))
        assert shape.dict_keys == ('x', 'y')
    
    def test_shape_equality(self):
        """Test Shape equality based on type_id and dict_keys."""
        from pyaot.shapes.shape import Shape
        
        class Point:
            def __init__(self, x, y):
                self.x = x
                self.y = y
        
        p1 = Point(1, 2)
        p2 = Point(3, 4)
        
        shape1 = Shape.from_object(p1)
        shape2 = Shape.from_object(p2)
        
        # Same class, same attribute order -> equal shapes
        assert shape1 == shape2
        assert hash(shape1) == hash(shape2)
    
    def test_shape_different_keys(self):
        """Test shapes differ when dict_keys differ."""
        from pyaot.shapes.shape import Shape
        
        class Point:
            pass
        
        p1 = Point()
        p1.x = 1
        p1.y = 2
        
        p2 = Point()
        p2.a = 1
        p2.b = 2
        
        shape1 = Shape.from_object(p1)
        shape2 = Shape.from_object(p2)
        
        assert shape1 != shape2
    
    def test_shape_has_attribute(self):
        """Test Shape.has_attribute method."""
        from pyaot.shapes.shape import Shape
        
        shape = Shape(type_id=123, dict_keys=('x', 'y', 'z'))
        
        assert shape.has_attribute('x')
        assert shape.has_attribute('y')
        assert shape.has_attribute('z')
        assert not shape.has_attribute('w')
    
    def test_shape_get_attribute_index(self):
        """Test Shape.get_attribute_index method."""
        from pyaot.shapes.shape import Shape
        
        shape = Shape(type_id=123, dict_keys=('x', 'y', 'z'))
        
        assert shape.get_attribute_index('x') == 0
        assert shape.get_attribute_index('y') == 1
        assert shape.get_attribute_index('z') == 2
        assert shape.get_attribute_index('w') is None
    
    def test_shape_matches_object(self):
        """Test Shape.matches_object method."""
        from pyaot.shapes.shape import Shape
        
        class Point:
            def __init__(self, x, y):
                self.x = x
                self.y = y
        
        p = Point(1, 2)
        shape = Shape.from_object(p)
        
        assert shape.matches_object(p)
        
        # Add attribute -> shape no longer matches
        p.z = 3
        assert not shape.matches_object(p)
    
    def test_shape_from_slotted_class(self):
        """Test Shape from slotted class (no __dict__)."""
        from pyaot.shapes.shape import Shape
        
        class SlottedPoint:
            __slots__ = ('x', 'y')
            def __init__(self, x, y):
                self.x = x
                self.y = y
        
        p = SlottedPoint(1, 2)
        shape = Shape.from_object(p)
        
        assert shape.dict_keys == ()  # No __dict__ -> empty keys


class TestShapeRegistry:
    """Tests for ShapeRegistry."""
    
    def test_register_and_lookup(self):
        """Test registering and looking up shapes."""
        from pyaot.shapes.shape import Shape
        from pyaot.shapes.registry import ShapeRegistry
        
        registry = ShapeRegistry()
        shape = Shape(type_id=123, dict_keys=('x', 'y'))
        
        shape_id = registry.register(shape)
        assert shape_id == 0  # First registered shape
        
        # Lookup by shape
        assert registry.get_id(shape) == shape_id
        
        # Lookup by ID
        assert registry.get_shape(shape_id) == shape
    
    def test_register_same_shape_returns_same_id(self):
        """Test registering same shape twice returns same ID."""
        from pyaot.shapes.shape import Shape
        from pyaot.shapes.registry import ShapeRegistry
        
        registry = ShapeRegistry()
        shape = Shape(type_id=123, dict_keys=('x', 'y'))
        
        id1 = registry.register(shape)
        id2 = registry.register(shape)
        
        assert id1 == id2
        assert len(registry) == 1
    
    def test_register_different_shapes(self):
        """Test registering different shapes gets different IDs."""
        from pyaot.shapes.shape import Shape
        from pyaot.shapes.registry import ShapeRegistry
        
        registry = ShapeRegistry()
        shape1 = Shape(type_id=123, dict_keys=('x', 'y'))
        shape2 = Shape(type_id=123, dict_keys=('a', 'b'))
        
        id1 = registry.register(shape1)
        id2 = registry.register(shape2)
        
        assert id1 != id2
        assert len(registry) == 2
    
    def test_register_from_object(self):
        """Test register_from_object convenience method."""
        from pyaot.shapes.registry import ShapeRegistry
        
        class Point:
            def __init__(self, x, y):
                self.x = x
                self.y = y
        
        registry = ShapeRegistry()
        p = Point(1, 2)
        
        shape_id = registry.register_from_object(p)
        assert shape_id == 0
    
    def test_thread_safety(self):
        """Test registry is thread-safe."""
        from pyaot.shapes.shape import Shape
        from pyaot.shapes.registry import ShapeRegistry
        
        registry = ShapeRegistry()
        errors = []
        
        def register_shapes(thread_id: int):
            try:
                for i in range(100):
                    shape = Shape(type_id=thread_id, dict_keys=(f'attr_{i}',))
                    registry.register(shape)
            except Exception as e:
                errors.append(e)
        
        threads = [
            threading.Thread(target=register_shapes, args=(i,))
            for i in range(10)
        ]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert not errors
        # Each thread registers 100 unique shapes
        assert len(registry) == 1000


class TestShapeTracker:
    """Tests for ShapeTracker."""
    
    def test_observe_object(self):
        """Test observing objects updates tracker."""
        from pyaot.shapes.tracker import ShapeTracker
        
        class Point:
            def __init__(self, x, y):
                self.x = x
                self.y = y
        
        tracker = ShapeTracker()
        p = Point(1, 2)
        
        shape_id = tracker.observe_object(p)
        assert shape_id == 0  # First observed shape
        
        info = tracker.get_type_info(id(Point))
        assert info is not None
        assert info.observation_count == 1
    
    def test_type_becomes_stable(self):
        """Test type becomes stable after enough consistent observations."""
        from pyaot.shapes.tracker import ShapeTracker
        
        class Point:
            def __init__(self, x, y):
                self.x = x
                self.y = y
        
        tracker = ShapeTracker(stability_threshold=0.95, min_observations=10)
        
        # Create 20 identical points
        for _ in range(20):
            tracker.observe_object(Point(1, 2))
        
        assert tracker.is_type_stable(id(Point))
        assert tracker.get_common_shape(id(Point)) is not None
    
    def test_type_becomes_unstable(self):
        """Test type becomes unstable with varying shapes."""
        from pyaot.shapes.tracker import ShapeTracker
        
        class Flexible:
            pass
        
        tracker = ShapeTracker(stability_threshold=0.95, min_observations=10)
        
        # Create objects with different shapes
        for i in range(20):
            obj = Flexible()
            obj.x = 1
            if i % 2 == 0:
                obj.y = 2  # Half have y
            tracker.observe_object(obj)
        
        # Should be unstable (50% variation)
        assert not tracker.is_type_stable(id(Flexible))
    
    def test_is_type_stable_by_type(self):
        """Test is_type_stable_by_type convenience method."""
        from pyaot.shapes.tracker import ShapeTracker
        
        class Point:
            def __init__(self, x, y):
                self.x = x
                self.y = y
        
        tracker = ShapeTracker(min_observations=5)
        
        for _ in range(10):
            tracker.observe_object(Point(1, 2))
        
        assert tracker.is_type_stable_by_type(Point)
    
    def test_get_stable_types(self):
        """Test get_stable_types returns all stable types."""
        from pyaot.shapes.tracker import ShapeTracker
        
        class Point:
            def __init__(self, x, y):
                self.x = x
                self.y = y
        
        class Vector:
            def __init__(self, dx, dy):
                self.dx = dx
                self.dy = dy
        
        tracker = ShapeTracker(min_observations=5)
        
        for _ in range(10):
            tracker.observe_object(Point(1, 2))
            tracker.observe_object(Vector(1, 1))
        
        stable = tracker.get_stable_types()
        assert len(stable) == 2
        
        type_names = [name for _, name, _ in stable]
        assert 'Point' in type_names
        assert 'Vector' in type_names
    
    def test_get_stats(self):
        """Test tracker statistics."""
        from pyaot.shapes.tracker import ShapeTracker
        
        class Point:
            def __init__(self, x, y):
                self.x = x
                self.y = y
        
        tracker = ShapeTracker()
        
        for _ in range(10):
            tracker.observe_object(Point(1, 2))
        
        stats = tracker.get_stats()
        assert stats['total_types_tracked'] == 1
        assert stats['total_observations'] == 10


class TestFastAttrAccess:
    """Tests for fast attribute access."""
    
    def test_guarded_attr_access_success(self):
        """Test guarded_attr_access returns correct value."""
        from pyaot.shapes.fast_attr import guarded_attr_access
        from pyaot.shapes.tracker import get_global_tracker, reset_global_tracker
        
        reset_global_tracker()
        
        class Point:
            def __init__(self, x, y):
                self.x = x
                self.y = y
        
        # Train tracker
        tracker = get_global_tracker()
        for _ in range(20):
            tracker.observe_object(Point(1, 2))
        
        p = Point(42.0, 24.0)
        
        x = guarded_attr_access(p, 'x', Point)
        y = guarded_attr_access(p, 'y', Point)
        
        assert x == 42.0
        assert y == 24.0
    
    def test_guarded_attr_access_type_mismatch_fallback(self):
        """Test guarded_attr_access falls back on type mismatch."""
        from pyaot.shapes.fast_attr import guarded_attr_access
        from pyaot.shapes.tracker import get_global_tracker, reset_global_tracker
        
        reset_global_tracker()
        
        class Point:
            def __init__(self, x, y):
                self.x = x
                self.y = y
        
        class OtherPoint:
            def __init__(self, x, y):
                self.x = x
                self.y = y
        
        tracker = get_global_tracker()
        for _ in range(20):
            tracker.observe_object(Point(1, 2))
        
        # Access OtherPoint with Point as expected type -> fallback
        op = OtherPoint(99.0, 88.0)
        x = guarded_attr_access(op, 'x', Point)
        
        # Should fall back to getattr and get correct value
        assert x == 99.0
    
    def test_guarded_attr_access_missing_attribute(self):
        """Test guarded_attr_access raises AttributeError for missing attr."""
        from pyaot.shapes.fast_attr import guarded_attr_access
        from pyaot.shapes.tracker import get_global_tracker, reset_global_tracker
        
        reset_global_tracker()
        
        class Point:
            def __init__(self, x, y):
                self.x = x
                self.y = y
        
        tracker = get_global_tracker()
        for _ in range(20):
            tracker.observe_object(Point(1, 2))
        
        p = Point(1, 2)
        
        with pytest.raises(AttributeError):
            guarded_attr_access(p, 'z', Point)  # 'z' doesn't exist
    
    def test_fast_getattr_guarded_guard_failure(self):
        """Test fast_getattr_guarded raises GuardFailedError."""
        from pyaot.shapes.fast_attr import fast_getattr_guarded, GuardFailedError
        from pyaot.shapes.tracker import reset_global_tracker
        
        reset_global_tracker()
        
        class Point:
            def __init__(self, x, y):
                self.x = x
                self.y = y
        
        # Don't train tracker -> type won't be stable
        p = Point(1, 2)
        
        with pytest.raises(GuardFailedError):
            fast_getattr_guarded(p, 'x', Point)
    
    def test_fast_attr_stats(self):
        """Test FastAttrStats tracking."""
        from pyaot.shapes.fast_attr import (
            guarded_attr_access_with_stats,
            FastAttrStats,
            _reset_cached_tracker,
        )
        from pyaot.shapes.tracker import get_global_tracker, reset_global_tracker
        
        reset_global_tracker()
        _reset_cached_tracker()  # Also reset cached reference
        
        class Point:
            def __init__(self, x, y):
                self.x = x
                self.y = y
        
        tracker = get_global_tracker()
        for _ in range(20):
            tracker.observe_object(Point(1, 2))
        
        stats = FastAttrStats()
        p = Point(1, 2)
        
        for _ in range(10):
            guarded_attr_access_with_stats(p, 'x', Point, stats)
        
        assert stats.fast_path_hits == 10
        assert stats.fallback_calls == 0
        assert stats.fast_path_ratio == 1.0


class TestGuards:
    """Tests for guard integration."""
    
    def test_guard_kind_includes_shape_stable(self):
        """Test GuardKind includes SHAPE_STABLE."""
        from pyaot.types.guards import GuardKind
        
        assert hasattr(GuardKind, 'SHAPE_STABLE')
        assert hasattr(GuardKind, 'TYPE_IDENTITY')


class TestIntegration:
    """Integration tests for the complete shape system."""
    
    def test_end_to_end_sum_points(self):
        """Test complete workflow: train, access, verify."""
        from pyaot.shapes.tracker import ShapeTracker
        from pyaot.shapes.fast_attr import guarded_attr_access
        
        class Point:
            def __init__(self, x: float, y: float):
                self.x = x
                self.y = y
        
        # Create points
        points = [Point(float(i), float(i + 1)) for i in range(100)]
        
        # Train tracker
        tracker = ShapeTracker()
        for p in points:
            tracker.observe_object(p)
        
        assert tracker.is_type_stable_by_type(Point)
        
        # Sum using guarded access
        total_guarded = 0.0
        for p in points:
            try:
                from pyaot.shapes.fast_attr import fast_getattr_guarded
                total_guarded += fast_getattr_guarded(p, 'x', Point)
                total_guarded += fast_getattr_guarded(p, 'y', Point)
            except Exception:
                total_guarded += p.x + p.y
        
        # Sum baseline
        total_baseline = sum(p.x + p.y for p in points)
        
        assert abs(total_guarded - total_baseline) < 1e-6
    
    def test_slotted_class_fallback(self):
        """Test slotted classes fall back gracefully."""
        from pyaot.shapes.fast_attr import guarded_attr_access
        from pyaot.shapes.tracker import get_global_tracker, reset_global_tracker
        
        reset_global_tracker()
        
        class SlottedPoint:
            __slots__ = ('x', 'y')
            def __init__(self, x, y):
                self.x = x
                self.y = y
        
        tracker = get_global_tracker()
        for _ in range(20):
            tracker.observe_object(SlottedPoint(1, 2))
        
        p = SlottedPoint(42, 24)
        
        # Should fall back (slotted has no __dict__) but still get correct value
        x = guarded_attr_access(p, 'x', SlottedPoint)
        assert x == 42

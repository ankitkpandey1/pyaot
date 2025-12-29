"""
Shape definition for PyAOT side-table shape system.

A shape is an immutable identifier describing an object's attribute layout:
    Shape = (type_id, ordered_tuple_of_dict_keys)

Where:
    - type_id = id(type(obj)) - identity of the object's class
    - dict_keys = tuple(obj.__dict__.keys()) - attribute names in insertion order
"""

from dataclasses import dataclass
from typing import Tuple, Any, Optional

# ShapeID is a unique integer identifier for registered shapes
ShapeID = int


@dataclass(frozen=True)
class Shape:
    """
    Immutable shape descriptor for object attribute layout.
    
    Shapes are used as keys in the shape registry and represent
    the "structure" of an object's instance dictionary.
    
    Attributes:
        type_id: The id() of the object's type (class).
        dict_keys: Ordered tuple of attribute names from __dict__.
    
    Example:
        >>> class Point:
        ...     def __init__(self, x, y):
        ...         self.x = x
        ...         self.y = y
        >>> p = Point(1, 2)
        >>> shape = Shape.from_object(p)
        >>> shape.dict_keys
        ('x', 'y')
    """
    type_id: int
    dict_keys: Tuple[str, ...]
    
    @classmethod
    def from_object(cls, obj: Any) -> "Shape":
        """
        Create a Shape from an object instance.
        
        Args:
            obj: Any Python object with __dict__.
            
        Returns:
            Shape descriptor for this object.
            
        Note:
            Objects without __dict__ (e.g., slotted classes) will
            have an empty dict_keys tuple.
        """
        obj_dict = getattr(obj, '__dict__', None)
        if obj_dict is None:
            dict_keys: Tuple[str, ...] = ()
        else:
            dict_keys = tuple(obj_dict.keys())
        
        return cls(
            type_id=id(type(obj)),
            dict_keys=dict_keys,
        )
    
    @classmethod
    def from_type_and_keys(
        cls,
        obj_type: type,
        dict_keys: Tuple[str, ...],
    ) -> "Shape":
        """
        Create a Shape from a type and key tuple.
        
        This is useful when constructing expected shapes for guards.
        
        Args:
            obj_type: The type (class) object.
            dict_keys: Ordered tuple of attribute names.
            
        Returns:
            Shape descriptor.
        """
        return cls(
            type_id=id(obj_type),
            dict_keys=dict_keys,
        )
    
    def __hash__(self) -> int:
        """Hash based on type_id and dict_keys."""
        return hash((self.type_id, self.dict_keys))
    
    def __repr__(self) -> str:
        return f"Shape(type_id={self.type_id}, dict_keys={self.dict_keys})"
    
    def matches_object(self, obj: Any) -> bool:
        """
        Check if this shape matches an object's current layout.
        
        Args:
            obj: Object to check.
            
        Returns:
            True if the object has the same type_id and dict_keys.
        """
        if id(type(obj)) != self.type_id:
            return False
        
        obj_dict = getattr(obj, '__dict__', None)
        if obj_dict is None:
            return self.dict_keys == ()
        
        return tuple(obj_dict.keys()) == self.dict_keys
    
    def has_attribute(self, attr_name: str) -> bool:
        """
        Check if this shape includes a given attribute.
        
        Args:
            attr_name: Attribute name to check.
            
        Returns:
            True if attr_name is in dict_keys.
        """
        return attr_name in self.dict_keys
    
    def get_attribute_index(self, attr_name: str) -> Optional[int]:
        """
        Get the index of an attribute in dict_keys.
        
        This is informational only - we do NOT use positional
        access for attribute lookup (that would be unsafe).
        
        Args:
            attr_name: Attribute name.
            
        Returns:
            Index in dict_keys, or None if not present.
        """
        try:
            return self.dict_keys.index(attr_name)
        except ValueError:
            return None

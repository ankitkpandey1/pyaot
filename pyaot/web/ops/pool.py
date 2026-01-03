"""Generic object pooling for high-frequency allocations."""

from __future__ import annotations

from typing import Generic, TypeVar, List, Callable, Optional

T = TypeVar("T")

class ObjectPool(Generic[T]):
    """Simple LIFO object pool to reduce allocation overhead."""
    
    def __init__(self, factory: Callable[[], T], reset: Optional[Callable[[T], None]] = None, limit: int = 1000):
        self._factory = factory
        self._reset = reset
        self._pool: List[T] = []
        self._limit = limit
        
    def get(self) -> T:
        """Get an object from the pool or create new."""
        if self._pool:
            return self._pool.pop()
        return self._factory()
        
    def put(self, obj: T) -> None:
        """Return an object to the pool."""
        if len(self._pool) < self._limit:
            if self._reset:
                self._reset(obj)
            self._pool.append(obj)

"""
Per-process LRU cache for loaded artifacts.

Manages in-memory artifact references with eviction.
"""

from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Generic, Optional, TypeVar
import threading

from pyaot.config import get_config
from pyaot.logging import log_cache_event


K = TypeVar("K")
V = TypeVar("V")


class LRUCache(Generic[K, V]):
    """Thread-safe LRU cache for loaded artifacts.
    
    Per specification:
    - Variant selection is per-process
    - Variant eviction is per-process LRU
    - No cross-process coordination required
    """
    
    def __init__(self, max_size: Optional[int] = None):
        """Initialize the LRU cache.
        
        Args:
            max_size: Maximum number of items (uses config default if None).
        """
        self.max_size = max_size or get_config().lru_cache_size
        self._cache: OrderedDict[K, V] = OrderedDict()
        self._lock = threading.RLock()
        
        # Statistics
        self._hits = 0
        self._misses = 0
    
    def get(self, key: K) -> Optional[V]:
        """Get an item from cache, updating access order.
        
        Args:
            key: Cache key.
            
        Returns:
            Cached value, or None if not found.
        """
        with self._lock:
            if key in self._cache:
                # Move to end (most recently used)
                self._cache.move_to_end(key)
                self._hits += 1
                return self._cache[key]
            self._misses += 1
            return None
    
    def put(self, key: K, value: V) -> None:
        """Put an item in cache, evicting if necessary.
        
        Args:
            key: Cache key.
            value: Value to cache.
        """
        with self._lock:
            # If key exists, just update and move to end
            if key in self._cache:
                self._cache[key] = value
                self._cache.move_to_end(key)
                return
            
            # Add new entry
            self._cache[key] = value
            
            # Evict if over capacity
            while len(self._cache) > self.max_size:
                # Remove least recently used (first item)
                evicted_key, _ = self._cache.popitem(last=False)
                log_cache_event("evict", str(evicted_key))
    
    def remove(self, key: K) -> bool:
        """Remove an item from cache.
        
        Args:
            key: Cache key.
            
        Returns:
            True if item was removed.
        """
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False
    
    def clear(self) -> None:
        """Clear all cached items."""
        with self._lock:
            self._cache.clear()
    
    def __contains__(self, key: K) -> bool:
        """Check if key is in cache."""
        with self._lock:
            return key in self._cache
    
    def __len__(self) -> int:
        """Get number of cached items."""
        with self._lock:
            return len(self._cache)
    
    @property
    def hit_rate(self) -> float:
        """Get cache hit rate."""
        total = self._hits + self._misses
        if total == 0:
            return 0.0
        return self._hits / total
    
    def get_stats(self) -> dict:
        """Get cache statistics."""
        with self._lock:
            return {
                "size": len(self._cache),
                "max_size": self.max_size,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": self.hit_rate,
            }
    
    def keys(self) -> list:
        """Get list of cached keys."""
        with self._lock:
            return list(self._cache.keys())


@dataclass
class CachedArtifact:
    """A cached artifact with metadata."""
    cache_key: str
    function_name: str
    callable: Any  # The callable wrapper
    native_ptr: int  # Raw function pointer
    
    def __call__(self, *args, **kwargs):
        """Call the cached function."""
        return self.callable(*args, **kwargs)


# Global per-process artifact cache
_artifact_cache: Optional[LRUCache[str, CachedArtifact]] = None


def get_artifact_cache() -> LRUCache[str, CachedArtifact]:
    """Get the global artifact cache."""
    global _artifact_cache
    if _artifact_cache is None:
        _artifact_cache = LRUCache[str, CachedArtifact]()
    return _artifact_cache


def cache_artifact(
    cache_key: str,
    function_name: str,
    callable: Any,
    native_ptr: int,
) -> CachedArtifact:
    """Cache an artifact for this process.
    
    Args:
        cache_key: The artifact hash.
        function_name: Function name for logging.
        callable: The callable wrapper.
        native_ptr: Native function pointer.
        
    Returns:
        The cached artifact.
    """
    artifact = CachedArtifact(
        cache_key=cache_key,
        function_name=function_name,
        callable=callable,
        native_ptr=native_ptr,
    )
    get_artifact_cache().put(cache_key, artifact)
    return artifact


def get_cached_artifact(cache_key: str) -> Optional[CachedArtifact]:
    """Get a cached artifact.
    
    Args:
        cache_key: The artifact hash.
        
    Returns:
        Cached artifact, or None if not found.
    """
    return get_artifact_cache().get(cache_key)

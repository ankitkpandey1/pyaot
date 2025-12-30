"""
Stub Registry.

Central registry for callsite stubs with lookup and statistics.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from pyaot.callsite.stub import CallsiteStub


@dataclass
class StubStats:
    """Aggregate statistics for all stubs."""
    total_stubs: int = 0
    total_native_calls: int = 0
    total_fallback_calls: int = 0
    total_guard_failures: int = 0
    
    @property
    def overall_native_rate(self) -> float:
        """Fraction of calls that used native path."""
        total = self.total_native_calls + self.total_fallback_calls
        if total == 0:
            return 0.0
        return self.total_native_calls / total


class StubRegistry:
    """
    Registry of callsite stubs.
    
    Thread-safe registry for looking up and managing stubs.
    """
    
    def __init__(self):
        self._stubs: Dict[str, CallsiteStub] = {}
        self._lock = threading.Lock()
    
    def register(self, stub: CallsiteStub) -> None:
        """Register a stub."""
        with self._lock:
            self._stubs[stub.callsite_id] = stub
    
    def get(self, callsite_id: str) -> Optional[CallsiteStub]:
        """Get stub by callsite ID."""
        with self._lock:
            return self._stubs.get(callsite_id)
    
    def has_stub(self, callsite_id: str) -> bool:
        """Check if stub exists for callsite."""
        with self._lock:
            return callsite_id in self._stubs
    
    def remove(self, callsite_id: str) -> bool:
        """Remove a stub. Returns True if removed."""
        with self._lock:
            if callsite_id in self._stubs:
                del self._stubs[callsite_id]
                return True
            return False
    
    def get_all(self) -> List[CallsiteStub]:
        """Get all registered stubs."""
        with self._lock:
            return list(self._stubs.values())
    
    def get_stats(self) -> StubStats:
        """Get aggregate statistics."""
        with self._lock:
            stats = StubStats(total_stubs=len(self._stubs))
            
            for stub in self._stubs.values():
                stats.total_native_calls += stub.native_calls
                stats.total_fallback_calls += stub.fallback_calls
                stats.total_guard_failures += stub.guard_failures
            
            return stats
    
    def clear(self) -> None:
        """Clear all stubs."""
        with self._lock:
            self._stubs.clear()
    
    def execute(self, callsite_id: str, *args, **kwargs):
        """
        Execute via stub if available.
        
        Returns:
            (result, used_stub) tuple
        """
        stub = self.get(callsite_id)
        if stub is not None:
            return stub.execute(*args, **kwargs), True
        return None, False


# Global registry
_registry: Optional[StubRegistry] = None
_registry_lock = threading.Lock()


def get_stub_registry() -> StubRegistry:
    """Get the global stub registry."""
    global _registry
    with _registry_lock:
        if _registry is None:
            _registry = StubRegistry()
        return _registry


def reset_stub_registry() -> None:
    """Reset the global stub registry."""
    global _registry
    with _registry_lock:
        if _registry is not None:
            _registry.clear()
        _registry = None

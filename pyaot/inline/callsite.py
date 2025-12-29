"""
Callsite profiling for Phase 5.

Tracks per-callsite statistics including call counts, callee identity,
and timing information for identifying hot monomorphic call sites.
"""

from __future__ import annotations

import sys
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable, Tuple, Counter
from collections import Counter as CounterClass
import time
import json


@dataclass
class CallsiteProfile:
    """
    Profile data for a single call site.
    
    Tracks call frequency, callee identity, and timing for
    detecting hot monomorphic call sites eligible for inlining.
    """
    
    # Unique identifier: module:filename:bytecode_offset
    callsite_id: str
    
    # Caller information
    caller_module: str = ""
    caller_qualname: str = ""
    caller_filename: str = ""
    caller_lineno: int = 0
    
    # Call statistics
    total_calls: int = 0
    inclusive_cpu_time_ns: int = 0
    exclusive_cpu_time_ns: int = 0
    
    # Callee tracking: id(function) -> call count
    observed_callees: CounterClass = field(default_factory=CounterClass)
    
    # For bound methods: id(type(receiver)) -> count
    observed_receiver_types: CounterClass = field(default_factory=CounterClass)
    
    # Sampled argument type signatures
    arg_type_signatures: List[Tuple[str, ...]] = field(default_factory=list)
    
    # Guard failure events from previous runs
    failure_events: int = 0
    
    # Last observed callee (for monomorphism check)
    _last_callee_id: Optional[int] = field(default=None, repr=False)
    _last_callee_name: str = ""
    
    def record_call(
        self,
        callee: Callable,
        duration_ns: int,
        args: Tuple[Any, ...] = (),
        receiver: Optional[Any] = None,
    ) -> None:
        """
        Record a call at this call site.
        
        Args:
            callee: The called function.
            duration_ns: Call duration in nanoseconds.
            args: Arguments passed to the call.
            receiver: For bound methods, the receiver object.
        """
        self.total_calls += 1
        self.inclusive_cpu_time_ns += duration_ns
        
        # Track callee identity
        callee_id = id(callee)
        self.observed_callees[callee_id] += 1
        self._last_callee_id = callee_id
        self._last_callee_name = getattr(callee, '__name__', str(callee))
        
        # Track receiver type for bound methods
        if receiver is not None:
            receiver_type_id = id(type(receiver))
            self.observed_receiver_types[receiver_type_id] += 1
        
        # Sample argument types (limit to first 100 samples)
        if len(self.arg_type_signatures) < 100:
            sig = tuple(type(arg).__name__ for arg in args)
            self.arg_type_signatures.append(sig)
    
    @property
    def is_monomorphic(self) -> bool:
        """Check if call site is monomorphic (single callee)."""
        return len(self.observed_callees) == 1
    
    @property
    def dominant_callee_share(self) -> float:
        """Get the share of calls to the dominant callee."""
        if not self.observed_callees or self.total_calls == 0:
            return 0.0
        max_calls = max(self.observed_callees.values())
        return max_calls / self.total_calls
    
    @property
    def dominant_callee_id(self) -> Optional[int]:
        """Get the id of the most frequently called callee."""
        if not self.observed_callees:
            return None
        return self.observed_callees.most_common(1)[0][0]
    
    @property
    def avg_call_time_ns(self) -> float:
        """Average time per call in nanoseconds."""
        if self.total_calls == 0:
            return 0.0
        return self.inclusive_cpu_time_ns / self.total_calls
    
    def get_arg_type_stability(self) -> float:
        """
        Calculate argument type stability.
        
        Returns:
            Ratio of calls with the dominant arg type signature.
        """
        if not self.arg_type_signatures:
            return 0.0
        
        counter = CounterClass(self.arg_type_signatures)
        max_count = max(counter.values())
        return max_count / len(self.arg_type_signatures)
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "callsite_id": self.callsite_id,
            "caller_module": self.caller_module,
            "caller_qualname": self.caller_qualname,
            "caller_filename": self.caller_filename,
            "caller_lineno": self.caller_lineno,
            "total_calls": self.total_calls,
            "inclusive_cpu_time_ns": self.inclusive_cpu_time_ns,
            "exclusive_cpu_time_ns": self.exclusive_cpu_time_ns,
            "observed_callees": dict(self.observed_callees),
            "observed_receiver_types": dict(self.observed_receiver_types),
            "arg_type_signatures": self.arg_type_signatures[:20],  # Limit for storage
            "failure_events": self.failure_events,
            "last_callee_name": self._last_callee_name,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CallsiteProfile":
        """Deserialize from dictionary."""
        profile = cls(callsite_id=data["callsite_id"])
        profile.caller_module = data.get("caller_module", "")
        profile.caller_qualname = data.get("caller_qualname", "")
        profile.caller_filename = data.get("caller_filename", "")
        profile.caller_lineno = data.get("caller_lineno", 0)
        profile.total_calls = data.get("total_calls", 0)
        profile.inclusive_cpu_time_ns = data.get("inclusive_cpu_time_ns", 0)
        profile.exclusive_cpu_time_ns = data.get("exclusive_cpu_time_ns", 0)
        profile.observed_callees = CounterClass(data.get("observed_callees", {}))
        profile.observed_receiver_types = CounterClass(data.get("observed_receiver_types", {}))
        profile.arg_type_signatures = [tuple(s) for s in data.get("arg_type_signatures", [])]
        profile.failure_events = data.get("failure_events", 0)
        profile._last_callee_name = data.get("last_callee_name", "")
        return profile


class CallsiteTracker:
    """
    Tracks call sites during profiling.
    
    Thread-safe tracker that records per-callsite statistics
    for identifying hot monomorphic call sites.
    """
    
    def __init__(self):
        self._callsites: Dict[str, CallsiteProfile] = {}
        self._lock = threading.Lock()
        self._call_stack: List[Tuple[str, int]] = []  # Stack for timing
    
    def get_or_create(
        self,
        callsite_id: str,
        caller_module: str = "",
        caller_qualname: str = "",
        caller_filename: str = "",
        caller_lineno: int = 0,
    ) -> CallsiteProfile:
        """Get or create a callsite profile."""
        with self._lock:
            if callsite_id not in self._callsites:
                self._callsites[callsite_id] = CallsiteProfile(
                    callsite_id=callsite_id,
                    caller_module=caller_module,
                    caller_qualname=caller_qualname,
                    caller_filename=caller_filename,
                    caller_lineno=caller_lineno,
                )
            return self._callsites[callsite_id]
    
    def record_call(
        self,
        callsite_id: str,
        callee: Callable,
        duration_ns: int,
        args: Tuple[Any, ...] = (),
        receiver: Optional[Any] = None,
    ) -> None:
        """Record a call at the given call site."""
        profile = self.get_or_create(callsite_id)
        with self._lock:
            profile.record_call(callee, duration_ns, args, receiver)
    
    def get_hot_callsites(
        self,
        min_calls: int = 1000,
        min_time_fraction: float = 0.01,
    ) -> List[CallsiteProfile]:
        """
        Get hot call sites that meet the threshold.
        
        Args:
            min_calls: Minimum number of calls.
            min_time_fraction: Minimum fraction of total time.
            
        Returns:
            List of hot callsite profiles.
        """
        total_time = sum(p.inclusive_cpu_time_ns for p in self._callsites.values())
        
        hot = []
        for profile in self._callsites.values():
            if profile.total_calls >= min_calls:
                if total_time == 0 or profile.inclusive_cpu_time_ns / total_time >= min_time_fraction:
                    hot.append(profile)
        
        # Sort by total time descending
        hot.sort(key=lambda p: p.inclusive_cpu_time_ns, reverse=True)
        return hot
    
    def get_monomorphic_callsites(self, min_calls: int = 1000) -> List[CallsiteProfile]:
        """Get call sites that are monomorphic and meet call threshold."""
        return [
            p for p in self._callsites.values()
            if p.total_calls >= min_calls and p.dominant_callee_share >= 0.995
        ]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get tracker statistics."""
        with self._lock:
            total_callsites = len(self._callsites)
            total_calls = sum(p.total_calls for p in self._callsites.values())
            monomorphic = sum(1 for p in self._callsites.values() if p.is_monomorphic)
            hot = len(self.get_hot_callsites())
            
            return {
                "total_callsites": total_callsites,
                "total_calls": total_calls,
                "monomorphic_callsites": monomorphic,
                "hot_callsites": hot,
            }
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        with self._lock:
            return {
                "callsites": {k: v.to_dict() for k, v in self._callsites.items()},
                "stats": self.get_stats(),
            }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CallsiteTracker":
        """Deserialize from dictionary."""
        tracker = cls()
        for callsite_id, profile_data in data.get("callsites", {}).items():
            tracker._callsites[callsite_id] = CallsiteProfile.from_dict(profile_data)
        return tracker
    
    def save(self, path: str) -> None:
        """Save to JSON file."""
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
    
    @classmethod
    def load(cls, path: str) -> "CallsiteTracker":
        """Load from JSON file."""
        with open(path, "r") as f:
            return cls.from_dict(json.load(f))
    
    def clear(self) -> None:
        """Clear all callsite data."""
        with self._lock:
            self._callsites.clear()


# Global tracker instance
_global_tracker: Optional[CallsiteTracker] = None
_tracker_lock = threading.Lock()


def get_global_callsite_tracker() -> CallsiteTracker:
    """Get the global callsite tracker."""
    global _global_tracker
    with _tracker_lock:
        if _global_tracker is None:
            _global_tracker = CallsiteTracker()
        return _global_tracker


def reset_global_callsite_tracker() -> None:
    """Reset the global callsite tracker."""
    global _global_tracker
    with _tracker_lock:
        _global_tracker = CallsiteTracker()

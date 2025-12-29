"""
Telemetry system for Phase 5 inline optimization.

Provides per-callsite metrics collection, global counters,
and rejection logging for observability and debugging.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum, auto


class RejectionReason(Enum):
    """Reasons why a callsite was rejected for inlining."""
    INSUFFICIENT_CALLS = auto()
    POLYMORPHIC = auto()
    HAS_VARARGS = auto()
    HAS_KWARGS = auto()
    NOT_LEAF = auto()
    HAS_CLOSURE = auto()
    IS_GENERATOR = auto()
    IS_COROUTINE = auto()
    INCOMPATIBLE_TYPES = auto()
    NO_SOURCE = auto()
    BUILTIN = auto()
    EXCEPTION_DRIVEN = auto()
    GLOBAL_MUTATION = auto()
    UNSTABLE_RECEIVER = auto()


@dataclass
class CallsiteMetrics:
    """Metrics for a single callsite."""
    callsite_id: str
    
    # Call statistics
    total_calls: int = 0
    optimized_calls: int = 0
    fallback_calls: int = 0
    
    # Callee tracking
    dominant_callee_share: float = 0.0
    
    # Guard statistics
    guard_checks: int = 0
    guard_failures: int = 0
    guard_failure_by_type: Dict[str, int] = field(default_factory=dict)
    
    # Timing
    total_native_time_ns: int = 0
    total_fallback_time_ns: int = 0
    avg_guard_check_ns: float = 0.0
    
    # Status
    inline_enabled: bool = False
    rejection_reason: Optional[RejectionReason] = None
    rejection_details: str = ""
    
    @property
    def guard_failure_rate(self) -> float:
        """Get guard failure rate as fraction."""
        if self.guard_checks == 0:
            return 0.0
        return self.guard_failures / self.guard_checks
    
    @property
    def native_ratio(self) -> float:
        """Ratio of optimized to total calls."""
        total = self.optimized_calls + self.fallback_calls
        if total == 0:
            return 0.0
        return self.optimized_calls / total
    
    def record_native_call(self, duration_ns: int) -> None:
        """Record a successful native call."""
        self.optimized_calls += 1
        self.total_native_time_ns += duration_ns
    
    def record_fallback_call(self, duration_ns: int) -> None:
        """Record a fallback call."""
        self.fallback_calls += 1
        self.total_fallback_time_ns += duration_ns
    
    def record_guard_check(self, passed: bool, guard_type: str = "") -> None:
        """Record a guard check."""
        self.guard_checks += 1
        if not passed:
            self.guard_failures += 1
            if guard_type:
                self.guard_failure_by_type[guard_type] = (
                    self.guard_failure_by_type.get(guard_type, 0) + 1
                )
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "callsite_id": self.callsite_id,
            "total_calls": self.total_calls,
            "optimized_calls": self.optimized_calls,
            "fallback_calls": self.fallback_calls,
            "dominant_callee_share": self.dominant_callee_share,
            "guard_checks": self.guard_checks,
            "guard_failures": self.guard_failures,
            "guard_failure_rate": self.guard_failure_rate,
            "guard_failure_by_type": self.guard_failure_by_type,
            "native_ratio": self.native_ratio,
            "inline_enabled": self.inline_enabled,
            "rejection_reason": self.rejection_reason.name if self.rejection_reason else None,
            "rejection_details": self.rejection_details,
        }


@dataclass 
class GlobalMetrics:
    """Global telemetry counters."""
    # Call counts
    total_calls_observed: int = 0
    total_optimized_calls: int = 0
    total_fallback_calls: int = 0
    
    # Callsite counts
    total_callsites: int = 0
    eligible_callsites: int = 0
    inlined_callsites: int = 0
    rejected_callsites: int = 0
    
    # Timing
    observe_time_ns: int = 0
    emit_time_ns: int = 0
    
    # Guard statistics
    total_guard_checks: int = 0
    total_guard_failures: int = 0
    
    @property
    def fast_path_success_rate(self) -> float:
        """Rate of successful fast-path execution."""
        total = self.total_optimized_calls + self.total_fallback_calls
        if total == 0:
            return 0.0
        return self.total_optimized_calls / total
    
    @property
    def overall_guard_failure_rate(self) -> float:
        """Overall guard failure rate."""
        if self.total_guard_checks == 0:
            return 0.0
        return self.total_guard_failures / self.total_guard_checks
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "total_calls_observed": self.total_calls_observed,
            "total_optimized_calls": self.total_optimized_calls,
            "total_fallback_calls": self.total_fallback_calls,
            "total_callsites": self.total_callsites,
            "eligible_callsites": self.eligible_callsites,
            "inlined_callsites": self.inlined_callsites,
            "rejected_callsites": self.rejected_callsites,
            "observe_time_ms": self.observe_time_ns / 1_000_000,
            "emit_time_ms": self.emit_time_ns / 1_000_000,
            "fast_path_success_rate": self.fast_path_success_rate,
            "overall_guard_failure_rate": self.overall_guard_failure_rate,
        }


class InlineTelemetry:
    """
    Central telemetry collector for Phase 5 inlining.
    
    Thread-safe singleton that collects:
    - Per-callsite metrics
    - Global counters
    - Rejection logs
    """
    
    _instance: Optional["InlineTelemetry"] = None
    _lock = threading.Lock()
    
    def __new__(cls) -> "InlineTelemetry":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        
        self._callsite_metrics: Dict[str, CallsiteMetrics] = {}
        self._global_metrics = GlobalMetrics()
        self._rejection_log: List[Dict[str, Any]] = []
        self._metrics_lock = threading.Lock()
        self._enabled = False
    
    def enable(self) -> None:
        """Enable telemetry collection."""
        self._enabled = True
    
    def disable(self) -> None:
        """Disable telemetry collection."""
        self._enabled = False
    
    @property
    def is_enabled(self) -> bool:
        """Check if telemetry is enabled."""
        return self._enabled
    
    def get_or_create_callsite(self, callsite_id: str) -> CallsiteMetrics:
        """Get or create metrics for a callsite."""
        with self._metrics_lock:
            if callsite_id not in self._callsite_metrics:
                self._callsite_metrics[callsite_id] = CallsiteMetrics(
                    callsite_id=callsite_id
                )
                self._global_metrics.total_callsites += 1
            return self._callsite_metrics[callsite_id]
    
    def record_observation(self, callsite_id: str, callee_share: float) -> None:
        """Record a callsite observation during profiling."""
        if not self._enabled:
            return
        metrics = self.get_or_create_callsite(callsite_id)
        metrics.total_calls += 1
        metrics.dominant_callee_share = callee_share
        self._global_metrics.total_calls_observed += 1
    
    def record_native_call(self, callsite_id: str, duration_ns: int) -> None:
        """Record a native call execution."""
        if not self._enabled:
            return
        metrics = self.get_or_create_callsite(callsite_id)
        metrics.record_native_call(duration_ns)
        self._global_metrics.total_optimized_calls += 1
    
    def record_fallback_call(self, callsite_id: str, duration_ns: int) -> None:
        """Record a fallback call execution."""
        if not self._enabled:
            return
        metrics = self.get_or_create_callsite(callsite_id)
        metrics.record_fallback_call(duration_ns)
        self._global_metrics.total_fallback_calls += 1
    
    def record_guard_check(
        self,
        callsite_id: str,
        passed: bool,
        guard_type: str = "",
    ) -> None:
        """Record a guard check."""
        if not self._enabled:
            return
        metrics = self.get_or_create_callsite(callsite_id)
        metrics.record_guard_check(passed, guard_type)
        self._global_metrics.total_guard_checks += 1
        if not passed:
            self._global_metrics.total_guard_failures += 1
    
    def record_rejection(
        self,
        callsite_id: str,
        reason: RejectionReason,
        details: str = "",
    ) -> None:
        """Record a callsite rejection."""
        metrics = self.get_or_create_callsite(callsite_id)
        metrics.rejection_reason = reason
        metrics.rejection_details = details
        self._global_metrics.rejected_callsites += 1
        
        self._rejection_log.append({
            "callsite_id": callsite_id,
            "reason": reason.name,
            "details": details,
            "timestamp": time.time(),
        })
    
    def record_inline_enabled(self, callsite_id: str) -> None:
        """Record that inlining was enabled for a callsite."""
        metrics = self.get_or_create_callsite(callsite_id)
        metrics.inline_enabled = True
        self._global_metrics.inlined_callsites += 1
        self._global_metrics.eligible_callsites += 1
    
    def record_observe_time(self, duration_ns: int) -> None:
        """Record observation phase duration."""
        self._global_metrics.observe_time_ns += duration_ns
    
    def record_emit_time(self, duration_ns: int) -> None:
        """Record emission phase duration."""
        self._global_metrics.emit_time_ns += duration_ns
    
    def get_callsite_report(self, callsite_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed report for a callsite."""
        metrics = self._callsite_metrics.get(callsite_id)
        if metrics:
            return metrics.to_dict()
        return None
    
    def get_global_metrics(self) -> Dict[str, Any]:
        """Get global metrics summary."""
        return self._global_metrics.to_dict()
    
    def get_all_callsite_metrics(self) -> Dict[str, Dict[str, Any]]:
        """Get metrics for all callsites."""
        return {
            cid: m.to_dict() for cid, m in self._callsite_metrics.items()
        }
    
    def get_rejection_log(self) -> List[Dict[str, Any]]:
        """Get the rejection log."""
        return list(self._rejection_log)
    
    def get_amortization_estimate(self, baseline_time_ns: float) -> Dict[str, Any]:
        """
        Estimate amortization point.
        
        Args:
            baseline_time_ns: Average time per call in baseline.
            
        Returns:
            Dict with amortization analysis.
        """
        total_calls = (
            self._global_metrics.total_optimized_calls +
            self._global_metrics.total_fallback_calls
        )
        
        if total_calls == 0:
            return {
                "can_estimate": False,
                "reason": "no calls recorded",
            }
        
        # Average optimized time per call
        optimized_count = self._global_metrics.total_optimized_calls
        if optimized_count == 0:
            return {
                "can_estimate": False,
                "reason": "no optimized calls",
            }
        
        # Compute savings per call
        avg_optimized_ns = sum(
            m.total_native_time_ns / max(1, m.optimized_calls)
            for m in self._callsite_metrics.values()
            if m.optimized_calls > 0
        ) / max(1, len([m for m in self._callsite_metrics.values() if m.optimized_calls > 0]))
        
        savings_per_call_ns = baseline_time_ns - avg_optimized_ns
        if savings_per_call_ns <= 0:
            return {
                "can_estimate": False,
                "reason": "no savings observed",
            }
        
        # Amortization point
        setup_time_ns = (
            self._global_metrics.observe_time_ns +
            self._global_metrics.emit_time_ns
        )
        
        amortization_calls = int(setup_time_ns / savings_per_call_ns) + 1
        
        return {
            "can_estimate": True,
            "observe_emit_time_ms": setup_time_ns / 1_000_000,
            "savings_per_call_ns": savings_per_call_ns,
            "amortization_calls": amortization_calls,
            "current_calls": total_calls,
            "is_amortized": total_calls >= amortization_calls,
        }
    
    def export_to_json(self, path: str) -> None:
        """Export all telemetry to JSON file."""
        data = {
            "global_metrics": self.get_global_metrics(),
            "callsite_metrics": self.get_all_callsite_metrics(),
            "rejection_log": self.get_rejection_log(),
            "timestamp": time.time(),
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    
    def reset(self) -> None:
        """Reset all telemetry data."""
        with self._metrics_lock:
            self._callsite_metrics.clear()
            self._global_metrics = GlobalMetrics()
            self._rejection_log.clear()


def get_telemetry() -> InlineTelemetry:
    """Get the global telemetry instance."""
    return InlineTelemetry()


def reset_telemetry() -> None:
    """Reset the global telemetry instance."""
    InlineTelemetry._instance = None

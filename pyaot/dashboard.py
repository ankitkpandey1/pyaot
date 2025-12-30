"""
Profiling Dashboard for PyAOT.

Terminal-based visualization of:
- Hot functions
- Compilation statistics
- Guard failure rates
- Performance metrics
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class FunctionStats:
    """Statistics for a single function."""
    name: str
    total_calls: int = 0
    native_calls: int = 0
    fallback_calls: int = 0
    total_time_ns: int = 0
    avg_time_ns: float = 0.0
    is_compiled: bool = False
    guard_failures: int = 0
    
    @property
    def native_ratio(self) -> float:
        total = self.native_calls + self.fallback_calls
        return self.native_calls / total if total > 0 else 0.0
    
    @property
    def guard_failure_rate(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return self.guard_failures / self.total_calls


@dataclass
class DashboardState:
    """Current state of the dashboard."""
    functions: Dict[str, FunctionStats] = field(default_factory=dict)
    total_native_calls: int = 0
    total_fallback_calls: int = 0
    total_compilations: int = 0
    start_time: datetime = field(default_factory=datetime.now)
    
    @property
    def uptime_seconds(self) -> float:
        return (datetime.now() - self.start_time).total_seconds()


class ProfilingDashboard:
    """
    Terminal-based profiling visualization.
    
    Provides real-time stats on:
    - Hot functions and their performance
    - Compilation status
    - Guard failure rates
    
    Usage:
        dashboard = ProfilingDashboard()
        dashboard.start()
        # ... run application ...
        dashboard.show_summary()
    """
    
    def __init__(self):
        self._state = DashboardState()
        self._refresh_interval = 1.0  # seconds
        self._running = False
    
    def start(self) -> None:
        """Start collecting statistics."""
        self._state = DashboardState()
        self._running = True
    
    def stop(self) -> None:
        """Stop collecting statistics."""
        self._running = False
    
    def record_call(
        self,
        func_name: str,
        is_native: bool,
        time_ns: int,
    ) -> None:
        """Record a function call."""
        if func_name not in self._state.functions:
            self._state.functions[func_name] = FunctionStats(name=func_name)
        
        stats = self._state.functions[func_name]
        stats.total_calls += 1
        stats.total_time_ns += time_ns
        
        if is_native:
            stats.native_calls += 1
            self._state.total_native_calls += 1
        else:
            stats.fallback_calls += 1
            self._state.total_fallback_calls += 1
        
        stats.avg_time_ns = stats.total_time_ns / stats.total_calls
    
    def record_compilation(self, func_name: str) -> None:
        """Record a function compilation."""
        if func_name not in self._state.functions:
            self._state.functions[func_name] = FunctionStats(name=func_name)
        
        self._state.functions[func_name].is_compiled = True
        self._state.total_compilations += 1
    
    def record_guard_failure(self, func_name: str) -> None:
        """Record a guard failure."""
        if func_name in self._state.functions:
            self._state.functions[func_name].guard_failures += 1
    
    def show_hotspots(self, top_n: int = 10) -> str:
        """
        Display hot functions with timing.
        
        Returns:
            Formatted hotspot report.
        """
        lines = [
            "╔══════════════════════════════════════════════════════════════════╗",
            "║                    PyAOT Hotspot Analysis                        ║",
            "╠══════════════════════════════════════════════════════════════════╣",
        ]
        
        # Sort by total time
        sorted_funcs = sorted(
            self._state.functions.values(),
            key=lambda s: s.total_time_ns,
            reverse=True,
        )[:top_n]
        
        if not sorted_funcs:
            lines.append("║  No function calls recorded yet                                  ║")
        else:
            header = "║ {:25} {:>10} {:>10} {:>8} {:>8} ║".format(
                "Function", "Calls", "Avg (μs)", "Native%", "Status"
            )
            lines.append(header)
            lines.append("║" + "─" * 66 + "║")
            
            for stats in sorted_funcs:
                status = "✓ native" if stats.is_compiled else "○ python"
                native_pct = f"{stats.native_ratio * 100:.1f}%"
                avg_us = f"{stats.avg_time_ns / 1000:.2f}"
                
                line = "║ {:25} {:>10} {:>10} {:>8} {:>8} ║".format(
                    stats.name[:25],
                    stats.total_calls,
                    avg_us,
                    native_pct,
                    status,
                )
                lines.append(line)
        
        lines.append("╚══════════════════════════════════════════════════════════════════╝")
        
        return "\n".join(lines)
    
    def show_compilation_stats(self) -> str:
        """
        Display compilation statistics.
        
        Returns:
            Formatted compilation stats.
        """
        state = self._state
        total_calls = state.total_native_calls + state.total_fallback_calls
        native_ratio = (
            state.total_native_calls / total_calls * 100
            if total_calls > 0 else 0
        )
        
        compiled_funcs = sum(1 for f in state.functions.values() if f.is_compiled)
        total_funcs = len(state.functions)
        
        lines = [
            "╔══════════════════════════════════════════════════════════════════╗",
            "║                  PyAOT Compilation Statistics                    ║",
            "╠══════════════════════════════════════════════════════════════════╣",
            f"║  Uptime:               {state.uptime_seconds:>10.1f} seconds                    ║",
            f"║  Total Calls:          {total_calls:>10,}                                 ║",
            f"║  Native Calls:         {state.total_native_calls:>10,} ({native_ratio:>5.1f}%)                   ║",
            f"║  Fallback Calls:       {state.total_fallback_calls:>10,}                                 ║",
            f"║  Compiled Functions:   {compiled_funcs:>10} / {total_funcs:<10}                  ║",
            f"║  Total Compilations:   {state.total_compilations:>10}                                 ║",
            "╚══════════════════════════════════════════════════════════════════╝",
        ]
        
        return "\n".join(lines)
    
    def show_guard_failures(self) -> str:
        """
        Display guard failure analysis.
        
        Returns:
            Formatted guard failure report.
        """
        lines = [
            "╔══════════════════════════════════════════════════════════════════╗",
            "║                    Guard Failure Analysis                        ║",
            "╠══════════════════════════════════════════════════════════════════╣",
        ]
        
        # Filter functions with guard failures
        failing = [
            f for f in self._state.functions.values()
            if f.guard_failures > 0
        ]
        
        if not failing:
            lines.append("║  No guard failures detected - types are stable ✓                ║")
        else:
            header = "║ {:30} {:>12} {:>12} {:>8} ║".format(
                "Function", "Failures", "Total Calls", "Rate"
            )
            lines.append(header)
            lines.append("║" + "─" * 66 + "║")
            
            for stats in sorted(failing, key=lambda s: s.guard_failures, reverse=True):
                rate = f"{stats.guard_failure_rate * 100:.2f}%"
                line = "║ {:30} {:>12} {:>12} {:>8} ║".format(
                    stats.name[:30],
                    stats.guard_failures,
                    stats.total_calls,
                    rate,
                )
                lines.append(line)
        
        lines.append("╚══════════════════════════════════════════════════════════════════╝")
        
        return "\n".join(lines)
    
    def show_summary(self) -> str:
        """
        Show complete dashboard summary.
        
        Returns:
            Full dashboard output.
        """
        parts = [
            self.show_compilation_stats(),
            "",
            self.show_hotspots(),
            "",
            self.show_guard_failures(),
        ]
        return "\n".join(parts)
    
    def get_state(self) -> DashboardState:
        """Get current dashboard state."""
        return self._state
    
    def export_json(self) -> Dict[str, Any]:
        """Export dashboard state as JSON-compatible dict."""
        return {
            "uptime_seconds": self._state.uptime_seconds,
            "total_native_calls": self._state.total_native_calls,
            "total_fallback_calls": self._state.total_fallback_calls,
            "total_compilations": self._state.total_compilations,
            "functions": {
                name: {
                    "total_calls": stats.total_calls,
                    "native_calls": stats.native_calls,
                    "fallback_calls": stats.fallback_calls,
                    "avg_time_ns": stats.avg_time_ns,
                    "is_compiled": stats.is_compiled,
                    "guard_failures": stats.guard_failures,
                }
                for name, stats in self._state.functions.items()
            },
        }


# Global dashboard instance
_dashboard: Optional[ProfilingDashboard] = None


def get_dashboard() -> ProfilingDashboard:
    """Get the global profiling dashboard."""
    global _dashboard
    if _dashboard is None:
        _dashboard = ProfilingDashboard()
    return _dashboard


def show_dashboard() -> None:
    """Print the current dashboard to stdout."""
    dashboard = get_dashboard()
    print(dashboard.show_summary())

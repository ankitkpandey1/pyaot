"""Minimal execution tracer for regions.

Records only:
- Branch decisions
- Type/shape stability
- Attribute offsets

Output: Guard Table + Hot Path Metadata.
"""

import sys
import opcode
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

@dataclass
class Guard:
    """A single guard condition."""
    kind: str  # 'type', 'attr', 'bool'
    target: str  # name of variable or attribute
    expected: Any  # Expected value/type/offset

@dataclass
class TraceData:
    """Captured trace data for a region."""
    guards: List[Guard] = field(default_factory=list)
    branch_decisions: List[bool] = field(default_factory=list)
    # Map of (type_name, attr_name) -> offset
    attr_offsets: Dict[Tuple[str, str], int] = field(default_factory=dict)

class RegionTracer:
    """Traces region execution to build guard tables."""
    
    def __init__(self):
        self._current_trace: Optional[TraceData] = None
        self._active_region_id: Optional[str] = None
        
    def start_trace(self, region_id: str):
        """Begin tracing a region execution."""
        self._active_region_id = region_id
        self._current_trace = TraceData()
        # Enable system tracing
        sys.settrace(self._trace_callback)
        
    def end_trace(self) -> Optional[TraceData]:
        """End tracing and return collected data."""
        sys.settrace(None)
        trace = self._current_trace
        self._current_trace = None
        self._active_region_id = None
        return trace
        
    def _trace_callback(self, frame, event, arg):
        """Internal trace callback."""
        if self._current_trace is None:
            return None
            
        if event == 'opcode':
            # This requires Python 3.12+ sys.settrace capability or similar
            # For standard tracing, we approximate via 'line' or specific events
            # Note: Detailed opcode tracing is expensive in Python.
            # We focus on what we can capture: Types on call/return, etc.
            pass
            
        return self._trace_callback

    # Explicit hooks for the POC phase (to be replaced by automatic hooks later)
    def record_type(self, name: str, value: Any):
        """Record a type guard."""
        if self._current_trace:
            self._current_trace.guards.append(
                Guard('type', name, type(value))
            )

    def record_attr_access(self, obj: Any, attr: str):
        """Record an attribute access offset."""
        if self._current_trace:
            # Emulate offset/layout check
            cls_name = type(obj).__name__
            # In real native code, this tracks object layout version/offset
            self._current_trace.attr_offsets[(cls_name, attr)] = 0 # Placeholder offset
            
    def record_branch(self, decision: bool):
        """Record a branch decision."""
        if self._current_trace:
            self._current_trace.branch_decisions.append(decision)

# Global tracer instance
_global_tracer = RegionTracer()

def get_tracer() -> RegionTracer:
    return _global_tracer

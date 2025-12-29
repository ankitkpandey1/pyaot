"""
Profile collector for PyAOT.

Uses sys.setprofile to collect runtime information about function calls
including timing, argument types, and shapes.
"""

import sys
import time
import random
from typing import Any, Callable, Optional, Tuple, Dict
import platform

from pyaot.config import get_config
from pyaot.profiler.data import (
    ProfileData,
    FunctionProfile,
    TypeSignature,
    ShapeSignature,
)


def _get_type_name(obj: Any) -> str:
    """Get the type name of an object.
    
    Special handling for NumPy arrays to include dtype.
    """
    t = type(obj)
    type_name = f"{t.__module__}.{t.__qualname__}"
    
    # Special handling for numpy arrays
    if hasattr(obj, 'dtype') and hasattr(obj, 'shape'):
        type_name = f"ndarray[{obj.dtype}]"
    
    return type_name


def _get_shape(obj: Any) -> Optional[Tuple[int, ...]]:
    """Get the shape of an object if it has one.
    
    Returns None for non-array objects.
    """
    if hasattr(obj, 'shape'):
        shape = obj.shape
        if isinstance(shape, tuple):
            return shape
    return None


def _build_type_signature(args: Tuple, kwargs: Dict) -> TypeSignature:
    """Build a type signature from function arguments."""
    arg_types = tuple(_get_type_name(arg) for arg in args)
    kwarg_types = {key: _get_type_name(val) for key, val in kwargs.items()}
    return TypeSignature(arg_types=arg_types, kwarg_types=kwarg_types)


def _build_shape_signature(args: Tuple, kwargs: Dict) -> ShapeSignature:
    """Build a shape signature from function arguments."""
    arg_shapes = tuple(_get_shape(arg) for arg in args)
    return ShapeSignature(arg_shapes=arg_shapes)


class ProfileCollector:
    """Collects runtime profile information for Python functions.
    
    Uses sys.setprofile for tracing function calls. Sampling is used
    to minimize overhead (default: 1 in 1000 calls profiled in detail).
    
    Usage:
        collector = ProfileCollector()
        collector.start()
        # ... run code ...
        collector.stop()
        data = collector.get_data()
    """
    
    def __init__(self, sample_rate: Optional[int] = None):
        """Initialize the collector.
        
        Args:
            sample_rate: Sample 1 in N calls for detailed profiling.
                        If None, uses config default.
        """
        config = get_config()
        self.sample_rate = sample_rate or config.sample_rate
        self.data = ProfileData(
            python_version=platform.python_version(),
        )
        self._active = False
        self._call_stack: list = []  # Stack of (frame, start_time)
        self._start_time: int = 0
        self._sample_counter = 0
        self._previous_profiler: Optional[Callable] = None
    
    def start(self) -> None:
        """Start profile collection."""
        if self._active:
            return
        
        self._active = True
        self._start_time = time.perf_counter_ns()
        self._previous_profiler = sys.getprofile()
        sys.setprofile(self._profile_callback)
    
    def stop(self) -> None:
        """Stop profile collection."""
        if not self._active:
            return
        
        self._active = False
        sys.setprofile(self._previous_profiler)
        self.data.profile_duration_ns = time.perf_counter_ns() - self._start_time
    
    def get_data(self) -> ProfileData:
        """Get collected profile data."""
        return self.data
    
    def clear(self) -> None:
        """Clear collected data."""
        self.data = ProfileData(
            python_version=platform.python_version(),
        )
        self._call_stack.clear()
    
    def _should_sample(self) -> bool:
        """Determine if this call should be sampled for detailed profiling."""
        self._sample_counter += 1
        if self._sample_counter >= self.sample_rate:
            self._sample_counter = 0
            return True
        return False
    
    def _profile_callback(
        self,
        frame,
        event: str,
        arg: Any,
    ) -> Optional[Callable]:
        """Profile callback for sys.setprofile.
        
        Events:
            'call': Function entry
            'return': Function exit
            'c_call': C function entry
            'c_return': C function exit
            'c_exception': C function exception
        """
        # Only handle regular function calls
        if event not in ('call', 'return'):
            return None
        
        # Skip internal frames
        code = frame.f_code
        filename = code.co_filename
        
        # Skip PyAOT internals and standard library
        if 'pyaot' in filename or filename.startswith('<'):
            return None
        
        if event == 'call':
            self._handle_call(frame, code)
        elif event == 'return':
            self._handle_return(frame, code, arg)
        
        return None
    
    def _handle_call(self, frame, code) -> None:
        """Handle function call event."""
        start_time = time.perf_counter_ns()
        
        # Get function identity
        module = frame.f_globals.get('__name__', '<unknown>')
        qualname = code.co_qualname if hasattr(code, 'co_qualname') else code.co_name
        filename = code.co_filename
        lineno = code.co_firstlineno
        
        # Get or create profile
        profile = self.data.get_or_create(module, qualname, filename, lineno)
        
        # Record callee relationship
        if self._call_stack:
            caller_profile = self._call_stack[-1][0]
            caller_profile.callees[profile.key] += 1
        
        # Sample for detailed profiling (args, shapes)
        sample_this = self._should_sample()
        
        self._call_stack.append((profile, start_time, sample_this, frame))
    
    def _handle_return(self, frame, code, return_value) -> None:
        """Handle function return event."""
        if not self._call_stack:
            return
        
        # Pop the call stack
        profile, start_time, sample_this, call_frame = self._call_stack.pop()
        
        # Always record timing
        duration_ns = time.perf_counter_ns() - start_time
        
        if sample_this:
            # Extract arguments from the frame
            # Note: locals may have been modified, but we get initial values
            try:
                args = self._extract_args(call_frame, code)
                kwargs = self._extract_kwargs(call_frame, code)
                
                type_sig = _build_type_signature(args, kwargs)
                shape_sig = _build_shape_signature(args, kwargs)
                
                profile.record_call(duration_ns, type_sig, shape_sig)
            except Exception:
                # If we can't extract args, just record timing
                profile.call_count += 1
                profile.total_time_ns += duration_ns
        else:
            # Non-sampled call: just count
            profile.call_count += 1
            profile.total_time_ns += duration_ns
    
    def _extract_args(self, frame, code) -> Tuple:
        """Extract positional arguments from a frame."""
        # Get argument count (excluding kwargs)
        argcount = code.co_argcount
        varnames = code.co_varnames[:argcount]
        
        args = []
        for name in varnames:
            if name in frame.f_locals:
                args.append(frame.f_locals[name])
        
        return tuple(args)
    
    def _extract_kwargs(self, frame, code) -> Dict:
        """Extract keyword arguments from a frame."""
        # Python 3.8+ has co_kwonlyargcount
        kwonlyargcount = getattr(code, 'co_kwonlyargcount', 0)
        if kwonlyargcount == 0:
            return {}
        
        argcount = code.co_argcount
        kwnames = code.co_varnames[argcount:argcount + kwonlyargcount]
        
        kwargs = {}
        for name in kwnames:
            if name in frame.f_locals:
                kwargs[name] = frame.f_locals[name]
        
        return kwargs


# Global collector for convenience
_global_collector: Optional[ProfileCollector] = None


def get_global_collector() -> ProfileCollector:
    """Get or create the global profile collector."""
    global _global_collector
    if _global_collector is None:
        _global_collector = ProfileCollector()
    return _global_collector


def start_profiling(sample_rate: Optional[int] = None) -> ProfileCollector:
    """Start global profiling.
    
    Args:
        sample_rate: Optional sample rate override.
        
    Returns:
        The active ProfileCollector.
    """
    global _global_collector
    _global_collector = ProfileCollector(sample_rate=sample_rate)
    _global_collector.start()
    return _global_collector


def stop_profiling() -> ProfileData:
    """Stop global profiling and return collected data.
    
    Returns:
        The collected ProfileData.
    """
    collector = get_global_collector()
    collector.stop()
    return collector.get_data()

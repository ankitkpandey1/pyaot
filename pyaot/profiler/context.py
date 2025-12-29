"""
Profiling context manager for PyAOT.

Provides a convenient way to scope profiling to specific code regions.
"""

from contextlib import contextmanager
from typing import Optional, Generator

from pyaot.profiler.collector import ProfileCollector
from pyaot.profiler.data import ProfileData


@contextmanager
def profiling_session(
    sample_rate: Optional[int] = None,
    save_path: Optional[str] = None,
) -> Generator[ProfileCollector, None, None]:
    """Context manager for scoped profiling.
    
    Usage:
        with profiling_session() as collector:
            # ... run code to profile ...
        data = collector.get_data()
        
        # Or save automatically:
        with profiling_session(save_path="profile.json"):
            # ... run code ...
    
    Args:
        sample_rate: Optional sample rate override (1 in N).
        save_path: Optional path to save profile data on exit.
        
    Yields:
        The active ProfileCollector.
    """
    collector = ProfileCollector(sample_rate=sample_rate)
    try:
        collector.start()
        yield collector
    finally:
        collector.stop()
        if save_path:
            collector.get_data().save(save_path)


def profile_function(func, *args, **kwargs):
    """Profile a single function call.
    
    Convenience function for profiling a single invocation.
    
    Args:
        func: The function to profile.
        *args: Positional arguments.
        **kwargs: Keyword arguments.
        
    Returns:
        Tuple of (result, ProfileData).
    """
    with profiling_session(sample_rate=1) as collector:
        result = func(*args, **kwargs)
    return result, collector.get_data()

"""
PyAOT: Profile-Guided Ahead-of-Time Compilation for Python Hot Paths

A production-grade AOT compilation system that identifies hot execution paths
in Python programs, selectively compiles eligible functions into native code,
and seamlessly integrates compiled artifacts back into CPython execution.

Core Design Principle:
    This system optimizes reality, not Python as a language.
    Profiling defines truth; compilation freezes it; guards preserve safety.
"""

__version__ = "0.1.0"
__author__ = "PyAOT Contributors"

from pyaot.config import Config, get_config
from pyaot.exceptions import (
    AOTError,
    CompilationError,
    GuardFailure,
    CacheError,
    EligibilityError,
)

# Public API
__all__ = [
    # Configuration
    "Config",
    "get_config",
    # Exceptions
    "AOTError",
    "CompilationError",
    "GuardFailure",
    "CacheError",
    "EligibilityError",
    # Version
    "__version__",
]


def enable() -> None:
    """Enable AOT compilation system globally."""
    get_config().enabled = True


def disable() -> None:
    """Disable AOT compilation system globally."""
    get_config().enabled = False


def is_enabled() -> bool:
    """Check if AOT compilation is enabled."""
    return get_config().enabled

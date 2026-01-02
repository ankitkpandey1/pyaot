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
__author__ = "Ankit Kumar Pandey"

from pyaot.config import Config, get_config
from pyaot.exceptions import (
    AOTError,
    CompilationError,
    GuardFailure,
    CacheError,
    EligibilityError,
)

# Import adaptive compilation
from pyaot.adaptive import (
    adaptive,
    compile_adaptive,
    get_adaptive_compiler,
    AdaptiveCompiler,
    NativeArtifact,
)

# Import type hints
from pyaot.hints import (
    extract_type_hints,
    has_compilable_hints,
    TypeHintExtractor,
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
    # Adaptive Compilation
    "adaptive",
    "compile_adaptive",
    "get_adaptive_compiler",
    "AdaptiveCompiler",
    "NativeArtifact",
    # Type Hints
    "extract_type_hints",
    "has_compilable_hints",
    "TypeHintExtractor",
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


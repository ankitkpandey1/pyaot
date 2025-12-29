"""
Logging utilities for PyAOT.

Provides structured logging for:
- Compilation decisions
- Guard failures
- Cache hits/misses
- Performance metrics
"""

import logging
from typing import Optional, Any
from functools import lru_cache

from pyaot.config import get_config


# Module-level logger
_logger: Optional[logging.Logger] = None


@lru_cache(maxsize=1)
def get_logger() -> logging.Logger:
    """Get or create the PyAOT logger."""
    logger = logging.getLogger("pyaot")
    
    # Configure based on config
    config = get_config()
    logger.setLevel(config.log_level)
    
    # Add handler if none exists
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setLevel(config.log_level)
        formatter = logging.Formatter(
            "[%(asctime)s] %(levelname)s [pyaot.%(module)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    
    return logger


def log_compilation_decision(
    function_name: str,
    eligible: bool,
    reason: Optional[str] = None,
    hotness_score: Optional[float] = None,
) -> None:
    """Log a compilation eligibility decision."""
    logger = get_logger()
    if eligible:
        logger.info(
            f"Function '{function_name}' eligible for compilation "
            f"(hotness={hotness_score:.2f})" if hotness_score else
            f"Function '{function_name}' eligible for compilation"
        )
    else:
        logger.debug(
            f"Function '{function_name}' not eligible: {reason}"
        )


def log_guard_failure(
    function_name: str,
    guard_type: str,
    expected: Any,
    actual: Any,
) -> None:
    """Log a guard failure (debug level only)."""
    logger = get_logger()
    logger.debug(
        f"Guard failure in '{function_name}': {guard_type} "
        f"expected {expected}, got {actual}"
    )


def log_cache_event(
    event: str,  # "hit", "miss", "write", "evict"
    cache_key: str,
    function_name: Optional[str] = None,
) -> None:
    """Log a cache event."""
    logger = get_logger()
    if event == "hit":
        logger.debug(f"Cache hit for '{function_name or cache_key[:16]}'")
    elif event == "miss":
        logger.debug(f"Cache miss for '{function_name or cache_key[:16]}'")
    elif event == "write":
        logger.info(f"Cached artifact for '{function_name or cache_key[:16]}'")
    elif event == "evict":
        logger.debug(f"Evicted '{function_name or cache_key[:16]}' from LRU")


def log_compilation_start(function_name: str) -> None:
    """Log the start of compilation."""
    logger = get_logger()
    logger.info(f"Compiling function '{function_name}'...")


def log_compilation_complete(
    function_name: str,
    duration_ms: float,
) -> None:
    """Log successful compilation."""
    logger = get_logger()
    logger.info(
        f"Compiled '{function_name}' in {duration_ms:.1f}ms"
    )


def log_fallback(function_name: str, reason: str) -> None:
    """Log fallback to Python execution."""
    logger = get_logger()
    logger.debug(f"Falling back to Python for '{function_name}': {reason}")

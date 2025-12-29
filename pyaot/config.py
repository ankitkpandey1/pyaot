"""
Configuration management for PyAOT.

Supports environment variables and programmatic configuration.
All metrics collection is disabled by default per specification.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import logging


@dataclass
class Config:
    """Central configuration for PyAOT system.
    
    Attributes:
        enabled: Master switch for AOT compilation
        cache_dir: Directory for artifact cache
        log_level: Logging verbosity
        sample_rate: Profiling sample rate (1/N calls sampled)
        min_call_count: Minimum calls for eligibility
        min_stability_score: Minimum stability score for eligibility
        guard_overhead_budget: Maximum guard overhead as fraction of call time
        metrics_enabled: Enable detailed metrics collection (off by default)
        
        Inline Configuration:
        inline_enabled: Enable call-boundary elimination inlining
        inline_min_calls: Minimum calls for inline eligibility
        inline_min_callee_share: Minimum callee share for monomorphism (0.0-1.0)
        inline_log_rejections: Log rejection reasons for debugging
        inline_telemetry_enabled: Enable per-callsite telemetry collection
        
        Adaptive Compilation:
        adaptive_enabled: Enable unified adaptive compilation
        use_type_hints: Check PEP 484 hints before profiling
        continuous_pgo: Monitor guard failures and recompile on drift
        drift_threshold: Guard failure rate that triggers recompile
        source_hash_check: Invalidate cache on source code change
    """
    
    # Master switch
    enabled: bool = True
    
    # Cache configuration
    cache_dir: Path = field(default_factory=lambda: Path.home() / ".aot_cache")
    
    # Logging
    log_level: int = logging.WARNING
    
    # Profiling (sampled by default to maintain <5% overhead)
    sample_rate: int = 1000  # Sample 1 in N calls
    metrics_enabled: bool = False  # Disabled by default per spec
    
    # Selection thresholds (per specification)
    min_call_count: int = 100
    min_stability_score: float = 0.95
    
    # Guard configuration
    guard_overhead_budget: float = 0.05  # 5% max guard overhead
    
    # Compilation
    max_variants_per_function: int = 4
    lru_cache_size: int = 128
    
    # Inline Configuration
    inline_enabled: bool = True  # Master switch for inlining
    inline_min_calls: int = 1000  # Higher threshold than general compilation
    inline_min_callee_share: float = 0.995  # 99.5% monomorphism required
    inline_log_rejections: bool = False  # Log why callsites are rejected
    inline_telemetry_enabled: bool = False  # Per-callsite metrics
    inline_max_depth: int = 1  # No deep inlining
    
    # Adaptive Compilation Configuration
    adaptive_enabled: bool = True  # Master switch for adaptive compilation
    use_type_hints: bool = True  # Check hints before profiling
    continuous_pgo: bool = True  # Monitor and recompile on drift
    drift_threshold: float = 0.005  # Guard failure rate to trigger recompile (0.5%)
    source_hash_check: bool = True  # Invalidate cache on source change
    
    def __post_init__(self):
        """Ensure cache directory exists."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)


# Global configuration singleton
_config: Optional[Config] = None


def get_config() -> Config:
    """Get or create the global configuration."""
    global _config
    if _config is None:
        _config = load_config_from_env()
    return _config


def set_config(config: Config) -> None:
    """Set the global configuration."""
    global _config
    _config = config


def load_config_from_env() -> Config:
    """Load configuration from environment variables.
    
    Environment Variables:
        AOT_DISABLED: Set to "1" to disable AOT compilation
        AOT_CACHE_DIR: Custom cache directory path
        AOT_LOG_LEVEL: Logging level (DEBUG, INFO, WARNING, ERROR)
        AOT_SAMPLE_RATE: Profiling sample rate (1 in N)
        AOT_MIN_CALLS: Minimum call count threshold
        AOT_MIN_STABILITY: Minimum stability score (0.0-1.0)
        AOT_METRICS_ENABLED: Set to "1" to enable metrics
        
        Inline Configuration:
        AOT_INLINE_ENABLED: Set to "0" to disable inlining
        AOT_INLINE_MIN_CALLS: Minimum calls for inline eligibility (default 1000)
        AOT_INLINE_MIN_CALLEE_SHARE: Minimum callee share (default 0.995)
        AOT_INLINE_LOG_REJECTIONS: Set to "1" to log rejection reasons
        AOT_INLINE_TELEMETRY: Set to "1" to enable per-callsite telemetry
        
        Adaptive Compilation:
        AOT_ADAPTIVE_ENABLED: Set to "0" to disable adaptive compilation
        AOT_USE_TYPE_HINTS: Set to "0" to skip type hint extraction
        AOT_CONTINUOUS_PGO: Set to "0" to disable continuous monitoring
        AOT_DRIFT_THRESHOLD: Guard failure rate threshold (default 0.005)
        AOT_SOURCE_HASH_CHECK: Set to "0" to disable source hash validation
    """
    config = Config()
    
    # Master switch
    if os.environ.get("AOT_DISABLED", "0") == "1":
        config.enabled = False
    
    # Cache directory
    if cache_dir := os.environ.get("AOT_CACHE_DIR"):
        config.cache_dir = Path(cache_dir)
    
    # Logging level
    log_level_str = os.environ.get("AOT_LOG_LEVEL", "WARNING").upper()
    level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
    }
    config.log_level = level_map.get(log_level_str, logging.WARNING)
    
    # Profiling
    if sample_rate := os.environ.get("AOT_SAMPLE_RATE"):
        config.sample_rate = max(1, int(sample_rate))
    
    # Selection thresholds
    if min_calls := os.environ.get("AOT_MIN_CALLS"):
        config.min_call_count = max(1, int(min_calls))
    
    if min_stability := os.environ.get("AOT_MIN_STABILITY"):
        config.min_stability_score = max(0.0, min(1.0, float(min_stability)))
    
    # Metrics (disabled by default, must explicitly enable)
    if os.environ.get("AOT_METRICS_ENABLED", "0") == "1":
        config.metrics_enabled = True
    
    # Inline Configuration
    if os.environ.get("AOT_INLINE_ENABLED", "1") == "0":
        config.inline_enabled = False
    
    if inline_min_calls := os.environ.get("AOT_INLINE_MIN_CALLS"):
        config.inline_min_calls = max(1, int(inline_min_calls))
    
    if inline_share := os.environ.get("AOT_INLINE_MIN_CALLEE_SHARE"):
        config.inline_min_callee_share = max(0.0, min(1.0, float(inline_share)))
    
    if os.environ.get("AOT_INLINE_LOG_REJECTIONS", "0") == "1":
        config.inline_log_rejections = True
    
    if os.environ.get("AOT_INLINE_TELEMETRY", "0") == "1":
        config.inline_telemetry_enabled = True
    
    # Adaptive Compilation Configuration
    if os.environ.get("AOT_ADAPTIVE_ENABLED", "1") == "0":
        config.adaptive_enabled = False
    
    if os.environ.get("AOT_USE_TYPE_HINTS", "1") == "0":
        config.use_type_hints = False
    
    if os.environ.get("AOT_CONTINUOUS_PGO", "1") == "0":
        config.continuous_pgo = False
    
    if drift_threshold := os.environ.get("AOT_DRIFT_THRESHOLD"):
        config.drift_threshold = max(0.0, min(1.0, float(drift_threshold)))
    
    if os.environ.get("AOT_SOURCE_HASH_CHECK", "1") == "0":
        config.source_hash_check = False
    
    return config


def reset_config() -> None:
    """Reset configuration to defaults. Useful for testing."""
    global _config
    _config = None

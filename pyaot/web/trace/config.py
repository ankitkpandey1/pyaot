"""
Tracer configuration for tunable thresholds.

All thresholds are configurable via TracerConfig, enabling
runtime tuning and testing with different values.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TracerConfig:
    """Configuration for trace recording and eligibility.

    All thresholds are tunable, with sensible defaults based on
    production observations. Adjust via telemetry during canary.
    """

    # Eligibility thresholds
    min_observations: int = 100
    min_client_prefixes: int = 3
    min_observation_window_seconds: int = 3600  # 1 hour
    min_branch_stability: float = 0.95  # 95% identical
    max_trace_length: int = 200

    # Buffer settings
    trace_buffer_size: int = 256

    # Store settings
    trace_ttl_seconds: int = 86400  # 24 hours

    # Performance budgets
    max_tracing_overhead_percent: float = 5.0
    max_memory_per_trace_bytes: int = 10_240  # 10KB

    def validate(self) -> list[str]:
        """Validate configuration values, return list of errors."""
        errors: list[str] = []

        if self.min_observations < 1:
            errors.append("min_observations must be >= 1")
        if self.min_client_prefixes < 1:
            errors.append("min_client_prefixes must be >= 1")
        if self.min_observation_window_seconds < 0:
            errors.append("min_observation_window_seconds must be >= 0")
        if not 0.0 <= self.min_branch_stability <= 1.0:
            errors.append("min_branch_stability must be between 0.0 and 1.0")
        if self.max_trace_length < 1:
            errors.append("max_trace_length must be >= 1")
        if self.trace_buffer_size < 1:
            errors.append("trace_buffer_size must be >= 1")

        return errors

    @classmethod
    def for_testing(cls) -> "TracerConfig":
        """Create a config suitable for testing (lower thresholds)."""
        return cls(
            min_observations=2,
            min_client_prefixes=1,
            min_observation_window_seconds=0,
            min_branch_stability=0.5,
            max_trace_length=50,
            trace_buffer_size=32,
        )

    @classmethod
    def for_production(cls) -> "TracerConfig":
        """Create production-ready config with conservative thresholds."""
        return cls(
            min_observations=100,
            min_client_prefixes=3,
            min_observation_window_seconds=3600,
            min_branch_stability=0.95,
            max_trace_length=200,
            trace_buffer_size=256,
        )


# Default global config (can be replaced at runtime)
_default_config: TracerConfig | None = None


def get_config() -> TracerConfig:
    """Get the current tracer configuration."""
    global _default_config
    if _default_config is None:
        _default_config = TracerConfig()
    return _default_config


def set_config(config: TracerConfig) -> None:
    """Set the tracer configuration."""
    global _default_config
    errors = config.validate()
    if errors:
        raise ValueError(f"Invalid config: {', '.join(errors)}")
    _default_config = config


def reset_config() -> None:
    """Reset to default configuration."""
    global _default_config
    _default_config = None

"""Unit tests for TracerConfig.

Tests configuration validation, factory methods, and runtime updates.
"""

import pytest

from pyaot.web.trace.config import (
    TracerConfig,
    get_config,
    set_config,
    reset_config,
)


class TestTracerConfig:
    """Tests for TracerConfig dataclass."""

    def test_default_values(self) -> None:
        """Default config has production-ready values."""
        config = TracerConfig()

        assert config.min_observations == 100
        assert config.min_client_prefixes == 3
        assert config.min_observation_window_seconds == 3600
        assert config.min_branch_stability == 0.95
        assert config.max_trace_length == 200
        assert config.trace_buffer_size == 256

    def test_for_testing_factory(self) -> None:
        """Testing factory creates permissive config."""
        config = TracerConfig.for_testing()

        assert config.min_observations == 2
        assert config.min_client_prefixes == 1
        assert config.min_observation_window_seconds == 0
        assert config.min_branch_stability == 0.5
        assert config.max_trace_length == 50

    def test_for_production_factory(self) -> None:
        """Production factory creates conservative config."""
        config = TracerConfig.for_production()

        assert config.min_observations == 100
        assert config.min_client_prefixes == 3
        assert config.min_branch_stability == 0.95

    def test_validation_valid_config(self) -> None:
        """Valid config passes validation."""
        config = TracerConfig()
        errors = config.validate()

        assert errors == []

    def test_validation_invalid_observations(self) -> None:
        """Zero observations fails validation."""
        config = TracerConfig(min_observations=0)
        errors = config.validate()

        assert len(errors) == 1
        assert "min_observations" in errors[0]

    def test_validation_invalid_branch_stability(self) -> None:
        """Branch stability outside 0-1 fails validation."""
        config = TracerConfig(min_branch_stability=1.5)
        errors = config.validate()

        assert len(errors) == 1
        assert "min_branch_stability" in errors[0]

    def test_validation_negative_window(self) -> None:
        """Negative observation window fails validation."""
        config = TracerConfig(min_observation_window_seconds=-1)
        errors = config.validate()

        assert len(errors) == 1
        assert "min_observation_window_seconds" in errors[0]


class TestGlobalConfig:
    """Tests for global config management."""

    def setup_method(self) -> None:
        """Reset config before each test."""
        reset_config()

    def teardown_method(self) -> None:
        """Reset config after each test."""
        reset_config()

    def test_get_config_returns_default(self) -> None:
        """get_config returns default when not set."""
        config = get_config()

        assert config.min_observations == 100

    def test_set_config_updates_global(self) -> None:
        """set_config updates the global config."""
        custom = TracerConfig(min_observations=50)
        set_config(custom)

        config = get_config()
        assert config.min_observations == 50

    def test_set_config_validates(self) -> None:
        """set_config rejects invalid config."""
        invalid = TracerConfig(min_observations=-1)

        with pytest.raises(ValueError, match="Invalid config"):
            set_config(invalid)

    def test_reset_config_clears(self) -> None:
        """reset_config restores defaults."""
        set_config(TracerConfig(min_observations=50))
        reset_config()

        config = get_config()
        assert config.min_observations == 100

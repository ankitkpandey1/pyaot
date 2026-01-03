"""Canary deployment controller for gradual trace rollout.

Controls gradual rollout of trace compilation to a subset of traffic,
enabling safe production deployment with easy rollback.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING, Any

from pyaot.web.ops.metrics import MetricsCollector, get_metrics

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class CanaryStage(Enum):
    """Canary deployment stage."""

    OFF = auto()  # No trace compilation
    CANARY_1 = auto()  # 1% traffic
    CANARY_5 = auto()  # 5% traffic
    CANARY_25 = auto()  # 25% traffic
    CANARY_50 = auto()  # 50% traffic
    FULL = auto()  # 100% traffic


# Percentage of traffic for each stage
STAGE_PERCENTAGES: dict[CanaryStage, float] = {
    CanaryStage.OFF: 0.0,
    CanaryStage.CANARY_1: 0.01,
    CanaryStage.CANARY_5: 0.05,
    CanaryStage.CANARY_25: 0.25,
    CanaryStage.CANARY_50: 0.50,
    CanaryStage.FULL: 1.0,
}


@dataclass
class CanaryConfig:
    """Configuration for canary deployment.

    Attributes:
        initial_stage: Starting stage.
        auto_promote: Whether to auto-promote on SLO success.
        promotion_delay_seconds: Time before auto-promotion.
        min_requests_before_promote: Minimum requests before promotion.
    """

    initial_stage: CanaryStage = CanaryStage.CANARY_1
    auto_promote: bool = True
    promotion_delay_seconds: int = 300  # 5 minutes
    min_requests_before_promote: int = 1000


class CanaryController:
    """Controls gradual rollout of trace compilation.

    Uses consistent hashing to deterministically route requests
    to compiled path based on client IP or request ID.
    """

    def __init__(
        self,
        config: CanaryConfig | None = None,
        metrics: MetricsCollector | None = None,
    ) -> None:
        """Initialize canary controller.

        Args:
            config: Canary configuration.
            metrics: Metrics collector.
        """
        self._config = config or CanaryConfig()
        self._metrics = metrics or get_metrics()
        self._stage = self._config.initial_stage
        self._request_count = 0
        self._stage_start_time = 0.0
        self._lock = threading.Lock()

    @property
    def stage(self) -> CanaryStage:
        """Get current canary stage."""
        return self._stage

    @property
    def percentage(self) -> float:
        """Get current traffic percentage."""
        return STAGE_PERCENTAGES[self._stage]

    def should_use_compiled(self, request_id: str) -> bool:
        """Determine if request should use compiled path.

        Uses consistent hashing for deterministic routing.

        Args:
            request_id: Unique request identifier (client IP, session, etc.).

        Returns:
            True if request should use compiled trace.
        """
        if self._stage == CanaryStage.OFF:
            return False
        if self._stage == CanaryStage.FULL:
            return True

        # Consistent hash for deterministic routing
        hash_value = int(hashlib.md5(request_id.encode()).hexdigest(), 16)
        bucket = (hash_value % 100) / 100.0

        return bucket < self.percentage

    def record_request(self, used_compiled: bool) -> None:
        """Record a request for canary tracking.

        Args:
            used_compiled: Whether compiled path was used.
        """
        with self._lock:
            self._request_count += 1

            if used_compiled:
                self._metrics.inc("py_aot.canary.compiled_requests")
            else:
                self._metrics.inc("py_aot.canary.baseline_requests")

    def promote(self) -> bool:
        """Promote to next canary stage.

        Returns:
            True if promoted, False if already at FULL.
        """
        stages = list(CanaryStage)
        current_idx = stages.index(self._stage)

        if current_idx >= len(stages) - 1:
            return False

        with self._lock:
            self._stage = stages[current_idx + 1]
            self._request_count = 0
            self._stage_start_time = 0.0

        logger.info(
            f"Canary promoted to {self._stage.name} ({self.percentage:.0%} traffic)"
        )
        return True

    def demote(self) -> bool:
        """Demote to previous canary stage.

        Returns:
            True if demoted, False if already at OFF.
        """
        stages = list(CanaryStage)
        current_idx = stages.index(self._stage)

        if current_idx <= 0:
            return False

        with self._lock:
            self._stage = stages[current_idx - 1]
            self._request_count = 0

        logger.info(
            f"Canary demoted to {self._stage.name} ({self.percentage:.0%} traffic)"
        )
        return True

    def set_stage(self, stage: CanaryStage) -> None:
        """Set canary stage directly.

        Args:
            stage: Target stage.
        """
        with self._lock:
            self._stage = stage
            self._request_count = 0
            self._stage_start_time = 0.0

        logger.info(f"Canary set to {stage.name} ({self.percentage:.0%} traffic)")

    def disable(self) -> None:
        """Disable canary (set to OFF)."""
        self.set_stage(CanaryStage.OFF)

    def enable_full(self) -> None:
        """Enable full deployment."""
        self.set_stage(CanaryStage.FULL)

    def check_auto_promote(self) -> bool:
        """Check if auto-promotion conditions are met.

        Returns:
            True if promotion should occur.
        """
        if not self._config.auto_promote:
            return False

        if self._stage == CanaryStage.FULL:
            return False

        # Check minimum requests
        if self._request_count < self._config.min_requests_before_promote:
            return False

        # Check SLOs
        slos = self._metrics.check_slos()
        if not all(slos.values()):
            return False

        return True

    def get_status(self) -> dict[str, Any]:
        """Get canary status.

        Returns:
            Dict with status information.
        """
        return {
            "stage": self._stage.name,
            "percentage": self.percentage,
            "request_count": self._request_count,
            "auto_promote": self._config.auto_promote,
            "can_promote": self.check_auto_promote(),
            "slos": self._metrics.check_slos(),
        }

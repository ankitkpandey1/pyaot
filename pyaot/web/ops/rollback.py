"""Automatic rollback controller for trace compilation.

Monitors SLOs and automatically disables trace compilation when
thresholds are breached, preventing production incidents.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING, Any, Callable

from pyaot.web.ops.metrics import MetricsCollector, get_metrics

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class RollbackState(Enum):
    """State of the rollback controller."""

    ENABLED = auto()  # Trace compilation active
    DISABLED = auto()  # Rolled back, CPython only
    CANARY = auto()  # Partial rollout


@dataclass
class RollbackEvent:
    """Record of a rollback event.

    Attributes:
        timestamp: When rollback occurred.
        reason: Why rollback was triggered.
        metrics_snapshot: Metrics at time of rollback.
    """

    timestamp: float
    reason: str
    metrics_snapshot: dict[str, Any]


class RollbackController:
    """Controls automatic rollback based on SLO breaches.

    Policy:
    - guard_miss_rate > 1% for 5min → rollback
    - deopt_rate > 0.1% for 5min → rollback
    - p99 latency increase > 5% → rollback

    After rollback, manual re-enable required.
    """

    # Alert thresholds (from VISION.md)
    GUARD_MISS_THRESHOLD = 0.01
    DEOPT_THRESHOLD = 0.001
    BREACH_WINDOW_SECONDS = 300  # 5 minutes
    CHECK_INTERVAL_SECONDS = 10

    def __init__(
        self,
        metrics: MetricsCollector | None = None,
        on_rollback: Callable[[RollbackEvent], None] | None = None,
    ) -> None:
        """Initialize rollback controller.

        Args:
            metrics: Metrics collector to monitor.
            on_rollback: Callback when rollback occurs.
        """
        self._metrics = metrics or get_metrics()
        self._on_rollback = on_rollback
        self._state = RollbackState.ENABLED
        self._events: list[RollbackEvent] = []
        self._breach_start: float | None = None
        self._lock = threading.Lock()
        self._monitor_thread: threading.Thread | None = None
        self._running = False

    @property
    def state(self) -> RollbackState:
        """Get current rollback state."""
        return self._state

    @property
    def is_enabled(self) -> bool:
        """Check if trace compilation is enabled."""
        return self._state == RollbackState.ENABLED

    def enable(self) -> None:
        """Enable trace compilation."""
        with self._lock:
            self._state = RollbackState.ENABLED
            self._breach_start = None
            logger.info("PyAOT trace compilation enabled")

    def disable(self, reason: str = "manual") -> None:
        """Disable trace compilation (rollback).

        Args:
            reason: Reason for rollback.
        """
        with self._lock:
            if self._state == RollbackState.DISABLED:
                return

            self._state = RollbackState.DISABLED

            event = RollbackEvent(
                timestamp=time.time(),
                reason=reason,
                metrics_snapshot=self._metrics.get_summary(),
            )
            self._events.append(event)

            logger.warning(f"PyAOT rollback triggered: {reason}")

            if self._on_rollback:
                self._on_rollback(event)

    def check_and_rollback(self) -> bool:
        """Check SLOs and trigger rollback if breached.

        Returns:
            True if rollback was triggered.
        """
        if self._state == RollbackState.DISABLED:
            return False

        slos = self._metrics.check_slos()
        all_passing = all(slos.values())

        with self._lock:
            if all_passing:
                # Reset breach timer
                self._breach_start = None
                return False

            # SLO breach detected
            now = time.time()
            if self._breach_start is None:
                self._breach_start = now
                logger.warning(f"SLO breach detected: {slos}")
                return False

            # Check if breach duration exceeds threshold
            breach_duration = now - self._breach_start
            if breach_duration >= self.BREACH_WINDOW_SECONDS:
                failed_slos = [k for k, v in slos.items() if not v]
                reason = f"SLO breach for {breach_duration:.0f}s: {failed_slos}"
                self.disable(reason)
                return True

        return False

    def start_monitoring(self) -> None:
        """Start background SLO monitoring."""
        if self._running:
            return

        self._running = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
        logger.info("PyAOT rollback monitoring started")

    def stop_monitoring(self) -> None:
        """Stop background SLO monitoring."""
        self._running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=1)
            self._monitor_thread = None

    def _monitor_loop(self) -> None:
        """Background monitoring loop."""
        while self._running:
            try:
                self.check_and_rollback()
            except Exception as e:
                logger.error(f"Rollback check error: {e}")

            time.sleep(self.CHECK_INTERVAL_SECONDS)

    def get_events(self) -> list[RollbackEvent]:
        """Get all rollback events."""
        return self._events.copy()

    def get_status(self) -> dict[str, Any]:
        """Get controller status.

        Returns:
            Dict with status information.
        """
        return {
            "state": self._state.name,
            "is_enabled": self.is_enabled,
            "breach_active": self._breach_start is not None,
            "breach_duration_s": (
                time.time() - self._breach_start if self._breach_start else 0
            ),
            "rollback_events": len(self._events),
            "slos": self._metrics.check_slos(),
        }

"""
Trace eligibility evaluation for anti-poisoning.

This is the single most important defense against trace poisoning.
A trace is eligible for compilation only if ALL rules pass.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pyaot.web.trace.config import TracerConfig, get_config

if TYPE_CHECKING:
    from pyaot.web.trace.signature import RequestSignature


@dataclass
class ObservationRecord:
    """Record of observations for a request signature."""

    signature: "RequestSignature"
    observation_count: int = 0
    first_observation_time: float = 0.0
    last_observation_time: float = 0.0
    client_prefixes: set[str] = field(default_factory=set)
    branch_fingerprints: dict[int, int] = field(
        default_factory=lambda: defaultdict(int)
    )
    shape_history: list[int] = field(default_factory=list)

    def record_observation(
        self,
        client_ip: str,
        branch_fingerprint: int,
        shape_id: int,
    ) -> None:
        """Record a new observation."""
        now = time.time()

        if self.observation_count == 0:
            self.first_observation_time = now

        self.observation_count += 1
        self.last_observation_time = now

        # Extract IP prefix (first 3 octets for IPv4)
        prefix = _extract_ip_prefix(client_ip)
        self.client_prefixes.add(prefix)

        # Track branch fingerprint frequency
        self.branch_fingerprints[branch_fingerprint] += 1

        # Track recent shapes (keep last 100)
        self.shape_history.append(shape_id)
        if len(self.shape_history) > 100:
            self.shape_history = self.shape_history[-100:]


@dataclass
class EligibilityResult:
    """Result of eligibility evaluation."""

    eligible: bool
    reason: str | None = None
    observations: int = 0
    client_prefixes: int = 0
    observation_window_hours: float = 0.0
    branch_stability: float = 0.0
    dominant_fingerprint: int | None = None


class EligibilityEvaluator:
    """Evaluates trace eligibility for compilation.

    Anti-poisoning core: ensures traces are stable, well-observed,
    and come from diverse sources.
    """

    def __init__(self, config: TracerConfig | None = None) -> None:
        """Initialize with optional config. Uses global config if not provided."""
        self._config = config or get_config()
        self._records: dict[RequestSignature, ObservationRecord] = {}
        self._blacklisted: set[RequestSignature] = set()

    @property
    def config(self) -> TracerConfig:
        """Get current configuration."""
        return self._config

    def update_config(self, config: TracerConfig) -> None:
        """Update configuration at runtime."""
        self._config = config

    def record_observation(
        self,
        signature: "RequestSignature",
        client_ip: str,
        branch_fingerprint: int,
        shape_id: int,
        trace_length: int,
    ) -> None:
        """Record a trace observation for eligibility tracking."""
        # Guard: skip blacklisted or oversized traces
        if signature in self._blacklisted:
            return
        if trace_length > self._config.max_trace_length:
            return

        if signature not in self._records:
            self._records[signature] = ObservationRecord(signature=signature)

        self._records[signature].record_observation(
            client_ip=client_ip,
            branch_fingerprint=branch_fingerprint,
            shape_id=shape_id,
        )

    def evaluate(self, signature: "RequestSignature") -> EligibilityResult:
        """Evaluate if a signature is eligible for compilation."""
        # Guard: blacklisted
        if signature in self._blacklisted:
            return EligibilityResult(eligible=False, reason="blacklisted")

        # Guard: no observations
        if signature not in self._records:
            return EligibilityResult(eligible=False, reason="no observations")

        record = self._records[signature]
        return self._check_eligibility(record)

    def _check_eligibility(self, record: ObservationRecord) -> EligibilityResult:
        """Run all eligibility checks on an observation record."""
        cfg = self._config

        # Check 1: minimum observations
        if record.observation_count < cfg.min_observations:
            return EligibilityResult(
                eligible=False,
                reason=f"insufficient observations: {record.observation_count} < {cfg.min_observations}",
                observations=record.observation_count,
            )

        # Check 2: client diversity
        num_prefixes = len(record.client_prefixes)
        if num_prefixes < cfg.min_client_prefixes:
            return EligibilityResult(
                eligible=False,
                reason=f"insufficient client diversity: {num_prefixes} < {cfg.min_client_prefixes}",
                observations=record.observation_count,
                client_prefixes=num_prefixes,
            )

        # Check 3: observation window
        window_seconds = record.last_observation_time - record.first_observation_time
        window_hours = window_seconds / 3600
        if window_seconds < cfg.min_observation_window_seconds:
            return EligibilityResult(
                eligible=False,
                reason=f"observation window too short: {window_seconds:.0f}s < {cfg.min_observation_window_seconds}s",
                observations=record.observation_count,
                client_prefixes=num_prefixes,
                observation_window_hours=window_hours,
            )

        # Check 4: branch stability
        stability_result = self._compute_branch_stability(record)
        if stability_result is None:
            return EligibilityResult(eligible=False, reason="no branch data")

        branch_stability, dominant_fingerprint = stability_result
        if branch_stability < cfg.min_branch_stability:
            return EligibilityResult(
                eligible=False,
                reason=f"unstable branches: {branch_stability:.1%} < {cfg.min_branch_stability:.0%}",
                observations=record.observation_count,
                client_prefixes=num_prefixes,
                observation_window_hours=window_hours,
                branch_stability=branch_stability,
            )

        # Check 5: shape stability (no new shapes in last 20%)
        if not self._check_shape_stability(record):
            return EligibilityResult(
                eligible=False,
                reason="shape instability: new shapes in recent observations",
                observations=record.observation_count,
                client_prefixes=num_prefixes,
                observation_window_hours=window_hours,
                branch_stability=branch_stability,
            )

        # All checks passed
        return EligibilityResult(
            eligible=True,
            observations=record.observation_count,
            client_prefixes=num_prefixes,
            observation_window_hours=window_hours,
            branch_stability=branch_stability,
            dominant_fingerprint=dominant_fingerprint,
        )

    def _compute_branch_stability(
        self, record: ObservationRecord
    ) -> tuple[float, int] | None:
        """Compute branch stability ratio and dominant fingerprint."""
        total = sum(record.branch_fingerprints.values())
        if total == 0:
            return None

        dominant_count = max(record.branch_fingerprints.values())
        dominant_fingerprint = max(
            record.branch_fingerprints.keys(),
            key=lambda k: record.branch_fingerprints[k],
        )
        return dominant_count / total, dominant_fingerprint

    def _check_shape_stability(self, record: ObservationRecord) -> bool:
        """Check shape stability (no new shapes in last 20%)."""
        if len(record.shape_history) < 20:
            return True

        recent = record.shape_history[-20:]
        earlier = record.shape_history[:-20]
        new_shapes = set(recent) - set(earlier)
        return len(new_shapes) == 0

    def blacklist(self, signature: "RequestSignature") -> None:
        """Blacklist a signature (poison suspicion)."""
        self._blacklisted.add(signature)
        self._records.pop(signature, None)

    def reset(self, signature: "RequestSignature") -> None:
        """Reset observations for a signature (re-observe)."""
        self._records.pop(signature, None)

    def get_eligible_signatures(self) -> list["RequestSignature"]:
        """Get all currently eligible signatures."""
        return [sig for sig in self._records if self.evaluate(sig).eligible]


def _extract_ip_prefix(ip: str) -> str:
    """Extract IP prefix for diversity checking.

    For IPv4: first 3 octets (e.g., 192.168.1.x -> 192.168.1)
    For IPv6: first 48 bits
    """
    if ":" in ip:
        parts = ip.split(":")
        return ":".join(parts[:3])

    parts = ip.split(".")
    return ".".join(parts[:3])

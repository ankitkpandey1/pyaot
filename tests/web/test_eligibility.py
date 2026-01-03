"""Unit tests for EligibilityEvaluator.

Tests anti-poisoning rules and eligibility evaluation.
"""

from pyaot.web.trace.config import TracerConfig
from pyaot.web.trace.eligibility import EligibilityEvaluator, _extract_ip_prefix
from pyaot.web.trace.signature import RequestSignature


def make_signature(path: str = "/test") -> RequestSignature:
    """Create a test signature."""
    return RequestSignature(
        http_method="GET",
        path_template=path,
        auth_state="anon",
        param_types=(),
        header_shape_hash="abc",
        body_shape_hash="def",
    )


class TestEligibilityEvaluator:
    """Tests for EligibilityEvaluator anti-poisoning."""

    def test_no_observations_not_eligible(self) -> None:
        """Signature with no observations is not eligible."""
        evaluator = EligibilityEvaluator()
        sig = make_signature()

        result = evaluator.evaluate(sig)

        assert result.eligible is False
        assert result.reason == "no observations"

    def test_insufficient_observations(self) -> None:
        """Signature with too few observations is not eligible."""
        config = TracerConfig(min_observations=10)
        evaluator = EligibilityEvaluator(config=config)
        sig = make_signature()

        # Record only 5 observations
        for i in range(5):
            evaluator.record_observation(
                signature=sig,
                client_ip=f"192.168.{i}.1",
                branch_fingerprint=1,
                shape_id=0,
                trace_length=10,
            )

        result = evaluator.evaluate(sig)

        assert result.eligible is False
        assert "insufficient observations" in result.reason

    def test_insufficient_client_diversity(self) -> None:
        """Signature from single IP prefix is not eligible."""
        config = TracerConfig.for_testing()
        config = TracerConfig(
            min_observations=5,
            min_client_prefixes=3,
            min_observation_window_seconds=0,
            min_branch_stability=0.5,
        )
        evaluator = EligibilityEvaluator(config=config)
        sig = make_signature()

        # All from same IP prefix
        for i in range(10):
            evaluator.record_observation(
                signature=sig,
                client_ip=f"192.168.1.{i}",  # Same prefix
                branch_fingerprint=1,
                shape_id=0,
                trace_length=10,
            )

        result = evaluator.evaluate(sig)

        assert result.eligible is False
        assert "diversity" in result.reason

    def test_observation_window_too_short(self) -> None:
        """Signature with observations in short window is not eligible."""
        config = TracerConfig(
            min_observations=2,
            min_client_prefixes=1,
            min_observation_window_seconds=3600,  # 1 hour required
            min_branch_stability=0.5,
        )
        evaluator = EligibilityEvaluator(config=config)
        sig = make_signature()

        # Record observations (in same time window due to fast execution)
        for i in range(5):
            evaluator.record_observation(
                signature=sig,
                client_ip=f"192.168.{i}.1",
                branch_fingerprint=1,
                shape_id=0,
                trace_length=10,
            )

        result = evaluator.evaluate(sig)

        assert result.eligible is False
        assert "window" in result.reason

    def test_unstable_branches(self) -> None:
        """Signature with unstable branches is not eligible."""
        config = TracerConfig(
            min_observations=5,
            min_client_prefixes=1,
            min_observation_window_seconds=0,
            min_branch_stability=0.9,  # 90% required
        )
        evaluator = EligibilityEvaluator(config=config)
        sig = make_signature()

        # Record with varying branch fingerprints (unstable)
        for i in range(10):
            evaluator.record_observation(
                signature=sig,
                client_ip=f"192.168.{i}.1",
                branch_fingerprint=i % 3,  # 3 different fingerprints
                shape_id=0,
                trace_length=10,
            )

        result = evaluator.evaluate(sig)

        assert result.eligible is False
        assert "unstable" in result.reason

    def test_eligible_signature(self) -> None:
        """Signature meeting all criteria is eligible."""
        config = TracerConfig(
            min_observations=5,
            min_client_prefixes=2,
            min_observation_window_seconds=0,
            min_branch_stability=0.8,
        )
        evaluator = EligibilityEvaluator(config=config)
        sig = make_signature()

        # Record stable observations from diverse clients
        for i in range(10):
            evaluator.record_observation(
                signature=sig,
                client_ip=f"192.168.{i % 5}.1",  # 5 different prefixes
                branch_fingerprint=1,  # All same (stable)
                shape_id=0,
                trace_length=10,
            )

        result = evaluator.evaluate(sig)

        assert result.eligible is True
        assert result.observations == 10
        assert result.branch_stability == 1.0

    def test_blacklisted_signature_not_eligible(self) -> None:
        """Blacklisted signature is not eligible."""
        evaluator = EligibilityEvaluator()
        sig = make_signature()

        evaluator.blacklist(sig)

        result = evaluator.evaluate(sig)

        assert result.eligible is False
        assert result.reason == "blacklisted"

    def test_oversized_trace_not_recorded(self) -> None:
        """Traces exceeding max length are not recorded."""
        config = TracerConfig(max_trace_length=100)
        evaluator = EligibilityEvaluator(config=config)
        sig = make_signature()

        evaluator.record_observation(
            signature=sig,
            client_ip="192.168.1.1",
            branch_fingerprint=1,
            shape_id=0,
            trace_length=200,  # Exceeds max
        )

        result = evaluator.evaluate(sig)

        assert result.eligible is False
        assert result.reason == "no observations"

    def test_reset_clears_observations(self) -> None:
        """reset clears observations for a signature."""
        config = TracerConfig.for_testing()
        evaluator = EligibilityEvaluator(config=config)
        sig = make_signature()

        evaluator.record_observation(
            signature=sig,
            client_ip="192.168.1.1",
            branch_fingerprint=1,
            shape_id=0,
            trace_length=10,
        )
        evaluator.reset(sig)

        result = evaluator.evaluate(sig)

        assert result.eligible is False
        assert result.reason == "no observations"

    def test_get_eligible_signatures(self) -> None:
        """get_eligible_signatures returns only eligible ones."""
        config = TracerConfig(
            min_observations=2,
            min_client_prefixes=1,
            min_observation_window_seconds=0,
            min_branch_stability=0.5,
        )
        evaluator = EligibilityEvaluator(config=config)

        sig1 = make_signature("/eligible")
        sig2 = make_signature("/not-eligible")

        # Make sig1 eligible
        for i in range(5):
            evaluator.record_observation(
                signature=sig1,
                client_ip=f"192.168.{i}.1",
                branch_fingerprint=1,
                shape_id=0,
                trace_length=10,
            )

        # sig2 has only 1 observation
        evaluator.record_observation(
            signature=sig2,
            client_ip="192.168.1.1",
            branch_fingerprint=1,
            shape_id=0,
            trace_length=10,
        )

        eligible = evaluator.get_eligible_signatures()

        assert sig1 in eligible
        assert sig2 not in eligible


class TestExtractIpPrefix:
    """Tests for IP prefix extraction."""

    def test_ipv4_prefix(self) -> None:
        """IPv4 prefix is first 3 octets."""
        prefix = _extract_ip_prefix("192.168.1.100")

        assert prefix == "192.168.1"

    def test_ipv6_prefix(self) -> None:
        """IPv6 prefix is first 3 groups."""
        prefix = _extract_ip_prefix("2001:db8:85a3:0:0:8a2e:370:7334")

        assert prefix == "2001:db8:85a3"

"""Benchmarks for trace eligibility evaluation.

Measures anti-poisoning rule evaluation overhead.
"""

from pyaot.web.trace.config import TracerConfig
from pyaot.web.trace.eligibility import EligibilityEvaluator
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


class TestEligibilityBenchmarks:
    """Benchmarks for EligibilityEvaluator performance."""

    def test_record_observation(self, benchmark) -> None:
        """Benchmark single observation recording."""
        config = TracerConfig.for_testing()
        evaluator = EligibilityEvaluator(config=config)
        sig = make_signature()
        counter = [0]

        def record():
            evaluator.record_observation(
                signature=sig,
                client_ip=f"192.168.{counter[0] % 256}.1",
                branch_fingerprint=1,
                shape_id=0,
                trace_length=50,
            )
            counter[0] += 1

        benchmark(record)

    def test_evaluate_eligible(self, benchmark) -> None:
        """Benchmark evaluation of eligible signature."""
        config = TracerConfig(
            min_observations=5,
            min_client_prefixes=2,
            min_observation_window_seconds=0,
            min_branch_stability=0.5,
        )
        evaluator = EligibilityEvaluator(config=config)
        sig = make_signature()

        # Setup eligible signature
        for i in range(100):
            evaluator.record_observation(
                signature=sig,
                client_ip=f"192.168.{i % 10}.1",
                branch_fingerprint=1,
                shape_id=0,
                trace_length=50,
            )

        def evaluate():
            return evaluator.evaluate(sig)

        result = benchmark(evaluate)
        assert result.eligible

    def test_evaluate_not_eligible(self, benchmark) -> None:
        """Benchmark evaluation of non-eligible signature."""
        config = TracerConfig.for_production()  # High thresholds
        evaluator = EligibilityEvaluator(config=config)
        sig = make_signature()

        # Only a few observations
        for i in range(5):
            evaluator.record_observation(
                signature=sig,
                client_ip=f"192.168.{i}.1",
                branch_fingerprint=1,
                shape_id=0,
                trace_length=50,
            )

        def evaluate():
            return evaluator.evaluate(sig)

        result = benchmark(evaluate)
        assert not result.eligible


class TestSignatureBenchmarks:
    """Benchmarks for RequestSignature computation."""

    def test_signature_creation(self, benchmark) -> None:
        """Benchmark signature creation from request."""

        def create():
            return RequestSignature.from_request(
                method="POST",
                path_template="/api/users/<id>",
                params={"id": 42, "page": 1},
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer token",
                    "X-Request-ID": "abc123",
                },
                body={"name": "Alice", "email": "alice@example.com"},
            )

        benchmark(create)

    def test_signature_hash(self, benchmark) -> None:
        """Benchmark signature hashing."""
        sig = make_signature()

        benchmark(hash, sig)

    def test_signature_to_tuple(self, benchmark) -> None:
        """Benchmark signature tuple conversion."""
        sig = make_signature()

        benchmark(sig.to_tuple)

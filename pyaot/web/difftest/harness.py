"""Difftest harness for trace equivalence testing.

Compares compiled trace execution against CPython interpreter
to verify semantic equivalence.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable


class DifftestStatus(Enum):
    """Result status of a difftest run."""

    PASS = auto()  # Outputs match
    FAIL_STATUS = auto()  # Status codes differ
    FAIL_HEADERS = auto()  # Headers differ
    FAIL_BODY = auto()  # Body content differs
    FAIL_EXCEPTION = auto()  # Exception behavior differs
    FAIL_SIDE_EFFECTS = auto()  # Side effect log differs
    ERROR = auto()  # Test execution error


@dataclass
class DifftestResult:
    """Result of a difftest comparison.

    Attributes:
        status: Overall test status.
        passed: True if all checks passed.
        cpython_output: Output from CPython execution.
        compiled_output: Output from compiled trace.
        divergence_details: Description of any divergence.
        execution_time_cpython_ms: CPython execution time.
        execution_time_compiled_ms: Compiled execution time.
    """

    status: DifftestStatus
    passed: bool
    cpython_output: dict[str, Any] = field(default_factory=dict)
    compiled_output: dict[str, Any] = field(default_factory=dict)
    divergence_details: str = ""
    execution_time_cpython_ms: float = 0.0
    execution_time_compiled_ms: float = 0.0

    @property
    def speedup(self) -> float:
        """Calculate speedup factor of compiled vs CPython."""
        if self.execution_time_compiled_ms <= 0:
            return 0.0
        return self.execution_time_cpython_ms / self.execution_time_compiled_ms


@dataclass
class RequestInput:
    """Canonical input for difftest replay.

    Attributes:
        method: HTTP method.
        path: Request path.
        headers: HTTP headers.
        body: Request body.
        params: URL/query parameters.
    """

    method: str
    path: str
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResponseOutput:
    """Canonical output for difftest comparison.

    Attributes:
        status_code: HTTP status code.
        headers: Response headers.
        body: Response body.
        side_effect_log: Log of side effects performed.
    """

    status_code: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""
    side_effect_log: list[str] = field(default_factory=list)


class DifftestHarness:
    """Difftest harness for trace equivalence testing.

    Policy: All recorded canonical traces must pass 100% byte-for-byte
    equivalence on CI. Fuzzed trace checks require no divergences for
    a sampled set of N=1000. Any divergence fails the build.
    """

    def __init__(self) -> None:
        """Initialize difftest harness."""
        self._results: list[DifftestResult] = []
        self._fuzz_sample_size = 1000

    def run_test(
        self,
        request: RequestInput,
        cpython_handler: Callable[[RequestInput], ResponseOutput],
        compiled_handler: Callable[[RequestInput], ResponseOutput],
    ) -> DifftestResult:
        """Run a single difftest.

        Args:
            request: The input request.
            cpython_handler: Handler executed via CPython.
            compiled_handler: Handler executed via compiled trace.

        Returns:
            DifftestResult with comparison details.
        """
        # Execute CPython path
        try:
            start = time.perf_counter()
            cpython_output = cpython_handler(request)
            cpython_time = (time.perf_counter() - start) * 1000
        except Exception as e:
            return DifftestResult(
                status=DifftestStatus.ERROR,
                passed=False,
                divergence_details=f"CPython execution error: {e}",
            )

        # Execute compiled path
        try:
            start = time.perf_counter()
            compiled_output = compiled_handler(request)
            compiled_time = (time.perf_counter() - start) * 1000
        except Exception as e:
            return DifftestResult(
                status=DifftestStatus.ERROR,
                passed=False,
                divergence_details=f"Compiled execution error: {e}",
                execution_time_cpython_ms=cpython_time,
            )

        # Compare outputs
        result = self._compare_outputs(cpython_output, compiled_output)
        result.execution_time_cpython_ms = cpython_time
        result.execution_time_compiled_ms = compiled_time
        result.cpython_output = {
            "status_code": cpython_output.status_code,
            "body_hash": hashlib.sha256(cpython_output.body).hexdigest()[:16],
        }
        result.compiled_output = {
            "status_code": compiled_output.status_code,
            "body_hash": hashlib.sha256(compiled_output.body).hexdigest()[:16],
        }

        self._results.append(result)
        return result

    def run_canonical_tests(
        self,
        test_cases: list[tuple[RequestInput, ResponseOutput]],
        compiled_handler: Callable[[RequestInput], ResponseOutput],
    ) -> list[DifftestResult]:
        """Run canonical trace tests.

        All canonical tests must pass 100%.

        Args:
            test_cases: List of (request, expected_output) tuples.
            compiled_handler: Handler to test.

        Returns:
            List of DifftestResult for each test case.
        """
        results = []
        for request, expected in test_cases:
            # Compare compiled output to expected
            try:
                start = time.perf_counter()
                actual = compiled_handler(request)
                exec_time = (time.perf_counter() - start) * 1000
            except Exception as e:
                results.append(
                    DifftestResult(
                        status=DifftestStatus.ERROR,
                        passed=False,
                        divergence_details=f"Execution error: {e}",
                    )
                )
                continue

            result = self._compare_outputs(expected, actual)
            result.execution_time_compiled_ms = exec_time
            results.append(result)

        return results

    def _compare_outputs(
        self,
        expected: ResponseOutput,
        actual: ResponseOutput,
    ) -> DifftestResult:
        """Compare two response outputs.

        Args:
            expected: Expected (CPython) output.
            actual: Actual (compiled) output.

        Returns:
            DifftestResult with comparison details.
        """
        # Check status code
        if expected.status_code != actual.status_code:
            return DifftestResult(
                status=DifftestStatus.FAIL_STATUS,
                passed=False,
                divergence_details=(
                    f"Status mismatch: expected {expected.status_code}, "
                    f"got {actual.status_code}"
                ),
            )

        # Check headers
        for key, value in expected.headers.items():
            if actual.headers.get(key) != value:
                return DifftestResult(
                    status=DifftestStatus.FAIL_HEADERS,
                    passed=False,
                    divergence_details=(
                        f"Header mismatch for {key}: expected {value!r}, "
                        f"got {actual.headers.get(key)!r}"
                    ),
                )

        # Check body (byte-for-byte)
        if expected.body != actual.body:
            return DifftestResult(
                status=DifftestStatus.FAIL_BODY,
                passed=False,
                divergence_details=(
                    f"Body mismatch: expected {len(expected.body)} bytes, "
                    f"got {len(actual.body)} bytes"
                ),
            )

        # Check side effects
        if expected.side_effect_log != actual.side_effect_log:
            return DifftestResult(
                status=DifftestStatus.FAIL_SIDE_EFFECTS,
                passed=False,
                divergence_details="Side effect log mismatch",
            )

        # All checks passed
        return DifftestResult(
            status=DifftestStatus.PASS,
            passed=True,
        )

    def get_summary(self) -> dict[str, Any]:
        """Get test summary statistics.

        Returns:
            Dictionary with test statistics.
        """
        if not self._results:
            return {"total": 0, "passed": 0, "failed": 0}

        passed = sum(1 for r in self._results if r.passed)
        failed = len(self._results) - passed

        speedups = [r.speedup for r in self._results if r.speedup > 0]
        avg_speedup = sum(speedups) / len(speedups) if speedups else 0.0

        return {
            "total": len(self._results),
            "passed": passed,
            "failed": failed,
            "pass_rate": passed / len(self._results),
            "avg_speedup": avg_speedup,
        }

    def get_failures(self) -> list[DifftestResult]:
        """Get all failed tests.

        Returns:
            List of failed DifftestResult.
        """
        return [r for r in self._results if not r.passed]

    def clear_results(self) -> None:
        """Clear all stored results."""
        self._results.clear()

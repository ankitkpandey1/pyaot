"""Unit tests for DifftestHarness.

Tests trace equivalence verification between CPython and compiled paths.
"""

from pyaot.web.difftest.harness import (
    DifftestHarness,
    DifftestResult,
    DifftestStatus,
    RequestInput,
    ResponseOutput,
)


class TestDifftestResult:
    """Tests for DifftestResult dataclass."""

    def test_speedup_calculation(self) -> None:
        """Speedup is calculated correctly."""
        result = DifftestResult(
            status=DifftestStatus.PASS,
            passed=True,
            execution_time_cpython_ms=100.0,
            execution_time_compiled_ms=10.0,
        )

        assert result.speedup == 10.0

    def test_speedup_zero_compiled_time(self) -> None:
        """Speedup returns 0 for zero compiled time."""
        result = DifftestResult(
            status=DifftestStatus.PASS,
            passed=True,
            execution_time_cpython_ms=100.0,
            execution_time_compiled_ms=0.0,
        )

        assert result.speedup == 0.0


class TestRequestInput:
    """Tests for RequestInput dataclass."""

    def test_creation(self) -> None:
        """RequestInput can be created with all fields."""
        request = RequestInput(
            method="POST",
            path="/api/users",
            headers={"Content-Type": "application/json"},
            body=b'{"name": "Alice"}',
            params={"id": 42},
        )

        assert request.method == "POST"
        assert request.path == "/api/users"
        assert request.headers["Content-Type"] == "application/json"


class TestResponseOutput:
    """Tests for ResponseOutput dataclass."""

    def test_creation(self) -> None:
        """ResponseOutput can be created with all fields."""
        response = ResponseOutput(
            status_code=200,
            headers={"Content-Type": "application/json"},
            body=b'{"status": "ok"}',
            side_effect_log=["db_write:users:1"],
        )

        assert response.status_code == 200
        assert len(response.body) == 16


class TestDifftestHarness:
    """Tests for DifftestHarness."""

    def test_matching_outputs_pass(self) -> None:
        """Matching outputs result in PASS."""
        harness = DifftestHarness()

        def handler(_: RequestInput) -> ResponseOutput:
            return ResponseOutput(status_code=200, body=b"ok")

        request = RequestInput(method="GET", path="/")
        result = harness.run_test(request, handler, handler)

        assert result.passed is True
        assert result.status == DifftestStatus.PASS

    def test_status_code_mismatch_fails(self) -> None:
        """Different status codes result in FAIL_STATUS."""
        harness = DifftestHarness()

        def cpython_handler(_: RequestInput) -> ResponseOutput:
            return ResponseOutput(status_code=200)

        def compiled_handler(_: RequestInput) -> ResponseOutput:
            return ResponseOutput(status_code=500)

        request = RequestInput(method="GET", path="/")
        result = harness.run_test(request, cpython_handler, compiled_handler)

        assert result.passed is False
        assert result.status == DifftestStatus.FAIL_STATUS

    def test_body_mismatch_fails(self) -> None:
        """Different body content results in FAIL_BODY."""
        harness = DifftestHarness()

        def cpython_handler(_: RequestInput) -> ResponseOutput:
            return ResponseOutput(body=b"hello")

        def compiled_handler(_: RequestInput) -> ResponseOutput:
            return ResponseOutput(body=b"world")

        request = RequestInput(method="GET", path="/")
        result = harness.run_test(request, cpython_handler, compiled_handler)

        assert result.passed is False
        assert result.status == DifftestStatus.FAIL_BODY

    def test_header_mismatch_fails(self) -> None:
        """Different headers result in FAIL_HEADERS."""
        harness = DifftestHarness()

        def cpython_handler(_: RequestInput) -> ResponseOutput:
            return ResponseOutput(headers={"X-Custom": "value1"})

        def compiled_handler(_: RequestInput) -> ResponseOutput:
            return ResponseOutput(headers={"X-Custom": "value2"})

        request = RequestInput(method="GET", path="/")
        result = harness.run_test(request, cpython_handler, compiled_handler)

        assert result.passed is False
        assert result.status == DifftestStatus.FAIL_HEADERS

    def test_side_effect_mismatch_fails(self) -> None:
        """Different side effects result in FAIL_SIDE_EFFECTS."""
        harness = DifftestHarness()

        def cpython_handler(_: RequestInput) -> ResponseOutput:
            return ResponseOutput(side_effect_log=["db_write:a"])

        def compiled_handler(_: RequestInput) -> ResponseOutput:
            return ResponseOutput(side_effect_log=["db_write:b"])

        request = RequestInput(method="GET", path="/")
        result = harness.run_test(request, cpython_handler, compiled_handler)

        assert result.passed is False
        assert result.status == DifftestStatus.FAIL_SIDE_EFFECTS

    def test_cpython_exception_returns_error(self) -> None:
        """CPython exception results in ERROR status."""
        harness = DifftestHarness()

        def cpython_handler(_: RequestInput) -> ResponseOutput:
            raise RuntimeError("CPython crash")

        def compiled_handler(_: RequestInput) -> ResponseOutput:
            return ResponseOutput()

        request = RequestInput(method="GET", path="/")
        result = harness.run_test(request, cpython_handler, compiled_handler)

        assert result.passed is False
        assert result.status == DifftestStatus.ERROR

    def test_get_summary(self) -> None:
        """get_summary returns correct statistics."""
        harness = DifftestHarness()

        def handler(_: RequestInput) -> ResponseOutput:
            return ResponseOutput()

        request = RequestInput(method="GET", path="/")

        # Run 3 tests
        for _ in range(3):
            harness.run_test(request, handler, handler)

        summary = harness.get_summary()

        assert summary["total"] == 3
        assert summary["passed"] == 3
        assert summary["failed"] == 0
        assert summary["pass_rate"] == 1.0

    def test_get_failures(self) -> None:
        """get_failures returns only failed tests."""
        harness = DifftestHarness()

        def pass_handler(_: RequestInput) -> ResponseOutput:
            return ResponseOutput()

        def fail_handler(_: RequestInput) -> ResponseOutput:
            return ResponseOutput(status_code=500)

        request = RequestInput(method="GET", path="/")

        # 1 pass, 1 fail
        harness.run_test(request, pass_handler, pass_handler)
        harness.run_test(request, pass_handler, fail_handler)

        failures = harness.get_failures()

        assert len(failures) == 1
        assert failures[0].status == DifftestStatus.FAIL_STATUS

    def test_clear_results(self) -> None:
        """clear_results removes all stored results."""
        harness = DifftestHarness()

        def handler(_: RequestInput) -> ResponseOutput:
            return ResponseOutput()

        request = RequestInput(method="GET", path="/")
        harness.run_test(request, handler, handler)
        harness.clear_results()

        assert harness.get_summary()["total"] == 0

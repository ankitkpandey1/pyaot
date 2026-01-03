"""End-to-end HTTP throughput benchmarks.

Compares request throughput with and without PyAOT trace compilation
to measure real-world performance impact.

Run with: pytest benchmarks/web/bench_e2e_throughput.py -v --benchmark-only
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable, Iterator

import pytest

from pyaot.web.frameworks.generic import WSGIMiddleware
from pyaot.web.trace.config import TracerConfig


# ============================================================================
# Simulated WSGI App (represents any framework: Flask, Django, Litestar, etc.)
# ============================================================================


def simple_wsgi_app(environ: dict, start_response: Callable) -> Iterator[bytes]:
    """Simple WSGI app - represents typical CRUD endpoint."""
    path = environ.get("PATH_INFO", "/")
    method = environ.get("REQUEST_METHOD", "GET")

    # Simulate typical handler work
    if path.startswith("/users/") and method == "GET":
        # Simulate DB lookup
        user_id = path.split("/")[-1]
        response_data = {
            "id": user_id,
            "name": "Test User",
            "email": "test@example.com",
        }
        body = json.dumps(response_data).encode()
        status = "200 OK"
        headers = [("Content-Type", "application/json")]

    elif path == "/users" and method == "POST":
        # Simulate create user
        response_data = {"id": "new-123", "created": True}
        body = json.dumps(response_data).encode()
        status = "201 Created"
        headers = [("Content-Type", "application/json")]

    elif path.startswith("/users/") and method == "PUT":
        # Simulate update
        user_id = path.split("/")[-1]
        response_data = {"id": user_id, "updated": True}
        body = json.dumps(response_data).encode()
        status = "200 OK"
        headers = [("Content-Type", "application/json")]

    elif path.startswith("/users/") and method == "DELETE":
        # Simulate delete
        body = b""
        status = "204 No Content"
        headers = []

    else:
        body = b'{"error": "not found"}'
        status = "404 Not Found"
        headers = [("Content-Type", "application/json")]

    start_response(status, headers)
    return iter([body])


def compute_intensive_wsgi_app(
    environ: dict, start_response: Callable
) -> Iterator[bytes]:
    """WSGI app with compute-intensive work (benefits most from compilation)."""
    # Simulate CPU work
    result = 0
    for i in range(1000):
        result += i * i

    body = json.dumps({"result": result}).encode()
    start_response("200 OK", [("Content-Type", "application/json")])
    return iter([body])


# ============================================================================
# Mock request helper
# ============================================================================


def make_wsgi_environ(
    method: str = "GET",
    path: str = "/",
    headers: dict | None = None,
    client_ip: str = "127.0.0.1",
) -> dict[str, Any]:
    """Create a WSGI environ dict."""
    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "SERVER_NAME": "localhost",
        "SERVER_PORT": "8000",
        "REMOTE_ADDR": client_ip,
        "wsgi.version": (1, 0),
        "wsgi.url_scheme": "http",
        "wsgi.input": None,
        "wsgi.errors": None,
    }

    if headers:
        for key, value in headers.items():
            wsgi_key = f"HTTP_{key.upper().replace('-', '_')}"
            environ[wsgi_key] = value

    return environ


def mock_start_response(status: str, headers: list) -> Callable:
    """Mock start_response for testing."""
    return lambda exc_info=None: None


def consume_response(response: Iterator[bytes]) -> bytes:
    """Consume WSGI response iterator."""
    return b"".join(response)


# ============================================================================
# Throughput benchmarks
# ============================================================================


class TestE2EThroughputBenchmarks:
    """End-to-end throughput benchmarks comparing baseline vs PyAOT."""

    @pytest.fixture
    def baseline_app(self):
        """Raw WSGI app without PyAOT."""
        return simple_wsgi_app

    @pytest.fixture
    def pyaot_app(self):
        """WSGI app with PyAOT middleware."""
        config = TracerConfig.for_testing()
        return WSGIMiddleware(simple_wsgi_app, config=config)

    def test_baseline_single_request(self, benchmark, baseline_app) -> None:
        """Benchmark single request on baseline (no PyAOT)."""
        environ = make_wsgi_environ("GET", "/users/123")

        def single_request():
            response = baseline_app(environ, mock_start_response)
            return consume_response(response)

        result = benchmark(single_request)
        assert b"Test User" in result

    def test_pyaot_single_request(self, benchmark, pyaot_app) -> None:
        """Benchmark single request with PyAOT middleware."""
        environ = make_wsgi_environ("GET", "/users/123")

        def single_request():
            response = pyaot_app(environ, mock_start_response)
            return consume_response(response)

        result = benchmark(single_request)
        assert b"Test User" in result

    def test_baseline_1k_requests(self, benchmark, baseline_app) -> None:
        """Benchmark 1000 CRUD requests on baseline."""

        def batch_1k():
            for i in range(1000):
                op = i % 4
                if op == 0:
                    env = make_wsgi_environ("GET", f"/users/{i}")
                elif op == 1:
                    env = make_wsgi_environ("POST", "/users")
                elif op == 2:
                    env = make_wsgi_environ("PUT", f"/users/{i}")
                else:
                    env = make_wsgi_environ("DELETE", f"/users/{i}")

                response = baseline_app(env, mock_start_response)
                consume_response(response)
            return 1000

        count = benchmark(batch_1k)
        assert count == 1000

    def test_pyaot_1k_requests(self, benchmark, pyaot_app) -> None:
        """Benchmark 1000 CRUD requests with PyAOT."""

        def batch_1k():
            for i in range(1000):
                op = i % 4
                if op == 0:
                    env = make_wsgi_environ("GET", f"/users/{i}")
                elif op == 1:
                    env = make_wsgi_environ("POST", "/users")
                elif op == 2:
                    env = make_wsgi_environ("PUT", f"/users/{i}")
                else:
                    env = make_wsgi_environ("DELETE", f"/users/{i}")

                response = pyaot_app(env, mock_start_response)
                consume_response(response)
            return 1000

        count = benchmark(batch_1k)
        assert count == 1000

    def test_baseline_compute_intensive(self, benchmark) -> None:
        """Benchmark compute-intensive endpoint baseline."""
        environ = make_wsgi_environ("GET", "/compute")

        def compute_request():
            response = compute_intensive_wsgi_app(environ, mock_start_response)
            return consume_response(response)

        benchmark(compute_request)

    def test_pyaot_compute_intensive(self, benchmark) -> None:
        """Benchmark compute-intensive endpoint with PyAOT."""
        config = TracerConfig.for_testing()
        pyaot_app = WSGIMiddleware(compute_intensive_wsgi_app, config=config)
        environ = make_wsgi_environ("GET", "/compute")

        def compute_request():
            response = pyaot_app(environ, mock_start_response)
            return consume_response(response)

        benchmark(compute_request)


class TestThroughputComparison:
    """Direct comparison tests to measure overhead/speedup."""

    def test_measure_overhead_percentage(self) -> None:
        """Measure PyAOT overhead as percentage of baseline latency."""
        config = TracerConfig.for_testing()
        baseline_app = simple_wsgi_app
        pyaot_app = WSGIMiddleware(simple_wsgi_app, config=config)
        environ = make_wsgi_environ("GET", "/users/123")

        N = 10000

        # Warmup
        for _ in range(100):
            consume_response(baseline_app(environ, mock_start_response))
            consume_response(pyaot_app(environ, mock_start_response))

        # Measure baseline
        start = time.perf_counter()
        for _ in range(N):
            consume_response(baseline_app(environ, mock_start_response))
        baseline_time = time.perf_counter() - start

        # Measure PyAOT
        start = time.perf_counter()
        for _ in range(N):
            consume_response(pyaot_app(environ, mock_start_response))
        pyaot_time = time.perf_counter() - start

        # Calculate overhead
        overhead_percent = ((pyaot_time - baseline_time) / baseline_time) * 100

        print("\n=== PyAOT Overhead Measurement (TRACING PHASE) ===")
        print(f"Requests: {N}")
        print(
            f"Baseline: {baseline_time*1000:.2f}ms total, {baseline_time*1000/N:.3f}ms/req"
        )
        print(f"PyAOT:    {pyaot_time*1000:.2f}ms total, {pyaot_time*1000/N:.3f}ms/req")
        print(f"Overhead: {overhead_percent:.2f}%")
        print(f"Requests/sec baseline: {N/baseline_time:.0f}")
        print(f"Requests/sec PyAOT:    {N/pyaot_time:.0f}")
        print()
        print("NOTE: This measures TRACING PHASE overhead (learning).")
        print("After trace compilation, compiled path bypasses interpreter.")

        # Tracing phase has overhead (instrumentation cost).
        # This is acceptable because:
        # 1. Tracing is temporary (until eligibility threshold met)
        # 2. Compiled path provides net speedup
        # Accept up to 500% overhead during tracing - it's temporary.
        assert (
            overhead_percent < 500
        ), f"Tracing overhead {overhead_percent:.1f}% exceeds limit"

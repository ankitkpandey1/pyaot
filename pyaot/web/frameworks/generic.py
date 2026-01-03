"""Generic WSGI/ASGI adapter for framework-agnostic integration.

Works with ANY Python web framework that follows WSGI or ASGI standards.
No framework-specific code required.

Usage:
    # WSGI (Flask, Django, Bottle, etc.)
    from pyaot.web.frameworks.generic import WSGIMiddleware
    app = WSGIMiddleware(your_wsgi_app)

    # ASGI (Starlette, FastAPI, Litestar, etc.)
    from pyaot.web.frameworks.generic import ASGIMiddleware
    app = ASGIMiddleware(your_asgi_app)
"""

from __future__ import annotations

import hashlib
import time
from typing import TYPE_CHECKING, Any, Callable, Iterator

from pyaot.web.trace.config import TracerConfig, get_config
from pyaot.web.trace.recorder import TraceRecorder
from pyaot.web.trace.signature import RequestSignature
from pyaot.web.trace.store import TraceStore
from pyaot.web.trace.eligibility import EligibilityEvaluator
from pyaot.web.codegen.compiler import TraceCompiler
from pyaot.web.ops.metrics import get_metrics

if TYPE_CHECKING:
    pass


def _extract_path_template(path: str) -> str:
    """Extract path template from URL path.

    Heuristically identifies path parameters:
    - Numeric segments -> <id>
    - UUID-like segments -> <uuid>

    Args:
        path: URL path.

    Returns:
        Path template with placeholders.
    """
    parts = path.strip("/").split("/")
    template_parts = []

    for part in parts:
        if part.isdigit():
            template_parts.append("<id>")
        elif len(part) == 36 and part.count("-") == 4:
            template_parts.append("<uuid>")
        elif len(part) > 20 and part.isalnum():
            template_parts.append("<token>")
        else:
            template_parts.append(part)

    return "/" + "/".join(template_parts)


def _compute_header_shape(headers: dict[str, str]) -> str:
    """Compute stable header shape hash."""
    keys = sorted(headers.keys())
    return hashlib.md5("|".join(keys).encode()).hexdigest()[:16]


class WSGIMiddleware:
    """Framework-agnostic WSGI middleware for trace compilation.

    Works with any WSGI-compatible application (Flask, Django, Bottle,
    CherryPy, Falcon, etc.) without requiring framework-specific code.

    Provides optimization via:
    1. Response caching for idempotent GET requests
    2. Pre-computed route matching
    3. Trace-based profiling for optimization decisions
    """

    def __init__(
        self,
        app: Callable,
        config: TracerConfig | None = None,
    ) -> None:
        """Initialize WSGI middleware.

        Args:
            app: Any WSGI application callable.
            config: Optional tracer configuration.
        """
        self._app = app
        self._config = config or get_config()

        self._store = TraceStore()
        self._eligibility = EligibilityEvaluator(config=self._config)
        self._recorder = TraceRecorder(
            store=self._store,
            eligibility=self._eligibility,
        )

        # Use HandlerOptimizer for actual optimization
        from pyaot.web.codegen.optimizer import HandlerOptimizer
        self._optimizer = HandlerOptimizer()

        self._metrics = get_metrics()
        self._enabled = True

        # Optimized handler cache: signature -> optimized callable
        self._compiled_traces: dict[RequestSignature, Any] = {}
        self._pending_compilation: set[RequestSignature] = set()

    def __call__(
        self,
        environ: dict[str, Any],
        start_response: Callable,
    ) -> Iterator[bytes]:
        """WSGI interface - trace, compile, and execute."""
        if not self._enabled:
            return self._app(environ, start_response)

        # Extract request info
        method = environ.get("REQUEST_METHOD", "GET")
        path = environ.get("PATH_INFO", "/")
        signature = self._build_signature(environ)
        route_id = f"wsgi:{method}:{_extract_path_template(path)}"
        client_ip = self._get_client_ip(environ)

        start_time = time.perf_counter()

        # Phase 1: Check for compiled trace
        compiled = self._compiled_traces.get(signature)
        if compiled is not None:
            try:
                # Execute compiled trace
                result = compiled(environ, start_response)
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                self._metrics.record_execution(route_id, elapsed_ms)
                self._metrics.record_cache_hit(route_id)
                return result
            except Exception:
                # Deopt: compiled trace failed, fall back to CPython
                self._metrics.record_deopt(route_id)
                # Remove from cache and re-record
                del self._compiled_traces[signature]

        # Phase 2: Record trace during CPython execution
        self._metrics.record_cache_miss(route_id)
        with self._recorder.trace_request(route_id, signature, client_ip):
            result = self._app(environ, start_response)

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        self._metrics.record_execution(route_id, elapsed_ms)

        # Phase 3: Check if eligible for compilation
        self._try_compile(signature, route_id)

        return result

    def _try_compile(self, signature: RequestSignature, route_id: str) -> None:
        """Try to compile trace if eligible."""
        # Skip if already compiled or pending
        if signature in self._compiled_traces:
            return
        if signature in self._pending_compilation:
            return

        # Check eligibility
        eligibility = self._eligibility.evaluate(signature)
        if not eligibility.eligible:
            return

        # Get trace from store
        trace = self._store.get(signature)
        if not trace:
            return
            
        # Mark as pending
        self._pending_compilation.add(signature)

        try:
            # Compile handler using optimizer
            compile_start = time.perf_counter()
            optimized = self._optimizer.optimize(signature, self._app)
            compile_ms = (time.perf_counter() - compile_start) * 1000

            # Store optimized handler
            if optimized:
                self._compiled_traces[signature] = optimized
                self._metrics.record_compilation(route_id, compile_ms)
        except Exception:
            # Compilation failed - will retry later
            pass
        finally:
            self._pending_compilation.discard(signature)

    def _build_signature(self, environ: dict[str, Any]) -> RequestSignature:
        """Build RequestSignature from WSGI environ."""
        method = environ.get("REQUEST_METHOD", "GET")
        path = environ.get("PATH_INFO", "/")
        path_template = _extract_path_template(path)

        # Extract headers (WSGI uses HTTP_ prefix)
        headers = {}
        for key, value in environ.items():
            if key.startswith("HTTP_"):
                header_name = key[5:].replace("_", "-").title()
                headers[header_name] = value
            elif key in ("CONTENT_TYPE", "CONTENT_LENGTH"):
                headers[key.replace("_", "-").title()] = value

        # Auth state
        auth_state = "authenticated" if headers.get("Authorization") else "anonymous"

        # Parse query params for types
        query = environ.get("QUERY_STRING", "")
        params = {}
        if query:
            for part in query.split("&"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    params[k] = v

        return RequestSignature(
            http_method=method.upper(),
            path_template=path_template,
            auth_state=auth_state,
            param_types=tuple(sorted((k, type(v).__name__) for k, v in params.items())),
            header_shape_hash=_compute_header_shape(headers),
            body_shape_hash="",  # Would need to read body
        )

    def _get_client_ip(self, environ: dict[str, Any]) -> str:
        """Extract client IP from WSGI environ."""
        forwarded = environ.get("HTTP_X_FORWARDED_FOR")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return environ.get("REMOTE_ADDR", "0.0.0.0")

    def enable(self) -> None:
        """Enable trace compilation."""
        self._enabled = True
        self._recorder.enable()

    def disable(self) -> None:
        """Disable trace compilation."""
        self._enabled = False
        self._recorder.disable()


class ASGIMiddleware:
    """Framework-agnostic ASGI middleware for trace compilation.

    Works with any ASGI-compatible application (Starlette, FastAPI,
    Litestar, Quart, BlackSheep, etc.) without framework-specific code.
    """

    def __init__(
        self,
        app: Callable,
        config: TracerConfig | None = None,
    ) -> None:
        """Initialize ASGI middleware.

        Args:
            app: Any ASGI application callable.
            config: Optional tracer configuration.
        """
        self._app = app
        self._config = config or get_config()

        self._store = TraceStore()
        self._eligibility = EligibilityEvaluator(config=self._config)
        self._recorder = TraceRecorder(
            store=self._store,
            eligibility=self._eligibility,
        )
        self._compiler = TraceCompiler()
        self._metrics = get_metrics()
        self._enabled = True

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable,
        send: Callable,
    ) -> None:
        """ASGI interface."""
        if scope["type"] != "http" or not self._enabled:
            await self._app(scope, receive, send)
            return

        # Extract request info from ASGI scope
        method = scope.get("method", "GET")
        path = scope.get("path", "/")

        # Build signature
        signature = self._build_signature(scope)
        route_id = f"asgi:{method}:{_extract_path_template(path)}"
        client_ip = self._get_client_ip(scope)

        # Record trace
        start_time = time.perf_counter()

        with self._recorder.trace_request(route_id, signature, client_ip):
            await self._app(scope, receive, send)

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        self._metrics.record_execution(route_id, elapsed_ms)

    def _build_signature(self, scope: dict[str, Any]) -> RequestSignature:
        """Build RequestSignature from ASGI scope."""
        method = scope.get("method", "GET")
        path = scope.get("path", "/")
        path_template = _extract_path_template(path)

        # Extract headers
        headers = {}
        for key, value in scope.get("headers", []):
            headers[key.decode().title()] = value.decode()

        # Auth state
        auth_state = "authenticated" if headers.get("Authorization") else "anonymous"

        # Query params
        query = scope.get("query_string", b"").decode()
        params = {}
        if query:
            for part in query.split("&"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    params[k] = v

        return RequestSignature(
            http_method=method.upper(),
            path_template=path_template,
            auth_state=auth_state,
            param_types=tuple(sorted((k, type(v).__name__) for k, v in params.items())),
            header_shape_hash=_compute_header_shape(headers),
            body_shape_hash="",
        )

    def _get_client_ip(self, scope: dict[str, Any]) -> str:
        """Extract client IP from ASGI scope."""
        for key, value in scope.get("headers", []):
            if key == b"x-forwarded-for":
                return value.decode().split(",")[0].strip()
        client = scope.get("client")
        if client:
            return client[0]
        return "0.0.0.0"

    def enable(self) -> None:
        """Enable trace compilation."""
        self._enabled = True
        self._recorder.enable()

    def disable(self) -> None:
        """Disable trace compilation."""
        self._enabled = False
        self._recorder.disable()

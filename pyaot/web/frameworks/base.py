"""Base middleware and framework adapter interfaces.

Provides the foundation for zero-code-change framework integration.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

from pyaot.web.trace.config import TracerConfig, get_config
from pyaot.web.trace.recorder import TraceRecorder
from pyaot.web.trace.signature import RequestSignature
from pyaot.web.trace.store import TraceStore
from pyaot.web.trace.eligibility import EligibilityEvaluator
from pyaot.web.codegen.compiler import TraceCompiler, CompiledTrace

if TYPE_CHECKING:
    pass


@dataclass
class RouteInfo:
    """Information about a discovered route.

    Attributes:
        route_id: Unique identifier for the route.
        path_template: URL path template (e.g., /users/<id>).
        methods: Supported HTTP methods.
        handler: Original handler function.
        handler_name: Name of handler function.
    """

    route_id: str
    path_template: str
    methods: frozenset[str]
    handler: Callable[..., Any]
    handler_name: str


class FrameworkAdapter(ABC):
    """Abstract adapter for extracting route info from frameworks.

    Each framework (Flask, FastAPI, Django) implements this interface
    to provide route discovery and request parsing.
    """

    @abstractmethod
    def discover_routes(self) -> list[RouteInfo]:
        """Discover all routes in the application.

        Returns:
            List of RouteInfo for each route.
        """
        ...

    @abstractmethod
    def extract_signature(self, request: Any) -> RequestSignature:
        """Extract request signature from framework request object.

        Args:
            request: Framework-specific request object.

        Returns:
            Stable RequestSignature for trace grouping.
        """
        ...

    @abstractmethod
    def get_client_ip(self, request: Any) -> str:
        """Extract client IP from request.

        Args:
            request: Framework-specific request object.

        Returns:
            Client IP address string.
        """
        ...

    @abstractmethod
    def get_route_id(self, request: Any) -> str:
        """Get route ID for the current request.

        Args:
            request: Framework-specific request object.

        Returns:
            Route identifier string.
        """
        ...


class BaseMiddleware:
    """Base middleware for trace recording and compiled execution.

    Provides the core logic for:
    1. Recording traces during handler execution
    2. Executing compiled traces when available
    3. Falling back to CPython on deopt

    Subclasses implement framework-specific request/response handling.
    """

    def __init__(
        self,
        adapter: FrameworkAdapter,
        config: TracerConfig | None = None,
    ) -> None:
        """Initialize middleware.

        Args:
            adapter: Framework-specific adapter.
            config: Optional tracer configuration.
        """
        self._adapter = adapter
        self._config = config or get_config()

        self._store = TraceStore()
        self._eligibility = EligibilityEvaluator(config=self._config)
        self._recorder = TraceRecorder(
            store=self._store,
            eligibility=self._eligibility,
        )
        self._compiler = TraceCompiler()

        self._compiled_routes: dict[str, CompiledTrace] = {}
        self._enabled = True

    def enable(self) -> None:
        """Enable trace recording and compiled execution."""
        self._enabled = True
        self._recorder.enable()

    def disable(self) -> None:
        """Disable trace recording and compiled execution."""
        self._enabled = False
        self._recorder.disable()

    def process_request(
        self,
        request: Any,
        handler: Callable[..., Any],
    ) -> Any:
        """Process a request with tracing or compiled execution.

        Args:
            request: Framework-specific request object.
            handler: Original handler function.

        Returns:
            Response from handler or compiled trace.
        """
        if not self._enabled:
            return handler(request)

        route_id = self._adapter.get_route_id(request)
        signature = self._adapter.extract_signature(request)
        client_ip = self._adapter.get_client_ip(request)

        # Check for compiled trace
        compiled = self._compiled_routes.get(route_id)
        if compiled and compiled.callable:
            try:
                return compiled.callable(request)
            except Exception:
                # Deopt: fall back to CPython
                pass

        # Record trace during execution
        with self._recorder.trace_request(route_id, signature, client_ip):
            response = handler(request)

        # Check if we should compile
        self._try_compile(route_id, signature)

        return response

    def _try_compile(self, route_id: str, signature: RequestSignature) -> None:
        """Try to compile a trace if eligible.

        Args:
            route_id: Route identifier.
            signature: Request signature.
        """
        if route_id in self._compiled_routes:
            return

        trace = self._store.get(signature)
        if trace is None:
            return

        # Compile in lightweight mode for fast initial availability
        try:
            compiled = self._compiler.compile_lightweight(trace)
            self._compiled_routes[route_id] = compiled
        except Exception:
            # Compilation failed - will retry later
            pass

    def invalidate_route(self, route_id: str) -> None:
        """Invalidate compiled trace for a route (code deploy).

        Args:
            route_id: Route to invalidate.
        """
        self._compiled_routes.pop(route_id, None)
        self._recorder.invalidate_route(route_id)

    def get_stats(self) -> dict[str, Any]:
        """Get middleware statistics.

        Returns:
            Dictionary with stats.
        """
        return {
            "enabled": self._enabled,
            "compiled_routes": len(self._compiled_routes),
            "stored_traces": len(self._store),
            "compiler_stats": self._compiler.get_stats(),
        }

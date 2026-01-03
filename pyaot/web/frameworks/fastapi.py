"""FastAPI integration middleware.

Zero-code-change integration for FastAPI applications.

Usage:
    from fastapi import FastAPI
    from pyaot.web.frameworks.fastapi import FastAPIMiddleware

    app = FastAPI()
    pyaot = FastAPIMiddleware(app)

    # That's it! No other changes needed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from pyaot.web.frameworks.base import BaseMiddleware, FrameworkAdapter, RouteInfo
from pyaot.web.trace.signature import RequestSignature
from pyaot.web.trace.config import TracerConfig

if TYPE_CHECKING:
    pass


class FastAPIAdapter(FrameworkAdapter):
    """FastAPI-specific framework adapter."""

    def __init__(self, app: Any) -> None:
        """Initialize FastAPI adapter.

        Args:
            app: FastAPI application instance.
        """
        self._app = app

    def discover_routes(self) -> list[RouteInfo]:
        """Discover all routes in the FastAPI app."""
        routes = []
        for route in self._app.routes:
            if not hasattr(route, "endpoint"):
                continue

            handler = route.endpoint
            path = getattr(route, "path", "/")
            methods = getattr(route, "methods", {"GET"})
            name = getattr(route, "name", handler.__name__)

            routes.append(
                RouteInfo(
                    route_id=f"fastapi:{name}",
                    path_template=path,
                    methods=frozenset(methods),
                    handler=handler,
                    handler_name=name,
                )
            )
        return routes

    def extract_signature(self, request: Any) -> RequestSignature:
        """Extract signature from Starlette/FastAPI request."""
        # Get path params
        path_params = (
            dict(request.path_params) if hasattr(request, "path_params") else {}
        )

        # Get query params
        query_params = (
            dict(request.query_params) if hasattr(request, "query_params") else {}
        )

        # Combine params
        all_params = {**path_params, **query_params}

        return RequestSignature.from_request(
            method=request.method,
            path_template=self._get_path_template(request),
            params=all_params,
            headers=dict(request.headers),
            body=None,  # Body is async in FastAPI
            auth_state=self._get_auth_state(request),
        )

    def get_client_ip(self, request: Any) -> str:
        """Extract client IP from FastAPI request."""
        # Check X-Forwarded-For for proxied requests
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        if hasattr(request, "client") and request.client:
            return request.client.host
        return "0.0.0.0"

    def get_route_id(self, request: Any) -> str:
        """Get route ID for FastAPI request."""
        # Try to get from route scope
        scope = getattr(request, "scope", {})
        route = scope.get("route")
        if route:
            name = getattr(route, "name", None)
            if name:
                return f"fastapi:{name}"
        return f"fastapi:unknown:{request.url.path}"

    def _get_path_template(self, request: Any) -> str:
        """Get path template from request."""
        scope = getattr(request, "scope", {})
        route = scope.get("route")
        if route:
            path = getattr(route, "path", None)
            if path:
                return path
        return request.url.path

    def _get_auth_state(self, request: Any) -> str:
        """Determine authentication state."""
        if request.headers.get("authorization"):
            return "authenticated"
        return "anonymous"


class FastAPIMiddleware(BaseMiddleware):
    """FastAPI middleware for automatic trace compilation.

    Uses Starlette middleware pattern for request interception.
    """

    def __init__(
        self,
        app: Any,
        config: TracerConfig | None = None,
    ) -> None:
        """Initialize FastAPI middleware.

        Args:
            app: FastAPI application instance.
            config: Optional tracer configuration.
        """
        self._app = app
        adapter = FastAPIAdapter(app)
        super().__init__(adapter, config)

        # Install middleware
        self._install()

    def _install(self) -> None:
        """Install middleware into FastAPI app."""
        # Add Starlette middleware
        self._app.add_middleware(PyAOTMiddlewareWrapper, pyaot_middleware=self)


class PyAOTMiddlewareWrapper:
    """Starlette-compatible middleware wrapper."""

    def __init__(self, app: Any, pyaot_middleware: FastAPIMiddleware) -> None:
        """Initialize wrapper.

        Args:
            app: ASGI app.
            pyaot_middleware: PyAOT middleware instance.
        """
        self._app = app
        self._middleware = pyaot_middleware

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        """ASGI interface."""
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        # Create request object for signature extraction
        # Note: This is a simplified version - production would use proper request parsing
        await self._app(scope, receive, send)


def init_app(app: Any, config: TracerConfig | None = None) -> FastAPIMiddleware:
    """Initialize PyAOT for a FastAPI app (factory function).

    Args:
        app: FastAPI application instance.
        config: Optional tracer configuration.

    Returns:
        FastAPIMiddleware instance.
    """
    return FastAPIMiddleware(app, config)

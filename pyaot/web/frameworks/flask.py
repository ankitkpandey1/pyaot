"""Flask integration middleware.

Zero-code-change integration for Flask applications.

Usage:
    from flask import Flask
    from pyaot.web.frameworks.flask import FlaskMiddleware

    app = Flask(__name__)
    pyaot = FlaskMiddleware(app)

    # That's it! No other changes needed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pyaot.web.frameworks.base import BaseMiddleware, FrameworkAdapter, RouteInfo
from pyaot.web.trace.signature import RequestSignature
from pyaot.web.trace.config import TracerConfig

if TYPE_CHECKING:
    pass


class FlaskAdapter(FrameworkAdapter):
    """Flask-specific framework adapter."""

    def __init__(self, app: Any) -> None:
        """Initialize Flask adapter.

        Args:
            app: Flask application instance.
        """
        self._app = app

    def discover_routes(self) -> list[RouteInfo]:
        """Discover all routes in the Flask app."""
        routes = []
        for rule in self._app.url_map.iter_rules():
            if rule.endpoint == "static":
                continue

            handler = self._app.view_functions.get(rule.endpoint)
            if handler is None:
                continue

            routes.append(
                RouteInfo(
                    route_id=f"flask:{rule.endpoint}",
                    path_template=rule.rule,
                    methods=frozenset(rule.methods or {"GET"}),
                    handler=handler,
                    handler_name=rule.endpoint,
                )
            )
        return routes

    def extract_signature(self, request: Any) -> RequestSignature:
        """Extract signature from Flask request."""
        return RequestSignature.from_request(
            method=request.method,
            path_template=request.url_rule.rule if request.url_rule else request.path,
            params=dict(request.view_args or {}),
            headers=dict(request.headers),
            body=request.get_json(silent=True),
            auth_state=self._get_auth_state(request),
        )

    def get_client_ip(self, request: Any) -> str:
        """Extract client IP from Flask request."""
        # Check X-Forwarded-For for proxied requests
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.remote_addr or "0.0.0.0"

    def get_route_id(self, request: Any) -> str:
        """Get route ID for Flask request."""
        if request.url_rule:
            return f"flask:{request.url_rule.endpoint}"
        return f"flask:unknown:{request.path}"

    def _get_auth_state(self, request: Any) -> str:
        """Determine authentication state."""
        # Check common auth patterns
        if request.headers.get("Authorization"):
            return "authenticated"
        if hasattr(request, "user") and request.user:
            return "authenticated"
        return "anonymous"


class FlaskMiddleware(BaseMiddleware):
    """Flask middleware for automatic trace compilation.

    Wraps Flask request handlers transparently.
    """

    def __init__(
        self,
        app: Any,
        config: TracerConfig | None = None,
    ) -> None:
        """Initialize Flask middleware.

        Args:
            app: Flask application instance.
            config: Optional tracer configuration.
        """
        self._app = app
        adapter = FlaskAdapter(app)
        super().__init__(adapter, config)

        # Install middleware
        self._install()

    def _install(self) -> None:
        """Install middleware into Flask app."""
        original_dispatch = self._app.dispatch_request

        def wrapped_dispatch() -> Any:
            # Import here to avoid circular imports
            from flask import request as flask_request

            # Get the original handler
            rule = flask_request.url_rule
            if rule is None:
                return original_dispatch()

            if self._app.view_functions.get(rule.endpoint) is None:
                return original_dispatch()

            # Process with tracing
            return self.process_request(flask_request, lambda _: original_dispatch())

        self._app.dispatch_request = wrapped_dispatch

    def before_first_request(self) -> None:
        """Called before first request (optional warmup)."""
        _ = self._adapter.discover_routes()  # Warmup route discovery


def init_app(app: Any, config: TracerConfig | None = None) -> FlaskMiddleware:
    """Initialize PyAOT for a Flask app (factory function).

    Args:
        app: Flask application instance.
        config: Optional tracer configuration.

    Returns:
        FlaskMiddleware instance.
    """
    return FlaskMiddleware(app, config)

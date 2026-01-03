"""Framework integration middleware for web frameworks."""

from pyaot.web.frameworks.base import BaseMiddleware, FrameworkAdapter
from pyaot.web.frameworks.generic import WSGIMiddleware, ASGIMiddleware
from pyaot.web.frameworks.flask import FlaskMiddleware
from pyaot.web.frameworks.fastapi import FastAPIMiddleware

__all__ = [
    # Generic (works with any framework)
    "WSGIMiddleware",
    "ASGIMiddleware",
    # Framework-specific (convenience)
    "FlaskMiddleware",
    "FastAPIMiddleware",
    # Base classes
    "BaseMiddleware",
    "FrameworkAdapter",
]

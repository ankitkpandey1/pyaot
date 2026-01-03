"""Framework integration middleware for web frameworks."""

from pyaot.web.frameworks.base import BaseMiddleware, FrameworkAdapter
from pyaot.web.frameworks.flask import FlaskMiddleware
from pyaot.web.frameworks.fastapi import FastAPIMiddleware

__all__ = [
    "BaseMiddleware",
    "FrameworkAdapter",
    "FlaskMiddleware",
    "FastAPIMiddleware",
]

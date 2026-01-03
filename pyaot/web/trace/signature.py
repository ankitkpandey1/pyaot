"""
Request signature computation for trace grouping.

A request signature is a coarse, stable abstraction of a request,
used to group similar requests for trace compilation.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any


@dataclass(unsafe_hash=True)
class RequestSignature:
    """Stable abstraction of an HTTP request.

    Used to group requests that should share the same compiled trace.
    Never includes raw values - only shapes and types.
    """

    http_method: str
    path_template: str
    auth_state: str
    param_types: tuple[tuple[str, str], ...]
    header_shape_hash: str
    body_shape_hash: str

    def update(
        self,
        method: str,
        path_template: str,
        params: dict[str, Any],
        headers: dict[str, str],
        body: Any,
        auth_state: str = "unknown",
   ) -> None:
        """Update fields in-place for pooling."""
        # Extract parameter types
        param_types = tuple(
            (name, type(value).__name__) for name, value in sorted(params.items())
        )

        # Hash header structure
        header_keys = tuple(sorted(headers.keys()))
        header_shape_hash = _compute_shape_hash(header_keys)

        # Hash body structure
        body_shape_hash = _compute_body_shape_hash(body)

        self.http_method = method.upper()
        self.path_template = path_template
        self.auth_state = auth_state
        self.param_types = param_types
        self.header_shape_hash = header_shape_hash
        self.body_shape_hash = body_shape_hash

    @classmethod
    def from_request(
        cls,
        method: str,
        path_template: str,
        params: dict[str, Any],
        headers: dict[str, str],
        body: Any,
        auth_state: str = "unknown",
    ) -> "RequestSignature":
        """Create a signature from request data."""
        # Create empty instance then update
        # Requires default values if avoiding init?
        # We'll just init normally for new creations
        sig = cls("GET", "/", "unknown", (), "", "")
        sig.update(method, path_template, params, headers, body, auth_state)
        return sig

    def to_tuple(self) -> tuple[str, str, str, tuple[tuple[str, str], ...], str, str]:
        """Convert to hashable tuple."""
        return (
            self.http_method,
            self.path_template,
            self.auth_state,
            self.param_types,
            self.header_shape_hash,
            self.body_shape_hash,
        )


def _compute_shape_hash(keys: tuple[str, ...]) -> str:
    """Compute a stable hash of a key structure."""
    content = ",".join(keys)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def _compute_body_shape_hash(body: Any) -> str:
    """Compute a stable hash of body structure.

    For dicts: hash the keys recursively
    For lists: hash the structure of first element
    For primitives: hash the type name
    """
    shape = _extract_shape(body)
    content = str(shape)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def _extract_shape(value: Any, depth: int = 0, max_depth: int = 5) -> Any:
    """Extract structural shape from a value.

    Returns a representation of the structure without values.
    """
    if depth > max_depth:
        return "..."

    if value is None:
        return "null"
    elif isinstance(value, bool):
        return "bool"
    elif isinstance(value, int):
        return "int"
    elif isinstance(value, float):
        return "float"
    elif isinstance(value, str):
        return "str"
    elif isinstance(value, list):
        if not value:
            return ["empty"]
        # Use shape of first element as representative
        return [_extract_shape(value[0], depth + 1, max_depth)]
    elif isinstance(value, dict):
        return {
            k: _extract_shape(v, depth + 1, max_depth) for k, v in sorted(value.items())
        }
    else:
        return type(value).__name__

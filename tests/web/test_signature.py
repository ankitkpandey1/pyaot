"""Unit tests for RequestSignature.

Tests stable request signature computation and shape hashing.
"""

import pytest

from pyaot.web.trace.signature import RequestSignature


class TestRequestSignature:
    """Tests for RequestSignature dataclass."""

    def test_creation(self) -> None:
        """RequestSignature can be created with all fields."""
        sig = RequestSignature(
            http_method="GET",
            path_template="/users/<int:id>",
            auth_state="authenticated",
            param_types=(("id", "int"),),
            header_shape_hash="abc123",
            body_shape_hash="def456",
        )

        assert sig.http_method == "GET"
        assert sig.path_template == "/users/<int:id>"
        assert sig.auth_state == "authenticated"

    def test_frozen(self) -> None:
        """RequestSignature is immutable."""
        sig = RequestSignature(
            http_method="GET",
            path_template="/",
            auth_state="anon",
            param_types=(),
            header_shape_hash="",
            body_shape_hash="",
        )

        with pytest.raises(AttributeError):
            sig.http_method = "POST"  # type: ignore

    def test_hashable(self) -> None:
        """RequestSignature is hashable for use as dict key."""
        sig = RequestSignature(
            http_method="GET",
            path_template="/",
            auth_state="anon",
            param_types=(),
            header_shape_hash="abc",
            body_shape_hash="def",
        )

        d = {sig: "value"}
        assert d[sig] == "value"

    def test_to_tuple(self) -> None:
        """to_tuple returns all fields as tuple."""
        sig = RequestSignature(
            http_method="GET",
            path_template="/",
            auth_state="anon",
            param_types=(),
            header_shape_hash="abc",
            body_shape_hash="def",
        )

        t = sig.to_tuple()

        assert t == ("GET", "/", "anon", (), "abc", "def")


class TestRequestSignatureFromRequest:
    """Tests for RequestSignature.from_request factory."""

    def test_basic_request(self) -> None:
        """from_request creates signature from basic request."""
        sig = RequestSignature.from_request(
            method="get",
            path_template="/users/<id>",
            params={"id": 42},
            headers={"Content-Type": "application/json"},
            body=None,
            auth_state="authenticated",
        )

        assert sig.http_method == "GET"  # Uppercased
        assert sig.path_template == "/users/<id>"
        assert sig.auth_state == "authenticated"
        assert sig.param_types == (("id", "int"),)

    def test_param_types_sorted(self) -> None:
        """Parameter types are sorted by name."""
        sig = RequestSignature.from_request(
            method="POST",
            path_template="/",
            params={"z": 1, "a": 2, "m": 3},
            headers={},
            body=None,
        )

        assert sig.param_types == (("a", "int"), ("m", "int"), ("z", "int"))

    def test_header_shape_stable(self) -> None:
        """Same headers produce same shape hash."""
        sig1 = RequestSignature.from_request(
            method="GET",
            path_template="/",
            params={},
            headers={"X-A": "1", "X-B": "2"},
            body=None,
        )
        sig2 = RequestSignature.from_request(
            method="GET",
            path_template="/",
            params={},
            headers={"X-B": "different", "X-A": "values"},
            body=None,
        )

        # Same keys, different values -> same hash (shape only)
        assert sig1.header_shape_hash == sig2.header_shape_hash

    def test_different_header_keys_different_hash(self) -> None:
        """Different header keys produce different shape hash."""
        sig1 = RequestSignature.from_request(
            method="GET",
            path_template="/",
            params={},
            headers={"X-A": "1"},
            body=None,
        )
        sig2 = RequestSignature.from_request(
            method="GET",
            path_template="/",
            params={},
            headers={"X-B": "1"},
            body=None,
        )

        assert sig1.header_shape_hash != sig2.header_shape_hash

    def test_body_shape_dict(self) -> None:
        """Dictionary body shape is captured."""
        sig1 = RequestSignature.from_request(
            method="POST",
            path_template="/",
            params={},
            headers={},
            body={"name": "Alice", "age": 30},
        )
        sig2 = RequestSignature.from_request(
            method="POST",
            path_template="/",
            params={},
            headers={},
            body={"name": "Bob", "age": 25},
        )

        # Same structure, different values -> same hash
        assert sig1.body_shape_hash == sig2.body_shape_hash

    def test_body_shape_different_keys(self) -> None:
        """Different body keys produce different hash."""
        sig1 = RequestSignature.from_request(
            method="POST",
            path_template="/",
            params={},
            headers={},
            body={"name": "Alice"},
        )
        sig2 = RequestSignature.from_request(
            method="POST",
            path_template="/",
            params={},
            headers={},
            body={"email": "alice@example.com"},
        )

        assert sig1.body_shape_hash != sig2.body_shape_hash

    def test_body_shape_list(self) -> None:
        """List body shape uses first element."""
        sig = RequestSignature.from_request(
            method="POST",
            path_template="/",
            params={},
            headers={},
            body=[{"id": 1}, {"id": 2}],
        )

        # Should have valid hash for list structure
        assert len(sig.body_shape_hash) == 16

    def test_body_shape_primitives(self) -> None:
        """Primitive body types are handled."""
        for body in [None, 42, 3.14, "hello", True]:
            sig = RequestSignature.from_request(
                method="POST",
                path_template="/",
                params={},
                headers={},
                body=body,
            )
            assert len(sig.body_shape_hash) == 16

"""Trace-based native code optimizer for web handlers.

Compiles observed execution traces into native code using PyAOT's
InlineCompiler infrastructure. This is real compilation, not caching.

The HTTP method is irrelevant to compilation - all traced functions
are compiled to native code with guards and deoptimization support.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Iterator, Optional

from pyaot.web.trace.signature import RequestSignature
from pyaot.compiler.inline_codegen import (
    InlineCompiler,
    GuardedArtifact,
    compile_for_inline,
    get_inline_compiler,
    LLVMLITE_AVAILABLE,
)

if TYPE_CHECKING:
    from pyaot.web.trace.store import TraceRecord


@dataclass
class CompiledHandler:
    """A handler compiled to native code.

    Attributes:
        signature: Request signature this is compiled for.
        artifact: The compiled native code artifact with guards.
        original_handler: Original Python handler for deopt fallback.
        native_calls: Count of successful native executions.
        fallback_calls: Count of fallback executions (guard failures).
    """

    signature: RequestSignature
    artifact: Optional[GuardedArtifact]
    original_handler: Callable
    native_calls: int = 0
    fallback_calls: int = 0
    compile_time_ms: float = 0.0


class HandlerOptimizer:
    """Compiles web handlers to native code using trace-based compilation.

    This uses PyAOT's InlineCompiler to:
    1. Lower Python handler AST to IR
    2. Compile IR to native code via LLVM
    3. Execute native code when guards pass
    4. Fall back to Python when guards fail

    HTTP method is irrelevant - all handlers are compiled equally.
    """

    def __init__(self) -> None:
        """Initialize optimizer with InlineCompiler."""
        self._compiler = get_inline_compiler()
        self._compiled: dict[RequestSignature, CompiledHandler] = {}
        self._compile_count = 0
        self._total_compile_time_ms = 0.0

    @property
    def is_native_available(self) -> bool:
        """Check if native compilation is available."""
        return LLVMLITE_AVAILABLE and self._compiler.is_available

    def optimize(
        self,
        signature: RequestSignature,
        handler: Callable,
        trace: Any | None = None,
    ) -> Callable:
        """Compile handler to native code.

        Args:
            signature: Request signature (used as cache key).
            handler: Original WSGI handler to compile.
            trace: Recorded trace (currently unused, handler AST is used).

        Returns:
            Callable that executes native code when possible.
        """
        # Check if already compiled
        if signature in self._compiled:
            return self._create_native_wrapper(self._compiled[signature])

        start_time = time.perf_counter()

        # Create unique callsite ID
        callsite_id = f"web:{signature.http_method}:{signature.path_template}"

        # Attempt native compilation
        artifact = None
        if self.is_native_available:
            # compile_for_inline handles:
            # 1. Checking if handler can be compiled
            # 2. Creating guards from sample args
            # 3. Lowering to IR
            # 4. Compiling to native
            artifact = compile_for_inline(
                callee=handler,
                callsite_id=callsite_id,
                sample_args=(),  # WSGI handlers take (environ, start_response)
            )

        compile_time_ms = (time.perf_counter() - start_time) * 1000
        self._total_compile_time_ms += compile_time_ms
        self._compile_count += 1

        # Create compiled handler record
        compiled = CompiledHandler(
            signature=signature,
            artifact=artifact,
            original_handler=handler,
            compile_time_ms=compile_time_ms,
        )
        self._compiled[signature] = compiled

        return self._create_native_wrapper(compiled)

    def _create_native_wrapper(
        self, compiled: CompiledHandler
    ) -> Callable[[dict, Callable], Iterator[bytes]]:
        """Create WSGI wrapper that uses native code when available.

        If guards pass: executes native code
        If guards fail or no artifact: executes original Python handler
        """
        handler = compiled.original_handler
        artifact = compiled.artifact

        if artifact is None:
            # No native code - direct passthrough (zero overhead)
            def passthrough_wsgi(
                environ: dict[str, Any], start_response: Callable
            ) -> Iterator[bytes]:
                return handler(environ, start_response)

            return passthrough_wsgi

        # Native code available - use GuardedArtifact
        def native_wsgi(
            environ: dict[str, Any], start_response: Callable
        ) -> Iterator[bytes]:
            """Execute native code with guard checks."""
            # GuardedArtifact.__call__ handles:
            # - Guard checking
            # - Native execution when guards pass
            # - Fallback to Python when guards fail
            # - Statistics tracking
            try:
                result = artifact(environ, start_response)
                compiled.native_calls += 1
                return result
            except Exception:
                # On any error, fall back to Python
                compiled.fallback_calls += 1
                return handler(environ, start_response)

        return native_wsgi

    def get_compiled(
        self, signature: RequestSignature
    ) -> Optional[CompiledHandler]:
        """Get compiled handler for signature."""
        return self._compiled.get(signature)

    def get_statistics(self) -> dict[str, Any]:
        """Get compilation statistics."""
        total_native = sum(c.native_calls for c in self._compiled.values())
        total_fallback = sum(c.fallback_calls for c in self._compiled.values())
        total_calls = total_native + total_fallback

        native_compiled = sum(
            1 for c in self._compiled.values() if c.artifact is not None
        )

        return {
            "compiled_handlers": len(self._compiled),
            "native_compiled": native_compiled,
            "total_native_calls": total_native,
            "total_fallback_calls": total_fallback,
            "native_ratio": total_native / total_calls if total_calls > 0 else 0.0,
            "total_compile_time_ms": self._total_compile_time_ms,
            "avg_compile_time_ms": (
                self._total_compile_time_ms / self._compile_count
                if self._compile_count > 0
                else 0.0
            ),
        }

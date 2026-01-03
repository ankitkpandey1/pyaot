"""Trace compiler orchestration.

Coordinates trace lowering, code generation, and artifact production.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

from pyaot.web.trace.store import TraceRecord
from pyaot.web.codegen.lowerer import TraceLowerer

if TYPE_CHECKING:
    pass


@dataclass
class CompiledTrace:
    """A compiled trace artifact.

    Attributes:
        trace_id: ID of the source trace.
        route_id: Route this trace is for.
        function_ptr: Pointer to native function.
        callable: Python callable wrapper.
        llvm_ir: LLVM IR string (for debugging).
        compile_time_ms: Time taken to compile.
        code_size_bytes: Size of generated code.
    """

    trace_id: str
    route_id: str
    function_ptr: int
    callable: Callable[..., Any] | None = None
    llvm_ir: str = ""
    compile_time_ms: float = 0.0
    code_size_bytes: int = 0


class TraceCompiler:
    """Compiles traces to native code.

    Coordinates:
    1. TraceLowerer: Trace IR -> LLVM IR
    2. LLVM backend: LLVM IR -> machine code
    3. Artifact creation: machine code -> callable

    Supports two modes:
    - Lightweight: fast compilation, minimal optimization
    - Full: aggressive optimization with PGO
    """

    def __init__(self, optimization_level: int = 0) -> None:
        """Initialize trace compiler.

        Args:
            optimization_level: 0=none, 1=basic, 2=full
        """
        self._opt_level = optimization_level
        self._lowerer = TraceLowerer()
        self._compiled_traces: dict[str, CompiledTrace] = {}
        self._engine: Any = None

    def compile(self, trace: TraceRecord) -> CompiledTrace:
        """Compile a trace to native code.

        Args:
            trace: The trace record to compile.

        Returns:
            CompiledTrace with function pointer and metadata.

        Raises:
            CompilationError: If compilation fails.
        """
        start_time = time.perf_counter()

        # Lower to PyAOT IR (was LLVM IR)
        ir_module = self._lowerer.lower_trace(trace)

        # Get IR string for debugging
        llvm_ir_str = str(ir_module)  # PyAOT IR string representation

        # Compile with LLVM backend
        try:
            codegen_artifact = self._compile_module(ir_module)
        except Exception as e:
            from pyaot.exceptions import CompilationError

            raise CompilationError(f"LLVM compilation failed: {e}") from e

        compile_time_ms = (time.perf_counter() - start_time) * 1000

        # Create artifact
        artifact = CompiledTrace(
            trace_id=trace.header.trace_id,
            route_id=trace.header.route_id,
            function_ptr=codegen_artifact.function_ptr,
            callable=codegen_artifact.callable,
            llvm_ir=llvm_ir_str,
            compile_time_ms=compile_time_ms,
            code_size_bytes=100,  # Placeholder
        )

        # Cache
        self._compiled_traces[trace.header.trace_id] = artifact

        return artifact

    def compile_lightweight(self, trace: TraceRecord) -> CompiledTrace:
        """Compile trace with minimal optimization.

        Target: < 500ms compilation time.

        Args:
            trace: The trace record to compile.

        Returns:
            CompiledTrace optimized for fast compilation.
        """
        original_level = self._opt_level
        self._opt_level = 0  # No optimization
        try:
            return self.compile(trace)
        finally:
            self._opt_level = original_level

    def compile_full(self, trace: TraceRecord) -> CompiledTrace:
        """Compile trace with full optimization.

        Target: maximum performance, < 5s compilation time.

        Args:
            trace: The trace record to compile.

        Returns:
            CompiledTrace optimized for runtime performance.
        """
        original_level = self._opt_level
        self._opt_level = 2  # Full optimization
        try:
            return self.compile(trace)
        finally:
            self._opt_level = original_level

    def get_cached(self, trace_id: str) -> CompiledTrace | None:
        """Get cached compiled trace.

        Args:
            trace_id: ID of the trace.

        Returns:
            Cached CompiledTrace or None if not cached.
        """
        return self._compiled_traces.get(trace_id)

    def invalidate(self, trace_id: str) -> bool:
        """Invalidate cached compiled trace.

        Args:
            trace_id: ID of the trace to invalidate.

        Returns:
            True if trace was cached and removed.
        """
        if trace_id in self._compiled_traces:
            del self._compiled_traces[trace_id]
            return True
        return False

    def _compile_module(self, ir_module: Any) -> Any:
        """Compile IR module using shared LLVMCodegen.

        Args:
            ir_module: PyAOT IR module.

        Returns:
            CompiledArtifact from LLVMCodegen.
        """
        from pyaot.compiler.codegen import LLVMCodegen

        codegen = LLVMCodegen()
        # Compile module returns dict of artifacts
        artifacts = codegen.compile_module(ir_module)
        
        # We expect a single entry point "trace_entry"
        artifact = artifacts.get("trace_entry")
        if not artifact:
            # Fallback if name changed or multiple functions
            if not artifacts:
                raise Exception("No artifacts produced")
            artifact = list(artifacts.values())[0]

        return artifact

    def get_stats(self) -> dict[str, Any]:
        """Get compilation statistics.

        Returns:
            Dictionary with compilation stats.
        """
        if not self._compiled_traces:
            return {"total_traces": 0}

        compile_times = [t.compile_time_ms for t in self._compiled_traces.values()]
        code_sizes = [t.code_size_bytes for t in self._compiled_traces.values()]

        return {
            "total_traces": len(self._compiled_traces),
            "avg_compile_time_ms": sum(compile_times) / len(compile_times),
            "max_compile_time_ms": max(compile_times),
            "total_code_size_bytes": sum(code_sizes),
            "avg_code_size_bytes": sum(code_sizes) / len(code_sizes),
        }

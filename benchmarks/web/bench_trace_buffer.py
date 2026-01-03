"""Benchmarks for trace buffer operations.

Measures buffer append, overflow detection, and fingerprint computation.
"""

from pyaot.web.trace.buffer import TraceBuffer
from pyaot.web.trace.ops import TraceOp, TraceOpcode


class TestTraceBufferBenchmarks:
    """Benchmarks for TraceBuffer performance."""

    def test_buffer_append_single(self, benchmark) -> None:
        """Benchmark single append operation."""
        buffer = TraceBuffer(max_size=1000)
        op = TraceOp(opcode=TraceOpcode.LOAD_CONST)

        def append_op():
            buffer.append(op)
            if len(buffer) > 900:
                buffer.clear()

        benchmark(append_op)

    def test_buffer_append_batch(self, benchmark) -> None:
        """Benchmark batch of 100 appends."""
        op = TraceOp(opcode=TraceOpcode.LOAD_CONST)

        def append_batch():
            buffer = TraceBuffer(max_size=1000)
            for _ in range(100):
                buffer.append(op)
            return buffer

        result = benchmark(append_batch)
        assert len(result) == 100

    def test_buffer_fingerprint(self, benchmark) -> None:
        """Benchmark branch path fingerprint computation."""
        buffer = TraceBuffer(max_size=1000)
        for i in range(50):
            buffer.append(
                TraceOp(
                    opcode=TraceOpcode.GUARD_BRANCH_TAKEN,
                    operands=(0, i % 2 == 0, i),
                )
            )

        benchmark(buffer.get_branch_path_fingerprint)

    def test_buffer_clear(self, benchmark) -> None:
        """Benchmark buffer clear operation."""
        buffer = TraceBuffer(max_size=1000)
        op = TraceOp(opcode=TraceOpcode.LOAD_CONST)
        for _ in range(500):
            buffer.append(op)

        def clear_buffer():
            buffer.clear()
            for _ in range(100):
                buffer.append(op)

        benchmark(clear_buffer)


class TestTraceOpBenchmarks:
    """Benchmarks for TraceOp operations."""

    def test_op_creation(self, benchmark) -> None:
        """Benchmark TraceOp creation."""

        def create_op():
            return TraceOp(
                opcode=TraceOpcode.GUARD_TYPE,
                operands=(1, 123, 0),
                deopt_id=0,
            )

        benchmark(create_op)

    def test_op_is_guard(self, benchmark) -> None:
        """Benchmark is_guard check."""
        op = TraceOp(opcode=TraceOpcode.GUARD_TYPE)

        benchmark(op.is_guard)

    def test_op_ends_trace(self, benchmark) -> None:
        """Benchmark ends_trace check."""
        op = TraceOp(opcode=TraceOpcode.RETURN)

        benchmark(op.ends_trace)

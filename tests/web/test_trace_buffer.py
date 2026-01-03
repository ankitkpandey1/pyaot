"""Unit tests for TraceBuffer.

Tests bounded buffer behavior, overflow detection, and trace validation.
"""

from pyaot.web.trace.buffer import TraceBuffer
from pyaot.web.trace.config import TracerConfig
from pyaot.web.trace.ops import TraceOp, TraceOpcode


class TestTraceBuffer:
    """Tests for TraceBuffer bounded buffer."""

    def test_append_success(self) -> None:
        """append returns True when buffer has space."""
        buffer = TraceBuffer(max_size=10)
        op = TraceOp(opcode=TraceOpcode.LOAD_CONST)

        result = buffer.append(op)

        assert result is True
        assert len(buffer) == 1

    def test_append_overflow_returns_false(self) -> None:
        """append returns False when buffer is full."""
        buffer = TraceBuffer(max_size=2)
        op = TraceOp(opcode=TraceOpcode.LOAD_CONST)

        buffer.append(op)
        buffer.append(op)
        result = buffer.append(op)

        assert result is False
        assert buffer.overflowed is True

    def test_append_after_overflow_fails(self) -> None:
        """append fails after buffer has overflowed."""
        buffer = TraceBuffer(max_size=1)
        op = TraceOp(opcode=TraceOpcode.LOAD_CONST)

        buffer.append(op)
        buffer.append(op)  # Overflow
        result = buffer.append(op)  # Should still fail

        assert result is False

    def test_clear_resets_buffer(self) -> None:
        """clear resets buffer and overflow flag."""
        buffer = TraceBuffer(max_size=1)
        op = TraceOp(opcode=TraceOpcode.LOAD_CONST)

        buffer.append(op)
        buffer.append(op)  # Overflow
        buffer.clear()

        assert len(buffer) == 0
        assert buffer.overflowed is False

    def test_is_valid_requires_termination(self) -> None:
        """is_valid returns False for unterminated trace."""
        buffer = TraceBuffer()
        buffer.append(TraceOp(opcode=TraceOpcode.LOAD_CONST))

        assert buffer.is_valid() is False

    def test_is_valid_accepts_return(self) -> None:
        """is_valid accepts trace ending with RETURN."""
        buffer = TraceBuffer()
        buffer.append(TraceOp(opcode=TraceOpcode.RETURN))

        assert buffer.is_valid() is True

    def test_is_valid_accepts_trace_end(self) -> None:
        """is_valid accepts trace ending with TRACE_END."""
        buffer = TraceBuffer()
        buffer.append(TraceOp(opcode=TraceOpcode.TRACE_END))

        assert buffer.is_valid() is True

    def test_is_valid_rejects_overflow(self) -> None:
        """is_valid returns False for overflowed buffer."""
        buffer = TraceBuffer(max_size=1)
        buffer.append(TraceOp(opcode=TraceOpcode.LOAD_CONST))
        buffer.append(TraceOp(opcode=TraceOpcode.RETURN))

        assert buffer.is_valid() is False

    def test_iteration(self) -> None:
        """Buffer supports iteration."""
        buffer = TraceBuffer()
        ops = [
            TraceOp(opcode=TraceOpcode.LOAD_CONST),
            TraceOp(opcode=TraceOpcode.RETURN),
        ]
        for op in ops:
            buffer.append(op)

        assert list(buffer) == ops

    def test_indexing(self) -> None:
        """Buffer supports indexing."""
        buffer = TraceBuffer()
        op = TraceOp(opcode=TraceOpcode.LOAD_CONST)
        buffer.append(op)

        assert buffer[0] == op

    def test_branch_fingerprint_empty(self) -> None:
        """Empty buffer has consistent fingerprint."""
        buffer = TraceBuffer()

        fp = buffer.get_branch_path_fingerprint()

        assert isinstance(fp, int)

    def test_branch_fingerprint_changes_with_branches(self) -> None:
        """Fingerprint changes based on branch decisions."""
        buffer1 = TraceBuffer()
        buffer1.append(
            TraceOp(opcode=TraceOpcode.GUARD_BRANCH_TAKEN, operands=(0, True, 0))
        )

        buffer2 = TraceBuffer()
        buffer2.append(
            TraceOp(opcode=TraceOpcode.GUARD_BRANCH_TAKEN, operands=(0, False, 0))
        )

        assert (
            buffer1.get_branch_path_fingerprint()
            != buffer2.get_branch_path_fingerprint()
        )

    def test_count_guards(self) -> None:
        """count_guards returns correct count."""
        buffer = TraceBuffer()
        buffer.append(TraceOp(opcode=TraceOpcode.GUARD_TYPE))
        buffer.append(TraceOp(opcode=TraceOpcode.LOAD_CONST))
        buffer.append(TraceOp(opcode=TraceOpcode.GUARD_SHAPE))

        assert buffer.count_guards() == 2

    def test_estimate_memory(self) -> None:
        """estimate_memory_bytes returns reasonable estimate."""
        buffer = TraceBuffer()
        for _ in range(10):
            buffer.append(TraceOp(opcode=TraceOpcode.LOAD_CONST))

        memory = buffer.estimate_memory_bytes()

        assert memory > 0
        assert memory < 10240  # Less than 10KB target

    def test_from_config_factory(self) -> None:
        """from_config creates buffer with config settings."""
        config = TracerConfig(trace_buffer_size=64)
        buffer = TraceBuffer.from_config(config)

        assert buffer.max_size == 64

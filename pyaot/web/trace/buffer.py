"""
Fixed-size trace buffer for bounded, safe trace recording.

Per-request trace buffer with overflow detection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator

from pyaot.web.trace.config import TracerConfig, get_config
from pyaot.web.trace.ops import TraceOp, TraceOpcode


@dataclass
class TraceBuffer:
    """Fixed-size ring buffer for trace operations.

    Properties:
    - Fixed size (default 256 entries, configurable)
    - Overflow detection (trace discarded on overflow, never truncated)
    - Compact storage

    Attributes:
        max_size: Maximum number of ops before overflow
        ops: List of recorded trace ops
        overflowed: Whether buffer has overflowed
    """

    max_size: int = field(default_factory=lambda: get_config().trace_buffer_size)
    ops: list[TraceOp] = field(default_factory=list)
    overflowed: bool = False

    @classmethod
    def from_config(cls, config: TracerConfig) -> "TraceBuffer":
        """Create a buffer with the given configuration."""
        return cls(max_size=config.trace_buffer_size)

    def append(self, op: TraceOp) -> bool:
        """Append an operation to the buffer.

        Args:
            op: The trace operation to append

        Returns:
            True if successfully appended, False if buffer overflowed
        """
        if self.overflowed:
            return False

        if len(self.ops) >= self.max_size:
            self.overflowed = True
            return False

        self.ops.append(op)
        return True

    def clear(self) -> None:
        """Clear the buffer for reuse."""
        self.ops.clear()
        self.overflowed = False

    def is_valid(self) -> bool:
        """Check if trace is valid (no overflow, properly terminated)."""
        if self.overflowed:
            return False
        if not self.ops:
            return False
        # Check for proper termination
        last_op = self.ops[-1]
        return last_op.opcode in (
            TraceOpcode.RETURN,
            TraceOpcode.RAISE,
            TraceOpcode.TRACE_END,
        )

    def __len__(self) -> int:
        """Return number of ops in buffer."""
        return len(self.ops)

    def __iter__(self) -> Iterator[TraceOp]:
        """Iterate over ops."""
        return iter(self.ops)

    def __getitem__(self, idx: int) -> TraceOp:
        """Get op by index."""
        return self.ops[idx]

    def get_branch_path_fingerprint(self) -> int:
        """Compute branch path fingerprint for this trace.

        Returns a hash of all branch decisions taken, used for
        identifying unique execution paths.
        """
        branch_decisions: list[bool] = []
        for op in self.ops:
            if op.opcode == TraceOpcode.GUARD_BRANCH_TAKEN:
                # operands: (cond_reg, expected_bool, deopt_id)
                expected = bool(op.operands[1]) if len(op.operands) > 1 else True
                branch_decisions.append(expected)
        return hash(tuple(branch_decisions))

    def count_guards(self) -> int:
        """Count number of guard operations."""
        return sum(1 for op in self.ops if op.is_guard())

    def estimate_memory_bytes(self) -> int:
        """Estimate memory usage in bytes.

        Target: ≤10KB per trace.
        """
        # Rough estimate: 40 bytes per TraceOp on average
        return len(self.ops) * 40

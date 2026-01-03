"""
Trace IR opcodes and data structures.

This module defines the Trace IR v1.0 specification (frozen).
All opcodes, guard types, and side-effect classifications are defined here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class TraceOpcode(Enum):
    """Trace IR opcodes (v1.0 - frozen)."""

    # Guards (no side effects)
    GUARD_TYPE = auto()  # reg, type_id, deopt_id
    GUARD_SHAPE = auto()  # reg, shape_id, deopt_id
    GUARD_NONNULL = auto()  # reg, deopt_id
    GUARD_BRANCH_TAKEN = auto()  # cond_reg, expected_bool, deopt_id
    GUARD_CALL_TARGET = auto()  # call_id, deopt_id
    GUARD_NO_EXCEPTION = auto()  # deopt_id

    # Loads / Stores
    LOAD_CONST = auto()  # dst, const_id
    LOAD_LOCAL = auto()  # dst, local_id
    STORE_LOCAL = auto()  # local_id, src
    LOAD_ATTR = auto()  # dst, obj, offset

    # Computation
    BINOP = auto()  # dst, left, right, op
    UNARYOP = auto()  # dst, src, op

    # Calls
    CALL_DIRECT = auto()  # dst, call_id, arg_regs...
    CALL_INDIRECT = auto()  # dst, func_reg, arg_regs...

    # Allocation
    ALLOC = auto()  # dst, type_id, escape_flag

    # Control / Exit
    BRANCH = auto()  # cond_reg, true_label, false_label
    RETURN = auto()  # value_reg
    RAISE = auto()  # exception_reg
    DEOPT = auto()  # deopt_id
    TRACE_END = auto()  # no operands


class SideEffectKind(Enum):
    """Side-effect classification for trace operations."""

    PURE = auto()  # No side effects
    LOCAL_MUTATION = auto()  # Mutates local/stack only
    EXTERNAL_COMMIT = auto()  # DB write, I/O, etc. - ends trace


class EscapeFlag(Enum):
    """Escape analysis result for allocations."""

    NOESCAPE = auto()  # Can be scalar replaced
    MAY_ESCAPE = auto()  # Must materialize


@dataclass
class TraceOp:
    """A single operation in a trace.

    Compact, immutable representation of one Trace IR instruction.
    """

    opcode: TraceOpcode
    operands: tuple[Any, ...] = field(default_factory=tuple)
    metadata_id: int = 0
    side_effect: SideEffectKind = SideEffectKind.PURE
    deopt_id: int | None = None

    def is_guard(self) -> bool:
        """Check if this op is a guard instruction."""
        return self.opcode.name.startswith("GUARD_")

    def is_control(self) -> bool:
        """Check if this op is a control flow instruction."""
        return self.opcode in (
            TraceOpcode.BRANCH,
            TraceOpcode.RETURN,
            TraceOpcode.RAISE,
            TraceOpcode.DEOPT,
            TraceOpcode.TRACE_END,
        )

    def ends_trace(self) -> bool:
        """Check if this op terminates the trace."""
        return (
            self.opcode
            in (
                TraceOpcode.RETURN,
                TraceOpcode.RAISE,
                TraceOpcode.TRACE_END,
            )
            or self.side_effect == SideEffectKind.EXTERNAL_COMMIT
        )


@dataclass
class DeoptMetadata:
    """Metadata for deoptimization points.

    Required for transferring control back to CPython interpreter.
    """

    deopt_id: int
    bytecode_pc: int  # Resume PC in bytecode
    live_locals: tuple[str, ...]  # Names of live locals
    stack_depth: int  # Operand stack depth
    reg_to_local: dict[int, str]  # Virtual reg → local name mapping


@dataclass
class ConstantTable:
    """Deduplicated constant storage for traces."""

    _constants: list[Any] = field(default_factory=list)
    _index: dict[int, int] = field(default_factory=dict)  # id(value) → index

    def add(self, value: Any) -> int:
        """Add a constant and return its ID."""
        key = id(value)
        if key in self._index:
            return self._index[key]
        idx = len(self._constants)
        self._constants.append(value)
        self._index[key] = idx
        return idx

    def get(self, idx: int) -> Any:
        """Get constant by ID."""
        return self._constants[idx]

    def __len__(self) -> int:
        return len(self._constants)


@dataclass
class ShapeTable:
    """Deduplicated shape storage for traces."""

    _shapes: list[tuple[int, tuple[str, ...]]] = field(default_factory=list)
    _index: dict[tuple[int, tuple[str, ...]], int] = field(default_factory=dict)

    def add(self, type_id: int, dict_keys: tuple[str, ...]) -> int:
        """Add a shape and return its ID."""
        key = (type_id, dict_keys)
        if key in self._index:
            return self._index[key]
        idx = len(self._shapes)
        self._shapes.append(key)
        self._index[key] = idx
        return idx

    def get(self, idx: int) -> tuple[int, tuple[str, ...]]:
        """Get shape by ID."""
        return self._shapes[idx]

    def __len__(self) -> int:
        return len(self._shapes)


@dataclass
class CallTargetTable:
    """Deduplicated call target storage for traces.

    Call targets are identified by stable content hash, not pointers.
    """

    _targets: list[str] = field(default_factory=list)  # content hashes
    _index: dict[str, int] = field(default_factory=dict)

    def add(self, target_hash: str) -> int:
        """Add a call target and return its ID."""
        if target_hash in self._index:
            return self._index[target_hash]
        idx = len(self._targets)
        self._targets.append(target_hash)
        self._index[target_hash] = idx
        return idx

    def get(self, idx: int) -> str:
        """Get call target hash by ID."""
        return self._targets[idx]

    def __len__(self) -> int:
        return len(self._targets)

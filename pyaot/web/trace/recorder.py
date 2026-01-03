"""
Trace recorder with CPython bytecode instrumentation.

Records request execution traces via hybrid bytecode + runtime hooks.
"""

from __future__ import annotations

import hashlib
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Set, Tuple

from pyaot.web.trace.ops import (
    TraceOp,
    TraceOpcode,
    SideEffectKind,
    ConstantTable,
    ShapeTable,
    CallTargetTable,
)
from pyaot.web.trace.buffer import TraceBuffer
from pyaot.web.trace.signature import RequestSignature
from pyaot.web.trace.eligibility import EligibilityEvaluator
from pyaot.web.trace.store import TraceStore, TraceRecord


# CPython bytecode whitelist (Python 3.14)
# Tracing only records these opcodes
BYTECODE_WHITELIST: Set[str] = {
    # Loads / Stores
    "LOAD_FAST",
    "LOAD_FAST_CHECK",
    "STORE_FAST",
    "LOAD_CONST",
    "LOAD_ATTR",
    "LOAD_GLOBAL",
    "STORE_ATTR",
    # Comparisons
    "COMPARE_OP",
    "IS_OP",
    "CONTAINS_OP",
    # Binary / Unary operations
    "BINARY_OP",
    "UNARY_NOT",
    "UNARY_NEGATIVE",
    "UNARY_INVERT",
    # Calls (Python 3.11+)
    "CALL",
    "CALL_FUNCTION_EX",
    # Control flow
    "POP_JUMP_IF_TRUE",
    "POP_JUMP_IF_FALSE",
    "POP_JUMP_IF_NONE",
    "POP_JUMP_IF_NOT_NONE",
    "JUMP_FORWARD",
    "JUMP_BACKWARD",
    # Return
    "RETURN_VALUE",
    "RETURN_CONST",
    # Stack manipulation (needed for semantics)
    "POP_TOP",
    "COPY",
    "SWAP",
    # Build operations (for shapes)
    "BUILD_LIST",
    "BUILD_TUPLE",
    "BUILD_MAP",
    "BUILD_SET",
}

# Opcodes that immediately end the trace
TRACE_STOP_OPCODES: Set[str] = {
    "YIELD_VALUE",
    "SEND",
    "GET_AWAITABLE",
    "GET_AITER",
    "GET_ANEXT",
    "SETUP_FINALLY",
    "RAISE_VARARGS",
    "RERAISE",
    "IMPORT_NAME",
    "IMPORT_FROM",
    "IMPORT_STAR",
    "LOAD_BUILD_CLASS",
    "MAKE_FUNCTION",  # Unless we want to trace closures
}


@dataclass
class TraceContext:
    """Per-request tracing context."""

    buffer: TraceBuffer = field(default_factory=TraceBuffer)
    constants: ConstantTable = field(default_factory=ConstantTable)
    shapes: ShapeTable = field(default_factory=ShapeTable)
    call_targets: CallTargetTable = field(default_factory=CallTargetTable)

    # Request info
    signature: Optional[RequestSignature] = None
    route_id: str = ""
    client_ip: str = ""

    # State tracking
    active: bool = False
    deopt_counter: int = 0
    deopt_metadata: Dict[int, dict] = field(default_factory=dict)

    # Virtual register allocation
    next_reg: int = 0
    local_to_reg: Dict[str, int] = field(default_factory=dict)

    def allocate_reg(self) -> int:
        """Allocate a new virtual register."""
        reg = self.next_reg
        self.next_reg += 1
        return reg

    def allocate_deopt(self, bytecode_pc: int, live_locals: Tuple[str, ...]) -> int:
        """Allocate a deopt point and record metadata."""
        deopt_id = self.deopt_counter
        self.deopt_counter += 1
        self.deopt_metadata[deopt_id] = {
            "bytecode_pc": bytecode_pc,
            "live_locals": live_locals,
            "reg_to_local": dict(self.local_to_reg),
        }
        return deopt_id


# Thread-local storage for trace context
_trace_context = threading.local()


def get_current_context() -> Optional[TraceContext]:
    """Get the current thread's trace context."""
    return getattr(_trace_context, "context", None)


def set_current_context(ctx: Optional[TraceContext]) -> None:
    """Set the current thread's trace context."""
    _trace_context.context = ctx


class TraceRecorder:
    """Main trace recorder with CPython instrumentation.

    Records request execution traces via bytecode hooks.
    Uses the instrumentation whitelist to filter opcodes.
    """

    def __init__(
        self,
        store: Optional[TraceStore] = None,
        eligibility: Optional[EligibilityEvaluator] = None,
    ):
        self.store = store if store is not None else TraceStore()
        self.eligibility = eligibility if eligibility is not None else EligibilityEvaluator()
        self._enabled = True

    def enable(self) -> None:
        """Enable tracing."""
        self._enabled = True

    def disable(self) -> None:
        """Disable tracing."""
        self._enabled = False

    @contextmanager
    def trace_request(
        self,
        route_id: str,
        signature: RequestSignature,
        client_ip: str = "0.0.0.0",
    ):
        """Context manager for tracing a request.

        Usage:
            with recorder.trace_request(route_id, sig, ip) as ctx:
                # Handler code runs here
                pass
            # After: trace is finalized and stored
        """
        if not self._enabled:
            yield None
            return

        ctx = TraceContext(
            signature=signature,
            route_id=route_id,
            client_ip=client_ip,
            active=True,
        )
        
        # Ensure trace is never empty
        ctx.buffer.append(TraceOp(opcode=TraceOpcode.TRACE_START))

        set_current_context(ctx)

        try:
            yield ctx
        finally:
            ctx.active = False
            self._finalize_trace(ctx)
            set_current_context(None)

    def _finalize_trace(self, ctx: TraceContext) -> None:
        """Finalize and store a completed trace.

        Args:
            ctx: The trace context to finalize.
        """
        # Guard: must have signature
        if ctx.signature is None:
            return

        if ctx.buffer.overflowed:
            return

        # Ensure trace ends properly
        if ctx.buffer.ops and ctx.buffer.ops[-1].opcode not in (
            TraceOpcode.RETURN,
            TraceOpcode.RAISE,
            TraceOpcode.TRACE_END,
        ):
            ctx.buffer.append(TraceOp(opcode=TraceOpcode.TRACE_END))

        if not ctx.buffer.is_valid():
            return

        # Record observation for eligibility
        branch_fingerprint = ctx.buffer.get_branch_path_fingerprint()
        shape_id = 0  # TODO: compute aggregate shape ID

        self.eligibility.record_observation(
            signature=ctx.signature,
            client_ip=ctx.client_ip,
            branch_fingerprint=branch_fingerprint,
            shape_id=shape_id,
            trace_length=len(ctx.buffer),
        )

        # Check eligibility
        result = self.eligibility.evaluate(ctx.signature)
        if not result.eligible:
            return

        # Store the trace
        self.store.store(
            route_id=ctx.route_id,
            signature=ctx.signature,
            ops=tuple(ctx.buffer.ops),
            constants=ctx.constants,
            shapes=ctx.shapes,
            call_targets=ctx.call_targets,
            observation_count=result.observations,
            client_prefixes=result.client_prefixes,
            branch_stability=result.branch_stability,
        )

    def record_load_fast(self, name: str, value: Any) -> None:
        """Record LOAD_FAST operation."""
        ctx = get_current_context()
        if not ctx or not ctx.active:
            return

        # Allocate register if needed
        if name not in ctx.local_to_reg:
            ctx.local_to_reg[name] = ctx.allocate_reg()

        dst = ctx.local_to_reg[name]

        # Record shape for non-primitives
        if hasattr(value, "__dict__"):
            type_id = id(type(value))
            dict_keys = (
                tuple(sorted(value.__dict__.keys()))
                if hasattr(value, "__dict__")
                else ()
            )
            shape_id = ctx.shapes.add(type_id, dict_keys)

            # Add shape guard
            deopt_id = ctx.allocate_deopt(0, tuple(ctx.local_to_reg.keys()))
            ctx.buffer.append(
                TraceOp(
                    opcode=TraceOpcode.GUARD_SHAPE,
                    operands=(dst, shape_id, deopt_id),
                    deopt_id=deopt_id,
                )
            )

        ctx.buffer.append(
            TraceOp(
                opcode=TraceOpcode.LOAD_LOCAL,
                operands=(dst, name),
            )
        )

    def record_store_fast(self, name: str, value: Any) -> None:
        """Record STORE_FAST operation."""
        ctx = get_current_context()
        if not ctx or not ctx.active:
            return

        if name not in ctx.local_to_reg:
            ctx.local_to_reg[name] = ctx.allocate_reg()

        src = ctx.local_to_reg.get(name, 0)

        ctx.buffer.append(
            TraceOp(
                opcode=TraceOpcode.STORE_LOCAL,
                operands=(name, src),
                side_effect=SideEffectKind.LOCAL_MUTATION,
            )
        )

    def record_load_const(self, value: Any) -> None:
        """Record LOAD_CONST operation."""
        ctx = get_current_context()
        if not ctx or not ctx.active:
            return

        const_id = ctx.constants.add(value)
        dst = ctx.allocate_reg()

        ctx.buffer.append(
            TraceOp(
                opcode=TraceOpcode.LOAD_CONST,
                operands=(dst, const_id),
            )
        )

    def record_load_attr(self, obj: Any, name: str, result: Any) -> None:
        """Record LOAD_ATTR operation with resolved offset."""
        ctx = get_current_context()
        if not ctx or not ctx.active:
            return

        # Try to get dict offset for fast access
        offset = -1
        if hasattr(obj, "__dict__") and isinstance(obj.__dict__, dict):
            keys = list(obj.__dict__.keys())
            if name in keys:
                offset = keys.index(name)

        dst = ctx.allocate_reg()
        obj_reg = 0  # TODO: track object register

        ctx.buffer.append(
            TraceOp(
                opcode=TraceOpcode.LOAD_ATTR,
                operands=(dst, obj_reg, offset, name),
            )
        )

    def record_call(
        self,
        func: Callable,
        args: Tuple[Any, ...],
        result: Any,
    ) -> None:
        """Record CALL operation."""
        ctx = get_current_context()
        if not ctx or not ctx.active:
            return

        # Compute stable call target hash
        target_hash = self._compute_call_target_hash(func)
        call_id = ctx.call_targets.add(target_hash)

        # Add call target guard
        deopt_id = ctx.allocate_deopt(0, tuple(ctx.local_to_reg.keys()))
        ctx.buffer.append(
            TraceOp(
                opcode=TraceOpcode.GUARD_CALL_TARGET,
                operands=(call_id, deopt_id),
                deopt_id=deopt_id,
            )
        )

        dst = ctx.allocate_reg()

        ctx.buffer.append(
            TraceOp(
                opcode=TraceOpcode.CALL_DIRECT,
                operands=(dst, call_id, len(args)),
            )
        )

    def record_branch(self, condition: bool, expected: bool) -> None:
        """Record branch taken/not taken."""
        ctx = get_current_context()
        if not ctx or not ctx.active:
            return

        deopt_id = ctx.allocate_deopt(0, tuple(ctx.local_to_reg.keys()))

        ctx.buffer.append(
            TraceOp(
                opcode=TraceOpcode.GUARD_BRANCH_TAKEN,
                operands=(0, expected, deopt_id),  # 0 = cond_reg placeholder
                deopt_id=deopt_id,
            )
        )

    def record_return(self, value: Any) -> None:
        """Record RETURN_VALUE operation."""
        ctx = get_current_context()
        if not ctx or not ctx.active:
            return

        value_reg = 0  # TODO: track value register

        ctx.buffer.append(
            TraceOp(
                opcode=TraceOpcode.RETURN,
                operands=(value_reg,),
            )
        )

    def record_external_commit(self, operation: str) -> None:
        """Record external side effect (ends trace)."""
        ctx = get_current_context()
        if not ctx or not ctx.active:
            return

        # External commit ends the trace
        ctx.buffer.append(
            TraceOp(
                opcode=TraceOpcode.TRACE_END,
                side_effect=SideEffectKind.EXTERNAL_COMMIT,
            )
        )
        ctx.active = False  # Stop further tracing

    def _compute_call_target_hash(self, func: Callable) -> str:
        """Compute stable content hash for a function.

        Based on code content, not pointer.
        """
        try:
            code = func.__code__
            content = (
                code.co_code,
                code.co_consts,
                code.co_names,
                getattr(func, "__qualname__", str(func)),
                getattr(func, "__module__", ""),
            )
            content_str = str(content)
            return hashlib.sha256(content_str.encode()).hexdigest()[:32]
        except AttributeError:
            # Built-in or C function
            return hashlib.sha256(str(func).encode()).hexdigest()[:32]

    def get_compiled_trace(
        self,
        signature: RequestSignature,
    ) -> Optional[TraceRecord]:
        """Get compiled trace for a request signature."""
        return self.store.get(signature)

    def invalidate_route(self, route_id: str) -> int:
        """Invalidate all traces for a route (code deploy)."""
        return self.store.invalidate_route(route_id)

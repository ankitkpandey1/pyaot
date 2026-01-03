"""Deoptimization materialization for trace compilation.

Generates deopt stubs that transfer control back to CPython interpreter
when guards fail, reconstructing the interpreter frame state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from llvmlite import ir as llvm_ir


@dataclass
class DeoptPoint:
    """Information about a deoptimization point.

    Attributes:
        deopt_id: Unique identifier for this deopt point.
        bytecode_pc: Resume PC in Python bytecode.
        live_locals: Names of live local variables.
        reg_to_local: Mapping from virtual registers to local names.
        stack_depth: Operand stack depth at deopt point.
    """

    deopt_id: int
    bytecode_pc: int
    live_locals: tuple[str, ...]
    reg_to_local: dict[int, str]
    stack_depth: int = 0


@dataclass
class DeoptStub:
    """A generated deopt stub.

    Attributes:
        deopt_id: ID of the deopt point.
        block: LLVM block containing the stub.
        materialization_fn: Function pointer for frame reconstruction.
    """

    deopt_id: int
    block: Any  # llvm_ir.Block
    materialization_fn: Any | None = None


class DeoptMaterializer:
    """Generates deoptimization stubs for trace compilation.

    Deopt stubs are responsible for:
    1. Saving virtual register values
    2. Reconstructing Python frame state
    3. Transferring control to CPython interpreter

    Transactional deopt: no partial side effects are visible.
    """

    def __init__(self, module: "llvm_ir.Module") -> None:
        """Initialize deopt materializer.

        Args:
            module: LLVM module to generate stubs in.
        """
        self._module = module
        self._stubs: dict[int, DeoptStub] = {}
        self._deopt_points: dict[int, DeoptPoint] = {}

    def register_deopt_point(self, point: DeoptPoint) -> None:
        """Register a deoptimization point.

        Args:
            point: Deopt point metadata from trace recording.
        """
        self._deopt_points[point.deopt_id] = point

    def get_deopt_block(self, builder: "llvm_ir.IRBuilder", deopt_id: int) -> Any:
        """Get or create deopt block for the given ID.

        Args:
            builder: LLVM IR builder.
            deopt_id: Deopt point identifier.

        Returns:
            LLVM block for the deopt stub.
        """
        if deopt_id in self._stubs:
            return self._stubs[deopt_id].block

        # Create new stub
        func = builder.block.function
        block = func.append_basic_block(name=f"deopt_{deopt_id}")

        stub = DeoptStub(deopt_id=deopt_id, block=block)
        self._stubs[deopt_id] = stub

        return block

    def generate_stub(
        self,
        builder: "llvm_ir.IRBuilder",
        deopt_id: int,
        live_regs: dict[int, Any],
    ) -> None:
        """Generate deopt stub code.

        Generates code that:
        1. Materializes virtual registers to Python frame
        2. Calls CPython to resume execution
        3. Returns from compiled trace

        Args:
            builder: LLVM IR builder positioned at stub block.
            deopt_id: Deopt point identifier.
            live_regs: Mapping from virtual reg to LLVM value.
        """
        from llvmlite import ir as llvm_ir

        point = self._deopt_points.get(deopt_id)
        if point is None:
            # Unknown deopt point - should not happen
            # Generate a trap for debugging
            builder.unreachable()
            return

        # Generate frame reconstruction
        # This would call a runtime function like:
        # pyaot_deopt_materialize(frame_ptr, bytecode_pc, locals_dict)

        # For now, generate a placeholder return
        # In production, this would:
        # 1. Create new PyFrameObject
        # 2. Copy values from virtual regs to f_localsplus
        # 3. Set f_lasti to bytecode_pc
        # 4. Call PyEval_EvalFrame

        # Placeholder: return null to indicate deopt
        ret_type = builder.function.return_value.type
        if str(ret_type) == "void":
            builder.ret_void()
        else:
            null_val = llvm_ir.Constant(ret_type, None)
            builder.ret(null_val)

    def generate_all_stubs(
        self,
        builder: "llvm_ir.IRBuilder",
        live_regs: dict[int, Any],
    ) -> None:
        """Generate all deopt stubs.

        Args:
            builder: LLVM IR builder.
            live_regs: Mapping from virtual reg to LLVM value.
        """
        for deopt_id, stub in self._stubs.items():
            # Save current position
            orig_block = builder.block

            # Position at stub block
            builder.position_at_end(stub.block)

            # Generate stub code
            self.generate_stub(builder, deopt_id, live_regs)

            # Restore position
            builder.position_at_end(orig_block)

    def get_stub_count(self) -> int:
        """Get number of generated stubs."""
        return len(self._stubs)

    def get_stubs(self) -> list[DeoptStub]:
        """Get all generated stubs."""
        return list(self._stubs.values())

"""Trace IR to PyAOT IR lowering.

Converts Trace IR operations to PyAOT IR, enabling reuse of the main compiler pipeline.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from pyaot.web.trace.ops import TraceOp, TraceOpcode
from pyaot.web.trace.store import TraceRecord
from pyaot.compiler.ir import (
    IRModule,
    IRFunction,
    IRBasicBlock,
    IRInstruction,
    IRType,
    IRValue,
    Opcode,
)

if TYPE_CHECKING:
    pass


class TraceLowerer:
    """Lowers Trace IR to PyAOT IR.
    
    Translates observed execution (TraceOps) into the canonical PyAOT Intermediate Representation.
    This allows the web module to utilize the existing optimization and codegen pipeline.
    """

    def __init__(self) -> None:
        """Initialize trace lowerer."""
        self._module: Optional[IRModule] = None
        self._function: Optional[IRFunction] = None
        self._current_block: Optional[IRBasicBlock] = None
        self._regs: Dict[int, IRValue] = {}  # trace reg -> IRValue

    def lower_trace(self, trace: TraceRecord) -> IRModule:
        """Lower a trace to PyAOT IR.

        Args:
            trace: The trace record to lower.

        Returns:
            PyAOT IR module containing the compiled trace function.
        """
        # Create module
        self._module = IRModule(name=f"trace_{trace.header.trace_id}")

        # Create function signature: (request_ptr) -> response_ptr
        # We model pointers as i64 for compatibility with simple integer constants
        func = IRFunction(
            name="trace_entry",
            return_type=IRType.i64(),
            arg_names=["request_context"],
            arg_types=[IRType.i64()],
        )
        self._module.add_function(func)
        self._function = func

        # Create entry block
        self._current_block = func.new_block("entry")
        self._regs = {}

        # Lower each operation
        for op in trace.ops:
            self._lower_op(op)

        # Ensure block termination
        if not self._current_block.is_terminated():
            # Implicit return 0 if trace ends without return
            null_val = func.new_value(IRType.i64(), "null")
            self._emit(Opcode.CONST_INT, result=null_val, operands=[0])
            self._emit(Opcode.RET, operands=[null_val])

        return self._module

    def _lower_op(self, op: TraceOp) -> None:
        """Lower a single trace operation."""
        opcode = op.opcode

        # Guards
        if opcode == TraceOpcode.GUARD_TYPE:
            self._lower_guard_type(op)
        elif opcode == TraceOpcode.GUARD_SHAPE:
            self._lower_guard_shape(op)
        # ... other guards omitted for brevity in v1 refactor, 
        # mapping them to generalized GUARD_FAIL checks or generic checks

        # Loads / Stores
        elif opcode == TraceOpcode.LOAD_CONST:
            self._lower_load_const(op)
        elif opcode == TraceOpcode.LOAD_LOCAL:
            self._lower_load_local(op)
        elif opcode == TraceOpcode.STORE_LOCAL:
            self._lower_store_local(op)
        elif opcode == TraceOpcode.LOAD_ATTR:
            self._lower_load_attr(op)

        # Computation
        elif opcode == TraceOpcode.BINOP:
            self._lower_binop(op)
        elif opcode == TraceOpcode.UNARYOP:
            self._lower_unaryop(op)

        # Calls
        elif opcode == TraceOpcode.CALL_DIRECT:
            self._lower_call_direct(op)
        
        # Control
        elif opcode == TraceOpcode.RETURN:
            self._lower_return(op)
        elif opcode == TraceOpcode.TRACE_END:
            pass  # Handled by loop or block check
        
        # Fallback for implementation gaps in v1
        else:
            pass

    def _emit(
        self, 
        opcode: Opcode, 
        result: Optional[IRValue] = None, 
        operands: List[Any] = None,
        metadata: Dict[str, Any] = None
    ) -> None:
        """Emit an instruction to the current block."""
        if operands is None:
            operands = []
        inst = IRInstruction(
            opcode=opcode,
            result=result,
            operands=operands,
            metadata=metadata or {}
        )
        self._current_block.append(inst)

    def _lower_load_const(self, op: TraceOp) -> None:
        """Lower LOAD_CONST -> CONST_INT/FLOAT/etc."""
        dst, const_id = op.operands[:2]
        # For this refactor, we simplify constants to int64 handles
        # In a real impl, we'd lookup type from ConstantTable
        val = self._function.new_value(IRType.i64(), f"r{dst}")
        self._regs[dst] = val
        self._emit(Opcode.CONST_INT, result=val, operands=[const_id])

    def _lower_load_local(self, op: TraceOp) -> None:
        """Lower LOAD_LOCAL."""
        dst = op.operands[0]
        val = self._function.new_value(IRType.i64(), f"r{dst}")
        self._regs[dst] = val
        self._emit(Opcode.CONST_INT, result=val, operands=[0]) # Placeholder

    def _lower_store_local(self, op: TraceOp) -> None:
        pass # Placeholder

    def _lower_load_attr(self, op: TraceOp) -> None:
        dst = op.operands[0]
        val = self._function.new_value(IRType.i64(), f"r{dst}")
        self._regs[dst] = val
        self._emit(Opcode.CONST_INT, result=val, operands=[0])

    def _lower_binop(self, op: TraceOp) -> None:
        """Lower BINOP -> ADD/SUB/etc."""
        dst, left_reg, right_reg, op_kind = op.operands[:4]
        left = self._regs.get(left_reg)
        right = self._regs.get(right_reg)
        
        if not left or not right:
            return

        # Map op_kind
        ir_opcode = Opcode.ADD
        if op_kind == "-": ir_opcode = Opcode.SUB
        elif op_kind == "*": ir_opcode = Opcode.MUL
        elif op_kind == "/": ir_opcode = Opcode.DIV
        
        res = self._function.new_value(IRType.i64(), f"r{dst}")
        self._regs[dst] = res
        self._emit(ir_opcode, result=res, operands=[left, right])

    def _lower_unaryop(self, op: TraceOp) -> None:
        dst, src_reg, op_kind = op.operands[:3]
        src = self._regs.get(src_reg)
        if not src: return
        
        ir_opcode = Opcode.NEG if op_kind == "-" else Opcode.ADD # fallback
        res = self._function.new_value(IRType.i64(), f"r{dst}")
        self._regs[dst] = res
        self._emit(ir_opcode, result=res, operands=[src])

    def _lower_call_direct(self, op: TraceOp) -> None:
        """Lower CALL_DIRECT -> CALL."""
        dst = op.operands[0]
        # In this simplistic lowering, we just produce a placeholder
        res = self._function.new_value(IRType.i64(), f"r{dst}")
        self._regs[dst] = res
        self._emit(Opcode.CONST_INT, result=res, operands=[0])

    def _lower_return(self, op: TraceOp) -> None:
        """Lower RETURN -> RET."""
        # Assume returning ptr
        val = None
        if op.operands:
            reg = op.operands[0]
            val = self._regs.get(reg)
        
        # If val is not ptr, might need cast (omitted)
        if val:
            self._emit(Opcode.RET, operands=[val])
        else:
            null_val = self._function.new_value(IRType.i64(), "null")
            self._emit(Opcode.CONST_INT, result=null_val, operands=[0])
            self._emit(Opcode.RET, operands=[null_val])

    def _lower_guard_type(self, op: TraceOp) -> None:
        """Lower GUARD_TYPE -> GUARD_TYPE."""
        # Map TraceOp GUARD to IROp GUARD
        # reg, type_id, deopt_id = op.operands
        # For now, no-op or placeholder
        pass

    def _lower_guard_shape(self, op: TraceOp) -> None:
        pass

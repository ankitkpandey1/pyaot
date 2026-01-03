"""Trace IR to LLVM IR lowering.

Converts Trace IR operations to LLVM IR, handling guards, deopt,
and all computation opcodes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pyaot.web.trace.ops import TraceOp, TraceOpcode
from pyaot.web.trace.store import TraceRecord
from pyaot.web.codegen.guards import GuardGenerator
from pyaot.web.codegen.deopt import DeoptMaterializer, DeoptPoint

if TYPE_CHECKING:
    pass


@dataclass
class LoweringContext:
    """Context for trace lowering.

    Attributes:
        module: LLVM module being built.
        function: Current LLVM function.
        builder: LLVM IR builder.
        regs: Mapping from virtual reg to LLVM value.
        guard_gen: Guard generator.
        deopt_mat: Deopt materializer.
    """

    module: Any  # llvm_ir.Module
    function: Any  # llvm_ir.Function
    builder: Any  # llvm_ir.IRBuilder
    regs: dict[int, Any] = field(default_factory=dict)
    guard_gen: GuardGenerator | None = None
    deopt_mat: DeoptMaterializer | None = None


class TraceLowerer:
    """Lowers Trace IR to LLVM IR.

    Handles all Trace IR opcodes:
    - Guards: GUARD_TYPE, GUARD_SHAPE, GUARD_NONNULL, etc.
    - Loads: LOAD_CONST, LOAD_LOCAL, LOAD_ATTR
    - Stores: STORE_LOCAL
    - Computation: BINOP, UNARYOP
    - Calls: CALL_DIRECT, CALL_INDIRECT
    - Control: BRANCH, RETURN, DEOPT, TRACE_END
    """

    def __init__(self) -> None:
        """Initialize trace lowerer."""
        self._ctx: LoweringContext | None = None

    def lower_trace(self, trace: TraceRecord) -> Any:
        """Lower a trace to LLVM IR.

        Args:
            trace: The trace record to lower.

        Returns:
            LLVM module containing the compiled trace.
        """
        from llvmlite import ir as llvm_ir

        # Create LLVM module
        module = llvm_ir.Module(name=f"trace_{trace.header.trace_id}")

        # Create function signature
        # For web handlers: (request_ptr) -> response_ptr
        void_ptr = llvm_ir.IntType(8).as_pointer()
        func_type = llvm_ir.FunctionType(void_ptr, [void_ptr])
        func = llvm_ir.Function(module, func_type, name="trace_entry")

        # Create entry block
        entry = func.append_basic_block(name="entry")
        builder = llvm_ir.IRBuilder(entry)

        # Initialize context
        deopt_targets: dict[int, Any] = {}
        guard_gen = GuardGenerator(
            builder, 
            deopt_targets, 
            hot_path_weight=trace.header.observation_count
        )
        deopt_mat = DeoptMaterializer(module)

        self._ctx = LoweringContext(
            module=module,
            function=func,
            builder=builder,
            guard_gen=guard_gen,
            deopt_mat=deopt_mat,
        )

        # Register deopt points from trace
        for deopt_id, metadata in trace.deopt_points.items():
            point = DeoptPoint(
                deopt_id=deopt_id,
                bytecode_pc=metadata.get("bytecode_pc", 0),
                live_locals=tuple(metadata.get("live_locals", [])),
                reg_to_local=metadata.get("reg_to_local", {}),
            )
            deopt_mat.register_deopt_point(point)

        # Lower each operation
        for op in trace.ops:
            self._lower_op(op)

        # Generate deopt stubs
        deopt_mat.generate_all_stubs(builder, self._ctx.regs)

        return module

    def _lower_op(self, op: TraceOp) -> None:
        """Lower a single trace operation.

        Args:
            op: The trace operation to lower.
        """
        opcode = op.opcode

        # Guard opcodes
        if opcode == TraceOpcode.GUARD_TYPE:
            self._lower_guard_type(op)
        elif opcode == TraceOpcode.GUARD_SHAPE:
            self._lower_guard_shape(op)
        elif opcode == TraceOpcode.GUARD_NONNULL:
            self._lower_guard_nonnull(op)
        elif opcode == TraceOpcode.GUARD_BRANCH_TAKEN:
            self._lower_guard_branch(op)
        elif opcode == TraceOpcode.GUARD_CALL_TARGET:
            self._lower_guard_call_target(op)
        elif opcode == TraceOpcode.GUARD_NO_EXCEPTION:
            self._lower_guard_no_exception(op)

        # Load/Store opcodes
        elif opcode == TraceOpcode.LOAD_CONST:
            self._lower_load_const(op)
        elif opcode == TraceOpcode.LOAD_LOCAL:
            self._lower_load_local(op)
        elif opcode == TraceOpcode.STORE_LOCAL:
            self._lower_store_local(op)
        elif opcode == TraceOpcode.LOAD_ATTR:
            self._lower_load_attr(op)

        # Computation opcodes
        elif opcode == TraceOpcode.BINOP:
            self._lower_binop(op)
        elif opcode == TraceOpcode.UNARYOP:
            self._lower_unaryop(op)

        # Call opcodes
        elif opcode == TraceOpcode.CALL_DIRECT:
            self._lower_call_direct(op)
        elif opcode == TraceOpcode.CALL_INDIRECT:
            self._lower_call_indirect(op)

        # Allocation
        elif opcode == TraceOpcode.ALLOC:
            self._lower_alloc(op)

        # Control opcodes
        elif opcode == TraceOpcode.BRANCH:
            self._lower_branch(op)
        elif opcode == TraceOpcode.RETURN:
            self._lower_return(op)
        elif opcode == TraceOpcode.RAISE:
            self._lower_raise(op)
        elif opcode == TraceOpcode.DEOPT:
            self._lower_deopt(op)
        elif opcode == TraceOpcode.TRACE_END:
            self._lower_trace_end(op)

    def _lower_guard_type(self, op: TraceOp) -> None:
        """Lower GUARD_TYPE operation."""
        if not self._ctx or not self._ctx.guard_gen:
            return
        # operands: (reg, type_id, deopt_id)
        reg, type_id, deopt_id = op.operands[:3]
        value_ptr = self._ctx.regs.get(reg)
        if value_ptr is not None:
            self._ctx.guard_gen.generate_type_guard(value_ptr, type_id, deopt_id)

    def _lower_guard_shape(self, op: TraceOp) -> None:
        """Lower GUARD_SHAPE operation."""
        if not self._ctx or not self._ctx.guard_gen:
            return
        reg, shape_id, deopt_id = op.operands[:3]
        value_ptr = self._ctx.regs.get(reg)
        if value_ptr is not None:
            self._ctx.guard_gen.generate_shape_guard(value_ptr, shape_id, deopt_id)

    def _lower_guard_nonnull(self, op: TraceOp) -> None:
        """Lower GUARD_NONNULL operation."""
        if not self._ctx or not self._ctx.guard_gen:
            return
        reg, deopt_id = op.operands[:2]
        value_ptr = self._ctx.regs.get(reg)
        if value_ptr is not None:
            self._ctx.guard_gen.generate_nonnull_guard(value_ptr, deopt_id)

    def _lower_guard_branch(self, op: TraceOp) -> None:
        """Lower GUARD_BRANCH_TAKEN operation."""
        if not self._ctx or not self._ctx.guard_gen:
            return
        cond_reg, expected, deopt_id = op.operands[:3]
        cond = self._ctx.regs.get(cond_reg)
        if cond is not None:
            self._ctx.guard_gen.generate_branch_guard(cond, bool(expected), deopt_id)

    def _lower_guard_call_target(self, op: TraceOp) -> None:
        """Lower GUARD_CALL_TARGET operation."""
        if not self._ctx or not self._ctx.guard_gen:
            return
        call_id, deopt_id = op.operands[:2]
        # Placeholder: would get function pointer from call_id
        self._ctx.guard_gen.generate_call_target_guard(None, call_id, deopt_id)

    def _lower_guard_no_exception(self, op: TraceOp) -> None:
        """Lower GUARD_NO_EXCEPTION operation."""
        if not self._ctx or not self._ctx.guard_gen:
            return
        deopt_id = op.operands[0] if op.operands else (op.deopt_id or 0)
        self._ctx.guard_gen.generate_no_exception_guard(deopt_id)

    def _lower_load_const(self, op: TraceOp) -> None:
        """Lower LOAD_CONST operation."""
        from llvmlite import ir as llvm_ir

        if not self._ctx:
            return
        # operands: (dst, const_id)
        dst, const_id = op.operands[:2]
        # For now, create a placeholder i64 constant
        val = llvm_ir.Constant(llvm_ir.IntType(64), const_id)
        self._ctx.regs[dst] = val

    def _lower_load_local(self, op: TraceOp) -> None:
        """Lower LOAD_LOCAL operation."""
        from llvmlite import ir as llvm_ir

        if not self._ctx:
            return
        # operands: (dst, local_name)
        dst = op.operands[0]
        # Placeholder: would load from frame locals
        val = llvm_ir.Constant(llvm_ir.IntType(64), 0)
        self._ctx.regs[dst] = val

    def _lower_store_local(self, op: TraceOp) -> None:
        """Lower STORE_LOCAL operation."""
        if not self._ctx:
            return
        # operands: (local_name, src)
        # Placeholder: would store to frame locals
        pass

    def _lower_load_attr(self, op: TraceOp) -> None:
        """Lower LOAD_ATTR operation."""
        from llvmlite import ir as llvm_ir

        if not self._ctx:
            return
        # operands: (dst, obj_reg, offset, name)
        dst = op.operands[0]
        # Placeholder: would load attribute at offset
        val = llvm_ir.Constant(llvm_ir.IntType(64), 0)
        self._ctx.regs[dst] = val

    def _lower_binop(self, op: TraceOp) -> None:
        """Lower BINOP operation."""
        from llvmlite import ir as llvm_ir

        if not self._ctx:
            return
        # operands: (dst, left, right, op_kind)
        dst, left_reg, right_reg, op_kind = op.operands[:4]
        left = self._ctx.regs.get(left_reg)
        right = self._ctx.regs.get(right_reg)

        if left is None or right is None:
            val = llvm_ir.Constant(llvm_ir.IntType(64), 0)
        else:
            # Map op_kind to LLVM instruction
            builder = self._ctx.builder
            if op_kind == "+":
                val = builder.add(left, right)
            elif op_kind == "-":
                val = builder.sub(left, right)
            elif op_kind == "*":
                val = builder.mul(left, right)
            elif op_kind == "/":
                val = builder.sdiv(left, right)
            else:
                val = llvm_ir.Constant(llvm_ir.IntType(64), 0)

        self._ctx.regs[dst] = val

    def _lower_unaryop(self, op: TraceOp) -> None:
        """Lower UNARYOP operation."""
        from llvmlite import ir as llvm_ir

        if not self._ctx:
            return
        # operands: (dst, src, op_kind)
        dst, src_reg, op_kind = op.operands[:3]
        src = self._ctx.regs.get(src_reg)

        if src is None:
            val = llvm_ir.Constant(llvm_ir.IntType(64), 0)
        else:
            builder = self._ctx.builder
            if op_kind == "-":
                val = builder.neg(src)
            elif op_kind == "not":
                val = builder.not_(src)
            else:
                val = src

        self._ctx.regs[dst] = val

    def _lower_call_direct(self, op: TraceOp) -> None:
        """Lower CALL_DIRECT operation."""
        from llvmlite import ir as llvm_ir

        if not self._ctx:
            return
        # operands: (dst, call_id, arg_count)
        dst = op.operands[0]
        # Placeholder: would call the target function
        val = llvm_ir.Constant(llvm_ir.IntType(8).as_pointer(), None)
        self._ctx.regs[dst] = val

    def _lower_call_indirect(self, op: TraceOp) -> None:
        """Lower CALL_INDIRECT operation."""
        from llvmlite import ir as llvm_ir

        if not self._ctx:
            return
        dst = op.operands[0]
        val = llvm_ir.Constant(llvm_ir.IntType(8).as_pointer(), None)
        self._ctx.regs[dst] = val

    def _lower_alloc(self, op: TraceOp) -> None:
        """Lower ALLOC operation."""
        from llvmlite import ir as llvm_ir

        if not self._ctx:
            return
        # operands: (dst, type_id, escape_flag)
        dst = op.operands[0]
        # Placeholder: would allocate object
        val = llvm_ir.Constant(llvm_ir.IntType(8).as_pointer(), None)
        self._ctx.regs[dst] = val

    def _lower_branch(self, op: TraceOp) -> None:
        """Lower BRANCH operation."""
        if not self._ctx:
            return
        # operands: (cond_reg, true_label, false_label)
        # Placeholder: would create conditional branch
        pass

    def _lower_return(self, op: TraceOp) -> None:
        """Lower RETURN operation."""
        from llvmlite import ir as llvm_ir

        if not self._ctx:
            return
        # operands: (value_reg,)
        builder = self._ctx.builder
        value_reg = op.operands[0] if op.operands else None
        if value_reg is not None and value_reg in self._ctx.regs:
            # Would need to convert to void*
            val = self._ctx.regs[value_reg]
        else:
            val = llvm_ir.Constant(llvm_ir.IntType(8).as_pointer(), None)
        builder.ret(val)

    def _lower_raise(self, op: TraceOp) -> None:
        """Lower RAISE operation."""
        if not self._ctx:
            return
        # Transfer to deopt
        self._ctx.builder.unreachable()

    def _lower_deopt(self, op: TraceOp) -> None:
        """Lower DEOPT operation."""
        if not self._ctx or not self._ctx.deopt_mat:
            return
        deopt_id = op.operands[0] if op.operands else 0
        deopt_block = self._ctx.deopt_mat.get_deopt_block(self._ctx.builder, deopt_id)
        self._ctx.builder.branch(deopt_block)

    def _lower_trace_end(self, op: TraceOp) -> None:
        """Lower TRACE_END operation."""
        from llvmlite import ir as llvm_ir

        if not self._ctx:
            return
        # Return null to indicate end
        builder = self._ctx.builder
        val = llvm_ir.Constant(llvm_ir.IntType(8).as_pointer(), None)
        builder.ret(val)

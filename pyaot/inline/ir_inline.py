"""
IR-level inline expansion pass for Phase 5.

Inlines eligible callee IR into caller IR with guards and
deoptimization support. Integrates with LLVM codegen.
"""

from __future__ import annotations

import ast
import inspect
import copy
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
from enum import Enum, auto

from pyaot.compiler.ir import (
    IRModule,
    IRFunction,
    IRBasicBlock,
    IRInstruction,
    IRType,
    IRTypeKind,
    IRValue,
    Opcode,
)
from pyaot.inline.eligibility import InlineCandidate, IneligibilityReason
from pyaot.inline.guards import InlineGuardSet, create_inline_guards
from pyaot.inline.telemetry import get_telemetry, RejectionReason
from pyaot.config import get_config


class DeoptReason(Enum):
    """Reasons for deoptimization."""
    GUARD_CALLEE_ID = auto()
    GUARD_RECEIVER_TYPE = auto()
    GUARD_ARG_TYPE = auto()
    GUARD_SHAPE = auto()
    EXCEPTION = auto()


@dataclass
class DeoptInfo:
    """
    Deoptimization information for an inlined call.
    
    Contains all information needed to reconstruct the Python call
    on guard failure.
    """
    callsite_id: str
    original_callee: Callable
    original_callee_id: int
    
    # For reconstructing the call
    arg_names: List[str] = field(default_factory=list)
    arg_types: List[IRType] = field(default_factory=list)
    
    # Guard positions in the inlined code
    guard_block_name: str = ""
    deopt_block_name: str = ""
    continue_block_name: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize for cache storage."""
        return {
            "callsite_id": self.callsite_id,
            "callee_id": self.original_callee_id,
            "arg_names": self.arg_names,
            "arg_types": [str(t) for t in self.arg_types],
            "guard_block": self.guard_block_name,
            "deopt_block": self.deopt_block_name,
            "continue_block": self.continue_block_name,
        }


@dataclass
class InlinedCallsite:
    """
    Represents an inlined callsite in the IR.
    """
    callsite_id: str
    candidate: InlineCandidate
    guards: InlineGuardSet
    deopt_info: DeoptInfo
    
    # The inlined IR blocks
    guard_block: Optional[IRBasicBlock] = None
    body_blocks: List[IRBasicBlock] = field(default_factory=list)
    deopt_block: Optional[IRBasicBlock] = None


class IRInlinePass:
    """
    IR-level inline expansion pass.
    
    Copies callee IR into caller IR with:
    - Pre-inline guard checks
    - Deoptimization path to Python fallback
    - Value renaming for safety
    """
    
    def __init__(self):
        self._value_counter = 0
        self._block_counter = 0
        self._config = get_config()
        self._telemetry = get_telemetry()
        self._deopt_map: Dict[str, DeoptInfo] = {}
        self._inlined_callsites: List[InlinedCallsite] = []
    
    def _new_value_name(self, prefix: str = "inline") -> str:
        """Generate unique value name."""
        self._value_counter += 1
        return f"{prefix}_{self._value_counter}"
    
    def _new_block_name(self, prefix: str = "inline") -> str:
        """Generate unique block name."""
        self._block_counter += 1
        return f"{prefix}_{self._block_counter}"
    
    def can_inline_callee(self, callee: Callable) -> Tuple[bool, Optional[IneligibilityReason]]:
        """
        Check if a callee can be inlined at IR level.
        
        Requirements:
        - Must have source code available
        - Must be a simple function (single return, no complex control flow)
        - Must be leaf (no Python calls except whitelisted)
        """
        # Check for source
        try:
            source = inspect.getsource(callee)
            tree = ast.parse(source)
        except (OSError, TypeError, SyntaxError):
            return False, IneligibilityReason.NO_SOURCE
        
        # Must be a function definition
        if not tree.body or not isinstance(tree.body[0], ast.FunctionDef):
            return False, IneligibilityReason.NO_SOURCE
        
        func_def = tree.body[0]
        
        # Check for varargs/kwargs
        if func_def.args.vararg or func_def.args.kwarg:
            return False, IneligibilityReason.HAS_VARARGS
        
        # Check for simple body (single return for Phase 5)
        if len(func_def.body) == 1 and isinstance(func_def.body[0], ast.Return):
            return True, None
        
        # Allow simple multi-statement bodies (assignments + return)
        has_return = any(isinstance(stmt, ast.Return) for stmt in func_def.body)
        if not has_return:
            return False, IneligibilityReason.NOT_LEAF
        
        # Check for disallowed constructs
        for stmt in func_def.body:
            if isinstance(stmt, (ast.Yield, ast.YieldFrom)):
                return False, IneligibilityReason.IS_GENERATOR
            if isinstance(stmt, ast.AsyncFor) or isinstance(stmt, ast.AsyncWith):
                return False, IneligibilityReason.IS_COROUTINE
        
        return True, None
    
    def lower_callee_to_ir(
        self,
        callee: Callable,
        arg_types: List[IRType],
    ) -> Optional[IRFunction]:
        """
        Lower a callee function to IR for inlining.
        
        Args:
            callee: The function to lower.
            arg_types: Inferred types for arguments.
            
        Returns:
            IRFunction or None if lowering fails.
        """
        try:
            source = inspect.getsource(callee)
            tree = ast.parse(source)
        except (OSError, TypeError, SyntaxError):
            return None
        
        func_def = tree.body[0]
        if not isinstance(func_def, ast.FunctionDef):
            return None
        
        # Create IR function
        arg_names = [arg.arg for arg in func_def.args.args]
        
        # Default to float64 if not enough type info
        while len(arg_types) < len(arg_names):
            arg_types.append(IRType.f64())
        
        ir_func = IRFunction(
            name=f"_inline_{callee.__name__}",
            return_type=IRType.f64(),  # Default, can be refined
            arg_names=arg_names,
            arg_types=arg_types[:len(arg_names)],
        )
        
        # Create entry block
        entry = ir_func.new_block("entry")
        
        # Lower the body
        self._lower_function_body(ir_func, entry, func_def.body)
        
        return ir_func
    
    def _lower_function_body(
        self,
        ir_func: IRFunction,
        block: IRBasicBlock,
        stmts: List[ast.stmt],
    ) -> None:
        """Lower AST statements to IR in a block."""
        for stmt in stmts:
            if isinstance(stmt, ast.Return):
                # Lower return expression
                if stmt.value:
                    result = self._lower_expr(ir_func, block, stmt.value)
                    block.append(IRInstruction(
                        opcode=Opcode.RET,
                        operands=[result],
                    ))
                else:
                    block.append(IRInstruction(opcode=Opcode.RET))
            elif isinstance(stmt, ast.Assign):
                # Simple assignment
                if len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
                    name = stmt.targets[0].id
                    value = self._lower_expr(ir_func, block, stmt.value)
                    ir_func.set_local(name, value)
    
    def _lower_expr(
        self,
        ir_func: IRFunction,
        block: IRBasicBlock,
        expr: ast.expr,
    ) -> IRValue:
        """Lower an AST expression to IR."""
        if isinstance(expr, ast.Constant):
            # Constant value
            val = expr.value
            if isinstance(val, float):
                result = ir_func.new_value(IRType.f64(), "const")
                block.append(IRInstruction(
                    opcode=Opcode.CONST_FLOAT,
                    result=result,
                    operands=[val],
                ))
                return result
            elif isinstance(val, int):
                result = ir_func.new_value(IRType.i64(), "const")
                block.append(IRInstruction(
                    opcode=Opcode.CONST_INT,
                    result=result,
                    operands=[val],
                ))
                return result
        
        elif isinstance(expr, ast.Name):
            # Variable reference
            local = ir_func.get_local(expr.id)
            if local:
                return local
            # Unknown, create placeholder
            return ir_func.new_value(IRType.f64(), expr.id)
        
        elif isinstance(expr, ast.BinOp):
            # Binary operation
            left = self._lower_expr(ir_func, block, expr.left)
            right = self._lower_expr(ir_func, block, expr.right)
            
            # Determine opcode based on types and operation
            is_float = (left.type.kind == IRTypeKind.FLOAT64 or 
                       right.type.kind == IRTypeKind.FLOAT64)
            
            result_type = IRType.f64() if is_float else IRType.i64()
            result = ir_func.new_value(result_type, "binop")
            
            if isinstance(expr.op, ast.Add):
                opcode = Opcode.FADD if is_float else Opcode.ADD
            elif isinstance(expr.op, ast.Sub):
                opcode = Opcode.FSUB if is_float else Opcode.SUB
            elif isinstance(expr.op, ast.Mult):
                opcode = Opcode.FMUL if is_float else Opcode.MUL
            elif isinstance(expr.op, ast.Div):
                opcode = Opcode.FDIV if is_float else Opcode.DIV
            else:
                opcode = Opcode.FADD  # Default
            
            block.append(IRInstruction(
                opcode=opcode,
                result=result,
                operands=[left, right],
            ))
            return result
        
        elif isinstance(expr, ast.UnaryOp):
            operand = self._lower_expr(ir_func, block, expr.operand)
            is_float = operand.type.kind == IRTypeKind.FLOAT64
            result = ir_func.new_value(operand.type, "unary")
            
            if isinstance(expr.op, ast.USub):
                opcode = Opcode.FNEG if is_float else Opcode.NEG
            else:
                opcode = Opcode.FNEG  # Default
            
            block.append(IRInstruction(
                opcode=opcode,
                result=result,
                operands=[operand],
            ))
            return result
        
        # Default: return placeholder
        return ir_func.new_value(IRType.f64(), "unknown")
    
    def inline_callee(
        self,
        caller_ir: IRFunction,
        callsite_id: str,
        callee_ir: IRFunction,
        call_args: List[IRValue],
        candidate: InlineCandidate,
    ) -> Tuple[IRValue, InlinedCallsite]:
        """
        Inline callee IR into caller IR.
        
        Args:
            caller_ir: The caller's IR function.
            callsite_id: Unique identifier for this callsite.
            callee_ir: The callee's IR function to inline.
            call_args: Values to pass as arguments.
            candidate: The inline candidate info.
            
        Returns:
            (result_value, inlined_callsite)
        """
        # Create guard block
        guard_block = caller_ir.new_block(self._new_block_name("guard"))
        
        # Create deopt block (calls Python fallback)
        deopt_block = caller_ir.new_block(self._new_block_name("deopt"))
        
        # Create continue block (after inlined code)
        continue_block = caller_ir.new_block(self._new_block_name("continue"))
        
        # Create guards
        guards = create_inline_guards(
            candidate.callee,
            sample_args=tuple(),  # Will be checked at runtime
        )
        
        # Emit guard checks in guard block
        self._emit_guards(caller_ir, guard_block, guards, call_args, deopt_block, continue_block)
        
        # Copy callee blocks with renaming
        value_map: Dict[str, IRValue] = {}
        block_map: Dict[str, IRBasicBlock] = {}
        
        # Map arguments to call args
        for arg_name, call_arg in zip(callee_ir.arg_names, call_args):
            value_map[arg_name] = call_arg
        
        # Copy blocks
        inlined_blocks = []
        result_value = None
        
        for callee_block in callee_ir.blocks:
            new_block = caller_ir.new_block(self._new_block_name(f"inlined_{callee_block.name}"))
            block_map[callee_block.name] = new_block
            inlined_blocks.append(new_block)
            
            for inst in callee_block.instructions:
                new_inst = self._copy_instruction(inst, value_map, caller_ir)
                new_block.append(new_inst)
                
                # Track result value
                if inst.opcode == Opcode.RET and inst.operands:
                    result_value = value_map.get(
                        inst.operands[0].name if isinstance(inst.operands[0], IRValue) else None,
                        inst.operands[0] if isinstance(inst.operands[0], IRValue) else None
                    )
        
        # Link guard block to first inlined block
        if inlined_blocks:
            # Modify the guard block to branch to inline on success
            # (This is simplified - actual implementation would modify the branch)
            pass
        
        # Create deopt info
        deopt_info = DeoptInfo(
            callsite_id=callsite_id,
            original_callee=candidate.callee,
            original_callee_id=candidate.callee_id,
            arg_names=callee_ir.arg_names,
            arg_types=callee_ir.arg_types,
            guard_block_name=guard_block.name,
            deopt_block_name=deopt_block.name,
            continue_block_name=continue_block.name,
        )
        self._deopt_map[callsite_id] = deopt_info
        
        # Emit deopt path (PyObject_Call fallback)
        self._emit_deopt(caller_ir, deopt_block, deopt_info, call_args, continue_block)
        
        # Create inlined callsite record
        inlined = InlinedCallsite(
            callsite_id=callsite_id,
            candidate=candidate,
            guards=guards,
            deopt_info=deopt_info,
            guard_block=guard_block,
            body_blocks=inlined_blocks,
            deopt_block=deopt_block,
        )
        self._inlined_callsites.append(inlined)
        
        # Record in telemetry
        self._telemetry.record_inline_enabled(callsite_id)
        
        # Return result value (or create placeholder)
        if result_value is None:
            result_value = caller_ir.new_value(IRType.f64(), "inline_result")
        
        return result_value, inlined
    
    def _emit_guards(
        self,
        func: IRFunction,
        block: IRBasicBlock,
        guards: InlineGuardSet,
        args: List[IRValue],
        deopt_block: IRBasicBlock,
        continue_block: IRBasicBlock,
    ) -> None:
        """Emit guard instructions in a block."""
        # Guard: check callee identity (id(function) == expected_fn)
        # This is simplified - actual implementation would call C API
        
        # For now, emit placeholder guard instructions
        guard_result = func.new_value(IRType(kind=IRTypeKind.BOOL), "guard_result")
        block.append(IRInstruction(
            opcode=Opcode.GUARD_TYPE,
            result=guard_result,
            operands=[],  # Would include callee pointer and expected ID
            metadata={"expected_callee_id": guards.expected_callee_id},
        ))
        
        # Conditional branch based on guard
        block.append(IRInstruction(
            opcode=Opcode.BR_COND,
            operands=[
                guard_result,
                IRValue(name=continue_block.name, type=IRType.void()),
                IRValue(name=deopt_block.name, type=IRType.void()),
            ],
        ))
    
    def _emit_deopt(
        self,
        func: IRFunction,
        block: IRBasicBlock,
        deopt_info: DeoptInfo,
        args: List[IRValue],
        continue_block: IRBasicBlock,
    ) -> None:
        """Emit deoptimization path that calls Python fallback."""
        # Deopt: call PyObject_Call with original function and args
        # This is the safe fallback path
        
        # Emit a CALL instruction to the fallback
        result = func.new_value(IRType.pyobj(), "deopt_result")
        block.append(IRInstruction(
            opcode=Opcode.CALL,
            result=result,
            operands=["__pyaot_fallback__", *args],
            metadata={
                "is_deopt": True,
                "callsite_id": deopt_info.callsite_id,
                "original_callee_id": deopt_info.original_callee_id,
            },
        ))
        
        # Branch to continue block
        block.append(IRInstruction(
            opcode=Opcode.BR,
            operands=[IRValue(name=continue_block.name, type=IRType.void())],
        ))
    
    def _copy_instruction(
        self,
        inst: IRInstruction,
        value_map: Dict[str, IRValue],
        func: IRFunction,
    ) -> IRInstruction:
        """Copy an instruction with value renaming."""
        # Map operands
        new_operands = []
        for op in inst.operands:
            if isinstance(op, IRValue):
                if op.name in value_map:
                    new_operands.append(value_map[op.name])
                else:
                    # Create new value
                    new_val = func.new_value(op.type, self._new_value_name(op.name))
                    value_map[op.name] = new_val
                    new_operands.append(new_val)
            else:
                new_operands.append(op)
        
        # Create new result if needed
        new_result = None
        if inst.result:
            new_result = func.new_value(inst.result.type, self._new_value_name(inst.result.name))
            value_map[inst.result.name] = new_result
        
        return IRInstruction(
            opcode=inst.opcode,
            result=new_result,
            operands=new_operands,
            metadata=dict(inst.metadata),
        )
    
    def get_deopt_map(self) -> Dict[str, DeoptInfo]:
        """Get the deoptimization map."""
        return self._deopt_map
    
    def get_inlined_callsites(self) -> List[InlinedCallsite]:
        """Get all inlined callsites."""
        return self._inlined_callsites


class InlinePassManager:
    """
    Manages the inline expansion pass across a module.
    
    Coordinates:
    - Candidate identification
    - Callee IR lowering
    - Inline expansion
    - Guard and deopt generation
    """
    
    def __init__(self):
        self._pass = IRInlinePass()
        self._config = get_config()
        self._telemetry = get_telemetry()
        self._lowered_callees: Dict[int, IRFunction] = {}
    
    def process_module(
        self,
        module: IRModule,
        candidates: List[InlineCandidate],
        callee_map: Dict[int, Callable],
    ) -> IRModule:
        """
        Process a module, inlining eligible callsites.
        
        Args:
            module: The IR module to process.
            candidates: List of inline candidates.
            callee_map: Map from callee_id to callee function.
            
        Returns:
            Modified IR module with inlined callsites.
        """
        if not self._config.inline_enabled:
            return module
        
        for candidate in candidates:
            callee = callee_map.get(candidate.callee_id)
            if not callee:
                continue
            
            # Check if we can inline
            can_inline, reason = self._pass.can_inline_callee(callee)
            if not can_inline:
                if self._config.inline_log_rejections:
                    self._telemetry.record_rejection(
                        candidate.callsite_id,
                        RejectionReason(reason.value) if reason else RejectionReason.NO_SOURCE,
                        f"Cannot inline: {reason}",
                    )
                continue
            
            # Lower callee to IR
            callee_id = id(callee)
            if callee_id not in self._lowered_callees:
                arg_types = self._infer_arg_types(candidate)
                callee_ir = self._pass.lower_callee_to_ir(callee, arg_types)
                if callee_ir:
                    self._lowered_callees[callee_id] = callee_ir
            
            callee_ir = self._lowered_callees.get(callee_id)
            if not callee_ir:
                continue
            
            # For each function in module, look for call sites
            # (Simplified - actual implementation would track call sites)
        
        return module
    
    def _infer_arg_types(self, candidate: InlineCandidate) -> List[IRType]:
        """Infer IR types from candidate arg types."""
        type_map = {
            "int": IRType.i64(),
            "float": IRType.f64(),
            "bool": IRType(kind=IRTypeKind.BOOL),
        }
        return [type_map.get(t, IRType.f64()) for t in candidate.arg_types]
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get inline pass statistics."""
        return {
            "inlined_callsites": len(self._pass.get_inlined_callsites()),
            "lowered_callees": len(self._lowered_callees),
            "deopt_points": len(self._pass.get_deopt_map()),
        }

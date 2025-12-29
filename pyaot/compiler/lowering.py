"""
AST to IR lowering for PyAOT.

Transforms Python AST into the PyAOT IR for compilation.
"""

import ast
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass

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
from pyaot.types.inference import InferredType, FunctionSignature, IRTypeKind as TypeKind
from pyaot.exceptions import CompilationError


def _convert_type(itype: InferredType) -> IRType:
    """Convert an InferredType to IRType."""
    mapping = {
        TypeKind.VOID: IRTypeKind.VOID,
        TypeKind.BOOL: IRTypeKind.BOOL,
        TypeKind.INT32: IRTypeKind.INT32,
        TypeKind.INT64: IRTypeKind.INT64,
        TypeKind.FLOAT32: IRTypeKind.FLOAT32,
        TypeKind.FLOAT64: IRTypeKind.FLOAT64,
        TypeKind.NDARRAY: IRTypeKind.ARRAY,
        TypeKind.OBJECT: IRTypeKind.PTR,
    }
    kind = mapping.get(itype.kind, IRTypeKind.PTR)
    
    if kind == IRTypeKind.ARRAY:
        elem_type = IRType.f64()  # Default to float64 for arrays
        if itype.dtype:
            if "int" in itype.dtype:
                elem_type = IRType.i64()
            elif "float32" in itype.dtype:
                elem_type = IRType.f32()
        return IRType.array(elem_type, itype.shape)
    
    return IRType(kind=kind)


@dataclass
class LoweringContext:
    """Context for AST lowering."""
    function: IRFunction
    current_block: IRBasicBlock
    loop_break_target: Optional[IRBasicBlock] = None
    loop_continue_target: Optional[IRBasicBlock] = None


class ASTLowerer:
    """Lowers Python AST to PyAOT IR.
    
    Handles the subset of Python that is compilable:
    - Numeric operations
    - Loops
    - Function calls (to whitelisted functions)
    - Array indexing
    """
    
    def __init__(self):
        self.module: Optional[IRModule] = None
        self.ctx: Optional[LoweringContext] = None
    
    def lower_function(
        self,
        func_ast: ast.FunctionDef,
        signature: FunctionSignature,
        module_name: str = "main",
    ) -> IRFunction:
        """Lower a function AST to IR.
        
        Args:
            func_ast: The function definition AST node.
            signature: The inferred type signature.
            module_name: Name of the containing module.
            
        Returns:
            The lowered IRFunction.
            
        Raises:
            CompilationError: If lowering fails.
        """
        # Create module if needed
        if self.module is None:
            self.module = IRModule(name=module_name)
        
        # Convert types
        arg_types = [_convert_type(t) for t in signature.arg_types]
        return_type = _convert_type(signature.return_type)
        
        # Create function
        func = IRFunction(
            name=func_ast.name,
            return_type=return_type,
            arg_names=signature.arg_names,
            arg_types=arg_types,
        )
        
        # Create entry block
        entry = func.new_block("entry")
        
        # Set up context
        self.ctx = LoweringContext(
            function=func,
            current_block=entry,
        )
        
        # Lower function body
        try:
            for stmt in func_ast.body:
                self._lower_stmt(stmt)
            
            # Ensure function returns
            if not self.ctx.current_block.is_terminated():
                self._emit(IRInstruction(
                    opcode=Opcode.RET,
                    operands=[],
                ))
        except Exception as e:
            raise CompilationError(
                f"Failed to lower {func_ast.name}: {e}",
                function_name=func_ast.name,
                phase="lowering",
            )
        
        # Add to module
        self.module.add_function(func)
        
        return func
    
    def _emit(self, inst: IRInstruction) -> Optional[IRValue]:
        """Emit an instruction to the current block."""
        self.ctx.current_block.append(inst)
        return inst.result
    
    def _lower_stmt(self, stmt: ast.AST) -> None:
        """Lower a statement."""
        if isinstance(stmt, ast.Return):
            self._lower_return(stmt)
        elif isinstance(stmt, ast.Assign):
            self._lower_assign(stmt)
        elif isinstance(stmt, ast.AugAssign):
            self._lower_aug_assign(stmt)
        elif isinstance(stmt, ast.For):
            self._lower_for(stmt)
        elif isinstance(stmt, ast.While):
            self._lower_while(stmt)
        elif isinstance(stmt, ast.If):
            self._lower_if(stmt)
        elif isinstance(stmt, ast.Expr):
            # Expression statement (e.g., function call)
            self._lower_expr(stmt.value)
        elif isinstance(stmt, ast.Pass):
            pass  # No-op
        elif isinstance(stmt, ast.Break):
            if self.ctx.loop_break_target:
                self._emit(IRInstruction(
                    opcode=Opcode.BR,
                    operands=[self.ctx.loop_break_target],
                ))
        elif isinstance(stmt, ast.Continue):
            if self.ctx.loop_continue_target:
                self._emit(IRInstruction(
                    opcode=Opcode.BR,
                    operands=[self.ctx.loop_continue_target],
                ))
        else:
            raise CompilationError(
                f"Unsupported statement type: {type(stmt).__name__}",
                phase="lowering",
            )
    
    def _lower_return(self, stmt: ast.Return) -> None:
        """Lower a return statement."""
        if stmt.value:
            value = self._lower_expr(stmt.value)
            self._emit(IRInstruction(
                opcode=Opcode.RET,
                operands=[value],
            ))
        else:
            self._emit(IRInstruction(
                opcode=Opcode.RET,
                operands=[],
            ))
    
    def _lower_assign(self, stmt: ast.Assign) -> None:
        """Lower an assignment statement."""
        value = self._lower_expr(stmt.value)
        
        for target in stmt.targets:
            if isinstance(target, ast.Name):
                # Simple variable assignment
                self.ctx.function.set_local(target.id, value)
            elif isinstance(target, ast.Subscript):
                # Array assignment
                self._lower_subscript_assign(target, value)
            else:
                raise CompilationError(
                    f"Unsupported assignment target: {type(target).__name__}",
                    phase="lowering",
                )
    
    def _lower_aug_assign(self, stmt: ast.AugAssign) -> None:
        """Lower an augmented assignment (+=, etc.)."""
        if isinstance(stmt.target, ast.Name):
            name = stmt.target.id
            current = self.ctx.function.get_local(name)
            if current is None:
                raise CompilationError(
                    f"Undefined variable: {name}",
                    phase="lowering",
                )
            
            right = self._lower_expr(stmt.value)
            result = self._lower_binop(stmt.op, current, right)
            self.ctx.function.set_local(name, result)
        else:
            raise CompilationError(
                f"Unsupported augmented assignment target",
                phase="lowering",
            )
    
    def _lower_for(self, stmt: ast.For) -> None:
        """Lower a for loop.
        
        Currently supports: for i in range(n)
        """
        # Create blocks
        header = self.ctx.function.new_block("for_header")
        body = self.ctx.function.new_block("for_body")
        after = self.ctx.function.new_block("for_after")
        
        # Check for range() pattern
        if not self._is_range_loop(stmt):
            raise CompilationError(
                "Only `for i in range(...)` loops are supported",
                phase="lowering",
            )
        
        # Get range bounds
        start, end, step = self._get_range_bounds(stmt.iter)
        
        # Initialize loop variable
        if isinstance(stmt.target, ast.Name):
            loop_var = stmt.target.id
        else:
            raise CompilationError(
                "Loop variable must be a simple name",
                phase="lowering",
            )
        
        # Branch to header
        self._emit(IRInstruction(
            opcode=Opcode.BR,
            operands=[header],
        ))
        
        # Header: check condition
        self.ctx.current_block = header
        iter_val = self.ctx.function.get_local(loop_var)
        if iter_val is None:
            # Initialize with start
            iter_val = self.ctx.function.new_value(IRType.i64(), "iter")
            self._emit(IRInstruction(
                opcode=Opcode.CONST_INT,
                result=iter_val,
                operands=[start],
            ))
            self.ctx.function.set_local(loop_var, iter_val)
        
        # Compare
        cmp_result = self.ctx.function.new_value(IRType(kind=IRTypeKind.BOOL), "cmp")
        self._emit(IRInstruction(
            opcode=Opcode.LT,
            result=cmp_result,
            operands=[iter_val, end],
        ))
        
        # Conditional branch
        self._emit(IRInstruction(
            opcode=Opcode.BR_COND,
            operands=[cmp_result, body, after],
        ))
        
        # Body
        self.ctx.current_block = body
        old_break = self.ctx.loop_break_target
        old_continue = self.ctx.loop_continue_target
        self.ctx.loop_break_target = after
        self.ctx.loop_continue_target = header
        
        for body_stmt in stmt.body:
            self._lower_stmt(body_stmt)
        
        # Increment loop variable
        new_iter = self.ctx.function.new_value(IRType.i64(), "iter")
        self._emit(IRInstruction(
            opcode=Opcode.ADD,
            result=new_iter,
            operands=[iter_val, step],
        ))
        self.ctx.function.set_local(loop_var, new_iter)
        
        # Branch back to header
        if not self.ctx.current_block.is_terminated():
            self._emit(IRInstruction(
                opcode=Opcode.BR,
                operands=[header],
            ))
        
        # Restore context
        self.ctx.loop_break_target = old_break
        self.ctx.loop_continue_target = old_continue
        
        # Continue after loop
        self.ctx.current_block = after
    
    def _lower_while(self, stmt: ast.While) -> None:
        """Lower a while loop."""
        header = self.ctx.function.new_block("while_header")
        body = self.ctx.function.new_block("while_body")
        after = self.ctx.function.new_block("while_after")
        
        # Branch to header
        self._emit(IRInstruction(
            opcode=Opcode.BR,
            operands=[header],
        ))
        
        # Header: check condition
        self.ctx.current_block = header
        cond = self._lower_expr(stmt.test)
        
        self._emit(IRInstruction(
            opcode=Opcode.BR_COND,
            operands=[cond, body, after],
        ))
        
        # Body
        self.ctx.current_block = body
        old_break = self.ctx.loop_break_target
        old_continue = self.ctx.loop_continue_target
        self.ctx.loop_break_target = after
        self.ctx.loop_continue_target = header
        
        for body_stmt in stmt.body:
            self._lower_stmt(body_stmt)
        
        if not self.ctx.current_block.is_terminated():
            self._emit(IRInstruction(
                opcode=Opcode.BR,
                operands=[header],
            ))
        
        self.ctx.loop_break_target = old_break
        self.ctx.loop_continue_target = old_continue
        
        self.ctx.current_block = after
    
    def _lower_if(self, stmt: ast.If) -> None:
        """Lower an if statement."""
        then_block = self.ctx.function.new_block("if_then")
        else_block = self.ctx.function.new_block("if_else")
        after = self.ctx.function.new_block("if_after")
        
        # Condition
        cond = self._lower_expr(stmt.test)
        self._emit(IRInstruction(
            opcode=Opcode.BR_COND,
            operands=[cond, then_block, else_block if stmt.orelse else after],
        ))
        
        # Then branch
        self.ctx.current_block = then_block
        for body_stmt in stmt.body:
            self._lower_stmt(body_stmt)
        if not self.ctx.current_block.is_terminated():
            self._emit(IRInstruction(
                opcode=Opcode.BR,
                operands=[after],
            ))
        
        # Else branch
        if stmt.orelse:
            self.ctx.current_block = else_block
            for else_stmt in stmt.orelse:
                self._lower_stmt(else_stmt)
            if not self.ctx.current_block.is_terminated():
                self._emit(IRInstruction(
                    opcode=Opcode.BR,
                    operands=[after],
                ))
        
        self.ctx.current_block = after
    
    def _lower_expr(self, expr: ast.AST) -> IRValue:
        """Lower an expression to a value."""
        if isinstance(expr, ast.Constant):
            return self._lower_constant(expr)
        elif isinstance(expr, ast.Name):
            return self._lower_name(expr)
        elif isinstance(expr, ast.BinOp):
            left = self._lower_expr(expr.left)
            right = self._lower_expr(expr.right)
            return self._lower_binop(expr.op, left, right)
        elif isinstance(expr, ast.UnaryOp):
            operand = self._lower_expr(expr.operand)
            return self._lower_unaryop(expr.op, operand)
        elif isinstance(expr, ast.Compare):
            return self._lower_compare(expr)
        elif isinstance(expr, ast.Call):
            return self._lower_call(expr)
        elif isinstance(expr, ast.Subscript):
            return self._lower_subscript(expr)
        elif isinstance(expr, ast.BoolOp):
            return self._lower_boolop(expr)
        else:
            raise CompilationError(
                f"Unsupported expression type: {type(expr).__name__}",
                phase="lowering",
            )
    
    def _lower_constant(self, expr: ast.Constant) -> IRValue:
        """Lower a constant."""
        value = expr.value
        
        if isinstance(value, bool):
            result = self.ctx.function.new_value(IRType(kind=IRTypeKind.BOOL), "c")
            self._emit(IRInstruction(
                opcode=Opcode.CONST_BOOL,
                result=result,
                operands=[value],
            ))
        elif isinstance(value, int):
            result = self.ctx.function.new_value(IRType.i64(), "c")
            self._emit(IRInstruction(
                opcode=Opcode.CONST_INT,
                result=result,
                operands=[value],
            ))
        elif isinstance(value, float):
            result = self.ctx.function.new_value(IRType.f64(), "c")
            self._emit(IRInstruction(
                opcode=Opcode.CONST_FLOAT,
                result=result,
                operands=[value],
            ))
        else:
            raise CompilationError(
                f"Unsupported constant type: {type(value).__name__}",
                phase="lowering",
            )
        
        return result
    
    def _lower_name(self, expr: ast.Name) -> IRValue:
        """Lower a name reference."""
        value = self.ctx.function.get_local(expr.id)
        if value is None:
            raise CompilationError(
                f"Undefined variable: {expr.id}",
                phase="lowering",
            )
        return value
    
    def _lower_binop(self, op: ast.operator, left: IRValue, right: IRValue) -> IRValue:
        """Lower a binary operation."""
        # Determine if float or int operation
        is_float = (
            left.type.kind in (IRTypeKind.FLOAT32, IRTypeKind.FLOAT64) or
            right.type.kind in (IRTypeKind.FLOAT32, IRTypeKind.FLOAT64)
        )
        
        result_type = IRType.f64() if is_float else IRType.i64()
        result = self.ctx.function.new_value(result_type, "binop")
        
        opcode_map = {
            ast.Add: Opcode.FADD if is_float else Opcode.ADD,
            ast.Sub: Opcode.FSUB if is_float else Opcode.SUB,
            ast.Mult: Opcode.FMUL if is_float else Opcode.MUL,
            ast.Div: Opcode.FDIV if is_float else Opcode.DIV,
            ast.Mod: Opcode.MOD,
            ast.FloorDiv: Opcode.DIV,
        }
        
        opcode = opcode_map.get(type(op))
        if opcode is None:
            raise CompilationError(
                f"Unsupported binary operator: {type(op).__name__}",
                phase="lowering",
            )
        
        self._emit(IRInstruction(
            opcode=opcode,
            result=result,
            operands=[left, right],
        ))
        
        return result
    
    def _lower_unaryop(self, op: ast.unaryop, operand: IRValue) -> IRValue:
        """Lower a unary operation."""
        is_float = operand.type.kind in (IRTypeKind.FLOAT32, IRTypeKind.FLOAT64)
        
        if isinstance(op, ast.USub):
            result = self.ctx.function.new_value(operand.type, "neg")
            self._emit(IRInstruction(
                opcode=Opcode.FNEG if is_float else Opcode.NEG,
                result=result,
                operands=[operand],
            ))
            return result
        elif isinstance(op, ast.Not):
            # Logical not
            result = self.ctx.function.new_value(IRType(kind=IRTypeKind.BOOL), "not")
            self._emit(IRInstruction(
                opcode=Opcode.EQ,
                result=result,
                operands=[operand, 0],  # not x = (x == 0)
            ))
            return result
        else:
            raise CompilationError(
                f"Unsupported unary operator: {type(op).__name__}",
                phase="lowering",
            )
    
    def _lower_compare(self, expr: ast.Compare) -> IRValue:
        """Lower a comparison expression."""
        left = self._lower_expr(expr.left)
        
        # Handle chain comparisons by ANDing them
        result = None
        for op, comparator in zip(expr.ops, expr.comparators):
            right = self._lower_expr(comparator)
            
            opcode_map = {
                ast.Eq: Opcode.EQ,
                ast.NotEq: Opcode.NE,
                ast.Lt: Opcode.LT,
                ast.LtE: Opcode.LE,
                ast.Gt: Opcode.GT,
                ast.GtE: Opcode.GE,
            }
            
            opcode = opcode_map.get(type(op))
            if opcode is None:
                raise CompilationError(
                    f"Unsupported comparison: {type(op).__name__}",
                    phase="lowering",
                )
            
            cmp_result = self.ctx.function.new_value(IRType(kind=IRTypeKind.BOOL), "cmp")
            self._emit(IRInstruction(
                opcode=opcode,
                result=cmp_result,
                operands=[left, right],
            ))
            
            if result is None:
                result = cmp_result
            else:
                # AND with previous result
                and_result = self.ctx.function.new_value(IRType(kind=IRTypeKind.BOOL), "and")
                self._emit(IRInstruction(
                    opcode=Opcode.MUL,  # bool AND = multiply
                    result=and_result,
                    operands=[result, cmp_result],
                ))
                result = and_result
            
            left = right
        
        return result
    
    def _lower_call(self, expr: ast.Call) -> IRValue:
        """Lower a function call."""
        # Get function name
        if isinstance(expr.func, ast.Name):
            func_name = expr.func.id
        elif isinstance(expr.func, ast.Attribute):
            # e.g., np.sum
            func_name = f"{self._get_attr_name(expr.func)}"
        else:
            raise CompilationError(
                f"Unsupported call target",
                phase="lowering",
            )
        
        # Lower arguments
        args = [self._lower_expr(arg) for arg in expr.args]
        
        # Create call instruction
        result = self.ctx.function.new_value(IRType.f64(), "call")
        self._emit(IRInstruction(
            opcode=Opcode.CALL,
            result=result,
            operands=[func_name] + args,
        ))
        
        return result
    
    def _lower_subscript(self, expr: ast.Subscript) -> IRValue:
        """Lower array subscript."""
        array = self._lower_expr(expr.value)
        index = self._lower_expr(expr.slice)
        
        result = self.ctx.function.new_value(IRType.f64(), "elem")
        self._emit(IRInstruction(
            opcode=Opcode.ARRAY_LOAD,
            result=result,
            operands=[array, index],
        ))
        
        return result
    
    def _lower_subscript_assign(self, target: ast.Subscript, value: IRValue) -> None:
        """Lower array subscript assignment."""
        array = self._lower_expr(target.value)
        index = self._lower_expr(target.slice)
        
        self._emit(IRInstruction(
            opcode=Opcode.ARRAY_STORE,
            operands=[array, index, value],
        ))
    
    def _lower_boolop(self, expr: ast.BoolOp) -> IRValue:
        """Lower boolean operations (and, or)."""
        result = self._lower_expr(expr.values[0])
        
        for value in expr.values[1:]:
            right = self._lower_expr(value)
            new_result = self.ctx.function.new_value(IRType(kind=IRTypeKind.BOOL), "bool")
            
            if isinstance(expr.op, ast.And):
                self._emit(IRInstruction(
                    opcode=Opcode.MUL,
                    result=new_result,
                    operands=[result, right],
                ))
            else:  # Or
                # a or b = not (not a and not b) = 1 - (1-a)*(1-b)
                # Simplified: check if either is nonzero
                self._emit(IRInstruction(
                    opcode=Opcode.ADD,
                    result=new_result,
                    operands=[result, right],
                ))
            
            result = new_result
        
        return result
    
    def _is_range_loop(self, stmt: ast.For) -> bool:
        """Check if loop is `for i in range(...)`."""
        if not isinstance(stmt.iter, ast.Call):
            return False
        if not isinstance(stmt.iter.func, ast.Name):
            return False
        return stmt.iter.func.id == "range"
    
    def _get_range_bounds(self, call: ast.Call) -> Tuple[int, IRValue, int]:
        """Get start, end, step from range() call."""
        args = call.args
        
        if len(args) == 1:
            start = 0
            end = self._lower_expr(args[0])
            step = 1
        elif len(args) == 2:
            start = args[0].value if isinstance(args[0], ast.Constant) else 0
            end = self._lower_expr(args[1])
            step = 1
        elif len(args) == 3:
            start = args[0].value if isinstance(args[0], ast.Constant) else 0
            end = self._lower_expr(args[1])
            step = args[2].value if isinstance(args[2], ast.Constant) else 1
        else:
            raise CompilationError(
                "range() requires 1-3 arguments",
                phase="lowering",
            )
        
        return start, end, step
    
    def _get_attr_name(self, node: ast.Attribute) -> str:
        """Get full attribute name (e.g., 'np.sum')."""
        parts = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if isinstance(node, ast.Name):
            parts.append(node.id)
        return ".".join(reversed(parts))

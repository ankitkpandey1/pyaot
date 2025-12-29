"""
LLVM code generation for PyAOT.

Uses llvmlite to generate native code from the PyAOT IR.
"""

from __future__ import annotations

import ctypes
from typing import Dict, Optional, Callable, Any, TYPE_CHECKING
from dataclasses import dataclass
import platform
import tempfile
import os

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
from pyaot.exceptions import CompilationError
from pyaot.logging import log_compilation_start, log_compilation_complete

# Try to import llvmlite
try:
    from llvmlite import ir as llvm_ir
    from llvmlite import binding as llvm
    LLVMLITE_AVAILABLE = True
except ImportError:
    LLVMLITE_AVAILABLE = False
    llvm = None
    llvm_ir = None


@dataclass
class CompiledArtifact:
    """A compiled native artifact."""
    function_ptr: int
    callable: Callable
    ir_hash: str
    source_file: Optional[str] = None
    

class LLVMCodegen:
    """Generates LLVM IR and native code from PyAOT IR.
    
    Uses llvmlite for code generation and JIT compilation.
    """
    
    def __init__(self):
        if not LLVMLITE_AVAILABLE:
            raise CompilationError(
                "llvmlite is not installed. Install with: pip install llvmlite",
                phase="codegen",
            )
        
        # Initialize LLVM targets (required for llvmlite 0.46+)
        # Note: llvm.initialize() is deprecated - use specific initializers
        llvm.initialize_all_targets()
        llvm.initialize_native_target()
        llvm.initialize_native_asmprinter()
        
        self._module = None
        self._builder = None
        self._func = None
        self._values: Dict[str, Any] = {}
        self._blocks: Dict[str, Any] = {}
    
    def compile_module(self, ir_module: IRModule) -> Dict[str, CompiledArtifact]:
        """Compile an IR module to native code.
        
        Args:
            ir_module: The IR module to compile.
            
        Returns:
            Dict mapping function names to CompiledArtifact objects.
        """
        import time
        start = time.perf_counter()
        
        # Create LLVM module
        self._module = llvm_ir.Module(name=ir_module.name)
        self._module.triple = llvm.get_default_triple()
        
        # Compile each function
        for func in ir_module.functions.values():
            log_compilation_start(func.name)
            self._compile_function(func)
        
        # Create execution engine
        artifacts = self._create_artifacts(ir_module)
        
        duration_ms = (time.perf_counter() - start) * 1000
        for name in artifacts:
            log_compilation_complete(name, duration_ms / len(artifacts))
        
        return artifacts
    
    def compile_function(self, ir_func: IRFunction) -> CompiledArtifact:
        """Compile a single IR function.
        
        Args:
            ir_func: The IR function to compile.
            
        Returns:
            CompiledArtifact with function pointer and callable wrapper.
        """
        import time
        start = time.perf_counter()
        log_compilation_start(ir_func.name)
        
        # Create module for this function
        self._module = llvm_ir.Module(name=f"module_{ir_func.name}")
        self._module.triple = llvm.get_default_triple()
        
        # Compile the function
        self._compile_function(ir_func)
        
        # Create execution engine and get artifact
        ir_module = IRModule(name=f"module_{ir_func.name}")
        ir_module.add_function(ir_func)
        artifacts = self._create_artifacts(ir_module)
        
        duration_ms = (time.perf_counter() - start) * 1000
        log_compilation_complete(ir_func.name, duration_ms)
        
        return artifacts[ir_func.name]
    
    def _compile_function(self, ir_func: IRFunction) -> Any:
        """Compile an IR function to LLVM IR."""
        self._values.clear()
        self._blocks.clear()
        
        # Create function type
        arg_types = [self._to_llvm_type(t) for t in ir_func.arg_types]
        ret_type = self._to_llvm_type(ir_func.return_type)
        func_type = llvm_ir.FunctionType(ret_type, arg_types)
        
        # Create function
        self._func = llvm_ir.Function(self._module, func_type, name=ir_func.name)
        
        # Name arguments
        for arg, name in zip(self._func.args, ir_func.arg_names):
            arg.name = name
            self._values[name] = arg
        
        # Create blocks first (for forward references)
        for ir_block in ir_func.blocks:
            block = self._func.append_basic_block(ir_block.name)
            self._blocks[ir_block.name] = block
        
        # Generate code for each block
        for ir_block in ir_func.blocks:
            block = self._blocks[ir_block.name]
            self._builder = llvm_ir.IRBuilder(block)
            
            for inst in ir_block.instructions:
                self._compile_instruction(inst)
        
        return self._func
    
    def _compile_instruction(self, inst: IRInstruction) -> None:
        """Compile a single IR instruction."""
        opcode = inst.opcode
        
        # Constants
        if opcode == Opcode.CONST_INT:
            value = llvm_ir.Constant(llvm_ir.IntType(64), inst.operands[0])
            self._values[inst.result.name] = value
        
        elif opcode == Opcode.CONST_FLOAT:
            value = llvm_ir.Constant(llvm_ir.DoubleType(), inst.operands[0])
            self._values[inst.result.name] = value
        
        elif opcode == Opcode.CONST_BOOL:
            value = llvm_ir.Constant(llvm_ir.IntType(1), int(inst.operands[0]))
            self._values[inst.result.name] = value
        
        # Arithmetic (integer)
        elif opcode == Opcode.ADD:
            left = self._get_value(inst.operands[0])
            right = self._get_value(inst.operands[1])
            result = self._builder.add(left, right, name=inst.result.name)
            self._values[inst.result.name] = result
        
        elif opcode == Opcode.SUB:
            left = self._get_value(inst.operands[0])
            right = self._get_value(inst.operands[1])
            result = self._builder.sub(left, right, name=inst.result.name)
            self._values[inst.result.name] = result
        
        elif opcode == Opcode.MUL:
            left = self._get_value(inst.operands[0])
            right = self._get_value(inst.operands[1])
            result = self._builder.mul(left, right, name=inst.result.name)
            self._values[inst.result.name] = result
        
        elif opcode == Opcode.DIV:
            left = self._get_value(inst.operands[0])
            right = self._get_value(inst.operands[1])
            result = self._builder.sdiv(left, right, name=inst.result.name)
            self._values[inst.result.name] = result
        
        elif opcode == Opcode.NEG:
            operand = self._get_value(inst.operands[0])
            result = self._builder.neg(operand, name=inst.result.name)
            self._values[inst.result.name] = result
        
        # Arithmetic (floating point)
        elif opcode == Opcode.FADD:
            left = self._get_value(inst.operands[0])
            right = self._get_value(inst.operands[1])
            result = self._builder.fadd(left, right, name=inst.result.name)
            self._values[inst.result.name] = result
        
        elif opcode == Opcode.FSUB:
            left = self._get_value(inst.operands[0])
            right = self._get_value(inst.operands[1])
            result = self._builder.fsub(left, right, name=inst.result.name)
            self._values[inst.result.name] = result
        
        elif opcode == Opcode.FMUL:
            left = self._get_value(inst.operands[0])
            right = self._get_value(inst.operands[1])
            result = self._builder.fmul(left, right, name=inst.result.name)
            self._values[inst.result.name] = result
        
        elif opcode == Opcode.FDIV:
            left = self._get_value(inst.operands[0])
            right = self._get_value(inst.operands[1])
            result = self._builder.fdiv(left, right, name=inst.result.name)
            self._values[inst.result.name] = result
        
        elif opcode == Opcode.FNEG:
            operand = self._get_value(inst.operands[0])
            result = self._builder.fneg(operand, name=inst.result.name)
            self._values[inst.result.name] = result
        
        # Comparisons
        elif opcode == Opcode.LT:
            left = self._get_value(inst.operands[0])
            right = self._get_value(inst.operands[1])
            if self._is_float(left) or self._is_float(right):
                result = self._builder.fcmp_ordered('<', left, right, name=inst.result.name)
            else:
                result = self._builder.icmp_signed('<', left, right, name=inst.result.name)
            self._values[inst.result.name] = result
        
        elif opcode == Opcode.LE:
            left = self._get_value(inst.operands[0])
            right = self._get_value(inst.operands[1])
            if self._is_float(left) or self._is_float(right):
                result = self._builder.fcmp_ordered('<=', left, right, name=inst.result.name)
            else:
                result = self._builder.icmp_signed('<=', left, right, name=inst.result.name)
            self._values[inst.result.name] = result
        
        elif opcode == Opcode.GT:
            left = self._get_value(inst.operands[0])
            right = self._get_value(inst.operands[1])
            if self._is_float(left) or self._is_float(right):
                result = self._builder.fcmp_ordered('>', left, right, name=inst.result.name)
            else:
                result = self._builder.icmp_signed('>', left, right, name=inst.result.name)
            self._values[inst.result.name] = result
        
        elif opcode == Opcode.GE:
            left = self._get_value(inst.operands[0])
            right = self._get_value(inst.operands[1])
            if self._is_float(left) or self._is_float(right):
                result = self._builder.fcmp_ordered('>=', left, right, name=inst.result.name)
            else:
                result = self._builder.icmp_signed('>=', left, right, name=inst.result.name)
            self._values[inst.result.name] = result
        
        elif opcode == Opcode.EQ:
            left = self._get_value(inst.operands[0])
            right = self._get_value(inst.operands[1])
            if self._is_float(left) or self._is_float(right):
                result = self._builder.fcmp_ordered('==', left, right, name=inst.result.name)
            else:
                result = self._builder.icmp_signed('==', left, right, name=inst.result.name)
            self._values[inst.result.name] = result
        
        elif opcode == Opcode.NE:
            left = self._get_value(inst.operands[0])
            right = self._get_value(inst.operands[1])
            if self._is_float(left) or self._is_float(right):
                result = self._builder.fcmp_ordered('!=', left, right, name=inst.result.name)
            else:
                result = self._builder.icmp_signed('!=', left, right, name=inst.result.name)
            self._values[inst.result.name] = result
        
        # Control flow
        elif opcode == Opcode.BR:
            target = self._blocks[inst.operands[0].name]
            self._builder.branch(target)
        
        elif opcode == Opcode.BR_COND:
            cond = self._get_value(inst.operands[0])
            true_block = self._blocks[inst.operands[1].name]
            false_block = self._blocks[inst.operands[2].name]
            self._builder.cbranch(cond, true_block, false_block)
        
        elif opcode == Opcode.RET:
            if inst.operands:
                value = self._get_value(inst.operands[0])
                self._builder.ret(value)
            else:
                self._builder.ret_void()
        
        # Array operations
        elif opcode == Opcode.ARRAY_LOAD:
            array_ptr = self._get_value(inst.operands[0])
            index = self._get_value(inst.operands[1])
            # GEP + load
            elem_ptr = self._builder.gep(
                llvm_ir.DoubleType(),
                array_ptr,
                [index],
                name=f"{inst.result.name}_ptr"
            )
            result = self._builder.load(llvm_ir.DoubleType(), elem_ptr, name=inst.result.name)
            self._values[inst.result.name] = result
        
        elif opcode == Opcode.ARRAY_STORE:
            array_ptr = self._get_value(inst.operands[0])
            index = self._get_value(inst.operands[1])
            value = self._get_value(inst.operands[2])
            elem_ptr = self._builder.gep(
                llvm_ir.DoubleType(),
                array_ptr,
                [index],
            )
            self._builder.store(value, elem_ptr)
        
        # Function calls (simplified - calls external C functions)
        elif opcode == Opcode.CALL:
            func_name = inst.operands[0]
            args = [self._get_value(a) for a in inst.operands[1:]]
            # For now, declare external function if needed
            if func_name not in self._module.globals:
                # Assume double(double) signature for math functions
                func_type = llvm_ir.FunctionType(
                    llvm_ir.DoubleType(),
                    [llvm_ir.DoubleType()] * len(args)
                )
                llvm_ir.Function(self._module, func_type, name=func_name)
            
            callee = self._module.get_global(func_name)
            result = self._builder.call(callee, args, name=inst.result.name)
            self._values[inst.result.name] = result
        
        else:
            raise CompilationError(
                f"Unsupported opcode: {opcode}",
                phase="codegen",
            )
    
    def _get_value(self, operand: Any) -> Any:
        """Get LLVM value for an operand."""
        if isinstance(operand, IRValue):
            return self._values[operand.name]
        elif isinstance(operand, int):
            return llvm_ir.Constant(llvm_ir.IntType(64), operand)
        elif isinstance(operand, float):
            return llvm_ir.Constant(llvm_ir.DoubleType(), operand)
        else:
            raise CompilationError(
                f"Unknown operand type: {type(operand)}",
                phase="codegen",
            )
    
    def _is_float(self, value: Any) -> bool:
        """Check if value is floating point."""
        return isinstance(value.type, (llvm_ir.FloatType, llvm_ir.DoubleType))
    
    def _to_llvm_type(self, ir_type: IRType) -> Any:
        """Convert IR type to LLVM type."""
        mapping = {
            IRTypeKind.VOID: llvm_ir.VoidType(),
            IRTypeKind.BOOL: llvm_ir.IntType(1),
            IRTypeKind.INT32: llvm_ir.IntType(32),
            IRTypeKind.INT64: llvm_ir.IntType(64),
            IRTypeKind.FLOAT32: llvm_ir.FloatType(),
            IRTypeKind.FLOAT64: llvm_ir.DoubleType(),
            IRTypeKind.PTR: llvm_ir.PointerType(llvm_ir.IntType(8)),
            IRTypeKind.ARRAY: llvm_ir.PointerType(llvm_ir.DoubleType()),
        }
        return mapping.get(ir_type.kind, llvm_ir.PointerType(llvm_ir.IntType(8)))
    
    def _create_artifacts(self, ir_module: IRModule) -> Dict[str, CompiledArtifact]:
        """Create executable artifacts from LLVM module."""
        # Verify module
        llvm_ir_str = str(self._module)
        
        try:
            mod = llvm.parse_assembly(llvm_ir_str)
            mod.verify()
        except Exception as e:
            raise CompilationError(
                f"LLVM verification failed: {e}",
                phase="codegen",
            )
        
        # Create execution engine
        target = llvm.Target.from_default_triple()
        target_machine = target.create_target_machine()
        
        backing_mod = llvm.parse_assembly(str(self._module))
        engine = llvm.create_mcjit_compiler(backing_mod, target_machine)
        
        # Get function pointers
        artifacts = {}
        for func_name in ir_module.functions:
            func_ptr = engine.get_function_address(func_name)
            
            # Create ctypes callable
            ir_func = ir_module.get_function(func_name)
            cfunc = self._create_ctypes_wrapper(ir_func, func_ptr)
            
            artifacts[func_name] = CompiledArtifact(
                function_ptr=func_ptr,
                callable=cfunc,
                ir_hash="",  # TODO: compute hash
            )
        
        # Keep engine alive (prevent garbage collection)
        for artifact in artifacts.values():
            artifact._engine = engine
        
        return artifacts
    
    def _create_ctypes_wrapper(
        self,
        ir_func: IRFunction,
        func_ptr: int,
    ) -> Callable:
        """Create a ctypes wrapper for a native function."""
        # Map IR types to ctypes
        ctype_map = {
            IRTypeKind.VOID: None,
            IRTypeKind.BOOL: ctypes.c_bool,
            IRTypeKind.INT32: ctypes.c_int32,
            IRTypeKind.INT64: ctypes.c_int64,
            IRTypeKind.FLOAT32: ctypes.c_float,
            IRTypeKind.FLOAT64: ctypes.c_double,
            IRTypeKind.PTR: ctypes.c_void_p,
            IRTypeKind.ARRAY: ctypes.c_void_p,
        }
        
        arg_types = [ctype_map[t.kind] for t in ir_func.arg_types]
        ret_type = ctype_map[ir_func.return_type.kind]
        
        func_type = ctypes.CFUNCTYPE(ret_type, *arg_types)
        return func_type(func_ptr)


def compile_function(
    ir_func: IRFunction,
) -> CompiledArtifact:
    """Convenience function to compile a single IR function.
    
    Args:
        ir_func: The IR function to compile.
        
    Returns:
        CompiledArtifact with callable wrapper.
    """
    codegen = LLVMCodegen()
    return codegen.compile_function(ir_func)

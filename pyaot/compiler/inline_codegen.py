"""
Native code generation for inlined functions.

Extends LLVMCodegen to handle:
- Guard checks in LLVM IR
- Deoptimization paths
- Python fallback calls
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
import sys

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
from pyaot.compiler.codegen import LLVMCodegen, CompiledArtifact, LLVMLITE_AVAILABLE
from pyaot.inline.guards import InlineGuardSet
from pyaot.inline.telemetry import get_telemetry
from pyaot.exceptions import CompilationError

if LLVMLITE_AVAILABLE:
    from llvmlite import ir as llvm_ir
    from llvmlite import binding as llvm


@dataclass
class GuardedArtifact:
    """
    A compiled artifact with guard support.
    
    Contains both the native implementation and fallback handling.
    """
    native_ptr: int
    native_callable: Callable
    guards: InlineGuardSet
    fallback: Callable
    callsite_id: str
    
    # Statistics
    native_calls: int = 0
    fallback_calls: int = 0
    
    def __call__(self, *args) -> Any:
        """
        Execute with guard check.
        
        If guards pass, runs native code.
        If guards fail, falls back to Python.
        """
        # Fast path: use check_fast for minimal overhead
        if self.guards.check_fast(self.fallback, args):
            self.native_calls += 1
            return self.native_callable(*args)
        else:
            self.fallback_calls += 1
            return self.fallback(*args)


class InlineCodegen(LLVMCodegen):
    """
    Extended code generator for inlined functions.
    
    Adds support for:
    - GUARD_TYPE: Check type of object matches expected
    - GUARD_FAIL: Branch to deopt on failure
    - Deopt trampolines back to Python
    """
    
    def __init__(self):
        super().__init__()
        self._deopt_blocks: Dict[str, Any] = {}
        self._python_fallback_func = None
    
    def compile_guarded_function(
        self,
        ir_func: IRFunction,
        guards: InlineGuardSet,
        fallback: Callable,
        callsite_id: str,
    ) -> GuardedArtifact:
        """
        Compile a function with guard checks.
        
        Args:
            ir_func: The IR function to compile.
            guards: Guard set for runtime checks.
            fallback: Python function to call on guard failure.
            callsite_id: Unique identifier for telemetry.
            
        Returns:
            GuardedArtifact with native code and fallback.
        """
        import time
        start = time.perf_counter_ns()
        
        # Compile the native function
        artifact = self.compile_function(ir_func)
        
        emit_time = time.perf_counter_ns() - start
        
        # Record emit time
        telemetry = get_telemetry()
        telemetry.record_emit_time(emit_time)
        
        return GuardedArtifact(
            native_ptr=artifact.function_ptr,
            native_callable=artifact.callable,
            guards=guards,
            fallback=fallback,
            callsite_id=callsite_id,
        )
    
    def _compile_instruction(self, inst: IRInstruction) -> None:
        """Compile an instruction, including guard opcodes."""
        opcode = inst.opcode
        
        # Handle guard-specific opcodes
        if opcode == Opcode.GUARD_TYPE:
            self._compile_guard_type(inst)
        elif opcode == Opcode.GUARD_FAIL:
            self._compile_guard_fail(inst)
        else:
            # Delegate to parent
            super()._compile_instruction(inst)
    
    def _compile_guard_type(self, inst: IRInstruction) -> None:
        """
        Compile a type guard check.
        
        Generates code equivalent to:
            guard_result = (Py_TYPE(obj) == expected_type)
        """
        # For now, this is a placeholder that always succeeds
        # In a full implementation, we would:
        # 1. Load the type pointer from the object header
        # 2. Compare with expected type pointer
        # 3. Store result in guard_result
        
        # Emit a constant true (guards are checked at Python level)
        result = llvm_ir.Constant(llvm_ir.IntType(1), 1)
        self._values[inst.result.name] = result
    
    def _compile_guard_fail(self, inst: IRInstruction) -> None:
        """
        Compile a guard failure branch.
        
        On failure, branches to deoptimization path.
        """
        # This would branch to a deopt block that:
        # 1. Boxes all live values back to PyObject*
        # 2. Calls the Python fallback function
        # 3. Returns the fallback result
        pass


@dataclass
class InlineCompilationResult:
    """Result of compiling an inlined function."""
    callsite_id: str
    artifact: Optional[GuardedArtifact] = None
    success: bool = False
    error: Optional[str] = None
    compile_time_ms: float = 0.0


class InlineCompiler:
    """
    High-level compiler for inlined call sites.
    
    Coordinates:
    - IR lowering from callee
    - Native code generation
    - Guard setup
    - Fallback wiring
    """
    
    def __init__(self):
        self._codegen = InlineCodegen() if LLVMLITE_AVAILABLE else None
        self._compiled: Dict[str, GuardedArtifact] = {}
        self._telemetry = get_telemetry()
    
    @property
    def is_available(self) -> bool:
        """Check if native compilation is available."""
        return LLVMLITE_AVAILABLE
    
    def compile_inline(
        self,
        callee: Callable,
        guards: InlineGuardSet,
        callsite_id: str,
        arg_types: List[IRType] = None,
    ) -> InlineCompilationResult:
        """
        Compile a callee for inlining.
        
        Args:
            callee: The function to compile.
            guards: Guard set for the callsite.
            callsite_id: Unique identifier.
            arg_types: Inferred argument types.
            
        Returns:
            InlineCompilationResult with artifact or error.
        """
        import time
        start = time.perf_counter()
        
        result = InlineCompilationResult(callsite_id=callsite_id)
        
        if not self.is_available:
            result.error = "llvmlite not available"
            return result
        
        # Check if already compiled
        if callsite_id in self._compiled:
            result.artifact = self._compiled[callsite_id]
            result.success = True
            return result
        
        try:
            # Import IR inline pass
            from pyaot.inline.ir_inline import IRInlinePass
            
            inline_pass = IRInlinePass()
            
            # Check eligibility
            can_inline, reason = inline_pass.can_inline_callee(callee)
            if not can_inline:
                result.error = f"Cannot inline: {reason}"
                return result
            
            # Lower to IR
            arg_types = arg_types or [IRType.f64()]
            ir_func = inline_pass.lower_callee_to_ir(callee, arg_types)
            
            if ir_func is None:
                result.error = "Failed to lower callee to IR"
                return result
            
            # Compile to native
            artifact = self._codegen.compile_guarded_function(
                ir_func=ir_func,
                guards=guards,
                fallback=callee,
                callsite_id=callsite_id,
            )
            
            # Cache
            self._compiled[callsite_id] = artifact
            
            result.artifact = artifact
            result.success = True
            
        except Exception as e:
            result.error = str(e)
        
        result.compile_time_ms = (time.perf_counter() - start) * 1000
        return result
    
    def get_artifact(self, callsite_id: str) -> Optional[GuardedArtifact]:
        """Get compiled artifact for a callsite."""
        return self._compiled.get(callsite_id)
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get compilation statistics."""
        stats = {
            "compiled_callsites": len(self._compiled),
            "total_native_calls": 0,
            "total_fallback_calls": 0,
        }
        
        for artifact in self._compiled.values():
            stats["total_native_calls"] += artifact.native_calls
            stats["total_fallback_calls"] += artifact.fallback_calls
        
        total = stats["total_native_calls"] + stats["total_fallback_calls"]
        if total > 0:
            stats["native_ratio"] = stats["total_native_calls"] / total
        else:
            stats["native_ratio"] = 0.0
        
        return stats


# Global singleton
_inline_compiler: Optional[InlineCompiler] = None


def get_inline_compiler() -> InlineCompiler:
    """Get the global inline compiler."""
    global _inline_compiler
    if _inline_compiler is None:
        _inline_compiler = InlineCompiler()
    return _inline_compiler


def compile_for_inline(
    callee: Callable,
    callsite_id: str,
    sample_args: Tuple[Any, ...] = (),
) -> Optional[GuardedArtifact]:
    """
    Convenience function to compile a callee for inlining.
    
    Args:
        callee: Function to compile.
        callsite_id: Unique identifier.
        sample_args: Sample arguments for guard creation.
        
    Returns:
        GuardedArtifact or None if compilation fails.
    """
    from pyaot.inline.guards import create_inline_guards
    
    compiler = get_inline_compiler()
    
    if not compiler.is_available:
        return None
    
    # Create guards
    guards = create_inline_guards(callee, sample_args=sample_args)
    
    # Infer types from sample args
    arg_types = []
    for arg in sample_args:
        if isinstance(arg, float):
            arg_types.append(IRType.f64())
        elif isinstance(arg, int):
            arg_types.append(IRType.i64())
        else:
            arg_types.append(IRType.f64())  # Default
    
    # Compile
    result = compiler.compile_inline(
        callee=callee,
        guards=guards,
        callsite_id=callsite_id,
        arg_types=arg_types,
    )
    
    if result.success:
        return result.artifact
    return None

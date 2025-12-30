"""
Callsite Stub Compiler Integration.

Integrates callsite stubs with LLVM codegen for native execution.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional, Tuple, Any
from dataclasses import dataclass

from pyaot.callsite.stub import CallsiteStub, create_stub
from pyaot.callsite.generator import StubGenerator, get_stub_generator
from pyaot.callsite.registry import StubRegistry, get_stub_registry


@dataclass
class StubCompilationResult:
    """Result of stub compilation."""
    success: bool = False
    stub: Optional[CallsiteStub] = None
    native_available: bool = False
    error: Optional[str] = None


class StubCompiler:
    """
    Compiles callsite stubs with native code.
    
    Integrates with LLVM codegen to provide native entry points.
    """
    
    def __init__(self):
        self._generator = get_stub_generator()
        self._registry = get_stub_registry()
        self._compiled_callees: Dict[int, Callable] = {}
    
    def compile_stub(
        self,
        callsite_id: str,
        callee: Callable,
        arg_types: Tuple[type, ...],
    ) -> StubCompilationResult:
        """
        Compile a stub with native code if possible.
        
        Args:
            callsite_id: Unique callsite identifier
            callee: The callee function
            arg_types: Expected argument types
            
        Returns:
            StubCompilationResult
        """
        result = StubCompilationResult()
        
        try:
            # Try to get native callable
            native_callable = self._get_or_compile_native(callee, arg_types)
            
            # Generate stub
            gen_result = self._generator.generate(
                callsite_id=callsite_id,
                callee=callee,
                arg_types=arg_types,
                native_callable=native_callable,
            )
            
            if gen_result.success and gen_result.stub:
                self._registry.register(gen_result.stub)
                result.success = True
                result.stub = gen_result.stub
                result.native_available = native_callable is not None
            else:
                result.error = gen_result.error
                
        except Exception as e:
            result.error = str(e)
        
        return result
    
    def _get_or_compile_native(
        self,
        callee: Callable,
        arg_types: Tuple[type, ...],
    ) -> Optional[Callable]:
        """Get or compile native version of callee."""
        callee_id = id(callee)
        
        if callee_id in self._compiled_callees:
            return self._compiled_callees[callee_id]
        
        # Try to compile with LLVM
        native = self._compile_with_llvm(callee, arg_types)
        
        if native:
            self._compiled_callees[callee_id] = native
        
        return native
    
    def _compile_with_llvm(
        self,
        callee: Callable,
        arg_types: Tuple[type, ...],
    ) -> Optional[Callable]:
        """Compile callee to native code using LLVM."""
        try:
            from pyaot.compiler.codegen import LLVMCodegen, LLVMLITE_AVAILABLE
            from pyaot.compiler.lowering import lower_function
            from pyaot.compiler.ir import IRModule
            
            if not LLVMLITE_AVAILABLE:
                return None
            
            # Lower to IR
            ir_func = lower_function(callee)
            if ir_func is None:
                return None
            
            # Compile
            codegen = LLVMCodegen()
            artifact = codegen.compile_function(ir_func)
            
            if artifact and artifact.callable:
                return artifact.callable
            
        except Exception:
            pass
        
        return None
    
    def execute_via_stub(
        self,
        callsite_id: str,
        *args,
        **kwargs,
    ) -> Tuple[Any, bool]:
        """
        Execute via stub if available.
        
        Returns:
            (result, used_native) tuple
        """
        stub = self._registry.get(callsite_id)
        
        if stub is None:
            return None, False
        
        result = stub.execute(*args, **kwargs)
        used_native = stub.native_calls > stub.fallback_calls
        
        return result, used_native
    
    def get_stats(self) -> Dict[str, Any]:
        """Get compilation statistics."""
        registry_stats = self._registry.get_stats()
        
        return {
            "total_stubs": registry_stats.total_stubs,
            "compiled_callees": len(self._compiled_callees),
            "native_calls": registry_stats.total_native_calls,
            "fallback_calls": registry_stats.total_fallback_calls,
            "native_rate": registry_stats.overall_native_rate,
        }


# Global compiler
_stub_compiler: Optional[StubCompiler] = None


def get_stub_compiler() -> StubCompiler:
    """Get the global stub compiler."""
    global _stub_compiler
    if _stub_compiler is None:
        _stub_compiler = StubCompiler()
    return _stub_compiler


def compile_callsite(
    callsite_id: str,
    callee: Callable,
    arg_types: Tuple[type, ...],
) -> StubCompilationResult:
    """
    Compile a callsite stub with native code.
    
    Convenience function using the global compiler.
    """
    compiler = get_stub_compiler()
    return compiler.compile_stub(callsite_id, callee, arg_types)

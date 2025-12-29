"""Compiler subpackage for PyAOT."""

from pyaot.compiler.ir import (
    IRModule,
    IRFunction,
    IRBasicBlock,
    IRInstruction,
    IRType,
)
from pyaot.compiler.lowering import ASTLowerer
from pyaot.compiler.codegen import LLVMCodegen, compile_function
from pyaot.compiler.numpy_support import NumPySupport
from pyaot.compiler.inline_codegen import (
    InlineCodegen,
    InlineCompiler,
    GuardedArtifact,
    get_inline_compiler,
    compile_for_inline,
)

__all__ = [
    # IR
    "IRModule",
    "IRFunction",
    "IRBasicBlock",
    "IRInstruction",
    "IRType",
    # Lowering
    "ASTLowerer",
    # Codegen
    "LLVMCodegen",
    "compile_function",
    # Inline Codegen (Phase 5)
    "InlineCodegen",
    "InlineCompiler",
    "GuardedArtifact",
    "get_inline_compiler",
    "compile_for_inline",
    # NumPy
    "NumPySupport",
]

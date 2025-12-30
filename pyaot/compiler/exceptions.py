"""
Exception Handling for PyAOT Compiled Code.

Provides try/except support in compiled functions by:
1. Detecting exception handling in AST
2. Generating appropriate IR with exception opcodes
3. Creating landing pads for LLVM unwinding
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple, Type

from pyaot.compiler.ir import (
    IRBasicBlock,
    IRFunction,
    IRInstruction,
    IRType,
    IRValue,
    Opcode,
)


@dataclass
class ExceptionHandler:
    """Represents an exception handler block."""
    exception_types: List[Type[Exception]]
    handler_block: IRBasicBlock
    binding_name: Optional[str] = None  # Name bound to exception (e as e:)


@dataclass
class TryBlock:
    """Represents a try-except-finally structure."""
    try_block: IRBasicBlock
    handlers: List[ExceptionHandler] = field(default_factory=list)
    finally_block: Optional[IRBasicBlock] = None
    exit_block: Optional[IRBasicBlock] = None


@dataclass
class ExceptionState:
    """Current exception state for compiled code."""
    has_exception: bool = False
    exception_type: Optional[Type[Exception]] = None
    exception_value: Optional[Exception] = None
    exception_tb: Optional[Any] = None
    
    def set(self, exc_type: Type, exc_val: Exception, exc_tb: Any) -> None:
        """Set exception state."""
        self.has_exception = True
        self.exception_type = exc_type
        self.exception_value = exc_val
        self.exception_tb = exc_tb
    
    def clear(self) -> None:
        """Clear exception state."""
        self.has_exception = False
        self.exception_type = None
        self.exception_value = None
        self.exception_tb = None


class ExceptionCompiler:
    """
    Compile exception handling constructs.
    
    Transforms Python try/except/finally to IR with proper
    exception propagation and cleanup.
    """
    
    def __init__(self, func: IRFunction):
        self.func = func
        self._try_blocks: List[TryBlock] = []
        self._current_try: Optional[TryBlock] = None
    
    def compile_try_except(
        self,
        try_body: List[ast.stmt],
        handlers: List[ast.ExceptHandler],
        orelse: List[ast.stmt],
        finalbody: List[ast.stmt],
    ) -> Tuple[IRBasicBlock, IRBasicBlock]:
        """
        Compile try-except-finally structure.
        
        Args:
            try_body: Statements in try block
            handlers: Exception handlers
            orelse: Else block (if no exception)
            finalbody: Finally block
            
        Returns:
            Tuple of (entry_block, exit_block)
        """
        # Create blocks
        try_block = self.func.new_block("try")
        exit_block = self.func.new_block("try_exit")
        
        # Create try block structure
        try_struct = TryBlock(
            try_block=try_block,
            exit_block=exit_block,
        )
        
        # Emit try begin marker
        try_block.append(IRInstruction(
            opcode=Opcode.TRY_BEGIN,
            metadata={"try_id": len(self._try_blocks)},
        ))
        
        # Create handler blocks
        for handler in handlers:
            handler_block = self.func.new_block("except")
            
            # Get exception types
            exc_types = self._get_exception_types(handler.type)
            
            # Create handler entry
            handler_block.append(IRInstruction(
                opcode=Opcode.EXCEPT,
                operands=[exc_types],
                metadata={"handler_name": handler.name},
            ))
            
            try_struct.handlers.append(ExceptionHandler(
                exception_types=exc_types,
                handler_block=handler_block,
                binding_name=handler.name,
            ))
        
        # Create finally block if present
        if finalbody:
            finally_block = self.func.new_block("finally")
            finally_block.append(IRInstruction(opcode=Opcode.FINALLY))
            try_struct.finally_block = finally_block
        
        # Emit try end
        try_block.append(IRInstruction(opcode=Opcode.TRY_END))
        
        self._try_blocks.append(try_struct)
        self._current_try = try_struct
        
        return try_block, exit_block
    
    def _get_exception_types(
        self,
        node: Optional[ast.expr],
    ) -> List[Type[Exception]]:
        """Extract exception types from AST node."""
        if node is None:
            # Bare except:
            return [BaseException]
        
        if isinstance(node, ast.Name):
            # Single exception type
            exc_type = self._resolve_exception_type(node.id)
            return [exc_type] if exc_type else [Exception]
        
        if isinstance(node, ast.Tuple):
            # Multiple exception types
            types = []
            for elt in node.elts:
                if isinstance(elt, ast.Name):
                    exc_type = self._resolve_exception_type(elt.id)
                    if exc_type:
                        types.append(exc_type)
            return types or [Exception]
        
        return [Exception]
    
    def _resolve_exception_type(self, name: str) -> Optional[Type[Exception]]:
        """Resolve exception type name to actual type."""
        builtins_exceptions = {
            'Exception': Exception,
            'BaseException': BaseException,
            'ValueError': ValueError,
            'TypeError': TypeError,
            'KeyError': KeyError,
            'IndexError': IndexError,
            'AttributeError': AttributeError,
            'RuntimeError': RuntimeError,
            'StopIteration': StopIteration,
            'ZeroDivisionError': ZeroDivisionError,
            'FileNotFoundError': FileNotFoundError,
            'IOError': IOError,
            'OSError': OSError,
        }
        return builtins_exceptions.get(name)
    
    def compile_raise(
        self,
        exc: Optional[ast.expr],
        cause: Optional[ast.expr],
    ) -> IRInstruction:
        """
        Compile raise statement.
        
        Args:
            exc: Exception to raise (None for re-raise)
            cause: Exception cause (__cause__)
            
        Returns:
            IRInstruction for raise.
        """
        if exc is None:
            # Re-raise current exception
            return IRInstruction(opcode=Opcode.RERAISE)
        
        # Raise new exception
        return IRInstruction(
            opcode=Opcode.RAISE,
            operands=[exc],
            metadata={"has_cause": cause is not None},
        )
    
    def emit_landing_pad(self, block: IRBasicBlock) -> None:
        """
        Emit LLVM landing pad for exception unwinding.
        
        The landing pad catches exceptions and dispatches
        to the appropriate handler.
        """
        if not self._current_try:
            return
        
        # Create landing pad instruction
        landing_pad = IRInstruction(
            opcode=Opcode.LANDING_PAD,
            result=self.func.new_value(IRType.pyobj(), "exc"),
            metadata={
                "handlers": [h.exception_types for h in self._current_try.handlers],
                "finally": self._current_try.finally_block is not None,
            },
        )
        block.append(landing_pad)
        
        # Dispatch to handlers
        for handler in self._current_try.handlers:
            # Check if exception matches this handler
            match_inst = IRInstruction(
                opcode=Opcode.EXCEPT_MATCH,
                result=self.func.new_value(IRType.i1(), "match"),
                operands=[landing_pad.result, handler.exception_types],
            )
            block.append(match_inst)
            
            # Branch to handler if match
            block.append(IRInstruction(
                opcode=Opcode.BR_COND,
                operands=[match_inst.result, handler.handler_block, None],
            ))


class ExceptionRuntime:
    """
    Runtime support for exception handling in compiled code.
    
    Provides:
    - Exception state management
    - Handler dispatch
    - Cleanup coordination
    """
    
    def __init__(self):
        self._state = ExceptionState()
        self._handler_stack: List[TryBlock] = []
    
    def enter_try(self, try_block: TryBlock) -> None:
        """Enter a try block."""
        self._handler_stack.append(try_block)
    
    def exit_try(self) -> None:
        """Exit current try block."""
        if self._handler_stack:
            self._handler_stack.pop()
    
    def handle_exception(
        self,
        exc_type: Type[Exception],
        exc_val: Exception,
        exc_tb: Any,
    ) -> Optional[ExceptionHandler]:
        """
        Handle an exception, finding appropriate handler.
        
        Args:
            exc_type: Exception type
            exc_val: Exception value
            exc_tb: Traceback
            
        Returns:
            Matching ExceptionHandler or None
        """
        self._state.set(exc_type, exc_val, exc_tb)
        
        # Search handler stack from top
        for try_block in reversed(self._handler_stack):
            for handler in try_block.handlers:
                if self._matches(exc_type, handler.exception_types):
                    return handler
        
        return None
    
    def _matches(
        self,
        exc_type: Type[Exception],
        handler_types: List[Type[Exception]],
    ) -> bool:
        """Check if exception type matches handler types."""
        return any(issubclass(exc_type, ht) for ht in handler_types)
    
    def get_current_exception(self) -> Tuple[Optional[Type], Optional[Exception], Optional[Any]]:
        """Get current exception info."""
        return (
            self._state.exception_type,
            self._state.exception_value,
            self._state.exception_tb,
        )
    
    def clear_exception(self) -> None:
        """Clear current exception."""
        self._state.clear()


# Global exception runtime
_exception_runtime: Optional[ExceptionRuntime] = None


def get_exception_runtime() -> ExceptionRuntime:
    """Get global exception runtime."""
    global _exception_runtime
    if _exception_runtime is None:
        _exception_runtime = ExceptionRuntime()
    return _exception_runtime


def try_except_wrapper(func: Callable, handlers: Dict[Type[Exception], Callable]) -> Callable:
    """
    Wrap a function with exception handling.
    
    Args:
        func: Function to wrap
        handlers: Dict mapping exception types to handler functions
        
    Returns:
        Wrapped function with exception handling
    """
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except BaseException as e:
            for exc_type, handler in handlers.items():
                if isinstance(e, exc_type):
                    return handler(e, *args, **kwargs)
            raise
    
    return wrapper

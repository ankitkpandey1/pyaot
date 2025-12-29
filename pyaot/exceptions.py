"""
Exception hierarchy for PyAOT.

All exceptions inherit from AOTError for easy catching.
Guard failures are designed to be silent and trigger fallback.
"""

from typing import Any, Optional, Tuple


class AOTError(Exception):
    """Base exception for all PyAOT errors."""
    
    def __init__(self, message: str, context: Optional[dict] = None):
        super().__init__(message)
        self.context = context or {}


class CompilationError(AOTError):
    """Raised when AOT compilation fails.
    
    This is a recoverable error - the system will fall back to
    interpreted Python execution.
    """
    
    def __init__(
        self,
        message: str,
        function_name: Optional[str] = None,
        phase: Optional[str] = None,
        context: Optional[dict] = None,
    ):
        super().__init__(message, context)
        self.function_name = function_name
        self.phase = phase  # e.g., "lowering", "codegen", "linking"


class GuardFailure(AOTError):
    """Raised when a guard check fails.
    
    This is an expected condition, not an error. The system will
    silently fall back to Python execution. This exception is only
    raised internally and should never propagate to user code.
    """
    
    def __init__(
        self,
        guard_type: str,
        expected: Any,
        actual: Any,
        function_name: Optional[str] = None,
    ):
        message = f"Guard failed: {guard_type} - expected {expected}, got {actual}"
        super().__init__(message)
        self.guard_type = guard_type
        self.expected = expected
        self.actual = actual
        self.function_name = function_name


class CacheError(AOTError):
    """Raised when cache operations fail.
    
    Cache errors are recoverable - the system will recompile.
    """
    
    def __init__(
        self,
        message: str,
        cache_key: Optional[str] = None,
        operation: Optional[str] = None,
        context: Optional[dict] = None,
    ):
        super().__init__(message, context)
        self.cache_key = cache_key
        self.operation = operation  # e.g., "read", "write", "evict"


class EligibilityError(AOTError):
    """Raised when a function is not eligible for AOT compilation.
    
    This provides clear feedback on why a function cannot be compiled.
    """
    
    def __init__(
        self,
        message: str,
        function_name: Optional[str] = None,
        reason: Optional[str] = None,
        disallowed_feature: Optional[str] = None,
        context: Optional[dict] = None,
    ):
        super().__init__(message, context)
        self.function_name = function_name
        self.reason = reason
        self.disallowed_feature = disallowed_feature


class TypeInferenceError(AOTError):
    """Raised when type inference fails or produces unstable results."""
    
    def __init__(
        self,
        message: str,
        function_name: Optional[str] = None,
        type_signatures: Optional[list] = None,
        stability_score: Optional[float] = None,
    ):
        super().__init__(message)
        self.function_name = function_name
        self.type_signatures = type_signatures
        self.stability_score = stability_score


class IRError(AOTError):
    """Raised when IR generation or validation fails."""
    
    def __init__(
        self,
        message: str,
        ir_node: Optional[str] = None,
        context: Optional[dict] = None,
    ):
        super().__init__(message, context)
        self.ir_node = ir_node

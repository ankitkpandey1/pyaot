"""
Diagnostics and Error Reporting for PyAOT.

Provides:
- Rich error messages with context
- Optimization suggestions
- Compilation failure analysis
"""

from __future__ import annotations

import inspect
import traceback
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Tuple


class DiagnosticLevel(Enum):
    """Severity level of diagnostic."""
    INFO = auto()
    WARNING = auto()
    ERROR = auto()
    HINT = auto()


@dataclass
class Diagnostic:
    """A single diagnostic message."""
    level: DiagnosticLevel
    message: str
    source_file: Optional[str] = None
    line_no: Optional[int] = None
    column: Optional[int] = None
    suggestion: Optional[str] = None
    code: Optional[str] = None  # Diagnostic code for filtering
    
    def __str__(self) -> str:
        loc = ""
        if self.source_file:
            loc = f"{self.source_file}"
            if self.line_no:
                loc += f":{self.line_no}"
                if self.column:
                    loc += f":{self.column}"
            loc += ": "
        
        prefix = {
            DiagnosticLevel.INFO: "info",
            DiagnosticLevel.WARNING: "warning",
            DiagnosticLevel.ERROR: "error",
            DiagnosticLevel.HINT: "hint",
        }[self.level]
        
        code_str = f"[{self.code}] " if self.code else ""
        
        result = f"{loc}{prefix}: {code_str}{self.message}"
        if self.suggestion:
            result += f"\n  suggestion: {self.suggestion}"
        
        return result


@dataclass
class DiagnosticContext:
    """Context for diagnostic generation."""
    func: Optional[Callable] = None
    func_name: Optional[str] = None
    source_file: Optional[str] = None
    source_lines: List[str] = field(default_factory=list)
    exception: Optional[Exception] = None


class DiagnosticReporter:
    """
    Rich error messages and optimization hints.
    
    Provides user-friendly diagnostics for:
    - Compilation failures
    - Guard failures
    - Type inference issues
    - Performance opportunities
    """
    
    def __init__(self):
        self._diagnostics: List[Diagnostic] = []
        self._context: Optional[DiagnosticContext] = None
    
    def set_context(self, func: Callable) -> None:
        """Set context for subsequent diagnostics."""
        try:
            source_lines = inspect.getsourcelines(func)[0]
            source_file = inspect.getfile(func)
        except (OSError, TypeError):
            source_lines = []
            source_file = None
        
        self._context = DiagnosticContext(
            func=func,
            func_name=func.__name__,
            source_file=source_file,
            source_lines=source_lines,
        )
    
    def report_compilation_failure(
        self,
        error: Exception,
        phase: str = "compilation",
    ) -> str:
        """
        Generate helpful error message for compilation failure.
        
        Args:
            error: The exception that occurred.
            phase: Compilation phase (lowering, codegen, etc.)
            
        Returns:
            Formatted error message.
        """
        ctx = self._context or DiagnosticContext()
        
        # Main error diagnostic
        main_diag = Diagnostic(
            level=DiagnosticLevel.ERROR,
            message=f"Failed during {phase}: {str(error)}",
            source_file=ctx.source_file,
            code=f"E{hash(type(error).__name__) % 1000:03d}",
        )
        self._diagnostics.append(main_diag)
        
        # Analyze error type
        suggestions = self._analyze_error(error, ctx)
        for suggestion in suggestions:
            self._diagnostics.append(Diagnostic(
                level=DiagnosticLevel.HINT,
                message=suggestion,
                source_file=ctx.source_file,
            ))
        
        return self._format_diagnostics()
    
    def _analyze_error(
        self,
        error: Exception,
        ctx: DiagnosticContext,
    ) -> List[str]:
        """Analyze error and generate suggestions."""
        suggestions = []
        error_msg = str(error).lower()
        
        # Type-related errors
        if "type" in error_msg or "typeerror" in type(error).__name__.lower():
            suggestions.append(
                "Add type hints to function parameters for better type inference"
            )
            suggestions.append(
                "Use @adaptive decorator for automatic type detection"
            )
        
        # Unsupported operation
        if "unsupported" in error_msg or "not implemented" in error_msg:
            suggestions.append(
                "Some Python constructs cannot be compiled to native code"
            )
            suggestions.append(
                "Try simplifying the function or extracting compilable parts"
            )
        
        # LLVM errors
        if "llvm" in error_msg:
            suggestions.append(
                "Check that llvmlite is correctly installed: pip install llvmlite"
            )
        
        return suggestions
    
    def suggest_optimizations(self, func: Callable) -> List[str]:
        """
        Suggest code changes for better optimization.
        
        Args:
            func: Function to analyze.
            
        Returns:
            List of optimization suggestions.
        """
        self.set_context(func)
        suggestions = []
        ctx = self._context
        
        # Check for type hints
        hints = getattr(func, '__annotations__', {})
        if not hints:
            suggestions.append(
                "Add type hints (e.g., def f(x: float) -> float) "
                "for faster compilation without profiling warmup"
            )
        
        # Check for loops
        if ctx and ctx.source_lines:
            source = "".join(ctx.source_lines)
            
            if "for " in source and "range" in source:
                suggestions.append(
                    "Numeric loops may benefit from vectorization. "
                    "Consider using numpy arrays for SIMD optimization"
                )
            
            if source.count("def ") > 1:
                suggestions.append(
                    "Multiple function definitions detected. "
                    "Consider using @adaptive on inner functions"
                )
        
        # Check function size
        try:
            import dis
            code = func.__code__
            if code.co_code and len(code.co_code) > 500:
                suggestions.append(
                    f"Function has {len(code.co_code)} bytecode instructions. "
                    "Consider splitting into smaller functions"
                )
        except Exception:
            pass
        
        return suggestions
    
    def report_guard_failure(
        self,
        expected_types: Tuple,
        actual_types: Tuple,
        func_name: str,
    ) -> str:
        """Report a guard failure with context."""
        diag = Diagnostic(
            level=DiagnosticLevel.WARNING,
            message=(
                f"Guard failure in {func_name}: "
                f"expected {expected_types}, got {actual_types}"
            ),
            code="W001",
            suggestion=(
                "Type mismatch caused fallback to Python. "
                "Call with consistent types for native execution"
            ),
        )
        self._diagnostics.append(diag)
        return str(diag)
    
    def report_ineligible(
        self,
        func: Callable,
        reason: str,
    ) -> str:
        """Report why a function is not eligible for compilation."""
        diag = Diagnostic(
            level=DiagnosticLevel.INFO,
            message=f"Function '{func.__name__}' not compiled: {reason}",
            code="I001",
        )
        self._diagnostics.append(diag)
        return str(diag)
    
    def _format_diagnostics(self) -> str:
        """Format all diagnostics as a string."""
        return "\n".join(str(d) for d in self._diagnostics)
    
    def clear(self) -> None:
        """Clear all diagnostics."""
        self._diagnostics.clear()
        self._context = None
    
    def get_diagnostics(self) -> List[Diagnostic]:
        """Get all diagnostics."""
        return self._diagnostics.copy()


# Global reporter instance
_reporter: Optional[DiagnosticReporter] = None


def get_diagnostic_reporter() -> DiagnosticReporter:
    """Get the global diagnostic reporter."""
    global _reporter
    if _reporter is None:
        _reporter = DiagnosticReporter()
    return _reporter


def diagnose_function(func: Callable) -> str:
    """
    Analyze a function and return optimization suggestions.
    
    Args:
        func: Function to diagnose.
        
    Returns:
        Formatted diagnostic report.
    """
    reporter = get_diagnostic_reporter()
    reporter.clear()
    reporter.set_context(func)
    
    suggestions = reporter.suggest_optimizations(func)
    
    result = [f"Diagnosis for '{func.__name__}':", ""]
    
    if suggestions:
        result.append("Suggestions:")
        for i, s in enumerate(suggestions, 1):
            result.append(f"  {i}. {s}")
    else:
        result.append("No optimization suggestions - function looks good!")
    
    return "\n".join(result)

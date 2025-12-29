"""
Inline expansion pass for Phase 5.

Expands eligible call sites by inlining callee code into the caller
with guards for safe fallback.
"""

from __future__ import annotations

import ast
import inspect
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple, Any

from pyaot.inline.eligibility import InlineCandidate
from pyaot.inline.guards import InlineGuardSet, create_inline_guards


@dataclass
class InlinedFunction:
    """
    Represents an inlined version of a function.
    
    Contains the original function plus a mapping of call sites
    to their inlined implementations.
    """
    original: Callable
    original_name: str
    
    # Map of callsite_id to (guarded native impl, guards)
    inlined_callsites: Dict[str, Tuple[Callable, InlineGuardSet]]
    
    # Statistics
    native_calls: int = 0
    fallback_calls: int = 0


class InlineExpander:
    """
    Expands call sites by inlining callee code.
    
    For Python-level inlining (no LLVM), this creates
    a version of the caller with the callee body substituted.
    """
    
    def __init__(self):
        self._cache: Dict[str, InlinedFunction] = {}
    
    def can_inline(self, candidate: InlineCandidate) -> bool:
        """Check if we can inline this candidate."""
        try:
            source = inspect.getsource(candidate.callee)
            ast.parse(source)
            return True
        except (OSError, TypeError, SyntaxError):
            return False
    
    def create_inlined_caller(
        self,
        caller: Callable,
        callee: Callable,
        call_arg_name: str = "x",
    ) -> Callable:
        """
        Create a version of caller with callee inlined.
        
        This is a simplified inline that works for simple numeric functions.
        For production, this would use IR-level inlining.
        
        Args:
            caller: The caller function.
            callee: The callee to inline.
            call_arg_name: Name of the variable passed to callee.
            
        Returns:
            Inlined version of caller.
        """
        # Get callee body
        try:
            callee_source = inspect.getsource(callee)
            callee_ast = ast.parse(callee_source)
        except (OSError, TypeError, SyntaxError):
            return caller  # Can't inline
        
        # Find return expression in callee
        callee_func = callee_ast.body[0]
        if not isinstance(callee_func, ast.FunctionDef):
            return caller
        
        # Simple case: single return statement
        if len(callee_func.body) == 1 and isinstance(callee_func.body[0], ast.Return):
            return_expr = callee_func.body[0].value
            
            # Get callee arg names
            callee_args = [arg.arg for arg in callee_func.args.args]
            
            # For simple numeric functions like inner(x) -> x * 1.000001 + 0.5
            # We can create a lambda
            if len(callee_args) == 1:
                # Create inlined version using exec
                # This is safe because we control the source
                inlined_code = ast.unparse(return_expr)
                arg_name = callee_args[0]
                
                # Create lambda
                exec_globals = caller.__globals__.copy()
                exec_locals = {}
                
                try:
                    exec(f"_inlined = lambda {arg_name}: {inlined_code}", exec_globals, exec_locals)
                    return exec_locals['_inlined']
                except Exception:
                    return caller
        
        return caller


def create_guarded_inline(
    callee: Callable,
    sample_args: Tuple[Any, ...] = (),
) -> Tuple[Callable, InlineGuardSet]:
    """
    Create a guarded inline version of a callee.
    
    Returns both the inlined implementation and its guards.
    For simple numeric functions, this creates a native-like
    version without Python call overhead.
    
    Args:
        callee: The function to inline.
        sample_args: Sample arguments for type inference.
        
    Returns:
        (inlined_impl, guards)
    """
    # Create guards
    guards = create_inline_guards(callee, sample_args=sample_args)
    
    # For simple functions, create optimized version
    # This bypasses the function call overhead
    try:
        source = inspect.getsource(callee)
        tree = ast.parse(source)
        func_def = tree.body[0]
        
        if isinstance(func_def, ast.FunctionDef):
            # Check for simple return
            if len(func_def.body) == 1 and isinstance(func_def.body[0], ast.Return):
                return_expr = func_def.body[0].value
                arg_names = [arg.arg for arg in func_def.args.args]
                
                # Create optimized lambda
                expr_str = ast.unparse(return_expr)
                lambda_str = f"lambda {', '.join(arg_names)}: {expr_str}"
                
                exec_globals = callee.__globals__.copy()
                exec_locals = {}
                exec(f"_opt = {lambda_str}", exec_globals, exec_locals)
                
                return exec_locals['_opt'], guards
    except Exception:
        pass
    
    # Fallback: return original (still benefits from guard caching)
    return callee, guards


class InlineCache:
    """
    Cache for inlined functions.
    
    Stores compiled inlined versions and their guards
    for reuse across multiple calls.
    """
    
    def __init__(self):
        self._cache: Dict[int, Tuple[Callable, InlineGuardSet]] = {}
        self._stats = {
            "hits": 0,
            "misses": 0,
            "invalidations": 0,
        }
    
    def get(self, callee_id: int) -> Optional[Tuple[Callable, InlineGuardSet]]:
        """Get cached inline implementation."""
        result = self._cache.get(callee_id)
        if result:
            self._stats["hits"] += 1
        else:
            self._stats["misses"] += 1
        return result
    
    def put(
        self,
        callee_id: int,
        impl: Callable,
        guards: InlineGuardSet,
    ) -> None:
        """Cache an inlined implementation."""
        self._cache[callee_id] = (impl, guards)
    
    def invalidate(self, callee_id: int) -> None:
        """Invalidate a cached implementation."""
        if callee_id in self._cache:
            del self._cache[callee_id]
            self._stats["invalidations"] += 1
    
    def clear(self) -> None:
        """Clear the cache."""
        self._cache.clear()
    
    def get_stats(self) -> Dict[str, int]:
        """Get cache statistics."""
        return {
            **self._stats,
            "size": len(self._cache),
        }


# Global inline cache
_global_inline_cache: Optional[InlineCache] = None


def get_inline_cache() -> InlineCache:
    """Get the global inline cache."""
    global _global_inline_cache
    if _global_inline_cache is None:
        _global_inline_cache = InlineCache()
    return _global_inline_cache

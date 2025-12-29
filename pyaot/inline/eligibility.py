"""
Eligibility analyzer for inline expansion.

Determines which call sites are eligible for inlining based on:
- Call count threshold
- Monomorphism (single callee)
- Leaf function detection
- Compiler-subset type compatibility
"""

from __future__ import annotations

import ast
import dis
import inspect
import types
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Set, Tuple, Any
from enum import Enum, auto

from pyaot.inline.callsite import CallsiteProfile


# Configuration thresholds
MIN_CALL_COUNT = 1000
MIN_CALLEE_SHARE = 0.995  # 99.5% single callee


class IneligibilityReason(Enum):
    """Reasons why a call site is not eligible for inlining."""
    INSUFFICIENT_CALLS = auto()
    POLYMORPHIC = auto()
    HAS_VARARGS = auto()
    HAS_KWARGS = auto()
    NOT_LEAF = auto()
    HAS_CLOSURE = auto()
    IS_GENERATOR = auto()
    IS_COROUTINE = auto()
    INCOMPATIBLE_TYPES = auto()
    NO_SOURCE = auto()
    BUILTIN = auto()


@dataclass
class InlineCandidate:
    """
    A call site that is eligible for inlining.
    
    Contains all information needed to generate inlined code.
    """
    callsite_id: str
    callee: Callable
    callee_id: int
    callee_name: str
    
    # For bound methods
    receiver_type_id: Optional[int] = None
    receiver_type_name: Optional[str] = None
    
    # Expected argument types
    arg_types: Tuple[str, ...] = ()
    
    # Profiling data
    total_calls: int = 0
    avg_call_time_ns: float = 0.0
    
    # Source info
    source_file: Optional[str] = None
    source_lineno: int = 0
    
    @property
    def estimated_inline_benefit_ns(self) -> float:
        """Estimate benefit from inlining (call overhead elimination)."""
        # Typical Python call overhead is 50-200ns
        # Conservative estimate: 100ns per call
        CALL_OVERHEAD_NS = 100
        return self.total_calls * CALL_OVERHEAD_NS


# Whitelisted functions that can be called from leaf functions
WHITELISTED_BUILTINS = {
    'abs', 'min', 'max', 'sum', 'len', 'range', 'enumerate', 'zip',
    'int', 'float', 'bool', 'str',
    'round', 'pow',
}

WHITELISTED_MODULES = {
    'math',
    'numpy',
    'operator',
}


def is_leaf_function(func: Callable) -> bool:
    """
    Check if function is a leaf (no Python calls except whitelisted).
    
    A leaf function contains only:
    - Arithmetic operations
    - Comparisons
    - Attribute access
    - Calls to whitelisted builtins/math functions
    """
    # Get bytecode
    try:
        code = func.__code__
    except AttributeError:
        # Built-in or C function - consider it a leaf
        return True
    
    # Analyze bytecode for call instructions
    for instr in dis.get_instructions(code):
        if instr.opname in ('CALL', 'CALL_FUNCTION', 'CALL_METHOD', 
                            'CALL_FUNCTION_KW', 'CALL_FUNCTION_EX'):
            # Check if it's calling a whitelisted function
            # This is conservative - we reject if we can't determine
            return False
        
        # Check for yield/await
        if instr.opname in ('YIELD_VALUE', 'YIELD_FROM', 'AWAIT', 
                            'GET_AWAITABLE', 'SEND'):
            return False
    
    return True


def is_leaf_function_ast(func: Callable) -> Tuple[bool, Optional[str]]:
    """
    Check if function is a leaf using AST analysis.
    
    Returns:
        (is_leaf, reason_if_not)
    """
    try:
        source = inspect.getsource(func)
        tree = ast.parse(source)
    except (OSError, TypeError, SyntaxError):
        return True, None  # Assume leaf if can't analyze
    
    class CallVisitor(ast.NodeVisitor):
        def __init__(self):
            self.has_non_leaf_call = False
            self.reason = None
        
        def visit_Call(self, node):
            # Check if call target is whitelisted
            if isinstance(node.func, ast.Name):
                if node.func.id not in WHITELISTED_BUILTINS:
                    self.has_non_leaf_call = True
                    self.reason = f"calls non-whitelisted: {node.func.id}"
            elif isinstance(node.func, ast.Attribute):
                # Allow module.func for whitelisted modules
                if isinstance(node.func.value, ast.Name):
                    if node.func.value.id not in WHITELISTED_MODULES:
                        self.has_non_leaf_call = True
                        self.reason = f"calls non-whitelisted: {node.func.value.id}.{node.func.attr}"
            else:
                self.has_non_leaf_call = True
                self.reason = "complex call expression"
            
            self.generic_visit(node)
        
        def visit_Yield(self, node):
            self.has_non_leaf_call = True
            self.reason = "contains yield"
        
        def visit_YieldFrom(self, node):
            self.has_non_leaf_call = True
            self.reason = "contains yield from"
        
        def visit_Await(self, node):
            self.has_non_leaf_call = True
            self.reason = "contains await"
    
    visitor = CallVisitor()
    visitor.visit(tree)
    
    return not visitor.has_non_leaf_call, visitor.reason


def check_signature_compatibility(func: Callable) -> Tuple[bool, Optional[IneligibilityReason]]:
    """
    Check if function signature is compatible with inlining.
    
    Rejects:
    - *args
    - **kwargs
    - Closures with mutable state
    """
    try:
        sig = inspect.signature(func)
    except (ValueError, TypeError):
        return False, IneligibilityReason.BUILTIN
    
    for param in sig.parameters.values():
        if param.kind == inspect.Parameter.VAR_POSITIONAL:
            return False, IneligibilityReason.HAS_VARARGS
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            return False, IneligibilityReason.HAS_KWARGS
    
    # Check for closures
    if hasattr(func, '__closure__') and func.__closure__:
        # Check if closure captures mutable state
        for cell in func.__closure__:
            try:
                val = cell.cell_contents
                if isinstance(val, (list, dict, set)):
                    return False, IneligibilityReason.HAS_CLOSURE
            except ValueError:
                pass  # Empty cell
    
    return True, None


def is_generator_or_coroutine(func: Callable) -> bool:
    """Check if function is a generator or coroutine."""
    if inspect.isgeneratorfunction(func):
        return True
    if inspect.iscoroutinefunction(func):
        return True
    if inspect.isasyncgenfunction(func):
        return True
    return False


def analyze_eligibility(
    profile: CallsiteProfile,
    callee: Optional[Callable] = None,
) -> Tuple[bool, Optional[InlineCandidate], Optional[IneligibilityReason]]:
    """
    Analyze if a call site is eligible for inlining.
    
    Args:
        profile: The callsite profile.
        callee: The callee function (if known).
        
    Returns:
        (is_eligible, candidate_if_eligible, reason_if_not)
    """
    # Check call count threshold
    if profile.total_calls < MIN_CALL_COUNT:
        return False, None, IneligibilityReason.INSUFFICIENT_CALLS
    
    # Check monomorphism
    if profile.dominant_callee_share < MIN_CALLEE_SHARE:
        return False, None, IneligibilityReason.POLYMORPHIC
    
    # If callee not provided, we can't analyze further
    if callee is None:
        return False, None, IneligibilityReason.NO_SOURCE
    
    # Check for generator/coroutine
    if is_generator_or_coroutine(callee):
        return False, None, IneligibilityReason.IS_GENERATOR
    
    # Check signature compatibility
    sig_ok, sig_reason = check_signature_compatibility(callee)
    if not sig_ok:
        return False, None, sig_reason
    
    # Check if leaf function (no Python calls)
    is_leaf, leaf_reason = is_leaf_function_ast(callee)
    if not is_leaf:
        return False, None, IneligibilityReason.NOT_LEAF
    
    # All checks passed - create candidate
    candidate = InlineCandidate(
        callsite_id=profile.callsite_id,
        callee=callee,
        callee_id=id(callee),
        callee_name=getattr(callee, '__name__', str(callee)),
        total_calls=profile.total_calls,
        avg_call_time_ns=profile.avg_call_time_ns,
    )
    
    # Add source info
    try:
        candidate.source_file = inspect.getfile(callee)
        candidate.source_lineno = inspect.getsourcelines(callee)[1]
    except (OSError, TypeError):
        pass
    
    # Add arg type signature
    if profile.arg_type_signatures:
        candidate.arg_types = profile.arg_type_signatures[0]
    
    return True, candidate, None


def get_inline_candidates(
    profiles: List[CallsiteProfile],
    callee_map: dict[int, Callable] = None,
) -> List[InlineCandidate]:
    """
    Get all inline candidates from a list of callsite profiles.
    
    Args:
        profiles: List of callsite profiles to analyze.
        callee_map: Optional mapping from callee_id to callee function.
        
    Returns:
        List of eligible inline candidates.
    """
    candidates = []
    callee_map = callee_map or {}
    
    for profile in profiles:
        callee_id = profile.dominant_callee_id
        callee = callee_map.get(callee_id)
        
        is_eligible, candidate, reason = analyze_eligibility(profile, callee)
        if is_eligible and candidate:
            candidates.append(candidate)
    
    # Sort by estimated benefit
    candidates.sort(key=lambda c: c.estimated_inline_benefit_ns, reverse=True)
    
    return candidates


def is_eligible_for_inline(
    func: Callable,
    min_calls: int = MIN_CALL_COUNT,
) -> Tuple[bool, Optional[IneligibilityReason]]:
    """
    Quick check if a function is eligible to be inlined.
    
    This checks callee-side eligibility only (not callsite heat).
    
    Args:
        func: The function to check.
        min_calls: Not used here (for API consistency).
        
    Returns:
        (is_eligible, reason_if_not)
    """
    # Check for generator/coroutine
    if is_generator_or_coroutine(func):
        return False, IneligibilityReason.IS_GENERATOR
    
    # Check signature
    sig_ok, sig_reason = check_signature_compatibility(func)
    if not sig_ok:
        return False, sig_reason
    
    # Check if leaf
    is_leaf, _ = is_leaf_function_ast(func)
    if not is_leaf:
        return False, IneligibilityReason.NOT_LEAF
    
    return True, None

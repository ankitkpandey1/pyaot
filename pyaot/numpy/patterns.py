"""
NumPy Fusion Patterns.

Common patterns that can be fused into single operations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Tuple


class FusionOp(Enum):
    """Operations that can be fused."""
    # Unary
    SQRT = auto()
    EXP = auto()
    LOG = auto()
    SIN = auto()
    COS = auto()
    ABS = auto()
    NEG = auto()
    
    # Binary
    ADD = auto()
    SUB = auto()
    MUL = auto()
    DIV = auto()
    POW = auto()
    
    # Reduction
    SUM = auto()
    MEAN = auto()
    MAX = auto()
    MIN = auto()
    DOT = auto()


@dataclass
class FusionPattern:
    """
    A pattern of operations that can be fused.
    
    Attributes:
        name: Pattern name (e.g., "hypot")
        operations: Tree of operations
        output_expr: C/LLVM expression template
    """
    name: str
    operations: Tuple[Any, ...]
    output_expr: str
    reduction: bool = False
    
    def matches(self, op_tree: Tuple) -> bool:
        """Check if operation tree matches this pattern."""
        return self._match_tree(self.operations, op_tree)
    
    def _match_tree(self, pattern: Any, tree: Any) -> bool:
        """Recursively match pattern against tree."""
        if isinstance(pattern, str):
            # Variable placeholder
            return True
        
        if isinstance(pattern, FusionOp):
            if isinstance(tree, tuple) and len(tree) > 0:
                return tree[0] == pattern
            return False
        
        if isinstance(pattern, tuple) and isinstance(tree, tuple):
            if len(pattern) != len(tree):
                return False
            return all(self._match_tree(p, t) for p, t in zip(pattern, tree))
        
        return pattern == tree


# Common fusion patterns
PATTERNS: Dict[str, FusionPattern] = {
    # sqrt(a^2 + b^2) -> hypot(a, b)
    "hypot": FusionPattern(
        name="hypot",
        operations=(FusionOp.SQRT, (FusionOp.ADD, 
            (FusionOp.MUL, "a", "a"), 
            (FusionOp.MUL, "b", "b"))),
        output_expr="sqrt({a}*{a} + {b}*{b})",
    ),
    
    # x / sqrt(sum(x^2)) -> normalize
    "normalize": FusionPattern(
        name="normalize",
        operations=(FusionOp.DIV, "x", 
            (FusionOp.SQRT, (FusionOp.SUM, (FusionOp.MUL, "x", "x")))),
        output_expr="{x} / sqrt(sum_sq)",
        reduction=True,
    ),
    
    # a*x + b -> axpb (fused multiply-add)
    "axpb": FusionPattern(
        name="axpb",
        operations=(FusionOp.ADD, (FusionOp.MUL, "a", "x"), "b"),
        output_expr="fma({a}, {x}, {b})",
    ),
    
    # exp(x) - 1 -> expm1
    "expm1": FusionPattern(
        name="expm1",
        operations=(FusionOp.SUB, (FusionOp.EXP, "x"), 1.0),
        output_expr="expm1({x})",
    ),
    
    # log(1 + x) -> log1p
    "log1p": FusionPattern(
        name="log1p",
        operations=(FusionOp.LOG, (FusionOp.ADD, 1.0, "x")),
        output_expr="log1p({x})",
    ),
    
    # sum(a * b) -> dot product
    "dot": FusionPattern(
        name="dot",
        operations=(FusionOp.SUM, (FusionOp.MUL, "a", "b")),
        output_expr="dot({a}, {b})",
        reduction=True,
    ),
    
    # sqrt(sum((a - b)^2)) -> euclidean distance
    "euclidean": FusionPattern(
        name="euclidean",
        operations=(FusionOp.SQRT, (FusionOp.SUM, 
            (FusionOp.MUL, 
                (FusionOp.SUB, "a", "b"),
                (FusionOp.SUB, "a", "b")))),
        output_expr="sqrt(sum_sq_diff)",
        reduction=True,
    ),
}


def get_pattern(name: str) -> Optional[FusionPattern]:
    """Get a fusion pattern by name."""
    return PATTERNS.get(name)


def find_matching_pattern(op_tree: Tuple) -> Optional[FusionPattern]:
    """Find a pattern that matches the operation tree."""
    for pattern in PATTERNS.values():
        if pattern.matches(op_tree):
            return pattern
    return None


def list_patterns() -> List[str]:
    """List all available fusion pattern names."""
    return list(PATTERNS.keys())

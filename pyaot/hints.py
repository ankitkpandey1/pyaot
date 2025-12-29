"""
Type hint extraction for PyAOT.

Extracts PEP 484 type annotations and maps them to IR types
for compilation without profiling.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Tuple,
    Union,
    get_type_hints,
    get_origin,
    get_args,
)

from pyaot.compiler.ir import IRType, IRTypeKind
from pyaot.types.inference import InferredType, FunctionSignature, PYTHON_TO_IR_TYPE


# Mapping from Python typing types to IR types
TYPING_TO_IR: Dict[Any, IRTypeKind] = {
    int: IRTypeKind.INT64,
    float: IRTypeKind.FLOAT64,
    bool: IRTypeKind.BOOL,
}


@dataclass
class HintExtractionResult:
    """Result of type hint extraction."""
    success: bool
    signature: Optional[FunctionSignature] = None
    error: Optional[str] = None
    source_hash: Optional[str] = None


class TypeHintExtractor:
    """
    Extract type information from PEP 484 annotations.
    
    Enables compilation without profiling when type hints
    provide sufficient information.
    
    Usage:
        extractor = TypeHintExtractor()
        result = extractor.extract(my_function)
        if result.success:
            # Compile using result.signature
    """
    
    def __init__(self, require_return_type: bool = False):
        """
        Initialize the extractor.
        
        Args:
            require_return_type: If True, require return type annotation.
        """
        self.require_return_type = require_return_type
    
    def extract(self, func: Callable) -> HintExtractionResult:
        """
        Extract type signature from function annotations.
        
        Args:
            func: The function to extract hints from.
            
        Returns:
            HintExtractionResult with signature if successful.
        """
        try:
            # Get type hints
            hints = get_type_hints(func)
            
            if not hints:
                return HintExtractionResult(
                    success=False,
                    error="No type hints found",
                )
            
            # Get function signature for parameter names
            sig = inspect.signature(func)
            param_names = list(sig.parameters.keys())
            
            # Extract argument types
            arg_types = []
            arg_names = []
            
            for name in param_names:
                if name not in hints:
                    return HintExtractionResult(
                        success=False,
                        error=f"Missing type hint for parameter: {name}",
                    )
                
                ir_type = self._hint_to_ir_type(hints[name])
                if ir_type is None:
                    return HintExtractionResult(
                        success=False,
                        error=f"Unsupported type hint for {name}: {hints[name]}",
                    )
                
                arg_types.append(ir_type)
                arg_names.append(name)
            
            # Extract return type
            return_hint = hints.get("return")
            if return_hint is None and self.require_return_type:
                return HintExtractionResult(
                    success=False,
                    error="Missing return type hint",
                )
            
            if return_hint is None:
                # Default to float64 for numeric functions
                return_type = InferredType(
                    kind=IRTypeKind.FLOAT64,
                    python_type="float",
                    confidence=0.8,
                )
            else:
                return_type = self._hint_to_ir_type(return_hint)
                if return_type is None:
                    return HintExtractionResult(
                        success=False,
                        error=f"Unsupported return type: {return_hint}",
                    )
            
            # Compute source hash for cache invalidation
            source_hash = self._compute_source_hash(func)
            
            signature = FunctionSignature(
                arg_types=arg_types,
                arg_names=arg_names,
                return_type=return_type,
                confidence=1.0,  # High confidence from explicit hints
            )
            
            return HintExtractionResult(
                success=True,
                signature=signature,
                source_hash=source_hash,
            )
            
        except Exception as e:
            return HintExtractionResult(
                success=False,
                error=f"Error extracting hints: {e}",
            )
    
    def _hint_to_ir_type(self, hint: Any) -> Optional[InferredType]:
        """
        Convert a type hint to an InferredType.
        
        Supports:
        - Basic types: int, float, bool
        - NumPy arrays: np.ndarray
        - Containers: List, Tuple (limited)
        """
        # Handle None type
        if hint is None or hint is type(None):
            return InferredType(
                kind=IRTypeKind.VOID,
                python_type="None",
            )
        
        # Handle basic types
        if hint in TYPING_TO_IR:
            return InferredType(
                kind=TYPING_TO_IR[hint],
                python_type=hint.__name__,
            )
        
        # Handle origin types (List[X], Tuple[X, Y], etc.)
        origin = get_origin(hint)
        
        if origin is list:
            args = get_args(hint)
            if args:
                element_type = self._hint_to_ir_type(args[0])
                return InferredType(
                    kind=IRTypeKind.LIST,
                    python_type=f"list[{args[0].__name__ if hasattr(args[0], '__name__') else args[0]}]",
                    element_type=element_type,
                )
            return InferredType(kind=IRTypeKind.LIST, python_type="list")
        
        if origin is tuple:
            return InferredType(kind=IRTypeKind.TUPLE, python_type="tuple")
        
        # Handle numpy arrays
        if hasattr(hint, "__module__") and "numpy" in str(hint.__module__):
            # This is a numpy type
            return InferredType(
                kind=IRTypeKind.NDARRAY,
                python_type="numpy.ndarray",
                dtype="float64",  # Default
            )
        
        # Check string representation for numpy
        hint_str = str(hint)
        if "ndarray" in hint_str or "numpy" in hint_str:
            return InferredType(
                kind=IRTypeKind.NDARRAY,
                python_type="numpy.ndarray",
                dtype="float64",
            )
        
        # Unsupported type
        return None
    
    def _compute_source_hash(self, func: Callable) -> str:
        """
        Compute a hash of the function source for cache invalidation.
        
        Changes to source code should invalidate cached artifacts.
        """
        import hashlib
        
        try:
            source = inspect.getsource(func)
        except (OSError, TypeError):
            # Can't get source (builtin, C extension, etc.)
            source = func.__name__
        
        # Include type hints in hash
        try:
            hints = get_type_hints(func)
            hints_str = str(sorted(hints.items()))
        except Exception:
            hints_str = ""
        
        content = f"{source}\n{hints_str}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def can_compile_from_hints(self, func: Callable) -> bool:
        """
        Check if function has sufficient hints for compilation.
        
        Returns True if all parameters have compilable type hints.
        """
        result = self.extract(func)
        return result.success
    
    def get_ir_types(self, func: Callable) -> Optional[List[IRType]]:
        """
        Get IR types from function hints.
        
        Returns list of IRType for use with compilation,
        or None if hints are insufficient.
        """
        result = self.extract(func)
        if not result.success:
            return None
        
        ir_types = []
        for inferred in result.signature.arg_types:
            ir_types.append(IRType(kind=inferred.kind))
        
        return ir_types


# Convenience functions

def extract_type_hints(func: Callable) -> Optional[FunctionSignature]:
    """
    Extract type signature from function hints.
    
    Returns FunctionSignature or None if hints are insufficient.
    """
    extractor = TypeHintExtractor()
    result = extractor.extract(func)
    return result.signature if result.success else None


def has_compilable_hints(func: Callable) -> bool:
    """Check if function has sufficient type hints for compilation."""
    return TypeHintExtractor().can_compile_from_hints(func)


def get_source_hash(func: Callable) -> str:
    """Get source hash for cache invalidation."""
    return TypeHintExtractor()._compute_source_hash(func)

"""
Type inference for AOT compilation.

Infers stable types from profile data for code generation.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum, auto

from pyaot.profiler.data import FunctionProfile, TypeSignature, ShapeSignature
from pyaot.exceptions import TypeInferenceError


class IRTypeKind(Enum):
    """Kinds of IR types."""
    VOID = auto()
    BOOL = auto()
    INT32 = auto()
    INT64 = auto()
    FLOAT32 = auto()
    FLOAT64 = auto()
    NDARRAY = auto()
    TUPLE = auto()
    LIST = auto()
    OBJECT = auto()  # Fallback for unknown types


@dataclass
class InferredType:
    """A type inferred from profile data.
    
    Includes the IR type kind, confidence, and array-specific info.
    """
    kind: IRTypeKind
    python_type: str  # Original Python type name
    confidence: float = 1.0
    
    # Array-specific info
    dtype: Optional[str] = None  # NumPy dtype
    shape: Optional[Tuple[int, ...]] = None
    ndim: Optional[int] = None
    
    # Container element types
    element_type: Optional["InferredType"] = None
    
    def is_numeric(self) -> bool:
        """Check if this is a numeric type."""
        return self.kind in (
            IRTypeKind.BOOL,
            IRTypeKind.INT32,
            IRTypeKind.INT64,
            IRTypeKind.FLOAT32,
            IRTypeKind.FLOAT64,
        )
    
    def is_array(self) -> bool:
        """Check if this is an array type."""
        return self.kind == IRTypeKind.NDARRAY
    
    def to_llvm_type_str(self) -> str:
        """Get the LLVM type string."""
        mapping = {
            IRTypeKind.VOID: "void",
            IRTypeKind.BOOL: "i1",
            IRTypeKind.INT32: "i32",
            IRTypeKind.INT64: "i64",
            IRTypeKind.FLOAT32: "float",
            IRTypeKind.FLOAT64: "double",
            IRTypeKind.NDARRAY: "ptr",  # Pointer to data
            IRTypeKind.OBJECT: "ptr",
        }
        return mapping.get(self.kind, "ptr")
    
    def __repr__(self) -> str:
        if self.kind == IRTypeKind.NDARRAY:
            return f"ndarray[{self.dtype}, shape={self.shape}]"
        return f"{self.kind.name}"


@dataclass
class FunctionSignature:
    """Inferred type signature for a function."""
    arg_types: List[InferredType]
    arg_names: List[str]
    return_type: InferredType
    confidence: float = 1.0
    
    def is_compilable(self) -> bool:
        """Check if all types are compilable."""
        for t in self.arg_types:
            if t.kind == IRTypeKind.OBJECT and t.confidence < 0.95:
                return False
        return True


# Mapping from Python type names to IR types
PYTHON_TO_IR_TYPE: Dict[str, IRTypeKind] = {
    "builtins.int": IRTypeKind.INT64,
    "builtins.float": IRTypeKind.FLOAT64,
    "builtins.bool": IRTypeKind.BOOL,
    "int": IRTypeKind.INT64,
    "float": IRTypeKind.FLOAT64,
    "bool": IRTypeKind.BOOL,
}


class TypeInferencer:
    """Infers types from profile data.
    
    Uses observed type signatures to determine the dominant
    types for function arguments and return values.
    """
    
    def __init__(self, min_confidence: float = 0.95):
        """Initialize the inferencer.
        
        Args:
            min_confidence: Minimum confidence for stable inference.
        """
        self.min_confidence = min_confidence
    
    def infer_from_profile(
        self,
        profile: FunctionProfile,
    ) -> FunctionSignature:
        """Infer function signature from profile data.
        
        Args:
            profile: The function profile with observed signatures.
            
        Returns:
            Inferred FunctionSignature.
            
        Raises:
            TypeInferenceError: If types are too unstable.
        """
        # Get dominant type signature
        type_sig = profile.get_dominant_type_signature()
        if type_sig is None:
            raise TypeInferenceError(
                "No type signatures observed",
                function_name=profile.key,
            )
        
        # Get dominant shape signature
        shape_sig = profile.get_dominant_shape_signature()
        
        # Calculate confidence
        type_stability = profile.get_type_stability()
        shape_stability = profile.get_shape_stability()
        confidence = 0.5 * type_stability + 0.5 * shape_stability
        
        if confidence < self.min_confidence:
            raise TypeInferenceError(
                f"Type instability: {confidence:.3f} < {self.min_confidence}",
                function_name=profile.key,
                stability_score=confidence,
            )
        
        # Infer argument types
        arg_types = []
        arg_names = []  # We don't have names from profile, use placeholders
        
        for i, python_type in enumerate(type_sig.arg_types):
            shape = None
            if shape_sig and i < len(shape_sig.arg_shapes):
                shape = shape_sig.arg_shapes[i]
            
            ir_type = self._infer_single_type(python_type, shape)
            arg_types.append(ir_type)
            arg_names.append(f"arg{i}")
        
        # Return type (we don't track this in profiling, assume float64 or void)
        return_type = InferredType(
            kind=IRTypeKind.FLOAT64,
            python_type="float",
            confidence=0.5,  # Low confidence since we don't track it
        )
        
        return FunctionSignature(
            arg_types=arg_types,
            arg_names=arg_names,
            return_type=return_type,
            confidence=confidence,
        )
    
    def _infer_single_type(
        self,
        python_type: str,
        shape: Optional[Tuple[int, ...]],
    ) -> InferredType:
        """Infer IR type from a Python type name."""
        # Check for ndarray
        if python_type.startswith("ndarray["):
            # Parse dtype from "ndarray[float64]"
            dtype = python_type[8:-1] if python_type.endswith("]") else "float64"
            return InferredType(
                kind=IRTypeKind.NDARRAY,
                python_type=python_type,
                dtype=dtype,
                shape=shape,
                ndim=len(shape) if shape else None,
            )
        
        # Check known types
        if python_type in PYTHON_TO_IR_TYPE:
            return InferredType(
                kind=PYTHON_TO_IR_TYPE[python_type],
                python_type=python_type,
            )
        
        # Handle numpy scalar types
        if "numpy" in python_type or python_type.startswith("np."):
            if "float64" in python_type:
                return InferredType(kind=IRTypeKind.FLOAT64, python_type=python_type)
            if "float32" in python_type:
                return InferredType(kind=IRTypeKind.FLOAT32, python_type=python_type)
            if "int64" in python_type:
                return InferredType(kind=IRTypeKind.INT64, python_type=python_type)
            if "int32" in python_type:
                return InferredType(kind=IRTypeKind.INT32, python_type=python_type)
            if "bool" in python_type:
                return InferredType(kind=IRTypeKind.BOOL, python_type=python_type)
        
        # Fallback to object
        return InferredType(
            kind=IRTypeKind.OBJECT,
            python_type=python_type,
            confidence=0.5,
        )
    
    def infer_arg_types(
        self,
        args: Tuple[Any, ...],
    ) -> List[InferredType]:
        """Infer types from actual argument values.
        
        Used for runtime guard checking.
        """
        types = []
        for arg in args:
            python_type = type(arg).__name__
            shape = getattr(arg, 'shape', None)
            types.append(self._infer_single_type(python_type, shape))
        return types

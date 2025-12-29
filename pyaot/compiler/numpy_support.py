"""
NumPy support for PyAOT.

Provides zero-copy buffer access and array handling
for compiled functions.
"""

from typing import Any, Optional, Tuple
import ctypes
from dataclasses import dataclass

from pyaot.compiler.ir import IRType, IRTypeKind


@dataclass
class ArrayInfo:
    """Information about a NumPy array for compilation."""
    data_ptr: int
    shape: Tuple[int, ...]
    strides: Tuple[int, ...]
    dtype: str
    ndim: int
    size: int
    itemsize: int
    
    @property
    def is_contiguous(self) -> bool:
        """Check if array is C-contiguous."""
        expected_stride = self.itemsize
        for i in range(self.ndim - 1, -1, -1):
            if self.strides[i] != expected_stride:
                return False
            expected_stride *= self.shape[i]
        return True


class NumPySupport:
    """Support for NumPy array operations in compiled code.
    
    Provides:
    - Zero-copy buffer access via ctypes
    - Shape and stride handling
    - Type mapping between NumPy and IR types
    """
    
    # NumPy dtype to IR type mapping
    DTYPE_MAP = {
        'float64': IRTypeKind.FLOAT64,
        'float32': IRTypeKind.FLOAT32,
        'int64': IRTypeKind.INT64,
        'int32': IRTypeKind.INT32,
        'bool': IRTypeKind.BOOL,
    }
    
    @classmethod
    def is_available(cls) -> bool:
        """Check if NumPy is available."""
        try:
            import numpy
            return True
        except ImportError:
            return False
    
    @classmethod
    def get_array_info(cls, arr: Any) -> Optional[ArrayInfo]:
        """Get array info for a NumPy-like array.
        
        Args:
            arr: Array-like object with shape, strides, dtype attributes.
            
        Returns:
            ArrayInfo or None if not a valid array.
        """
        if not hasattr(arr, 'ctypes') or not hasattr(arr, 'shape'):
            return None
        
        try:
            return ArrayInfo(
                data_ptr=arr.ctypes.data,
                shape=tuple(arr.shape),
                strides=tuple(arr.strides),
                dtype=str(arr.dtype),
                ndim=arr.ndim,
                size=arr.size,
                itemsize=arr.itemsize,
            )
        except Exception:
            return None
    
    @classmethod
    def get_data_pointer(cls, arr: Any) -> Optional[int]:
        """Get the raw data pointer for an array.
        
        Uses arr.ctypes.data for zero-copy access.
        
        Args:
            arr: NumPy array.
            
        Returns:
            Data pointer as integer, or None if not available.
        """
        if hasattr(arr, 'ctypes') and hasattr(arr.ctypes, 'data'):
            return arr.ctypes.data
        return None
    
    @classmethod
    def get_ir_type(cls, arr: Any) -> IRType:
        """Get the IR type for an array.
        
        Args:
            arr: NumPy array.
            
        Returns:
            IRType representing the array.
        """
        dtype_str = str(arr.dtype)
        elem_kind = cls.DTYPE_MAP.get(dtype_str, IRTypeKind.FLOAT64)
        elem_type = IRType(kind=elem_kind)
        
        return IRType.array(elem_type, tuple(arr.shape))
    
    @classmethod
    def create_ctypes_pointer(
        cls,
        arr: Any,
    ) -> ctypes.c_void_p:
        """Create a ctypes pointer for passing to native code.
        
        Args:
            arr: NumPy array.
            
        Returns:
            ctypes void pointer to array data.
        """
        data_ptr = cls.get_data_pointer(arr)
        if data_ptr is None:
            raise ValueError("Cannot get data pointer from array")
        return ctypes.c_void_p(data_ptr)
    
    @classmethod
    def wrap_array_function(
        cls,
        native_func: Any,
        takes_arrays: bool = True,
    ):
        """Wrap a native function to accept NumPy arrays.
        
        Automatically converts NumPy arrays to pointers.
        
        Args:
            native_func: The native function (ctypes callable).
            takes_arrays: Whether function takes array arguments.
            
        Returns:
            Wrapped function that accepts NumPy arrays.
        """
        if not takes_arrays:
            return native_func
        
        def wrapper(*args):
            converted_args = []
            for arg in args:
                if hasattr(arg, 'ctypes') and hasattr(arg, 'shape'):
                    # Convert array to pointer
                    converted_args.append(arg.ctypes.data)
                else:
                    converted_args.append(arg)
            return native_func(*converted_args)
        
        return wrapper
    
    @classmethod
    def ensure_contiguous(cls, arr: Any) -> Any:
        """Ensure array is C-contiguous.
        
        Returns a contiguous copy if necessary.
        
        Args:
            arr: NumPy array.
            
        Returns:
            Contiguous array (may be same object or copy).
        """
        try:
            import numpy as np
            if not arr.flags['C_CONTIGUOUS']:
                return np.ascontiguousarray(arr)
            return arr
        except ImportError:
            return arr
    
    @classmethod
    def validate_array_arg(
        cls,
        arr: Any,
        expected_dtype: Optional[str] = None,
        expected_shape: Optional[Tuple[int, ...]] = None,
        expected_ndim: Optional[int] = None,
    ) -> bool:
        """Validate an array argument.
        
        Args:
            arr: Array to validate.
            expected_dtype: Expected dtype string (e.g., 'float64').
            expected_shape: Expected exact shape.
            expected_ndim: Expected number of dimensions.
            
        Returns:
            True if array matches expectations.
        """
        if not hasattr(arr, 'shape') or not hasattr(arr, 'dtype'):
            return False
        
        if expected_dtype and str(arr.dtype) != expected_dtype:
            return False
        
        if expected_shape and arr.shape != expected_shape:
            return False
        
        if expected_ndim is not None and arr.ndim != expected_ndim:
            return False
        
        return True

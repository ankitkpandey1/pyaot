"""
GPU Array for PyAOT.

NumPy-compatible arrays that reside on GPU.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Tuple, Union
import numpy as np

from pyaot.gpu import CUDA_AVAILABLE, CUDA_BACKEND
from pyaot.gpu.runtime import get_runtime

# Import GPU backend
if CUDA_BACKEND == "cupy":
    import cupy as cp
else:
    cp = None


class GPUArray:
    """
    GPU-resident array with NumPy-like API.
    
    Provides automatic data transfer and supports basic operations.
    
    Example:
        # Create from NumPy
        gpu_arr = GPUArray.from_numpy(np_array)
        
        # Operations run on GPU
        result = gpu_arr * 2.0 + 1.0
        
        # Transfer back to CPU
        np_result = result.to_numpy()
    """
    
    def __init__(self, data: Any, dtype: np.dtype = np.float64):
        """
        Create GPUArray.
        
        Args:
            data: GPU array data (CuPy array or similar).
            dtype: Data type.
        """
        self._data = data
        self._dtype = dtype
    
    @classmethod
    def from_numpy(cls, arr: np.ndarray) -> "GPUArray":
        """
        Create GPUArray from NumPy array.
        
        Args:
            arr: NumPy array to transfer.
            
        Returns:
            GPUArray with data on GPU.
        """
        if not CUDA_AVAILABLE:
            raise RuntimeError("GPU not available")
        
        runtime = get_runtime()
        gpu_data = runtime.to_gpu(arr)
        
        return cls(data=gpu_data, dtype=arr.dtype)
    
    @classmethod 
    def zeros(cls, shape: Tuple[int, ...], dtype: np.dtype = np.float64) -> "GPUArray":
        """Create zero-filled GPUArray."""
        if not CUDA_AVAILABLE:
            raise RuntimeError("GPU not available")
        
        runtime = get_runtime()
        gpu_data = runtime.allocate(shape, dtype)
        
        return cls(data=gpu_data, dtype=dtype)
    
    @classmethod
    def ones(cls, shape: Tuple[int, ...], dtype: np.dtype = np.float64) -> "GPUArray":
        """Create one-filled GPUArray."""
        if not CUDA_AVAILABLE:
            raise RuntimeError("GPU not available")
        
        if CUDA_BACKEND == "cupy":
            gpu_data = cp.ones(shape, dtype=dtype)
            return cls(data=gpu_data, dtype=dtype)
        
        raise RuntimeError(f"Unknown backend: {CUDA_BACKEND}")
    
    def to_numpy(self) -> np.ndarray:
        """
        Transfer array to CPU as NumPy array.
        
        Returns:
            NumPy array with data from GPU.
        """
        runtime = get_runtime()
        return runtime.to_cpu(self._data)
    
    # Alias
    to_cpu = to_numpy
    
    @property
    def shape(self) -> Tuple[int, ...]:
        """Get array shape."""
        return self._data.shape
    
    @property
    def dtype(self) -> np.dtype:
        """Get data type."""
        return self._dtype
    
    @property
    def size(self) -> int:
        """Get total number of elements."""
        return self._data.size
    
    @property
    def nbytes(self) -> int:
        """Get size in bytes."""
        return self._data.nbytes
    
    # Arithmetic operations
    def __add__(self, other: Union["GPUArray", float, int]) -> "GPUArray":
        if isinstance(other, GPUArray):
            return GPUArray(self._data + other._data, self._dtype)
        return GPUArray(self._data + other, self._dtype)
    
    def __radd__(self, other: Union[float, int]) -> "GPUArray":
        return GPUArray(other + self._data, self._dtype)
    
    def __sub__(self, other: Union["GPUArray", float, int]) -> "GPUArray":
        if isinstance(other, GPUArray):
            return GPUArray(self._data - other._data, self._dtype)
        return GPUArray(self._data - other, self._dtype)
    
    def __rsub__(self, other: Union[float, int]) -> "GPUArray":
        return GPUArray(other - self._data, self._dtype)
    
    def __mul__(self, other: Union["GPUArray", float, int]) -> "GPUArray":
        if isinstance(other, GPUArray):
            return GPUArray(self._data * other._data, self._dtype)
        return GPUArray(self._data * other, self._dtype)
    
    def __rmul__(self, other: Union[float, int]) -> "GPUArray":
        return GPUArray(other * self._data, self._dtype)
    
    def __truediv__(self, other: Union["GPUArray", float, int]) -> "GPUArray":
        if isinstance(other, GPUArray):
            return GPUArray(self._data / other._data, self._dtype)
        return GPUArray(self._data / other, self._dtype)
    
    def __pow__(self, other: Union[float, int]) -> "GPUArray":
        return GPUArray(self._data ** other, self._dtype)
    
    def __neg__(self) -> "GPUArray":
        return GPUArray(-self._data, self._dtype)
    
    # Reductions
    def sum(self) -> float:
        """Sum of all elements."""
        return float(self._data.sum())
    
    def mean(self) -> float:
        """Mean of all elements."""
        return float(self._data.mean())
    
    def max(self) -> float:
        """Maximum element."""
        return float(self._data.max())
    
    def min(self) -> float:
        """Minimum element."""
        return float(self._data.min())
    
    def std(self) -> float:
        """Standard deviation."""
        return float(self._data.std())
    
    # Element-wise functions
    def sqrt(self) -> "GPUArray":
        """Element-wise square root."""
        if CUDA_BACKEND == "cupy":
            return GPUArray(cp.sqrt(self._data), self._dtype)
        raise RuntimeError(f"Unknown backend: {CUDA_BACKEND}")
    
    def exp(self) -> "GPUArray":
        """Element-wise exponential."""
        if CUDA_BACKEND == "cupy":
            return GPUArray(cp.exp(self._data), self._dtype)
        raise RuntimeError(f"Unknown backend: {CUDA_BACKEND}")
    
    def log(self) -> "GPUArray":
        """Element-wise natural logarithm."""
        if CUDA_BACKEND == "cupy":
            return GPUArray(cp.log(self._data), self._dtype)
        raise RuntimeError(f"Unknown backend: {CUDA_BACKEND}")
    
    def abs(self) -> "GPUArray":
        """Element-wise absolute value."""
        if CUDA_BACKEND == "cupy":
            return GPUArray(cp.abs(self._data), self._dtype)
        raise RuntimeError(f"Unknown backend: {CUDA_BACKEND}")
    
    def __repr__(self) -> str:
        return f"GPUArray(shape={self.shape}, dtype={self.dtype})"
    
    def __str__(self) -> str:
        return f"GPUArray(shape={self.shape}, dtype={self.dtype}, device=cuda:{get_runtime()._device_id})"


def to_gpu(arr: np.ndarray) -> GPUArray:
    """
    Transfer NumPy array to GPU.
    
    Args:
        arr: NumPy array.
        
    Returns:
        GPUArray.
    """
    return GPUArray.from_numpy(arr)


def to_cpu(arr: GPUArray) -> np.ndarray:
    """
    Transfer GPUArray to CPU.
    
    Args:
        arr: GPU array.
        
    Returns:
        NumPy array.
    """
    return arr.to_numpy()

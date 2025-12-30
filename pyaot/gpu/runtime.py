"""
GPU Runtime for PyAOT.

Manages GPU device, memory allocation, and kernel execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np

from pyaot.gpu import CUDA_AVAILABLE, CUDA_BACKEND

# Import GPU backend
if CUDA_BACKEND == "cupy":
    import cupy as cp
else:
    cp = None


@dataclass
class DeviceInfo:
    """Information about a GPU device."""
    id: int
    name: str
    compute_capability: Tuple[int, int]
    total_memory: int  # bytes
    multiprocessors: int


@dataclass
class MemoryStats:
    """GPU memory statistics."""
    total: int      # Total memory in bytes
    used: int       # Used memory in bytes
    free: int       # Free memory in bytes
    
    @property
    def used_percent(self) -> float:
        return (self.used / self.total) * 100 if self.total > 0 else 0.0


class GPURuntime:
    """
    Manage GPU device, memory, and kernel execution.
    
    Provides:
    - Device enumeration and selection
    - Memory allocation and transfer
    - Kernel launch configuration
    - Synchronization
    
    Example:
        runtime = GPURuntime()
        if runtime.is_available:
            arr_gpu = runtime.to_gpu(numpy_array)
            # ... run kernels ...
            result = runtime.to_cpu(arr_gpu)
    """
    
    def __init__(self, device_id: int = 0):
        self._device_id = device_id
        self._device_info: Optional[DeviceInfo] = None
        self._initialized = False
        
        if CUDA_AVAILABLE:
            self._initialize()
    
    @property
    def is_available(self) -> bool:
        """Check if GPU is available."""
        return CUDA_AVAILABLE and self._initialized
    
    @property
    def device_info(self) -> Optional[DeviceInfo]:
        """Get current device information."""
        return self._device_info
    
    def _initialize(self) -> None:
        """Initialize GPU runtime."""
        if CUDA_BACKEND == "cupy":
            self._init_cupy()
        self._initialized = True
    
    def _init_cupy(self) -> None:
        """Initialize with CuPy backend."""
        device = cp.cuda.Device(self._device_id)
        
        self._device_info = DeviceInfo(
            id=self._device_id,
            name=str(device),
            compute_capability=device.compute_capability,
            total_memory=device.mem_info[1],
            multiprocessors=device.attributes.get("MultiProcessorCount", 0),
        )
    
    def to_gpu(self, array: np.ndarray) -> Any:
        """
        Transfer NumPy array to GPU.
        
        Args:
            array: NumPy array to transfer.
            
        Returns:
            GPU array.
        """
        if not self.is_available:
            raise RuntimeError("GPU not available")
        
        if CUDA_BACKEND == "cupy":
            return cp.asarray(array)
        
        raise RuntimeError(f"Unknown backend: {CUDA_BACKEND}")
    
    def to_cpu(self, gpu_array: Any) -> np.ndarray:
        """
        Transfer GPU array to CPU.
        
        Args:
            gpu_array: GPU array to transfer.
            
        Returns:
            NumPy array.
        """
        if not self.is_available:
            raise RuntimeError("GPU not available")
        
        if CUDA_BACKEND == "cupy":
            return cp.asnumpy(gpu_array)
        
        raise RuntimeError(f"Unknown backend: {CUDA_BACKEND}")
    
    def allocate(
        self,
        shape: Tuple[int, ...],
        dtype: np.dtype = np.float64,
    ) -> Any:
        """
        Allocate GPU memory.
        
        Args:
            shape: Array shape.
            dtype: Data type.
            
        Returns:
            GPU array.
        """
        if not self.is_available:
            raise RuntimeError("GPU not available")
        
        if CUDA_BACKEND == "cupy":
            return cp.zeros(shape, dtype=dtype)
        
        raise RuntimeError(f"Unknown backend: {CUDA_BACKEND}")
    
    def get_memory_stats(self) -> MemoryStats:
        """Get GPU memory statistics."""
        if not self.is_available:
            return MemoryStats(total=0, used=0, free=0)
        
        if CUDA_BACKEND == "cupy":
            mempool = cp.get_default_memory_pool()
            device = cp.cuda.Device(self._device_id)
            free, total = device.mem_info
            
            return MemoryStats(
                total=total,
                used=total - free,
                free=free,
            )
        
        return MemoryStats(total=0, used=0, free=0)
    
    def synchronize(self) -> None:
        """Synchronize GPU with CPU."""
        if not self.is_available:
            return
        
        if CUDA_BACKEND == "cupy":
            cp.cuda.Device(self._device_id).synchronize()
    
    def launch_kernel(
        self,
        kernel: Any,
        grid: Tuple[int, ...],
        block: Tuple[int, ...],
        *args,
    ) -> None:
        """
        Launch a CUDA kernel.
        
        Args:
            kernel: Compiled kernel.
            grid: Grid dimensions.
            block: Block dimensions.
            args: Kernel arguments.
        """
        if not self.is_available:
            raise RuntimeError("GPU not available")
        
        kernel(grid, block, args)
    
    def compute_launch_config(
        self,
        n_elements: int,
        block_size: int = 256,
    ) -> Tuple[Tuple[int, ...], Tuple[int, ...]]:
        """
        Compute optimal launch configuration.
        
        Args:
            n_elements: Number of elements to process.
            block_size: Threads per block.
            
        Returns:
            Tuple of (grid, block) dimensions.
        """
        grid = ((n_elements + block_size - 1) // block_size,)
        block = (block_size,)
        return grid, block


# Global runtime instance
_runtime: Optional[GPURuntime] = None


def get_runtime() -> GPURuntime:
    """Get the global GPU runtime."""
    global _runtime
    if _runtime is None:
        _runtime = GPURuntime()
    return _runtime

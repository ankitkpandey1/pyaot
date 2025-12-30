"""
PyAOT GPU Module.

Provides GPU acceleration for parallel workloads via CUDA.

Components:
- cuda_codegen: Generate CUDA kernels from IR
- runtime: GPU memory and kernel management
- array: NumPy-compatible GPU arrays
"""

from __future__ import annotations

from typing import TYPE_CHECKING

# Check for CUDA availability
CUDA_AVAILABLE = False
CUDA_BACKEND = None

try:
    import cupy as cp
    CUDA_AVAILABLE = True
    CUDA_BACKEND = "cupy"
except ImportError:
    try:
        import pycuda.driver as cuda
        import pycuda.autoinit
        CUDA_AVAILABLE = True
        CUDA_BACKEND = "pycuda"
    except ImportError:
        pass

if TYPE_CHECKING:
    from pyaot.gpu.cuda_codegen import CUDACodegen
    from pyaot.gpu.runtime import GPURuntime
    from pyaot.gpu.array import GPUArray


def is_cuda_available() -> bool:
    """Check if CUDA is available."""
    return CUDA_AVAILABLE


def get_cuda_backend() -> str:
    """Get the active CUDA backend name."""
    return CUDA_BACKEND or "none"


__all__ = [
    "CUDA_AVAILABLE",
    "CUDA_BACKEND",
    "is_cuda_available",
    "get_cuda_backend",
]

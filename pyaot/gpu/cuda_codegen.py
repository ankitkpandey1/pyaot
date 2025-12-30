"""
CUDA Code Generation for PyAOT.

Generates CUDA kernels from PyAOT IR for GPU execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from pyaot.compiler.ir import (
    IRBasicBlock,
    IRFunction,
    IRInstruction,
    IRType,
    IRTypeKind,
    IRValue,
    Opcode,
)

# Check CUDA availability
try:
    import cupy as cp
    CUPY_AVAILABLE = True
except ImportError:
    CUPY_AVAILABLE = False
    cp = None


@dataclass
class CUDAKernel:
    """Compiled CUDA kernel."""
    name: str
    source: str
    func: Optional[Any] = None  # CuPy RawKernel or PyCUDA function
    grid: Tuple[int, ...] = (1,)
    block: Tuple[int, ...] = (256,)
    
    def __call__(self, *args, **kwargs) -> Any:
        """Execute the kernel."""
        if self.func is None:
            raise RuntimeError("Kernel not compiled")
        return self.func(self.grid, self.block, args)


@dataclass 
class CUDACompilationResult:
    """Result of CUDA compilation."""
    success: bool = False
    kernel: Optional[CUDAKernel] = None
    source: str = ""
    error: Optional[str] = None


class CUDACodegen:
    """
    Generate CUDA kernels from PyAOT IR.
    
    Transforms embarrassingly parallel IR to CUDA kernels.
    Currently supports:
    - Element-wise operations on arrays
    - Reduction operations (sum, max, min)
    - Map operations
    
    Example:
        codegen = CUDACodegen()
        result = codegen.compile_kernel(ir_func)
        if result.success:
            output = result.kernel(input_array)
    """
    
    def __init__(self):
        self._source_lines: List[str] = []
        self._indent = 0
    
    def compile_kernel(self, ir_func: IRFunction) -> CUDACompilationResult:
        """
        Compile IR function to CUDA kernel.
        
        Args:
            ir_func: IR function to compile.
            
        Returns:
            CUDACompilationResult with compiled kernel.
        """
        result = CUDACompilationResult()
        
        try:
            # Generate CUDA source
            source = self._generate_kernel_source(ir_func)
            result.source = source
            
            # Compile with CuPy if available
            if CUPY_AVAILABLE:
                kernel = self._compile_with_cupy(ir_func.name, source)
                result.kernel = kernel
                result.success = True
            else:
                result.error = "No CUDA backend available (install cupy)"
                
        except Exception as e:
            result.error = str(e)
        
        return result
    
    def _generate_kernel_source(self, ir_func: IRFunction) -> str:
        """Generate CUDA C source from IR function."""
        self._source_lines = []
        self._indent = 0
        
        # Generate kernel signature
        params = self._generate_params(ir_func)
        self._emit(f"extern \"C\" __global__ void {ir_func.name}({params}) {{")
        self._indent += 1
        
        # Thread index
        self._emit("int idx = blockIdx.x * blockDim.x + threadIdx.x;")
        
        # Generate body
        for block in ir_func.blocks:
            self._generate_block(block)
        
        self._indent -= 1
        self._emit("}")
        
        return "\n".join(self._source_lines)
    
    def _generate_params(self, ir_func: IRFunction) -> str:
        """Generate kernel parameter list."""
        params = []
        for name, typ in zip(ir_func.arg_names, ir_func.arg_types):
            ctype = self._to_cuda_type(typ)
            if typ.kind == IRTypeKind.ARRAY:
                params.append(f"{ctype}* {name}")
            else:
                params.append(f"{ctype} {name}")
        return ", ".join(params)
    
    def _to_cuda_type(self, ir_type: IRType) -> str:
        """Convert IR type to CUDA type."""
        mapping = {
            IRTypeKind.VOID: "void",
            IRTypeKind.BOOL: "bool",
            IRTypeKind.INT32: "int",
            IRTypeKind.INT64: "long long",
            IRTypeKind.FLOAT32: "float",
            IRTypeKind.FLOAT64: "double",
            IRTypeKind.PTR: "void*",
            IRTypeKind.ARRAY: "double",  # Element type
        }
        return mapping.get(ir_type.kind, "double")
    
    def _generate_block(self, block: IRBasicBlock) -> None:
        """Generate code for a basic block."""
        for inst in block.instructions:
            self._generate_instruction(inst)
    
    def _generate_instruction(self, inst: IRInstruction) -> None:
        """Generate code for an instruction."""
        opcode = inst.opcode
        
        if opcode == Opcode.ARRAY_LOAD:
            arr = inst.operands[0].name if isinstance(inst.operands[0], IRValue) else inst.operands[0]
            self._emit(f"double {inst.result.name} = {arr}[idx];")
            
        elif opcode == Opcode.ARRAY_STORE:
            arr = inst.operands[0].name if isinstance(inst.operands[0], IRValue) else inst.operands[0]
            val = self._get_operand(inst.operands[2])
            self._emit(f"{arr}[idx] = {val};")
            
        elif opcode == Opcode.FADD:
            left = self._get_operand(inst.operands[0])
            right = self._get_operand(inst.operands[1])
            self._emit(f"double {inst.result.name} = {left} + {right};")
            
        elif opcode == Opcode.FSUB:
            left = self._get_operand(inst.operands[0])
            right = self._get_operand(inst.operands[1])
            self._emit(f"double {inst.result.name} = {left} - {right};")
            
        elif opcode == Opcode.FMUL:
            left = self._get_operand(inst.operands[0])
            right = self._get_operand(inst.operands[1])
            self._emit(f"double {inst.result.name} = {left} * {right};")
            
        elif opcode == Opcode.FDIV:
            left = self._get_operand(inst.operands[0])
            right = self._get_operand(inst.operands[1])
            self._emit(f"double {inst.result.name} = {left} / {right};")
            
        elif opcode == Opcode.CONST_FLOAT:
            self._emit(f"double {inst.result.name} = {inst.operands[0]};")
            
        elif opcode == Opcode.CONST_INT:
            self._emit(f"long long {inst.result.name} = {inst.operands[0]};")
            
        elif opcode == Opcode.RET:
            pass  # GPU kernels don't return values directly
    
    def _get_operand(self, operand: Any) -> str:
        """Get operand as string."""
        if isinstance(operand, IRValue):
            return operand.name
        return str(operand)
    
    def _emit(self, line: str) -> None:
        """Emit a line of CUDA code."""
        self._source_lines.append("    " * self._indent + line)
    
    def _compile_with_cupy(self, name: str, source: str) -> CUDAKernel:
        """Compile CUDA source with CuPy."""
        if not CUPY_AVAILABLE:
            raise RuntimeError("CuPy not available")
        
        raw_kernel = cp.RawKernel(source, name)
        
        return CUDAKernel(
            name=name,
            source=source,
            func=raw_kernel,
        )


def generate_elementwise_kernel(
    operation: str,
    dtype: str = "double",
) -> str:
    """
    Generate a simple element-wise CUDA kernel.
    
    Args:
        operation: Operation expression (e.g., "x * 2.0")
        dtype: Data type.
        
    Returns:
        CUDA kernel source code.
    """
    return f'''
extern "C" __global__ void elementwise_kernel({dtype}* input, {dtype}* output, int n) {{
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx < n) {{
        {dtype} x = input[idx];
        output[idx] = {operation};
    }}
}}
'''


def generate_reduction_kernel(
    op: str = "+",
    identity: str = "0.0",
    dtype: str = "double",
) -> str:
    """
    Generate a reduction CUDA kernel.
    
    Args:
        op: Reduction operator (+, *, max, min).
        identity: Identity element.
        dtype: Data type.
        
    Returns:
        CUDA kernel source code.
    """
    return f'''
extern "C" __global__ void reduction_kernel({dtype}* input, {dtype}* output, int n) {{
    __shared__ {dtype} sdata[256];
    
    int tid = threadIdx.x;
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    
    // Load data
    sdata[tid] = (idx < n) ? input[idx] : {identity};
    __syncthreads();
    
    // Reduction in shared memory
    for (int s = blockDim.x / 2; s > 0; s >>= 1) {{
        if (tid < s) {{
            sdata[tid] = sdata[tid] {op} sdata[tid + s];
        }}
        __syncthreads();
    }}
    
    // Write result
    if (tid == 0) {{
        output[blockIdx.x] = sdata[0];
    }}
}}
'''

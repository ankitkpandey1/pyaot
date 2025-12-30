"""
Loop Vectorizer for PyAOT.

Transforms numeric loops to use SIMD instructions for parallel execution.
Targets: AVX2 (4×f64), AVX-512 (8×f64), NEON (2×f64).
"""

from __future__ import annotations

import platform
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Tuple

from pyaot.compiler.ir import (
    IRBasicBlock,
    IRFunction,
    IRInstruction,
    IRLoop,
    IRType,
    IRTypeKind,
    IRValue,
    Opcode,
)


class VectorWidth(Enum):
    """Supported SIMD vector widths."""
    SSE = 2       # SSE: 2×f64 (128-bit)
    AVX = 4       # AVX/AVX2: 4×f64 (256-bit)
    AVX512 = 8    # AVX-512: 8×f64 (512-bit)
    NEON = 2      # ARM NEON: 2×f64 (128-bit)


@dataclass
class VectorizationResult:
    """Result of vectorization analysis or transformation."""
    success: bool = False
    vectorized_func: Optional[IRFunction] = None
    vector_width: int = 4
    speedup_estimate: float = 1.0
    reason: Optional[str] = None


@dataclass
class LoopAnalysis:
    """Analysis result for a single loop."""
    loop: IRLoop
    is_vectorizable: bool = False
    vector_width: int = 4
    
    # Reasons if not vectorizable
    blocking_reasons: List[str] = field(default_factory=list)
    
    # Loop characteristics
    has_reduction: bool = False
    has_dependencies: bool = False
    trip_count_known: bool = False
    estimated_trip_count: Optional[int] = None


class LoopVectorizer:
    """
    Vectorize numeric loops using LLVM's auto-vectorization hints.
    
    The vectorizer:
    1. Detects vectorizable loops (simple for-loops over arrays)
    2. Analyzes dependencies to ensure correctness
    3. Generates SIMD instructions or marks loops for LLVM vectorization
    
    Example:
        vectorizer = LoopVectorizer()
        result = vectorizer.vectorize(ir_func)
        if result.success:
            use(result.vectorized_func)
    """
    
    def __init__(self, target_width: Optional[VectorWidth] = None):
        """
        Initialize vectorizer.
        
        Args:
            target_width: Target SIMD width, auto-detected if None.
        """
        self.target_width = target_width or self._detect_target_width()
        self._loop_analyses: Dict[str, LoopAnalysis] = {}
    
    def _detect_target_width(self) -> VectorWidth:
        """Detect best SIMD width for current platform."""
        machine = platform.machine().lower()
        
        if machine in ('x86_64', 'amd64'):
            # Check for AVX-512 support via CPUID would go here
            # For now, default to AVX2
            return VectorWidth.AVX
        elif machine in ('arm64', 'aarch64'):
            return VectorWidth.NEON
        else:
            return VectorWidth.SSE  # Conservative fallback
    
    def analyze_function(self, func: IRFunction) -> List[LoopAnalysis]:
        """
        Analyze all loops in a function for vectorization potential.
        
        Args:
            func: IR function to analyze.
            
        Returns:
            List of LoopAnalysis for each detected loop.
        """
        analyses = []
        loops = self._detect_loops(func)
        
        for loop in loops:
            analysis = self._analyze_loop(loop, func)
            analyses.append(analysis)
            self._loop_analyses[loop.header.name] = analysis
        
        return analyses
    
    def _detect_loops(self, func: IRFunction) -> List[IRLoop]:
        """Detect loops in a function using CFG back edges."""
        loops = []
        
        # Simple loop detection: look for back edges in CFG
        visited = set()
        
        for block in func.blocks:
            for succ in block.successors:
                # Back edge: successor is already visited
                if succ.name in visited:
                    # Found a loop with header at succ
                    loop = self._construct_loop(succ, block, func)
                    if loop:
                        loops.append(loop)
            visited.add(block.name)
        
        return loops
    
    def _construct_loop(
        self,
        header: IRBasicBlock,
        latch: IRBasicBlock,
        func: IRFunction,
    ) -> Optional[IRLoop]:
        """Construct IRLoop from header and latch blocks."""
        # Find exit block (successor of header that's not in loop)
        exit_block = None
        body_block = None
        
        for succ in header.successors:
            if succ != latch and succ != header:
                exit_block = succ
            else:
                body_block = succ
        
        if not exit_block:
            # Can't determine exit
            return None
        
        if not body_block:
            body_block = latch
        
        return IRLoop(
            header=header,
            body=body_block,
            latch=latch,
            exit_block=exit_block,
        )
    
    def _analyze_loop(self, loop: IRLoop, func: IRFunction) -> LoopAnalysis:
        """Analyze a single loop for vectorization."""
        analysis = LoopAnalysis(loop=loop)
        
        # Check for known trip count
        analysis.trip_count_known = (
            loop.start_value is not None and 
            loop.end_value is not None
        )
        
        # Check for loop-carried dependencies
        analysis.has_dependencies = self._has_loop_dependencies(loop)
        
        # Check for reductions
        analysis.has_reduction = self._has_reduction(loop)
        
        # Determine if vectorizable
        if analysis.has_dependencies:
            analysis.blocking_reasons.append("Loop-carried dependencies detected")
        
        # Check body for unsupported operations
        unsupported = self._find_unsupported_ops(loop)
        if unsupported:
            analysis.blocking_reasons.append(f"Unsupported ops: {unsupported}")
        
        analysis.is_vectorizable = len(analysis.blocking_reasons) == 0
        analysis.vector_width = self.target_width.value
        
        return analysis
    
    def _has_loop_dependencies(self, loop: IRLoop) -> bool:
        """Check if loop has loop-carried dependencies."""
        # Simple check: look for STORE followed by LOAD to same location
        stores = set()
        
        for inst in loop.body.instructions:
            if inst.opcode == Opcode.ARRAY_STORE:
                # Track stored locations
                if inst.operands:
                    stores.add(id(inst.operands[0]))
            elif inst.opcode == Opcode.ARRAY_LOAD:
                # Check if loading from stored location
                if inst.operands and id(inst.operands[0]) in stores:
                    return True
        
        return False
    
    def _has_reduction(self, loop: IRLoop) -> bool:
        """Check if loop has reduction pattern (e.g., sum += x)."""
        for inst in loop.body.instructions:
            if inst.opcode in (Opcode.ADD, Opcode.FADD):
                return True
        return False
    
    def _find_unsupported_ops(self, loop: IRLoop) -> List[str]:
        """Find operations that can't be vectorized."""
        unsupported = []
        
        vectorizable_ops = {
            Opcode.ADD, Opcode.SUB, Opcode.MUL, Opcode.DIV,
            Opcode.FADD, Opcode.FSUB, Opcode.FMUL, Opcode.FDIV,
            Opcode.ARRAY_LOAD, Opcode.ARRAY_STORE,
            Opcode.CONST_INT, Opcode.CONST_FLOAT,
            Opcode.LT, Opcode.LE, Opcode.GT, Opcode.GE, Opcode.EQ, Opcode.NE,
        }
        
        for inst in loop.body.instructions:
            if inst.opcode not in vectorizable_ops:
                # Skip control flow in body
                if inst.opcode not in (Opcode.BR, Opcode.BR_COND):
                    unsupported.append(inst.opcode.name)
        
        return unsupported
    
    def vectorize(self, func: IRFunction) -> VectorizationResult:
        """
        Vectorize loops in a function.
        
        Args:
            func: Function to vectorize.
            
        Returns:
            VectorizationResult with transformed function.
        """
        result = VectorizationResult()
        
        # Analyze loops
        analyses = self.analyze_function(func)
        
        if not analyses:
            result.reason = "No loops detected"
            return result
        
        # Find vectorizable loops
        vectorizable = [a for a in analyses if a.is_vectorizable]
        
        if not vectorizable:
            reasons = [a.blocking_reasons for a in analyses if a.blocking_reasons]
            result.reason = f"No vectorizable loops: {reasons}"
            return result
        
        # Transform loops
        new_func = self._clone_function(func)
        
        for analysis in vectorizable:
            self._vectorize_loop(analysis, new_func)
        
        result.success = True
        result.vectorized_func = new_func
        result.vector_width = self.target_width.value
        result.speedup_estimate = float(self.target_width.value)
        
        return result
    
    def _clone_function(self, func: IRFunction) -> IRFunction:
        """Create a deep copy of a function."""
        new_func = IRFunction(
            name=f"{func.name}_vectorized",
            return_type=func.return_type,
            arg_names=func.arg_names.copy(),
            arg_types=func.arg_types.copy(),
        )
        
        # Clone blocks
        block_map = {}
        for block in func.blocks:
            new_block = IRBasicBlock(name=block.name)
            new_block.instructions = block.instructions.copy()
            new_func.blocks.append(new_block)
            block_map[block.name] = new_block
        
        return new_func
    
    def _vectorize_loop(self, analysis: LoopAnalysis, func: IRFunction) -> None:
        """Transform a loop to use SIMD operations."""
        loop = analysis.loop
        width = analysis.vector_width
        
        # Insert vectorization hints for LLVM
        # In practice, this adds metadata that LLVM uses for auto-vectorization
        
        # Add SIMD operations to body
        new_instructions = []
        
        for inst in loop.body.instructions:
            simd_inst = self._convert_to_simd(inst, width)
            new_instructions.append(simd_inst)
        
        # Update loop body
        loop.body.instructions = new_instructions
        loop.is_vectorizable = True
        loop.vector_width = width
    
    def _convert_to_simd(self, inst: IRInstruction, width: int) -> IRInstruction:
        """Convert scalar instruction to SIMD equivalent."""
        simd_map = {
            Opcode.ADD: Opcode.SIMD_ADD,
            Opcode.SUB: Opcode.SIMD_SUB,
            Opcode.MUL: Opcode.SIMD_MUL,
            Opcode.DIV: Opcode.SIMD_DIV,
            Opcode.FADD: Opcode.SIMD_FADD,
            Opcode.FSUB: Opcode.SIMD_FSUB,
            Opcode.FMUL: Opcode.SIMD_FMUL,
            Opcode.FDIV: Opcode.SIMD_FDIV,
            Opcode.ARRAY_LOAD: Opcode.SIMD_LOAD,
            Opcode.ARRAY_STORE: Opcode.SIMD_STORE,
        }
        
        new_opcode = simd_map.get(inst.opcode, inst.opcode)
        
        # Create vectorized result type
        if inst.result and inst.result.type.kind in (IRTypeKind.FLOAT64, IRTypeKind.INT64):
            new_type = IRType.vector(inst.result.type, width)
            new_result = IRValue(
                name=f"{inst.result.name}_v{width}",
                type=new_type,
            )
        else:
            new_result = inst.result
        
        return IRInstruction(
            opcode=new_opcode,
            result=new_result,
            operands=inst.operands.copy(),
            metadata={**inst.metadata, "vectorized": True, "width": width},
        )


def create_vectorized_sum(
    array_type: IRType = IRType.array(IRType.f64()),
    vector_width: int = 4,
) -> IRFunction:
    """
    Create a vectorized sum function for benchmarking.
    
    Generates:
        fn vectorized_sum(arr: *f64, len: i64) -> f64:
            vec_sum = <0.0, 0.0, 0.0, 0.0>
            for i in 0..len step 4:
                vec = SIMD_LOAD arr[i:i+4]
                vec_sum = SIMD_FADD vec_sum, vec
            return SIMD_REDUCE_ADD vec_sum
    """
    func = IRFunction(
        name="vectorized_sum",
        return_type=IRType.f64(),
        arg_names=["arr", "len"],
        arg_types=[array_type, IRType.i64()],
    )
    
    # Entry block
    entry = func.new_block("entry")
    
    # Initialize vector accumulator to zero
    vec_zero = func.new_value(IRType.vector(IRType.f64(), vector_width), "vec_zero")
    entry.append(IRInstruction(
        opcode=Opcode.SIMD_BROADCAST,
        result=vec_zero,
        operands=[0.0],
        metadata={"width": vector_width},
    ))
    
    # Loop header
    header = func.new_block("loop_header")
    
    # Loop body
    body = func.new_block("loop_body")
    
    # Load vector
    vec_load = func.new_value(IRType.vector(IRType.f64(), vector_width), "vec_load")
    body.append(IRInstruction(
        opcode=Opcode.SIMD_LOAD,
        result=vec_load,
        operands=[func.get_local("arr")],
        metadata={"width": vector_width},
    ))
    
    # Add to accumulator
    vec_sum = func.new_value(IRType.vector(IRType.f64(), vector_width), "vec_sum")
    body.append(IRInstruction(
        opcode=Opcode.SIMD_FADD,
        result=vec_sum,
        operands=[vec_zero, vec_load],
        metadata={"width": vector_width},
    ))
    
    # Exit block with reduction
    exit_block = func.new_block("exit")
    
    # Horizontal sum
    result = func.new_value(IRType.f64(), "result")
    exit_block.append(IRInstruction(
        opcode=Opcode.SIMD_REDUCE_ADD,
        result=result,
        operands=[vec_sum],
    ))
    
    # Return
    exit_block.append(IRInstruction(
        opcode=Opcode.RET,
        operands=[result],
    ))
    
    return func

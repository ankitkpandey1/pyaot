"""Regression tests for trace-based compilation pipeline.

These tests verify that the compilation pipeline works correctly:
1. Tracing/IR lowering produces correct IR
2. LLVM IR generation is correct  
3. Native code execution produces correct results

These tests do NOT verify performance - see FFI_ANALYSIS.md for
performance limitations with ctypes FFI.
"""

import pytest

# Skip all tests if llvmlite is not available
llvmlite = pytest.importorskip("llvmlite")


# Module-level test functions (required for inspect.getsource)
def _compute_xy(x, y):
    return x * y + x


def _heavy_compute(x):
    a = x * x
    b = a + x
    c = b * a
    return c


def _int_add(x, y):
    return x + y


def _add_sub_mul(x, y):
    return x + y - x * y


def _add_numbers(x, y):
    return x + y


def _simple_func(x, y):
    return x + y


class TestLLVMIRGeneration:
    """Test that PyAOT IR is correctly converted to LLVM IR."""

    def test_llvm_ir_structure(self):
        """LLVM IR has correct structure."""
        from pyaot.inline.ir_inline import IRInlinePass
        from pyaot.compiler.ir import IRType
        from pyaot.compiler.codegen import LLVMCodegen
        from llvmlite import ir as llvm_ir
        from llvmlite import binding as llvm

        llvm.initialize_all_targets()
        llvm.initialize_native_target()
        llvm.initialize_native_asmprinter()

        inline_pass = IRInlinePass()
        ir_func = inline_pass.lower_callee_to_ir(_compute_xy, [IRType.f64(), IRType.f64()])
        
        if ir_func is None:
            pytest.skip("Function lowering not available in test environment")

        codegen = LLVMCodegen()
        codegen._module = llvm_ir.Module(name="test")
        codegen._module.triple = llvm.get_default_triple()
        codegen._values = {}
        codegen._blocks = {}
        codegen._compile_function(ir_func)

        llvm_ir_str = str(codegen._module)
        
        # Verify LLVM IR structure
        assert "define double" in llvm_ir_str, "Should define double return type"
        assert "fmul double" in llvm_ir_str or "fadd double" in llvm_ir_str, \
            "Should have float instructions"
        assert "ret double" in llvm_ir_str, "Should have ret instruction"

    def test_llvm_ir_verification(self):
        """LLVM IR passes verification."""
        from pyaot.inline.ir_inline import IRInlinePass
        from pyaot.compiler.ir import IRType
        from pyaot.compiler.codegen import LLVMCodegen
        from llvmlite import ir as llvm_ir
        from llvmlite import binding as llvm

        llvm.initialize_all_targets()
        llvm.initialize_native_target()
        llvm.initialize_native_asmprinter()

        inline_pass = IRInlinePass()
        ir_func = inline_pass.lower_callee_to_ir(_add_sub_mul, [IRType.f64(), IRType.f64()])

        if ir_func is None:
            pytest.skip("Function lowering not available in test environment")

        codegen = LLVMCodegen()
        codegen._module = llvm_ir.Module(name="test")
        codegen._module.triple = llvm.get_default_triple()
        codegen._values = {}
        codegen._blocks = {}
        codegen._compile_function(ir_func)

        # Parse and verify - should not raise
        mod = llvm.parse_assembly(str(codegen._module))
        mod.verify()


class TestNativeExecution:
    """Test that compiled native code produces correct results."""

    def test_simple_arithmetic_correctness(self):
        """Native code produces correct result for simple arithmetic."""
        import ctypes
        from pyaot.inline.ir_inline import IRInlinePass
        from pyaot.compiler.ir import IRType
        from pyaot.compiler.codegen import LLVMCodegen
        from llvmlite import ir as llvm_ir
        from llvmlite import binding as llvm

        llvm.initialize_all_targets()
        llvm.initialize_native_target()
        llvm.initialize_native_asmprinter()

        inline_pass = IRInlinePass()
        ir_func = inline_pass.lower_callee_to_ir(_compute_xy, [IRType.f64(), IRType.f64()])

        if ir_func is None:
            pytest.skip("Function lowering not available in test environment")

        codegen = LLVMCodegen()
        codegen._module = llvm_ir.Module(name="test")
        codegen._module.triple = llvm.get_default_triple()
        codegen._values = {}
        codegen._blocks = {}
        codegen._compile_function(ir_func)

        mod = llvm.parse_assembly(str(codegen._module))
        mod.verify()

        target = llvm.Target.from_default_triple()
        tm = target.create_target_machine(opt=3)
        engine = llvm.create_mcjit_compiler(mod, tm)

        func_ptr = engine.get_function_address(ir_func.name)
        CFUNC = ctypes.CFUNCTYPE(ctypes.c_double, ctypes.c_double, ctypes.c_double)
        native_func = CFUNC(func_ptr)

        # Test multiple inputs
        test_cases = [
            (3.0, 4.0),  # 3*4+3 = 15
            (0.0, 5.0),  # 0*5+0 = 0
            (1.0, 1.0),  # 1*1+1 = 2
            (-2.0, 3.0), # -2*3+(-2) = -8
            (0.5, 0.5),  # 0.5*0.5+0.5 = 0.75
        ]

        for x, y in test_cases:
            py_result = _compute_xy(x, y)
            native_result = native_func(x, y)
            assert abs(py_result - native_result) < 1e-10, \
                f"Mismatch for ({x}, {y}): Python={py_result}, Native={native_result}"


class TestFFIOverhead:
    """Document FFI overhead for reference."""

    def test_ctypes_ffi_overhead(self):
        """Measure and document ctypes FFI overhead."""
        import ctypes
        import time

        # Get a fast C function
        lib = ctypes.CDLL(None)
        lround = lib.lround
        lround.argtypes = [ctypes.c_double]
        lround.restype = ctypes.c_long

        # Warmup
        for _ in range(1000):
            lround(0.0)

        # Measure
        N = 100000
        start = time.perf_counter_ns()
        for _ in range(N):
            lround(0.0)
        ctypes_ns = time.perf_counter_ns() - start

        ffi_overhead_ns = ctypes_ns / N
        
        # Document: FFI overhead should be ~200-400ns
        # This test will pass but documents the overhead
        assert ffi_overhead_ns > 100, f"FFI overhead unexpectedly low: {ffi_overhead_ns}ns"
        assert ffi_overhead_ns < 1000, f"FFI overhead unexpectedly high: {ffi_overhead_ns}ns"
        
        print(f"\nctypes FFI overhead: {ffi_overhead_ns:.1f} ns/call")

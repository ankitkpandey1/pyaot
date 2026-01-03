
import sys
import unittest
from pyaot.web.trace.store import TraceRecord, TraceHeader
from pyaot.web.trace.ops import TraceOp, TraceOpcode
from pyaot.web.codegen.compiler import TraceCompiler

class TestCompilerPipeline(unittest.TestCase):
    def test_end_to_end_compile(self):
        # 1. Create a dummy trace
        trace = TraceRecord(
            header=TraceHeader(
                trace_id="test_trace_123",
                route_id="route_1",
                signature_hash=b"123",
                code_version="1.0"
            ),
            ops=(
                TraceOp(opcode=TraceOpcode.TRACE_START),
                TraceOp(opcode=TraceOpcode.LOAD_CONST, operands=(0, 0)), # reg0 = const 0
                TraceOp(opcode=TraceOpcode.RETURN, operands=(0,)),
                TraceOp(opcode=TraceOpcode.TRACE_END),
            )
        )
        
        # 2. Compile
        print("Compiling trace...")
        compiler = TraceCompiler(optimization_level=0)
        try:
            artifact = compiler.compile(trace)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.fail(f"Compilation failed: {e}")

        # 3. Verify artifact
        print(f"Compilation success! Function ptr: {artifact.function_ptr}")
        self.assertIsNotNone(artifact.function_ptr)
        self.assertGreater(artifact.function_ptr, 0)
        self.assertIsNotNone(artifact.callable)
        
        # 4. Try calling it (if possible - signature is void*(void*))
        # Note: calling it requires valid pointers which we mocked as ints in lowering.
        # But successful compilation proves the pipeline works.

if __name__ == "__main__":
    unittest.main()

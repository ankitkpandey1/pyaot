"""Test Step 4: Region Compilation Pipeline."""

import pytest
import os
import sys
from pyaot.region.compiler import compile_function
import pyaot_native

def test_compile_execution():
    """Test full cycle: AST -> C -> SO -> Load -> Run."""
    
    # 1. Define region function
    def add_nums(x, y):
        return x + y
        
    region_id = "add_nums_region"
    
    # 2. Compile and Load
    # This invokes:
    # - RegionCompiler.compile()
    #   - AST parse
    #   - Generate C (PyNumber_Add)
    #   - gcc -shared ...
    # - pyaot_native.load_region()
    try:
        handle = compile_function(add_nums, region_id)
    except Exception as e:
        pytest.fail(f"Compilation failed: {e}")
        
    assert isinstance(handle, int)
    # assert os.path.exists(so_path) # path is internal now
    
    # 3. Execute via Native Runner
    # pyaot_native.run_region should now find the loaded library and execute it
    result = pyaot_native.run_region(handle, (10, 20))
    
    assert result == 30
    print(f"Native result: {result}")

def test_compile_unsupported_op():
    """Test that unsupported operations raise errors gracefully."""
    # Subtraction not yet implemented in _generate_c
    def sub_nums(x, y):
        return x - y
        
    region_id = "sub_nums_region"
    
    # Compilation itself might succeed (generating generic C structure)
    # But currently _generate_c raises NotImplementedError or fallback?
    # Actually my implementation falls back to returning NULL or NotImplementedError code
    
    handle = compile_function(sub_nums, region_id)
    
    # Runtime error when executing
    with pytest.raises(RuntimeError):
         # The C code sets PyErr_SetString(PyExc_NotImplementedError...) and returns NULL
         # Rust runner converts NULL return to PyErr
         pyaot_native.run_region(handle, (10, 5))

if __name__ == "__main__":
    test_compile_execution()

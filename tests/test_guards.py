"""Unit tests for the guards module."""

import pytest
from pyaot.types.guards import Guard, GuardKind, GuardSet, GuardBuilder, GlobalVersionGuard
from pyaot.types.inference import InferredType, IRTypeKind


class TestGuard:
    """Tests for individual guards."""
    
    def test_type_guard_pass(self):
        guard = Guard(
            kind=GuardKind.TYPE,
            arg_index=0,
            expected=int,
            description="arg0 is int",
        )
        
        assert guard.check(42)
        assert guard.check(-1)
    
    def test_type_guard_fail(self):
        guard = Guard(
            kind=GuardKind.TYPE,
            arg_index=0,
            expected=int,
            description="arg0 is int",
        )
        
        assert not guard.check(3.14)
        assert not guard.check("hello")
    
    def test_shape_guard(self):
        try:
            import numpy as np
            
            guard = Guard(
                kind=GuardKind.SHAPE,
                arg_index=0,
                expected=(10, 20),
                description="arg0.shape == (10, 20)",
            )
            
            arr1 = np.zeros((10, 20))
            arr2 = np.zeros((10, 30))
            
            assert guard.check(arr1)
            assert not guard.check(arr2)
        except ImportError:
            pytest.skip("NumPy not available")
    
    def test_dtype_guard(self):
        try:
            import numpy as np
            
            guard = Guard(
                kind=GuardKind.DTYPE,
                arg_index=0,
                expected="float64",
                description="arg0.dtype == float64",
            )
            
            arr_f64 = np.zeros(10, dtype=np.float64)
            arr_f32 = np.zeros(10, dtype=np.float32)
            
            assert guard.check(arr_f64)
            assert not guard.check(arr_f32)
        except ImportError:
            pytest.skip("NumPy not available")


class TestGlobalVersionGuard:
    """Tests for global version guards."""
    
    def test_version_increment(self):
        module = "test_module"
        name = "test_var"
        
        v0 = GlobalVersionGuard.get_version(module, name)
        v1 = GlobalVersionGuard.increment_version(module, name)
        v2 = GlobalVersionGuard.get_version(module, name)
        
        assert v1 == v0 + 1
        assert v2 == v1
    
    def test_version_check_pass(self):
        module = "test_module2"
        name = "test_var2"
        
        current = GlobalVersionGuard.get_version(module, name)
        guard = GlobalVersionGuard(
            global_name=name,
            module_name=module,
            expected_version=current,
        )
        
        assert guard.check()
    
    def test_version_check_fail(self):
        module = "test_module3"
        name = "test_var3"
        
        current = GlobalVersionGuard.get_version(module, name)
        guard = GlobalVersionGuard(
            global_name=name,
            module_name=module,
            expected_version=current,
        )
        
        GlobalVersionGuard.increment_version(module, name)
        assert not guard.check()


class TestGuardSet:
    """Tests for GuardSet."""
    
    def test_empty_guard_set(self):
        guards = GuardSet()
        assert guards.check_all((1, 2, 3))
    
    def test_type_guards(self):
        guards = GuardSet(function_name="test_func")
        guards.add_type_guard(0, int)
        guards.add_type_guard(1, float)
        
        assert guards.check_all((42, 3.14))
        assert not guards.check_all((42, "wrong"))
    
    def test_shape_guards(self):
        try:
            import numpy as np
            
            guards = GuardSet()
            guards.add_shape_guard(0, (10,))
            
            assert guards.check_all((np.zeros(10),))
            assert not guards.check_all((np.zeros(20),))
        except ImportError:
            pytest.skip("NumPy not available")
    
    def test_missing_arg(self):
        guards = GuardSet()
        guards.add_type_guard(5, int)  # arg index 5
        
        # Only 3 args provided
        assert not guards.check_all((1, 2, 3))


class TestGuardBuilder:
    """Tests for GuardBuilder."""
    
    def test_build_numeric_guards(self):
        builder = GuardBuilder()
        
        arg_types = [
            InferredType(kind=IRTypeKind.INT64, python_type="int"),
            InferredType(kind=IRTypeKind.FLOAT64, python_type="float"),
        ]
        
        guards = builder.build_guards(arg_types, "test_func")
        
        assert len(guards.arg_guards) == 2
        assert guards.arg_guards[0].expected == int
        assert guards.arg_guards[1].expected == float
    
    def test_build_array_guards(self):
        builder = GuardBuilder(check_shapes=True, check_dtypes=True)
        
        arg_types = [
            InferredType(
                kind=IRTypeKind.NDARRAY,
                python_type="ndarray",
                dtype="float64",
                shape=(100,),
            ),
        ]
        
        guards = builder.build_guards(arg_types, "test_func")
        
        # Should have type, shape, and dtype guards
        assert len(guards.arg_guards) >= 1

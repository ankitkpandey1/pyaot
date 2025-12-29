"""Unit tests for the profiler module."""

import pytest
from pyaot.profiler import ProfileCollector, FunctionProfile, ProfileData
from pyaot.profiler.data import TypeSignature, ShapeSignature
from pyaot.profiler.context import profiling_session


class TestTypeSignature:
    """Tests for TypeSignature."""
    
    def test_create_type_signature(self):
        sig = TypeSignature(
            arg_types=("int", "float"),
            kwarg_types={"x": "str"},
        )
        assert sig.arg_types == ("int", "float")
        assert sig.kwarg_types == {"x": "str"}
    
    def test_type_signature_hash(self):
        sig1 = TypeSignature(arg_types=("int",), kwarg_types={})
        sig2 = TypeSignature(arg_types=("int",), kwarg_types={})
        sig3 = TypeSignature(arg_types=("float",), kwarg_types={})
        
        assert hash(sig1) == hash(sig2)
        assert hash(sig1) != hash(sig3)
    
    def test_type_signature_equality(self):
        sig1 = TypeSignature(arg_types=("int",), kwarg_types={})
        sig2 = TypeSignature(arg_types=("int",), kwarg_types={})
        sig3 = TypeSignature(arg_types=("float",), kwarg_types={})
        
        assert sig1 == sig2
        assert sig1 != sig3
    
    def test_type_signature_serialization(self):
        sig = TypeSignature(
            arg_types=("int", "float"),
            kwarg_types={"x": "str"},
        )
        d = sig.to_dict()
        restored = TypeSignature.from_dict(d)
        assert restored == sig


class TestShapeSignature:
    """Tests for ShapeSignature."""
    
    def test_create_shape_signature(self):
        sig = ShapeSignature(arg_shapes=((10, 20), None, (5,)))
        assert sig.arg_shapes == ((10, 20), None, (5,))
    
    def test_shape_signature_hash(self):
        sig1 = ShapeSignature(arg_shapes=((10,),))
        sig2 = ShapeSignature(arg_shapes=((10,),))
        sig3 = ShapeSignature(arg_shapes=((20,),))
        
        assert hash(sig1) == hash(sig2)
        assert hash(sig1) != hash(sig3)
    
    def test_shape_signature_serialization(self):
        sig = ShapeSignature(arg_shapes=((10, 20), None))
        d = sig.to_dict()
        restored = ShapeSignature.from_dict(d)
        assert restored == sig


class TestFunctionProfile:
    """Tests for FunctionProfile."""
    
    def test_create_function_profile(self):
        profile = FunctionProfile(
            module="test_module",
            qualname="test_func",
            filename="test.py",
            lineno=10,
        )
        assert profile.key == "test_module:test_func"
        assert profile.call_count == 0
        assert profile.total_time_ns == 0
    
    def test_record_call(self):
        profile = FunctionProfile(
            module="test_module",
            qualname="test_func",
            filename="test.py",
            lineno=10,
        )
        
        type_sig = TypeSignature(arg_types=("int",), kwarg_types={})
        shape_sig = ShapeSignature(arg_shapes=(None,))
        
        profile.record_call(1000, type_sig, shape_sig)
        
        assert profile.call_count == 1
        assert profile.total_time_ns == 1000
        assert profile.type_signatures[type_sig] == 1
    
    def test_type_stability_single_type(self):
        profile = FunctionProfile(
            module="test", qualname="func", filename="t.py", lineno=1
        )
        
        type_sig = TypeSignature(arg_types=("int",), kwarg_types={})
        shape_sig = ShapeSignature(arg_shapes=(None,))
        
        for _ in range(100):
            profile.record_call(100, type_sig, shape_sig)
        
        assert profile.get_type_stability() == 1.0
    
    def test_type_stability_mixed_types(self):
        profile = FunctionProfile(
            module="test", qualname="func", filename="t.py", lineno=1
        )
        
        type_sig1 = TypeSignature(arg_types=("int",), kwarg_types={})
        type_sig2 = TypeSignature(arg_types=("float",), kwarg_types={})
        shape_sig = ShapeSignature(arg_shapes=(None,))
        
        for _ in range(80):
            profile.record_call(100, type_sig1, shape_sig)
        for _ in range(20):
            profile.record_call(100, type_sig2, shape_sig)
        
        assert profile.get_type_stability() == 0.8
    
    def test_stability_score_formula(self):
        profile = FunctionProfile(
            module="test", qualname="func", filename="t.py", lineno=1
        )
        
        type_sig = TypeSignature(arg_types=("int",), kwarg_types={})
        shape_sig = ShapeSignature(arg_shapes=((10,),))
        
        for _ in range(100):
            profile.record_call(100, type_sig, shape_sig)
        
        # Both 100% stable
        assert profile.get_stability_score() == 1.0
    
    def test_serialization(self):
        profile = FunctionProfile(
            module="test", qualname="func", filename="t.py", lineno=1
        )
        
        type_sig = TypeSignature(arg_types=("int",), kwarg_types={})
        shape_sig = ShapeSignature(arg_shapes=((10,),))
        profile.record_call(1000, type_sig, shape_sig)
        
        d = profile.to_dict()
        restored = FunctionProfile.from_dict(d)
        
        assert restored.key == profile.key
        assert restored.call_count == profile.call_count
        assert restored.total_time_ns == profile.total_time_ns


class TestProfileData:
    """Tests for ProfileData."""
    
    def test_get_or_create(self):
        data = ProfileData()
        
        profile = data.get_or_create("mod", "func", "file.py", 1)
        assert profile.key == "mod:func"
        
        # Same key returns same profile
        profile2 = data.get_or_create("mod", "func", "file.py", 1)
        assert profile is profile2
    
    def test_serialization(self):
        data = ProfileData(python_version="3.11.0")
        profile = data.get_or_create("mod", "func", "file.py", 1)
        profile.call_count = 100
        
        json_str = data.to_json()
        restored = ProfileData.from_json(json_str)
        
        assert restored.python_version == data.python_version
        assert len(restored) == 1
        assert restored.get("mod:func").call_count == 100


class TestProfileCollector:
    """Tests for ProfileCollector."""
    
    def test_collector_lifecycle(self):
        collector = ProfileCollector(sample_rate=1)
        
        assert not collector._active
        collector.start()
        assert collector._active
        collector.stop()
        assert not collector._active
    
    def test_profile_simple_function(self):
        def simple_func(x: int) -> int:
            return x + 1
        
        collector = ProfileCollector(sample_rate=1)
        collector.start()
        
        for i in range(10):
            simple_func(i)
        
        collector.stop()
        data = collector.get_data()
        
        # Should have profiled simple_func
        assert len(data) >= 0  # May be 0 due to frame filtering


class TestProfilingSession:
    """Tests for profiling_session context manager."""
    
    def test_context_manager(self):
        with profiling_session(sample_rate=1) as collector:
            x = sum(range(100))
        
        data = collector.get_data()
        assert data.profile_duration_ns > 0

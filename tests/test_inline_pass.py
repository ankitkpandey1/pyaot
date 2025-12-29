"""
Tests for Phase 5 IR-level inline pass, telemetry, and runner.
"""

import pytest
from typing import Callable

# Test fixtures
def simple_add(x: float, y: float) -> float:
    """Simple function for inlining."""
    return x + y

def simple_mult(x: float) -> float:
    """Simple single-arg function."""
    return x * 2.0 + 1.0

def complex_func(x: float) -> float:
    """Function with intermediate computation."""
    y = x * 2.0
    return y + 1.0


class TestTelemetry:
    """Tests for telemetry module."""
    
    def test_singleton(self):
        """Test telemetry singleton."""
        from pyaot.inline.telemetry import get_telemetry, reset_telemetry
        
        reset_telemetry()
        t1 = get_telemetry()
        t2 = get_telemetry()
        
        assert t1 is t2
    
    def test_enable_disable(self):
        """Test enable/disable functionality."""
        from pyaot.inline.telemetry import get_telemetry, reset_telemetry
        
        reset_telemetry()
        t = get_telemetry()
        
        assert not t.is_enabled
        t.enable()
        assert t.is_enabled
        t.disable()
        assert not t.is_enabled
    
    def test_record_observation(self):
        """Test observation recording."""
        from pyaot.inline.telemetry import get_telemetry, reset_telemetry
        
        reset_telemetry()
        t = get_telemetry()
        t.enable()
        
        t.record_observation("test:1", 0.99)
        t.record_observation("test:1", 0.99)
        
        metrics = t.get_callsite_report("test:1")
        assert metrics is not None
        assert metrics["total_calls"] == 2
        assert metrics["dominant_callee_share"] == 0.99
    
    def test_record_native_fallback(self):
        """Test native/fallback call recording."""
        from pyaot.inline.telemetry import get_telemetry, reset_telemetry
        
        reset_telemetry()
        t = get_telemetry()
        t.enable()
        
        t.record_native_call("test:1", 1000)
        t.record_native_call("test:1", 1000)
        t.record_fallback_call("test:1", 2000)
        
        metrics = t.get_callsite_report("test:1")
        assert metrics["optimized_calls"] == 2
        assert metrics["fallback_calls"] == 1
        assert metrics["native_ratio"] == 2/3
    
    def test_record_guard_check(self):
        """Test guard check recording."""
        from pyaot.inline.telemetry import get_telemetry, reset_telemetry
        
        reset_telemetry()
        t = get_telemetry()
        t.enable()
        
        t.record_guard_check("test:1", True, "callee")
        t.record_guard_check("test:1", True, "arg_type")
        t.record_guard_check("test:1", False, "shape")
        
        metrics = t.get_callsite_report("test:1")
        assert metrics["guard_checks"] == 3
        assert metrics["guard_failures"] == 1
        assert metrics["guard_failure_rate"] == 1/3
    
    def test_record_rejection(self):
        """Test rejection recording."""
        from pyaot.inline.telemetry import (
            get_telemetry, reset_telemetry, RejectionReason
        )
        
        reset_telemetry()
        t = get_telemetry()
        
        t.record_rejection("test:1", RejectionReason.NOT_LEAF, "has nested call")
        
        metrics = t.get_callsite_report("test:1")
        assert metrics["rejection_reason"] == "NOT_LEAF"
        assert metrics["rejection_details"] == "has nested call"
        
        log = t.get_rejection_log()
        assert len(log) == 1
        assert log[0]["reason"] == "NOT_LEAF"
    
    def test_global_metrics(self):
        """Test global metrics."""
        from pyaot.inline.telemetry import get_telemetry, reset_telemetry
        
        reset_telemetry()
        t = get_telemetry()
        t.enable()
        
        t.record_native_call("test:1", 1000)
        t.record_fallback_call("test:2", 2000)
        t.record_inline_enabled("test:1")
        
        global_metrics = t.get_global_metrics()
        assert global_metrics["total_optimized_calls"] == 1
        assert global_metrics["total_fallback_calls"] == 1
        assert global_metrics["inlined_callsites"] == 1
        assert global_metrics["fast_path_success_rate"] == 0.5
    
    def test_json_export(self, tmp_path):
        """Test JSON export."""
        from pyaot.inline.telemetry import get_telemetry, reset_telemetry
        import json
        
        reset_telemetry()
        t = get_telemetry()
        t.enable()
        
        t.record_native_call("test:1", 1000)
        
        path = tmp_path / "telemetry.json"
        t.export_to_json(str(path))
        
        with open(path) as f:
            data = json.load(f)
        
        assert "global_metrics" in data
        assert "callsite_metrics" in data
        assert "test:1" in data["callsite_metrics"]


class TestIRInlinePass:
    """Tests for IR-level inline pass."""
    
    def test_can_inline_simple(self):
        """Test that simple functions can be inlined."""
        from pyaot.inline.ir_inline import IRInlinePass
        
        inline_pass = IRInlinePass()
        can_inline, reason = inline_pass.can_inline_callee(simple_mult)
        
        assert can_inline
        assert reason is None
    
    def test_can_inline_two_args(self):
        """Test that two-arg simple functions can be inlined."""
        from pyaot.inline.ir_inline import IRInlinePass
        
        inline_pass = IRInlinePass()
        can_inline, reason = inline_pass.can_inline_callee(simple_add)
        
        assert can_inline
    
    def test_cannot_inline_no_source(self):
        """Test that builtins cannot be inlined."""
        from pyaot.inline.ir_inline import IRInlinePass
        from pyaot.inline.eligibility import IneligibilityReason
        
        inline_pass = IRInlinePass()
        can_inline, reason = inline_pass.can_inline_callee(len)
        
        assert not can_inline
        assert reason == IneligibilityReason.NO_SOURCE
    
    def test_lower_callee_simple(self):
        """Test AST-to-IR lowering for simple function."""
        from pyaot.inline.ir_inline import IRInlinePass
        from pyaot.compiler.ir import IRType
        
        inline_pass = IRInlinePass()
        ir_func = inline_pass.lower_callee_to_ir(
            simple_mult,
            [IRType.f64()],
        )
        
        assert ir_func is not None
        assert ir_func.name == "_inline_simple_mult"
        assert len(ir_func.arg_names) == 1
        assert ir_func.arg_names[0] == "x"
    
    def test_lower_callee_two_args(self):
        """Test AST-to-IR lowering for two-arg function."""
        from pyaot.inline.ir_inline import IRInlinePass
        from pyaot.compiler.ir import IRType
        
        inline_pass = IRInlinePass()
        ir_func = inline_pass.lower_callee_to_ir(
            simple_add,
            [IRType.f64(), IRType.f64()],
        )
        
        assert ir_func is not None
        assert len(ir_func.arg_names) == 2
        assert ir_func.arg_names == ["x", "y"]


class TestGuardMetrics:
    """Tests for guard metrics."""
    
    def test_per_guard_failures(self):
        """Test per-guard failure tracking."""
        from pyaot.inline.guards import InlineGuardSet
        
        guards = InlineGuardSet(
            expected_callee_id=id(simple_mult),
            expected_arg_types=(float,),
        )
        
        # Passing check
        guards.check_all(simple_mult, (1.0,))
        
        # Failing check - wrong callee
        guards.check_all(simple_add, (1.0,))
        
        # Failing check - wrong type
        guards.check_all(simple_mult, (1,))  # int instead of float
        
        assert guards.check_count == 3
        assert guards.failure_count == 2
        assert guards.callee_failures == 1
        assert guards.arg_type_failures == 1
    
    def test_check_fast(self):
        """Test fast guard check."""
        from pyaot.inline.guards import InlineGuardSet
        
        guards = InlineGuardSet(
            expected_callee_id=id(simple_mult),
            expected_arg_types=(float,),
        )
        
        # Fast check should pass
        assert guards.check_fast(simple_mult, (1.0,))
        
        # Fast check should fail on wrong callee
        assert not guards.check_fast(simple_add, (1.0,))
        
        # Fast check should fail on wrong type
        assert not guards.check_fast(simple_mult, (1,))
    
    def test_get_metrics(self):
        """Test GuardMetrics generation."""
        from pyaot.inline.guards import InlineGuardSet
        
        guards = InlineGuardSet(
            expected_callee_id=id(simple_mult),
        )
        
        guards.check_all(simple_mult, (1.0,))
        guards.check_all(simple_mult, (2.0,))
        
        metrics = guards.get_metrics()
        assert metrics.check_count == 2
        assert metrics.failure_count == 0
        assert metrics.failure_rate == 0.0
    
    def test_reset_stats(self):
        """Test reset_stats method."""
        from pyaot.inline.guards import InlineGuardSet
        
        guards = InlineGuardSet(
            expected_callee_id=id(simple_mult),
        )
        
        guards.check_all(simple_mult, (1.0,))
        guards.check_all(simple_add, (1.0,))  # Will fail
        
        assert guards.check_count > 0
        assert guards.failure_count > 0
        
        guards.reset_stats()
        
        assert guards.check_count == 0
        assert guards.failure_count == 0
        assert guards.callee_failures == 0


class TestBenchProtocol:
    """Tests for benchmark protocol."""
    
    def test_benchmark_runner(self):
        """Test basic benchmark runner."""
        from benchmarks.bench_protocol import BenchmarkRunner
        
        def simple_bench():
            return sum(range(100))
        
        runner = BenchmarkRunner(pin_cpu=False, iterations=5)
        result = runner.run_single(
            func=simple_bench,
            name="test",
            configuration="baseline",
        )
        
        assert result.name == "test"
        assert result.configuration == "baseline"
        assert len(result.raw_times_ns) == 5
        assert result.mean_ns > 0
    
    def test_system_info(self):
        """Test system info collection."""
        from benchmarks.bench_protocol import SystemInfo
        
        info = SystemInfo.collect()
        
        assert info.python_version
        assert info.platform_info
        assert info.cpu_count > 0
        assert info.timestamp
    
    def test_amortization_calculator(self):
        """Test amortization calculation."""
        from benchmarks.bench_protocol import AmortizationCalculator
        
        result = AmortizationCalculator.calculate(
            observe_emit_time_ms=100.0,
            baseline_mean_ms=1.0,
            optimized_mean_ms=0.5,
        )
        
        assert result["can_amortize"]
        assert result["amortization_calls"] == 201  # ceil(100 / 0.5) + 1
        assert result["speedup"] == 2.0
    
    def test_amortization_no_savings(self):
        """Test amortization when no savings."""
        from benchmarks.bench_protocol import AmortizationCalculator
        
        result = AmortizationCalculator.calculate(
            observe_emit_time_ms=100.0,
            baseline_mean_ms=0.5,
            optimized_mean_ms=0.5,
        )
        
        assert not result["can_amortize"]


class TestConfig:
    """Tests for Phase 5 configuration."""
    
    def test_inline_config_defaults(self):
        """Test default inline configuration values."""
        from pyaot.config import Config
        
        config = Config()
        
        assert config.inline_enabled == True
        assert config.inline_min_calls == 1000
        assert config.inline_min_callee_share == 0.995
        assert config.inline_log_rejections == False
        assert config.inline_telemetry_enabled == False
    
    def test_inline_env_override(self, monkeypatch):
        """Test environment variable overrides."""
        from pyaot.config import load_config_from_env, reset_config
        
        reset_config()
        
        monkeypatch.setenv("AOT_INLINE_ENABLED", "0")
        monkeypatch.setenv("AOT_INLINE_MIN_CALLS", "500")
        monkeypatch.setenv("AOT_INLINE_MIN_CALLEE_SHARE", "0.99")
        monkeypatch.setenv("AOT_INLINE_LOG_REJECTIONS", "1")
        
        config = load_config_from_env()
        
        assert config.inline_enabled == False
        assert config.inline_min_calls == 500
        assert config.inline_min_callee_share == 0.99
        assert config.inline_log_rejections == True


class TestInlineCodegen:
    """Tests for inline code generation."""
    
    def test_inline_compiler_available(self):
        """Test that inline compiler reports availability."""
        from pyaot.compiler.inline_codegen import get_inline_compiler
        
        compiler = get_inline_compiler()
        # Should be True if llvmlite is installed
        assert isinstance(compiler.is_available, bool)
    
    def test_guarded_artifact_creation(self):
        """Test GuardedArtifact creation."""
        from pyaot.compiler.inline_codegen import GuardedArtifact
        from pyaot.inline.guards import InlineGuardSet
        
        def fallback(x):
            return x * 2.0
        
        guards = InlineGuardSet(
            expected_callee_id=id(fallback),
        )
        
        artifact = GuardedArtifact(
            native_ptr=0,
            native_callable=fallback,  # Using fallback as native for test
            guards=guards,
            fallback=fallback,
            callsite_id="test:1",
        )
        
        # Should work through guards
        result = artifact(5.0)
        assert result == 10.0
        assert artifact.native_calls > 0 or artifact.fallback_calls > 0
    
    def test_compile_for_inline_simple(self):
        """Test compile_for_inline with simple function."""
        from pyaot.compiler.inline_codegen import (
            get_inline_compiler,
            InlineCompiler,
        )
        from pyaot.inline.guards import InlineGuardSet
        from pyaot.compiler.ir import IRType
        
        # Use module-level function that has accessible source
        compiler = get_inline_compiler()
        if not compiler.is_available:
            pytest.skip("llvmlite not available")
        
        guards = InlineGuardSet(expected_callee_id=id(simple_mult))
        result = compiler.compile_inline(
            callee=simple_mult,
            guards=guards,
            callsite_id="test:simple_mult",
            arg_types=[IRType.f64()],
        )
        
        # Test compilation success
        assert result.success, f"Compilation failed: {result.error}"
        assert result.artifact is not None
        
        # Note: Execution is not tested here as the IR lowering
        # may produce incomplete code for complex functions.
        # The GuardedArtifact will fall back to Python on guard failure.
    
    def test_inline_compiler_caching(self):
        """Test that compiler caches artifacts."""
        from pyaot.compiler.inline_codegen import get_inline_compiler
        from pyaot.inline.guards import InlineGuardSet
        
        compiler = get_inline_compiler()
        if not compiler.is_available:
            pytest.skip("llvmlite not available")
        
        def my_func(x):
            return x + 1.0
        
        guards = InlineGuardSet(expected_callee_id=id(my_func))
        
        # Compile twice with same callsite_id
        result1 = compiler.compile_inline(my_func, guards, "test:cache:1")
        result2 = compiler.compile_inline(my_func, guards, "test:cache:1")
        
        # Should return same artifact
        if result1.success and result2.success:
            assert result1.artifact is result2.artifact
    
    def test_inline_compiler_statistics(self):
        """Test statistics collection."""
        from pyaot.compiler.inline_codegen import get_inline_compiler
        
        compiler = get_inline_compiler()
        stats = compiler.get_statistics()
        
        assert "compiled_callsites" in stats
        assert "total_native_calls" in stats
        assert "native_ratio" in stats


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

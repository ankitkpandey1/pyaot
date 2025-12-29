"""
Tests for Phase 5 inline infrastructure.

Tests:
- Callsite profiling
- Eligibility analysis
- Guard generation and checking
- Trampoline dispatch
"""

import pytest
from typing import List
from collections import Counter

# Import inline infrastructure
from pyaot.inline.callsite import (
    CallsiteProfile,
    CallsiteTracker,
    get_global_callsite_tracker,
    reset_global_callsite_tracker,
)
from pyaot.inline.eligibility import (
    is_eligible_for_inline,
    analyze_eligibility,
    is_leaf_function_ast,
    check_signature_compatibility,
    IneligibilityReason,
    MIN_CALL_COUNT,
)
from pyaot.inline.guards import (
    InlineGuardSet,
    create_inline_guards,
    GuardedInlineDispatcher,
    ShapeGuard,
)
from pyaot.inline.expansion import (
    create_guarded_inline,
    InlineCache,
    get_inline_cache,
)
from pyaot.inline.trampoline import (
    InlineTrampoline,
    create_trampoline,
    TrampolineRegistry,
    get_trampoline_registry,
)


# =============================================================================
# Test Functions
# =============================================================================

def simple_leaf(x: float) -> float:
    """Simple leaf function - eligible for inlining."""
    return x * 1.5 + 0.5


def non_leaf_with_call(x: float) -> float:
    """Non-leaf function - calls another function."""
    return simple_leaf(x) + 1.0


def func_with_varargs(*args) -> float:
    """Function with varargs - not eligible."""
    return sum(args)


def func_with_kwargs(**kwargs) -> float:
    """Function with kwargs - not eligible."""
    return kwargs.get('x', 0.0)


def generator_func(n: int):
    """Generator function - not eligible."""
    for i in range(n):
        yield i


async def async_func(x: float) -> float:
    """Async function - not eligible."""
    return x * 2


# =============================================================================
# Callsite Profiling Tests
# =============================================================================

class TestCallsiteProfile:
    """Tests for CallsiteProfile."""
    
    def test_record_call(self):
        """Test recording a call."""
        profile = CallsiteProfile(callsite_id="test:file:10")
        
        profile.record_call(simple_leaf, 1000, (1.0,))
        
        assert profile.total_calls == 1
        assert profile.inclusive_cpu_time_ns == 1000
        assert id(simple_leaf) in profile.observed_callees
    
    def test_is_monomorphic(self):
        """Test monomorphism detection."""
        profile = CallsiteProfile(callsite_id="test:file:10")
        
        # Single callee
        for _ in range(10):
            profile.record_call(simple_leaf, 100, (1.0,))
        
        assert profile.is_monomorphic
        assert profile.dominant_callee_share == 1.0
    
    def test_polymorphic_detection(self):
        """Test polymorphic detection."""
        profile = CallsiteProfile(callsite_id="test:file:10")
        
        # Multiple callees
        for _ in range(10):
            profile.record_call(simple_leaf, 100, (1.0,))
        for _ in range(2):
            profile.record_call(non_leaf_with_call, 100, (1.0,))
        
        assert not profile.is_monomorphic
        assert profile.dominant_callee_share < 1.0
    
    def test_serialization(self):
        """Test serialization/deserialization."""
        profile = CallsiteProfile(
            callsite_id="test:file:10",
            caller_module="test",
            caller_qualname="test.func",
        )
        profile.record_call(simple_leaf, 1000, (1.0, 2.0))
        
        # Round-trip
        data = profile.to_dict()
        loaded = CallsiteProfile.from_dict(data)
        
        assert loaded.callsite_id == profile.callsite_id
        assert loaded.total_calls == profile.total_calls


class TestCallsiteTracker:
    """Tests for CallsiteTracker."""
    
    def test_get_or_create(self):
        """Test get_or_create."""
        tracker = CallsiteTracker()
        
        p1 = tracker.get_or_create("site1")
        p2 = tracker.get_or_create("site1")
        
        assert p1 is p2
    
    def test_record_call(self):
        """Test record_call convenience method."""
        tracker = CallsiteTracker()
        
        tracker.record_call("site1", simple_leaf, 1000, (1.0,))
        
        profile = tracker.get_or_create("site1")
        assert profile.total_calls == 1
    
    def test_get_hot_callsites(self):
        """Test getting hot callsites."""
        tracker = CallsiteTracker()
        
        # Add many calls to one site
        for _ in range(1500):
            tracker.record_call("hot_site", simple_leaf, 1000, (1.0,))
        
        # Add few calls to another
        for _ in range(10):
            tracker.record_call("cold_site", simple_leaf, 100, (1.0,))
        
        hot = tracker.get_hot_callsites(min_calls=1000)
        assert len(hot) == 1
        assert hot[0].callsite_id == "hot_site"
    
    def test_get_monomorphic_callsites(self):
        """Test getting monomorphic callsites."""
        tracker = CallsiteTracker()
        
        # Monomorphic site
        for _ in range(1500):
            tracker.record_call("mono_site", simple_leaf, 100, (1.0,))
        
        mono = tracker.get_monomorphic_callsites(min_calls=1000)
        assert len(mono) == 1


# =============================================================================
# Eligibility Tests
# =============================================================================

class TestEligibility:
    """Tests for eligibility analysis."""
    
    def test_leaf_function_detection(self):
        """Test leaf function detection."""
        is_leaf, reason = is_leaf_function_ast(simple_leaf)
        assert is_leaf
    
    def test_non_leaf_detection(self):
        """Test non-leaf function detection."""
        is_leaf, reason = is_leaf_function_ast(non_leaf_with_call)
        assert not is_leaf
    
    def test_varargs_rejection(self):
        """Test varargs rejection."""
        ok, reason = check_signature_compatibility(func_with_varargs)
        assert not ok
        assert reason == IneligibilityReason.HAS_VARARGS
    
    def test_kwargs_rejection(self):
        """Test kwargs rejection."""
        ok, reason = check_signature_compatibility(func_with_kwargs)
        assert not ok
        assert reason == IneligibilityReason.HAS_KWARGS
    
    def test_generator_rejection(self):
        """Test generator rejection."""
        ok, reason = is_eligible_for_inline(generator_func)
        assert not ok
        assert reason == IneligibilityReason.IS_GENERATOR
    
    def test_eligible_function(self):
        """Test eligible function."""
        ok, reason = is_eligible_for_inline(simple_leaf)
        assert ok
        assert reason is None
    
    def test_analyze_eligibility_insufficient_calls(self):
        """Test eligibility with insufficient calls."""
        profile = CallsiteProfile(callsite_id="test:file:10")
        profile.total_calls = MIN_CALL_COUNT - 1
        
        is_eligible, candidate, reason = analyze_eligibility(profile, simple_leaf)
        assert not is_eligible
        assert reason == IneligibilityReason.INSUFFICIENT_CALLS


# =============================================================================
# Guard Tests
# =============================================================================

class TestGuards:
    """Tests for guard generation and checking."""
    
    def test_create_inline_guards(self):
        """Test guard creation."""
        guards = create_inline_guards(simple_leaf, sample_args=(1.0,))
        
        assert guards.expected_callee_id == id(simple_leaf)
        assert guards.expected_arg_types == (float,)
    
    def test_check_callee(self):
        """Test callee guard check."""
        guards = create_inline_guards(simple_leaf)
        
        assert guards.check_callee(simple_leaf)
        assert not guards.check_callee(non_leaf_with_call)
    
    def test_check_arg_types(self):
        """Test argument type check."""
        guards = create_inline_guards(simple_leaf, sample_args=(1.0,))
        
        assert guards.check_arg_types((1.0,))
        assert not guards.check_arg_types((1,))  # int != float
        assert not guards.check_arg_types(("x",))  # str != float
    
    def test_check_all(self):
        """Test all guards check."""
        guards = create_inline_guards(simple_leaf, sample_args=(1.0,))
        
        assert guards.check_all(simple_leaf, (1.0,))
        assert not guards.check_all(non_leaf_with_call, (1.0,))
        assert not guards.check_all(simple_leaf, (1,))
    
    def test_failure_tracking(self):
        """Test failure tracking."""
        guards = create_inline_guards(simple_leaf, sample_args=(1.0,))
        
        guards.check_all(simple_leaf, (1.0,))  # Pass
        guards.check_all(simple_leaf, (1,))    # Fail
        guards.check_all(simple_leaf, (1.0,))  # Pass
        
        assert guards.check_count == 3
        assert guards.failure_count == 1
        assert guards.failure_rate == pytest.approx(1/3)


class TestGuardedDispatcher:
    """Tests for guarded dispatcher."""
    
    def test_dispatch_native(self):
        """Test dispatch to native path."""
        guards = create_inline_guards(simple_leaf, sample_args=(1.0,))
        
        def native_impl(x):
            return x * 1.5 + 0.5
        
        dispatcher = GuardedInlineDispatcher(
            native_impl=native_impl,
            fallback=simple_leaf,
            guards=guards,
        )
        
        result = dispatcher(2.0)
        assert result == 3.5
        assert dispatcher.native_calls == 1
        assert dispatcher.fallback_calls == 0
    
    def test_dispatch_fallback(self):
        """Test fallback on guard failure."""
        guards = create_inline_guards(simple_leaf, sample_args=(1.0,))
        
        def native_impl(x):
            return x * 1.5 + 0.5
        
        dispatcher = GuardedInlineDispatcher(
            native_impl=native_impl,
            fallback=simple_leaf,
            guards=guards,
        )
        
        # Call with wrong type
        result = dispatcher(2)  # int instead of float
        assert result == simple_leaf(2)
        assert dispatcher.fallback_calls == 1


# =============================================================================
# Expansion Tests
# =============================================================================

class TestInlineExpansion:
    """Tests for inline expansion."""
    
    def test_create_guarded_inline(self):
        """Test creating guarded inline."""
        impl, guards = create_guarded_inline(simple_leaf, sample_args=(1.0,))
        
        # Should produce same result
        assert impl(2.0) == simple_leaf(2.0)
    
    def test_inline_cache(self):
        """Test inline cache."""
        cache = InlineCache()
        guards = create_inline_guards(simple_leaf)
        
        cache.put(id(simple_leaf), simple_leaf, guards)
        
        result = cache.get(id(simple_leaf))
        assert result is not None
        assert result[0] is simple_leaf
        
        stats = cache.get_stats()
        assert stats["hits"] == 1
        assert stats["size"] == 1


# =============================================================================
# Trampoline Tests
# =============================================================================

class TestTrampoline:
    """Tests for trampoline."""
    
    def test_trampoline_creation(self):
        """Test trampoline creation."""
        guards = create_inline_guards(simple_leaf, sample_args=(1.0,))
        trampoline = create_trampoline(simple_leaf, simple_leaf, guards)
        
        assert trampoline.native_impl is simple_leaf
        assert trampoline.fallback is simple_leaf
    
    def test_trampoline_call_native(self):
        """Test trampoline native path."""
        guards = create_inline_guards(simple_leaf, sample_args=(1.0,))
        trampoline = create_trampoline(simple_leaf, simple_leaf, guards)
        
        result = trampoline(2.0)
        assert result == 3.5
        assert trampoline.native_calls == 1
    
    def test_trampoline_fallback(self):
        """Test trampoline fallback."""
        guards = create_inline_guards(simple_leaf, sample_args=(1.0,))
        trampoline = create_trampoline(simple_leaf, simple_leaf, guards)
        
        # Wrong type triggers fallback
        result = trampoline(2)  # int
        assert result == simple_leaf(2)
        assert trampoline.fallback_calls == 1
    
    def test_trampoline_registry(self):
        """Test trampoline registry."""
        registry = TrampolineRegistry()
        guards = create_inline_guards(simple_leaf)
        trampoline = create_trampoline(simple_leaf, simple_leaf, guards)
        
        registry.register("site1", trampoline)
        
        assert registry.get("site1") is trampoline
        assert registry.get("site2") is None


# =============================================================================
# Integration Tests
# =============================================================================

class TestIntegration:
    """End-to-end integration tests."""
    
    def test_full_inline_pipeline(self):
        """Test the full inline pipeline."""
        # 1. Profile callsite
        tracker = CallsiteTracker()
        for _ in range(1500):
            tracker.record_call("test_site", simple_leaf, 100, (1.0,))
        
        # 2. Check eligibility
        profile = tracker.get_or_create("test_site")
        is_eligible, candidate, reason = analyze_eligibility(profile, simple_leaf)
        assert is_eligible
        
        # 3. Create inline
        impl, guards = create_guarded_inline(simple_leaf, sample_args=(1.0,))
        
        # 4. Create trampoline
        trampoline = create_trampoline(impl, simple_leaf, guards)
        
        # 5. Execute
        result = trampoline(2.0)
        assert result == 3.5
    
    def test_guard_failure_correctness(self):
        """Test that guard failures produce correct results."""
        guards = create_inline_guards(simple_leaf, sample_args=(1.0,))
        
        # Create a "native" that would give wrong result
        def wrong_native(x):
            return x * 999  # Wrong!
        
        trampoline = create_trampoline(wrong_native, simple_leaf, guards)
        
        # With correct type, we get the native (wrong) result
        # In real usage, native would be correct optimized version
        result_native = trampoline(2.0)
        assert result_native == 2.0 * 999  # Uses native
        
        # With wrong type, we get fallback (correct) result
        result_fallback = trampoline(2)  # int triggers fallback
        assert result_fallback == simple_leaf(2)  # Uses fallback

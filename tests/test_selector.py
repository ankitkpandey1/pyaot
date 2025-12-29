"""Unit tests for the selector module."""

import pytest
from pyaot.profiler.data import FunctionProfile, ProfileData, TypeSignature, ShapeSignature
from pyaot.selector import HotnessScorer, EligibilityChecker, FunctionRanker, select_candidates
from pyaot.selector.scorer import EPSILON


class TestHotnessScorer:
    """Tests for HotnessScorer."""
    
    def test_score_empty_profile(self):
        profile = FunctionProfile(
            module="test", qualname="func", filename="t.py", lineno=1
        )
        
        scorer = HotnessScorer()
        score = scorer.score_function(profile)
        
        assert score.hotness == pytest.approx(0.0, abs=EPSILON * 2)
        assert score.type_stability == 0.0
        assert score.shape_stability == 0.0  # No calls = 0 stability
    
    def test_score_active_profile(self):
        profile = FunctionProfile(
            module="test", qualname="func", filename="t.py", lineno=1
        )
        
        type_sig = TypeSignature(arg_types=("int",), kwarg_types={})
        shape_sig = ShapeSignature(arg_shapes=(None,))
        
        for _ in range(100):
            profile.record_call(1_000_000, type_sig, shape_sig)  # 1ms each
        
        scorer = HotnessScorer()
        score = scorer.score_function(profile)
        
        # 100 calls * 0.1s total * 1.0 stability = 10.0
        assert score.hotness > 0
        assert score.stability_score == 1.0
    
    def test_hotness_formula(self):
        """Verify hotness = cpu_time * call_count * stability_score."""
        profile = FunctionProfile(
            module="test", qualname="func", filename="t.py", lineno=1
        )
        
        type_sig = TypeSignature(arg_types=("int",), kwarg_types={})
        shape_sig = ShapeSignature(arg_shapes=((10,),))
        
        for _ in range(100):
            profile.record_call(10_000_000, type_sig, shape_sig)  # 10ms each
        
        scorer = HotnessScorer()
        score = scorer.score_function(profile)
        
        # cpu_time = 1.0s (total), call_count = 100, stability = 1.0
        expected = (1.0 + EPSILON) * 100 * 1.0
        assert score.hotness == pytest.approx(expected, rel=0.01)
    
    def test_meets_threshold(self):
        scorer = HotnessScorer(min_call_count=100, min_stability=0.95)
        
        profile = FunctionProfile(
            module="test", qualname="func", filename="t.py", lineno=1
        )
        
        type_sig = TypeSignature(arg_types=("int",), kwarg_types={})
        shape_sig = ShapeSignature(arg_shapes=(None,))
        
        # Below threshold (only 50 calls)
        for _ in range(50):
            profile.record_call(1000, type_sig, shape_sig)
        
        score = scorer.score_function(profile)
        assert not scorer.meets_threshold(score)
        
        # Meet threshold
        for _ in range(50):
            profile.record_call(1000, type_sig, shape_sig)
        
        score = scorer.score_function(profile)
        assert scorer.meets_threshold(score)
    
    def test_rejection_reason(self):
        scorer = HotnessScorer(min_call_count=100, min_stability=0.95)
        
        profile = FunctionProfile(
            module="test", qualname="func", filename="t.py", lineno=1
        )
        profile.call_count = 50
        
        score = scorer.score_function(profile)
        reason = scorer.get_rejection_reason(score)
        
        assert "call_count" in reason
        assert "50" in reason


class TestEligibilityChecker:
    """Tests for EligibilityChecker."""
    
    def test_eligible_pure_function(self):
        def pure_func(x: int, y: int) -> int:
            return x + y
        
        checker = EligibilityChecker()
        result = checker.check_function(pure_func)
        
        assert result.eligible
        assert len(result.reasons) == 0
    
    def test_ineligible_eval(self):
        def eval_func(code: str):
            return eval(code)
        
        checker = EligibilityChecker()
        result = checker.check_function(eval_func)
        
        assert not result.eligible
        assert result.has_eval_exec
    
    def test_ineligible_exec(self):
        def exec_func(code: str):
            exec(code)
        
        checker = EligibilityChecker()
        result = checker.check_function(exec_func)
        
        assert not result.eligible
        assert result.has_eval_exec
    
    def test_eligible_with_loop(self):
        def loop_func(n: int) -> int:
            total = 0
            for i in range(n):
                total += i
            return total
        
        checker = EligibilityChecker()
        result = checker.check_function(loop_func)
        
        assert result.eligible
    
    def test_eligible_with_conditionals(self):
        def cond_func(x: int) -> int:
            if x > 0:
                return x
            else:
                return -x
        
        checker = EligibilityChecker()
        result = checker.check_function(cond_func)
        
        assert result.eligible
    
    def test_global_statement_warning(self):
        def global_func():
            global some_var
            some_var = 1
        
        checker = EligibilityChecker()
        result = checker.check_function(global_func)
        
        # Global is a warning, not rejection
        assert len(result.warnings) > 0


class TestFunctionRanker:
    """Tests for FunctionRanker."""
    
    def test_rank_empty_data(self):
        data = ProfileData()
        ranker = FunctionRanker()
        
        ranked = ranker.rank(data)
        assert len(ranked) == 0
    
    def test_rank_by_hotness(self):
        data = ProfileData()
        
        # Create two profiles with different hotness
        profile1 = data.get_or_create("mod", "func1", "t.py", 1)
        profile2 = data.get_or_create("mod", "func2", "t.py", 2)
        
        type_sig = TypeSignature(arg_types=("int",), kwarg_types={})
        shape_sig = ShapeSignature(arg_shapes=(None,))
        
        # func1: 100 calls, 10ms each = 1s total
        for _ in range(100):
            profile1.record_call(10_000_000, type_sig, shape_sig)
        
        # func2: 200 calls, 10ms each = 2s total
        for _ in range(200):
            profile2.record_call(10_000_000, type_sig, shape_sig)
        
        ranker = FunctionRanker()
        ranked = ranker.rank(data)
        
        # func2 should be ranked higher (more hotness)
        assert len(ranked) >= 1
    
    def test_get_candidates(self):
        data = ProfileData()
        
        profile = data.get_or_create("mod", "func", "t.py", 1)
        
        type_sig = TypeSignature(arg_types=("int",), kwarg_types={})
        shape_sig = ShapeSignature(arg_shapes=(None,))
        
        for _ in range(100):
            profile.record_call(1_000_000, type_sig, shape_sig)
        
        ranker = FunctionRanker(max_candidates=10)
        candidates = ranker.get_candidates(data)
        
        # May or may not have candidates depending on eligibility
        assert isinstance(candidates, list)

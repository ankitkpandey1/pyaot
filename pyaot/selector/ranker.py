"""
Function ranking and candidate selection.

Combines hotness scoring and eligibility checking to produce
the final list of functions to compile.
"""

from dataclasses import dataclass
from typing import List, Optional

from pyaot.profiler.data import ProfileData, FunctionProfile
from pyaot.selector.scorer import HotnessScorer, FunctionScore
from pyaot.selector.eligibility import EligibilityChecker, EligibilityResult
from pyaot.config import get_config
from pyaot.logging import log_compilation_decision


@dataclass
class RankedFunction:
    """A function that has been scored and checked for eligibility."""
    score: FunctionScore
    eligibility: EligibilityResult
    rank: int
    
    @property
    def key(self) -> str:
        return self.score.function_key
    
    @property
    def eligible(self) -> bool:
        return self.eligibility.eligible and self.score.eligible
    
    @property
    def hotness(self) -> float:
        return self.score.hotness


class FunctionRanker:
    """Ranks and filters functions for AOT compilation.
    
    Combines scoring and eligibility checking to produce a
    prioritized list of compilation candidates.
    """
    
    def __init__(
        self,
        scorer: Optional[HotnessScorer] = None,
        checker: Optional[EligibilityChecker] = None,
        max_candidates: int = 100,
    ):
        """Initialize the ranker.
        
        Args:
            scorer: Hotness scorer (uses default if None).
            checker: Eligibility checker (uses default if None).
            max_candidates: Maximum number of candidates to return.
        """
        self.scorer = scorer or HotnessScorer()
        self.checker = checker or EligibilityChecker()
        self.max_candidates = max_candidates
    
    def rank(self, data: ProfileData) -> List[RankedFunction]:
        """Rank all functions in the profile data.
        
        Args:
            data: Profile data containing function profiles.
            
        Returns:
            List of RankedFunction objects, sorted by hotness descending.
        """
        # Score all functions
        scores = self.scorer.score_all(data)
        
        # Check thresholds and eligibility
        ranked = []
        for score in scores:
            # Check threshold first (fast)
            if not self.scorer.meets_threshold(score):
                rejection = self.scorer.get_rejection_reason(score)
                score.eligible = False
                score.rejection_reason = rejection
                log_compilation_decision(
                    score.function_key,
                    eligible=False,
                    reason=rejection,
                    hotness_score=score.hotness,
                )
                continue
            
            # Check AST eligibility (slower)
            eligibility = self.checker.check_from_profile(score.profile)
            
            if not eligibility.eligible:
                score.eligible = False
                score.rejection_reason = eligibility.summary()
            
            log_compilation_decision(
                score.function_key,
                eligible=eligibility.eligible,
                reason=eligibility.summary() if not eligibility.eligible else None,
                hotness_score=score.hotness,
            )
            
            ranked.append(RankedFunction(
                score=score,
                eligibility=eligibility,
                rank=0,  # Will be set after sorting
            ))
        
        # Sort by hotness descending
        ranked.sort(key=lambda x: x.hotness, reverse=True)
        
        # Assign ranks
        for i, item in enumerate(ranked):
            item.rank = i + 1
        
        return ranked
    
    def get_candidates(self, data: ProfileData) -> List[RankedFunction]:
        """Get eligible candidates for compilation.
        
        Args:
            data: Profile data containing function profiles.
            
        Returns:
            List of eligible RankedFunction objects, limited to max_candidates.
        """
        ranked = self.rank(data)
        eligible = [r for r in ranked if r.eligible]
        return eligible[:self.max_candidates]


def select_candidates(
    data: ProfileData,
    max_candidates: Optional[int] = None,
    min_call_count: Optional[int] = None,
    min_stability: Optional[float] = None,
) -> List[RankedFunction]:
    """Convenience function to select compilation candidates.
    
    Args:
        data: Profile data from profiling session.
        max_candidates: Maximum candidates to return.
        min_call_count: Minimum call count threshold.
        min_stability: Minimum stability score threshold.
        
    Returns:
        List of eligible RankedFunction objects.
    """
    config = get_config()
    
    scorer = HotnessScorer(
        min_call_count=min_call_count or config.min_call_count,
        min_stability=min_stability or config.min_stability_score,
    )
    
    ranker = FunctionRanker(
        scorer=scorer,
        max_candidates=max_candidates or 100,
    )
    
    return ranker.get_candidates(data)


def get_hotness_report(data: ProfileData) -> str:
    """Generate a human-readable hotness report.
    
    Args:
        data: Profile data from profiling session.
        
    Returns:
        Formatted report string.
    """
    ranker = FunctionRanker()
    ranked = ranker.rank(data)
    
    lines = [
        "=" * 80,
        "PyAOT Function Hotness Report",
        "=" * 80,
        "",
        f"Total functions profiled: {len(data)}",
        f"Eligible for compilation: {sum(1 for r in ranked if r.eligible)}",
        "",
        "-" * 80,
        f"{'Rank':<6} {'Eligible':<10} {'Calls':<10} {'Time(s)':<12} {'Stability':<10} {'Hotness':<12} Function",
        "-" * 80,
    ]
    
    for item in ranked[:50]:  # Show top 50
        lines.append(
            f"{item.rank:<6} "
            f"{'✓' if item.eligible else '✗':<10} "
            f"{item.score.call_count:<10} "
            f"{item.score.cpu_time_sec:<12.4f} "
            f"{item.score.stability_score:<10.3f} "
            f"{item.hotness:<12.2f} "
            f"{item.key}"
        )
        
        if not item.eligible:
            lines.append(f"       Reason: {item.score.rejection_reason or item.eligibility.summary()}")
    
    lines.extend([
        "-" * 80,
        "",
    ])
    
    return "\n".join(lines)

"""
Hotness scoring for function selection.

Implements the specification's hotness formula:
    type_stability = dominant_type_calls / total_calls
    shape_stability = dominant_shape_calls / total_calls  
    stability_score = 0.5 * type_stability + 0.5 * shape_stability
    hotness = cpu_time * call_count * stability_score
"""

from dataclasses import dataclass
from typing import List, Optional

from pyaot.profiler.data import ProfileData, FunctionProfile
from pyaot.config import get_config


# Epsilon to prevent division by zero and handle underflow
EPSILON = 1e-9


@dataclass
class FunctionScore:
    """Scoring result for a function.
    
    Contains all computed metrics used for ranking and eligibility.
    """
    function_key: str
    profile: FunctionProfile
    
    # Stability metrics
    type_stability: float
    shape_stability: float
    stability_score: float
    
    # Final hotness score
    hotness: float
    
    # Eligibility (filled by eligibility checker)
    eligible: bool = True
    rejection_reason: Optional[str] = None
    
    @property
    def call_count(self) -> int:
        return self.profile.call_count
    
    @property
    def cpu_time_sec(self) -> float:
        return self.profile.total_time_sec


class HotnessScorer:
    """Computes hotness scores for function profiles.
    
    Uses the specification's formula to rank functions by:
    - CPU time contribution
    - Call frequency
    - Type/shape stability
    """
    
    def __init__(
        self,
        min_call_count: Optional[int] = None,
        min_stability: Optional[float] = None,
    ):
        """Initialize the scorer.
        
        Args:
            min_call_count: Minimum calls for eligibility (default from config).
            min_stability: Minimum stability score (default from config).
        """
        config = get_config()
        self.min_call_count = min_call_count or config.min_call_count
        self.min_stability = min_stability or config.min_stability_score
    
    def score_function(self, profile: FunctionProfile) -> FunctionScore:
        """Compute the hotness score for a single function.
        
        Args:
            profile: The function profile to score.
            
        Returns:
            FunctionScore with all computed metrics.
        """
        # Handle underflow with epsilon
        cpu_time = profile.total_time_sec + EPSILON
        call_count = profile.call_count
        
        # Compute stability scores
        type_stability = profile.get_type_stability()
        shape_stability = profile.get_shape_stability()
        stability_score = 0.5 * type_stability + 0.5 * shape_stability
        
        # Compute final hotness
        hotness = cpu_time * call_count * stability_score
        
        return FunctionScore(
            function_key=profile.key,
            profile=profile,
            type_stability=type_stability,
            shape_stability=shape_stability,
            stability_score=stability_score,
            hotness=hotness,
        )
    
    def score_all(self, data: ProfileData) -> List[FunctionScore]:
        """Score all functions in the profile data.
        
        Args:
            data: Profile data containing function profiles.
            
        Returns:
            List of FunctionScore objects for all functions.
        """
        scores = []
        for profile in data:
            score = self.score_function(profile)
            scores.append(score)
        return scores
    
    def meets_threshold(self, score: FunctionScore) -> bool:
        """Check if a function meets the eligibility thresholds.
        
        Per specification:
        - call_count >= 100
        - stability_score >= 0.95
        
        Args:
            score: The function's score.
            
        Returns:
            True if the function meets all thresholds.
        """
        if score.call_count < self.min_call_count:
            return False
        if score.stability_score < self.min_stability:
            return False
        return True
    
    def get_rejection_reason(self, score: FunctionScore) -> Optional[str]:
        """Get the reason why a function doesn't meet thresholds.
        
        Args:
            score: The function's score.
            
        Returns:
            Rejection reason string, or None if eligible.
        """
        if score.call_count < self.min_call_count:
            return f"call_count ({score.call_count}) < min ({self.min_call_count})"
        if score.stability_score < self.min_stability:
            return f"stability_score ({score.stability_score:.3f}) < min ({self.min_stability})"
        return None

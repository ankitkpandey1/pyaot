"""
PyAOT Inline Module.

Provides profile-guided call-boundary elimination through inlining
of hot, monomorphic call sites into compiled native code.
"""

from pyaot.inline.callsite import CallsiteProfile, CallsiteTracker
from pyaot.inline.eligibility import (
    is_eligible_for_inline,
    InlineCandidate,
    analyze_eligibility,
)
from pyaot.inline.guards import InlineGuardSet, create_inline_guards

__all__ = [
    "CallsiteProfile",
    "CallsiteTracker",
    "is_eligible_for_inline",
    "InlineCandidate",
    "analyze_eligibility",
    "InlineGuardSet",
    "create_inline_guards",
]

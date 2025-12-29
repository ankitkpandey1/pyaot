"""
PyAOT Inline Module.

Provides profile-guided call-boundary elimination through inlining
of hot, monomorphic call sites into compiled native code.

Phase 5 Components:
- callsite: Callsite profiling and tracking
- eligibility: Eligibility analysis for inlining
- guards: Runtime guards with per-guard failure tracking
- trampoline: Guard-based dispatch between native/fallback
- expansion: AST-level inline expansion
- ir_inline: IR-level inline expansion with LLVM support
- telemetry: Per-callsite metrics and observability
"""

from pyaot.inline.callsite import (
    CallsiteProfile,
    CallsiteTracker,
    get_global_callsite_tracker,
)
from pyaot.inline.eligibility import (
    is_eligible_for_inline,
    InlineCandidate,
    analyze_eligibility,
    get_inline_candidates,
)
from pyaot.inline.guards import (
    InlineGuardSet,
    create_inline_guards,
    GuardMetrics,
)
from pyaot.inline.trampoline import (
    InlineTrampoline,
    TrampolineRegistry,
    create_trampoline,
    get_trampoline_registry,
)
from pyaot.inline.telemetry import (
    InlineTelemetry,
    CallsiteMetrics,
    GlobalMetrics,
    RejectionReason,
    get_telemetry,
)
from pyaot.inline.ir_inline import (
    IRInlinePass,
    InlinePassManager,
    DeoptInfo,
)

__all__ = [
    # Callsite
    "CallsiteProfile",
    "CallsiteTracker",
    "get_global_callsite_tracker",
    # Eligibility
    "is_eligible_for_inline",
    "InlineCandidate",
    "analyze_eligibility",
    "get_inline_candidates",
    # Guards
    "InlineGuardSet",
    "create_inline_guards",
    "GuardMetrics",
    # Trampoline
    "InlineTrampoline",
    "TrampolineRegistry",
    "create_trampoline",
    "get_trampoline_registry",
    # Telemetry
    "InlineTelemetry",
    "CallsiteMetrics",
    "GlobalMetrics",
    "RejectionReason",
    "get_telemetry",
    # IR Inline
    "IRInlinePass",
    "InlinePassManager",
    "DeoptInfo",
]

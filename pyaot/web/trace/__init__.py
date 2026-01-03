"""Trace recording and storage subsystem."""

from pyaot.web.trace.config import TracerConfig, get_config, set_config, reset_config
from pyaot.web.trace.ops import (
    TraceOp,
    TraceOpcode,
    SideEffectKind,
    EscapeFlag,
    DeoptMetadata,
    ConstantTable,
    ShapeTable,
    CallTargetTable,
)
from pyaot.web.trace.buffer import TraceBuffer
from pyaot.web.trace.recorder import TraceRecorder
from pyaot.web.trace.signature import RequestSignature
from pyaot.web.trace.eligibility import EligibilityEvaluator, EligibilityResult
from pyaot.web.trace.store import TraceStore, TraceRecord, TraceHeader

__all__ = [
    # Config
    "TracerConfig",
    "get_config",
    "set_config",
    "reset_config",
    # Ops
    "TraceOp",
    "TraceOpcode",
    "SideEffectKind",
    "EscapeFlag",
    "DeoptMetadata",
    "ConstantTable",
    "ShapeTable",
    "CallTargetTable",
    # Buffer
    "TraceBuffer",
    # Recorder
    "TraceRecorder",
    # Signature
    "RequestSignature",
    # Eligibility
    "EligibilityEvaluator",
    "EligibilityResult",
    # Store
    "TraceStore",
    "TraceRecord",
    "TraceHeader",
]

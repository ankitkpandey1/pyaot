"""
Callsite Stub Subsystem.

Frame elision via callsite-specialized entry stubs.
Bypasses Python frame creation for hot monomorphic callsites.
"""

from pyaot.callsite.stub import CallsiteStub, StubGuard, GuardType
from pyaot.callsite.generator import StubGenerator
from pyaot.callsite.registry import StubRegistry, get_stub_registry

__all__ = [
    "CallsiteStub",
    "StubGuard",
    "GuardType",
    "StubGenerator",
    "StubRegistry",
    "get_stub_registry",
]

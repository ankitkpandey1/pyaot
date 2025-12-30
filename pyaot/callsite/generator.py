"""
Stub Generator.

Generates callsite stubs from callsite profiles and compiled artifacts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from pyaot.callsite.stub import CallsiteStub, StubGuard, GuardType, create_stub


@dataclass
class StubGenerationResult:
    """Result of stub generation."""
    success: bool = False
    stub: Optional[CallsiteStub] = None
    error: Optional[str] = None
    guards_added: int = 0


class StubGenerator:
    """
    Generates callsite stubs for frame elision.
    
    Takes a callsite profile and compiled artifact,
    produces a CallsiteStub with appropriate guards.
    """
    
    def __init__(self):
        self._generated: Dict[str, CallsiteStub] = {}
    
    def generate(
        self,
        callsite_id: str,
        callee: Callable,
        arg_types: Tuple[type, ...],
        native_callable: Optional[Callable] = None,
    ) -> StubGenerationResult:
        """
        Generate a stub for a callsite.
        
        Args:
            callsite_id: Unique identifier for callsite
            callee: The function being called
            arg_types: Expected argument types
            native_callable: Native compiled version (if available)
            
        Returns:
            StubGenerationResult
        """
        result = StubGenerationResult()
        
        try:
            # Create stub with guards
            stub = create_stub(
                callsite_id=callsite_id,
                callee=callee,
                arg_types=arg_types,
                native_callable=native_callable,
            )
            
            self._generated[callsite_id] = stub
            
            result.success = True
            result.stub = stub
            result.guards_added = len(stub.guards)
            
        except Exception as e:
            result.error = str(e)
        
        return result
    
    def generate_from_profile(
        self,
        profile: Any,  # CallsiteProfile from inline/callsite.py
        callee: Callable,
        native_callable: Optional[Callable] = None,
    ) -> StubGenerationResult:
        """
        Generate stub from a callsite profile.
        
        Args:
            profile: CallsiteProfile with call stats
            callee: The callee function
            native_callable: Native compiled version
            
        Returns:
            StubGenerationResult
        """
        # Extract arg types from profile
        arg_types = ()
        if hasattr(profile, 'arg_type_signatures') and profile.arg_type_signatures:
            # Use dominant signature
            arg_types = profile.arg_type_signatures[0]
        
        return self.generate(
            callsite_id=profile.callsite_id,
            callee=callee,
            arg_types=arg_types,
            native_callable=native_callable,
        )
    
    def get_stub(self, callsite_id: str) -> Optional[CallsiteStub]:
        """Get a previously generated stub."""
        return self._generated.get(callsite_id)
    
    def get_all_stubs(self) -> List[CallsiteStub]:
        """Get all generated stubs."""
        return list(self._generated.values())
    
    def clear(self) -> None:
        """Clear all generated stubs."""
        self._generated.clear()


# Global generator
_generator: Optional[StubGenerator] = None


def get_stub_generator() -> StubGenerator:
    """Get the global stub generator."""
    global _generator
    if _generator is None:
        _generator = StubGenerator()
    return _generator

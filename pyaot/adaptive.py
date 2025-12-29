"""
Adaptive compilation controller for PyAOT.

Combines type hints, profiling, and native compilation into
a unified optimization pipeline with continuous monitoring.

Strategy:
1. Check for type hints → compile immediately if available
2. Otherwise, profile to infer types
3. Monitor guard failures → recompile on drift
4. Track source hashes → invalidate on code change
"""

from __future__ import annotations

import hashlib
import inspect
import threading
import time
import weakref
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

from pyaot.config import get_config
from pyaot.hints import TypeHintExtractor, HintExtractionResult, get_source_hash
from pyaot.types.inference import FunctionSignature, InferredType, TypeInferencer, IRTypeKind
from pyaot.compiler.ir import IRType
from pyaot.exceptions import CompilationError


@dataclass
class NativeArtifact:
    """
    A compiled native artifact with metadata.
    
    Tracks source hash for invalidation and guard statistics
    for drift detection.
    """
    func_id: int  # id(original_function)
    func_name: str
    native_callable: Callable
    fallback: Callable
    source_hash: str
    signature: FunctionSignature
    
    # Compilation metadata
    compiled_at: float = field(default_factory=time.time)
    compilation_source: str = "hints"  # "hints" or "profiling"
    
    # Guard statistics
    native_calls: int = 0
    fallback_calls: int = 0
    
    @property
    def guard_failure_rate(self) -> float:
        """Calculate guard failure rate."""
        total = self.native_calls + self.fallback_calls
        if total == 0:
            return 0.0
        return self.fallback_calls / total
    
    def __call__(self, *args, **kwargs) -> Any:
        """Execute with guard check."""
        # Fast path: type check
        if self._check_guards(args):
            self.native_calls += 1
            try:
                return self.native_callable(*args, **kwargs)
            except Exception:
                # Native failed, fall back
                self.fallback_calls += 1
                return self.fallback(*args, **kwargs)
        else:
            self.fallback_calls += 1
            return self.fallback(*args, **kwargs)
    
    def _check_guards(self, args: tuple) -> bool:
        """Check type guards for arguments."""
        if len(args) != len(self.signature.arg_types):
            return False
        
        for arg, expected in zip(args, self.signature.arg_types):
            if not self._check_type(arg, expected):
                return False
        
        return True
    
    def _check_type(self, arg: Any, expected: InferredType) -> bool:
        """Check if argument matches expected type."""
        if expected.kind == IRTypeKind.FLOAT64:
            return isinstance(arg, (float, int))
        elif expected.kind == IRTypeKind.INT64:
            return isinstance(arg, int) and not isinstance(arg, bool)
        elif expected.kind == IRTypeKind.BOOL:
            return isinstance(arg, bool)
        elif expected.kind == IRTypeKind.NDARRAY:
            return hasattr(arg, 'ndarray') or type(arg).__name__ == 'ndarray'
        elif expected.kind == IRTypeKind.LIST:
            return isinstance(arg, list)
        elif expected.kind == IRTypeKind.TUPLE:
            return isinstance(arg, tuple)
        else:
            return True  # Object type, always passes


@dataclass
class DriftEvent:
    """Record of a drift detection event."""
    func_id: int
    func_name: str
    timestamp: float
    old_failure_rate: float
    new_failure_rate: float
    action: str  # "recompile", "invalidate", "ignore"


class AdaptiveCompiler:
    """
    Unified adaptive compilation controller.
    
    Combines:
    - Type hint integration for fast bootstrap
    - Runtime profiling for untyped functions
    - Continuous monitoring for drift detection
    - Source hash tracking for cache invalidation
    
    Usage:
        compiler = AdaptiveCompiler()
        artifact = compiler.compile(my_function)
        if artifact:
            result = artifact(*args)  # Guarded native execution
    """
    
    def __init__(
        self,
        use_hints: bool = True,
        continuous_monitoring: bool = True,
        drift_threshold: float = 0.005,
    ):
        """
        Initialize the adaptive compiler.
        
        Args:
            use_hints: Check type hints before profiling.
            continuous_monitoring: Monitor guard failures for drift.
            drift_threshold: Guard failure rate that triggers recompile (0.5%).
        """
        self.use_hints = use_hints
        self.continuous_monitoring = continuous_monitoring
        self.drift_threshold = drift_threshold
        
        self._hint_extractor = TypeHintExtractor()
        self._type_inferencer = TypeInferencer()
        
        # Artifact cache: func_id -> NativeArtifact
        self._artifacts: Dict[int, NativeArtifact] = {}
        
        # Source hash cache: func_id -> hash
        self._source_hashes: Dict[int, str] = {}
        
        # Drift events log
        self._drift_events: List[DriftEvent] = []
        
        # Lock for thread safety
        self._lock = threading.RLock()
        
        # Functions pending recompilation
        self._pending_recompile: Set[int] = set()
    
    def compile(
        self,
        func: Callable,
        force_profile: bool = False,
    ) -> Optional[NativeArtifact]:
        """
        Compile a function to native code.
        
        Strategy:
        1. Check cache (with source hash validation)
        2. Try type hints if available
        3. Fall back to profiling
        
        Args:
            func: The function to compile.
            force_profile: Skip hints and force profiling.
            
        Returns:
            NativeArtifact or None if compilation fails.
        """
        func_id = id(func)
        
        with self._lock:
            # Check cache
            if func_id in self._artifacts:
                artifact = self._artifacts[func_id]
                
                # Validate source hash
                current_hash = get_source_hash(func)
                if current_hash != artifact.source_hash:
                    # Source changed, invalidate
                    self._invalidate(func_id, reason="source_changed")
                else:
                    return artifact
            
            # Try type hints first
            if self.use_hints and not force_profile:
                artifact = self._compile_from_hints(func)
                if artifact:
                    self._artifacts[func_id] = artifact
                    return artifact
            
            # Fall back to profiling
            artifact = self._compile_from_profiling(func)
            if artifact:
                self._artifacts[func_id] = artifact
                return artifact
            
            return None
    
    def _compile_from_hints(self, func: Callable) -> Optional[NativeArtifact]:
        """Compile using type hints."""
        result = self._hint_extractor.extract(func)
        
        if not result.success:
            return None
        
        return self._create_artifact(
            func=func,
            signature=result.signature,
            source_hash=result.source_hash,
            source="hints",
        )
    
    def _compile_from_profiling(self, func: Callable) -> Optional[NativeArtifact]:
        """
        Compile using runtime profiling.
        
        Currently returns None - profiling integration requires
        running the function with ProfileCollector.
        """
        # This would integrate with ProfileCollector to run the function
        # and collect type information. For now, return None to indicate
        # profiling is needed.
        return None
    
    def _create_artifact(
        self,
        func: Callable,
        signature: FunctionSignature,
        source_hash: str,
        source: str,
    ) -> NativeArtifact:
        """Create a NativeArtifact from signature."""
        # Try to compile to native
        native_callable = self._compile_native(func, signature)
        
        if native_callable is None:
            # Fall back to using Python function with guard checking
            native_callable = func
        
        return NativeArtifact(
            func_id=id(func),
            func_name=func.__name__,
            native_callable=native_callable,
            fallback=func,
            source_hash=source_hash,
            signature=signature,
            compilation_source=source,
        )
    
    def _compile_native(
        self,
        func: Callable,
        signature: FunctionSignature,
    ) -> Optional[Callable]:
        """
        Compile function to native code via LLVM.
        
        Returns the native callable, or None if compilation fails.
        
        Note: Currently returns None to use Python function with guard checking.
        Full LLVM compilation is work in progress.
        """
        # For now, return None to use Python function with guard checking.
        # The guard checking still provides value by validating types at runtime.
        # Full LLVM native compilation will be enabled once stable.
        return None
    
    def _create_sample_args(self, signature: FunctionSignature) -> tuple:
        """Create sample arguments from signature for type inference."""
        args = []
        for arg_type in signature.arg_types:
            if arg_type.kind == IRTypeKind.FLOAT64:
                args.append(1.0)
            elif arg_type.kind == IRTypeKind.INT64:
                args.append(1)
            elif arg_type.kind == IRTypeKind.BOOL:
                args.append(True)
            else:
                args.append(1.0)  # Default to float
        return tuple(args)
    
    def _invalidate(self, func_id: int, reason: str = "unknown") -> None:
        """Invalidate a cached artifact."""
        if func_id in self._artifacts:
            del self._artifacts[func_id]
        if func_id in self._source_hashes:
            del self._source_hashes[func_id]
    
    def monitor(self, artifact: NativeArtifact) -> None:
        """
        Check artifact for drift and trigger recompile if needed.
        
        Called periodically or after a batch of executions.
        """
        if not self.continuous_monitoring:
            return
        
        failure_rate = artifact.guard_failure_rate
        
        if failure_rate > self.drift_threshold:
            # Drift detected
            event = DriftEvent(
                func_id=artifact.func_id,
                func_name=artifact.func_name,
                timestamp=time.time(),
                old_failure_rate=0.0,
                new_failure_rate=failure_rate,
                action="recompile",
            )
            self._drift_events.append(event)
            self._pending_recompile.add(artifact.func_id)
    
    def should_recompile(self, func: Callable) -> bool:
        """Check if function should be recompiled."""
        func_id = id(func)
        
        # Check if pending
        if func_id in self._pending_recompile:
            return True
        
        # Check source hash
        if func_id in self._artifacts:
            artifact = self._artifacts[func_id]
            current_hash = get_source_hash(func)
            return current_hash != artifact.source_hash
        
        return False
    
    def get_artifact(self, func: Callable) -> Optional[NativeArtifact]:
        """Get cached artifact for a function."""
        return self._artifacts.get(id(func))
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get compilation statistics."""
        total_native = sum(a.native_calls for a in self._artifacts.values())
        total_fallback = sum(a.fallback_calls for a in self._artifacts.values())
        
        return {
            "compiled_functions": len(self._artifacts),
            "hint_compiled": sum(
                1 for a in self._artifacts.values() 
                if a.compilation_source == "hints"
            ),
            "profile_compiled": sum(
                1 for a in self._artifacts.values() 
                if a.compilation_source == "profiling"
            ),
            "total_native_calls": total_native,
            "total_fallback_calls": total_fallback,
            "native_ratio": total_native / (total_native + total_fallback) if (total_native + total_fallback) > 0 else 0.0,
            "drift_events": len(self._drift_events),
            "pending_recompile": len(self._pending_recompile),
        }
    
    def clear(self) -> None:
        """Clear all cached artifacts."""
        with self._lock:
            self._artifacts.clear()
            self._source_hashes.clear()
            self._drift_events.clear()
            self._pending_recompile.clear()


# Global singleton
_adaptive_compiler: Optional[AdaptiveCompiler] = None


def get_adaptive_compiler() -> AdaptiveCompiler:
    """Get the global adaptive compiler."""
    global _adaptive_compiler
    if _adaptive_compiler is None:
        config = get_config()
        _adaptive_compiler = AdaptiveCompiler(
            use_hints=True,
            continuous_monitoring=True,
            drift_threshold=0.005,
        )
    return _adaptive_compiler


def compile_adaptive(func: Callable) -> Optional[NativeArtifact]:
    """
    Convenience function to compile a function adaptively.
    
    Args:
        func: The function to compile.
        
    Returns:
        NativeArtifact or None if compilation fails.
    """
    return get_adaptive_compiler().compile(func)


def adaptive(func: Callable) -> Callable:
    """
    Decorator for adaptive compilation.
    
    Usage:
        @adaptive
        def my_function(x: float, y: float) -> float:
            return x * y + x
    
    The decorated function will be compiled to native code
    if type hints are available.
    """
    compiler = get_adaptive_compiler()
    artifact = compiler.compile(func)
    
    if artifact:
        # Return the artifact which is callable
        return artifact
    else:
        # Compilation failed, return original function
        return func

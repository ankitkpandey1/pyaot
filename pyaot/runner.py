"""
PyAOT Runner - automates observe → emit → run pipeline.

Provides the `pyaot run` command that:
1. Profiles the application to collect callsite data
2. Identifies eligible inline candidates
3. Compiles optimized artifacts
4. Runs the application with optimizations enabled
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from pyaot.config import get_config
from pyaot.profiler.collector import ProfileCollector, start_profiling, stop_profiling
from pyaot.inline.callsite import CallsiteTracker, get_global_callsite_tracker
from pyaot.inline.eligibility import (
    get_inline_candidates,
    analyze_eligibility,
    MIN_CALL_COUNT,
    MIN_CALLEE_SHARE,
)
from pyaot.inline.trampoline import (
    TrampolineRegistry,
    get_trampoline_registry,
    create_trampoline,
)
from pyaot.inline.guards import create_inline_guards
from pyaot.inline.expansion import create_guarded_inline
from pyaot.inline.telemetry import get_telemetry, RejectionReason


@dataclass
class RunResult:
    """Result from a PyAOT run."""
    success: bool
    exit_code: int = 0
    error: Optional[str] = None
    
    # Timing
    observe_time_ms: float = 0.0
    emit_time_ms: float = 0.0
    run_time_ms: float = 0.0
    total_time_ms: float = 0.0
    
    # Statistics
    callsites_observed: int = 0
    candidates_found: int = 0
    callsites_inlined: int = 0
    
    # Guard stats
    native_calls: int = 0
    fallback_calls: int = 0
    guard_failure_rate: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "success": self.success,
            "exit_code": self.exit_code,
            "error": self.error,
            "observe_time_ms": self.observe_time_ms,
            "emit_time_ms": self.emit_time_ms,
            "run_time_ms": self.run_time_ms,
            "total_time_ms": self.total_time_ms,
            "callsites_observed": self.callsites_observed,
            "candidates_found": self.candidates_found,
            "callsites_inlined": self.callsites_inlined,
            "native_calls": self.native_calls,
            "fallback_calls": self.fallback_calls,
            "guard_failure_rate": self.guard_failure_rate,
        }


class PyAOTRunner:
    """
    Runner that automates the observe → emit → run pipeline.
    
    Usage:
        runner = PyAOTRunner()
        result = runner.run("app.py", inline_enabled=True)
    """
    
    def __init__(
        self,
        inline_enabled: bool = True,
        profile_iterations: int = 1,
        min_calls: int = MIN_CALL_COUNT,
        min_callee_share: float = MIN_CALLEE_SHARE,
        verbose: bool = False,
    ):
        self.inline_enabled = inline_enabled
        self.profile_iterations = profile_iterations
        self.min_calls = min_calls
        self.min_callee_share = min_callee_share
        self.verbose = verbose
        
        self._config = get_config()
        self._telemetry = get_telemetry()
        self._tracker = get_global_callsite_tracker()
        self._registry = get_trampoline_registry()
        self._callee_map: Dict[int, Callable] = {}
    
    def run(
        self,
        script_path: str,
        script_args: List[str] = None,
    ) -> RunResult:
        """
        Run a Python script with PyAOT optimization.
        
        Args:
            script_path: Path to the Python script.
            script_args: Arguments to pass to the script.
            
        Returns:
            RunResult with timing and statistics.
        """
        script_args = script_args or []
        result = RunResult(success=True)
        
        total_start = time.perf_counter_ns()
        
        try:
            # Phase 1: Observe
            if self.verbose:
                print(f"[PyAOT] Observing: {script_path}")
            
            observe_start = time.perf_counter_ns()
            self._observe_phase(script_path, script_args)
            result.observe_time_ms = (time.perf_counter_ns() - observe_start) / 1_000_000
            
            # Get observation stats
            stats = self._tracker.get_stats()
            result.callsites_observed = stats["total_callsites"]
            
            if self.verbose:
                print(f"[PyAOT] Observed {result.callsites_observed} callsites")
            
            # Phase 2: Emit (if inlining enabled)
            if self.inline_enabled and result.callsites_observed > 0:
                if self.verbose:
                    print("[PyAOT] Analyzing and emitting optimizations...")
                
                emit_start = time.perf_counter_ns()
                candidates = self._emit_phase()
                result.emit_time_ms = (time.perf_counter_ns() - emit_start) / 1_000_000
                result.candidates_found = len(candidates)
                
                if self.verbose:
                    print(f"[PyAOT] Found {result.candidates_found} inline candidates")
            
            # Phase 3: Run with optimizations
            if self.verbose:
                print("[PyAOT] Running with optimizations...")
            
            run_start = time.perf_counter_ns()
            exit_code = self._run_phase(script_path, script_args)
            result.run_time_ms = (time.perf_counter_ns() - run_start) / 1_000_000
            result.exit_code = exit_code
            
            # Collect trampoline stats
            trampoline_stats = self._registry.get_all_stats()
            result.callsites_inlined = trampoline_stats["trampoline_count"]
            result.native_calls = trampoline_stats["total_native_calls"]
            result.fallback_calls = trampoline_stats["total_fallback_calls"]
            
            total = result.native_calls + result.fallback_calls
            if total > 0:
                result.guard_failure_rate = result.fallback_calls / total
            
        except Exception as e:
            result.success = False
            result.error = str(e)
            if self.verbose:
                import traceback
                traceback.print_exc()
        
        result.total_time_ms = (time.perf_counter_ns() - total_start) / 1_000_000
        
        # Record in telemetry
        self._telemetry.record_observe_time(int(result.observe_time_ms * 1_000_000))
        self._telemetry.record_emit_time(int(result.emit_time_ms * 1_000_000))
        
        return result
    
    def _observe_phase(self, script_path: str, script_args: List[str]) -> None:
        """Run the observation phase - profile the script."""
        # Reset tracker
        self._tracker.clear()
        
        # Start profiling
        collector = start_profiling()
        
        try:
            # Run the script
            for _ in range(self.profile_iterations):
                self._execute_script(script_path, script_args, capture_callees=True)
        finally:
            # Stop profiling
            stop_profiling()
    
    def _emit_phase(self) -> List[Any]:
        """Analyze callsites and create inlined trampolines."""
        # Get hot monomorphic callsites
        hot_callsites = self._tracker.get_monomorphic_callsites(
            min_calls=self.min_calls
        )
        
        # Analyze eligibility
        candidates = get_inline_candidates(hot_callsites, self._callee_map)
        
        # Create trampolines for eligible candidates
        for candidate in candidates:
            callee = self._callee_map.get(candidate.callee_id)
            if not callee:
                continue
            
            try:
                # Create guarded inline
                sample_args = tuple()  # Would use profiled arg types
                inlined_impl, guards = create_guarded_inline(callee, sample_args)
                
                # Create trampoline
                trampoline = create_trampoline(inlined_impl, callee, guards)
                
                # Register
                self._registry.register(candidate.callsite_id, trampoline)
                
                # Record in telemetry
                self._telemetry.record_inline_enabled(candidate.callsite_id)
                
            except Exception as e:
                if self._config.inline_log_rejections:
                    self._telemetry.record_rejection(
                        candidate.callsite_id,
                        RejectionReason.NO_SOURCE,
                        f"Failed to create trampoline: {e}",
                    )
        
        return candidates
    
    def _run_phase(self, script_path: str, script_args: List[str]) -> int:
        """Run the script with optimizations enabled."""
        return self._execute_script(script_path, script_args, capture_callees=False)
    
    def _execute_script(
        self,
        script_path: str,
        script_args: List[str],
        capture_callees: bool = False,
    ) -> int:
        """
        Execute a Python script.
        
        Args:
            script_path: Path to the script.
            script_args: Arguments for the script.
            capture_callees: Whether to capture callee functions.
            
        Returns:
            Exit code (0 for success).
        """
        # Prepare sys.argv
        old_argv = sys.argv
        sys.argv = [script_path] + script_args
        
        # Add script directory to path
        script_dir = str(Path(script_path).parent.absolute())
        if script_dir not in sys.path:
            sys.path.insert(0, script_dir)
        
        try:
            # Load and execute the script
            spec = importlib.util.spec_from_file_location("__main__", script_path)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                
                # Capture callees from module globals
                if capture_callees:
                    # After loading, extract callable objects
                    pass
                
                spec.loader.exec_module(module)
                
                # Capture callable globals
                if capture_callees:
                    for name, obj in vars(module).items():
                        if callable(obj) and not name.startswith("_"):
                            self._callee_map[id(obj)] = obj
                
                return 0
        except SystemExit as e:
            return e.code if isinstance(e.code, int) else 1
        except Exception as e:
            if self.verbose:
                import traceback
                traceback.print_exc()
            return 1
        finally:
            sys.argv = old_argv
    
    def get_report(self) -> Dict[str, Any]:
        """Get a comprehensive report of the run."""
        return {
            "config": {
                "inline_enabled": self.inline_enabled,
                "min_calls": self.min_calls,
                "min_callee_share": self.min_callee_share,
            },
            "callsite_stats": self._tracker.get_stats(),
            "trampoline_stats": self._registry.get_all_stats(),
            "telemetry": self._telemetry.get_global_metrics(),
        }


def run_script(
    script_path: str,
    script_args: List[str] = None,
    inline: bool = True,
    verbose: bool = False,
) -> RunResult:
    """
    Convenience function to run a script with PyAOT.
    
    Args:
        script_path: Path to the Python script.
        script_args: Arguments for the script.
        inline: Enable call-boundary elimination.
        verbose: Print progress messages.
        
    Returns:
        RunResult with timing and statistics.
    """
    runner = PyAOTRunner(inline_enabled=inline, verbose=verbose)
    return runner.run(script_path, script_args or [])


def main():
    """CLI entry point for `pyaot run`."""
    parser = argparse.ArgumentParser(
        description="Run a Python script with PyAOT optimization"
    )
    parser.add_argument("script", help="Path to Python script")
    parser.add_argument("args", nargs="*", help="Script arguments")
    parser.add_argument(
        "--inline/--no-inline",
        dest="inline",
        default=True,
        action=argparse.BooleanOptionalAction,
        help="Enable/disable call-boundary elimination",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print progress messages",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )
    parser.add_argument(
        "--min-calls",
        type=int,
        default=MIN_CALL_COUNT,
        help=f"Minimum calls for inline eligibility (default: {MIN_CALL_COUNT})",
    )
    
    args = parser.parse_args()
    
    runner = PyAOTRunner(
        inline_enabled=args.inline,
        min_calls=args.min_calls,
        verbose=args.verbose,
    )
    
    result = runner.run(args.script, args.args)
    
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        if result.success:
            print(f"\n[PyAOT] Completed successfully")
            print(f"  Observe: {result.observe_time_ms:.2f}ms")
            print(f"  Emit:    {result.emit_time_ms:.2f}ms")
            print(f"  Run:     {result.run_time_ms:.2f}ms")
            print(f"  Total:   {result.total_time_ms:.2f}ms")
            print(f"\n  Callsites: {result.callsites_observed}")
            print(f"  Candidates: {result.candidates_found}")
            print(f"  Inlined: {result.callsites_inlined}")
            if result.native_calls + result.fallback_calls > 0:
                print(f"  Native calls: {result.native_calls}")
                print(f"  Fallback calls: {result.fallback_calls}")
                print(f"  Guard failure rate: {result.guard_failure_rate:.2%}")
        else:
            print(f"\n[PyAOT] Failed: {result.error}")
    
    sys.exit(result.exit_code)


if __name__ == "__main__":
    main()

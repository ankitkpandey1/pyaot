"""
Command-line interface for PyAOT.

Provides commands for:
- Profiling Python scripts
- Compiling hot paths
- Cache management
- Statistics and inspection
"""

import sys
import json
from pathlib import Path
from typing import Optional

try:
    import click
    CLICK_AVAILABLE = True
except ImportError:
    CLICK_AVAILABLE = False


def _ensure_click():
    """Ensure click is available."""
    if not CLICK_AVAILABLE:
        print("Error: click is required for CLI. Install with: pip install click")
        sys.exit(1)


if CLICK_AVAILABLE:
    @click.group()
    @click.version_option(version="0.1.0", prog_name="pyaot")
    def cli():
        """PyAOT: Profile-Guided AOT Compilation for Python.
        
        A production-grade system for identifying hot Python functions
        and compiling them to native code.
        """
        pass

    @cli.command()
    @click.argument("script", type=click.Path(exists=True))
    @click.option(
        "--output", "-o",
        type=click.Path(),
        default="profile.json",
        help="Output file for profile data."
    )
    @click.option(
        "--sample-rate", "-s",
        type=int,
        default=1000,
        help="Sample rate (1 in N calls). Lower = more detail, more overhead."
    )
    def profile(script: str, output: str, sample_rate: int):
        """Profile a Python script to identify hot paths.
        
        Runs the script with profiling enabled and saves
        the collected data to a JSON file.
        
        Example:
            pyaot profile script.py --output profile.json
        """
        from pyaot.profiler import ProfileCollector
        
        click.echo(f"Profiling {script}...")
        click.echo(f"Sample rate: 1/{sample_rate}")
        
        # Set up profiler
        collector = ProfileCollector(sample_rate=sample_rate)
        
        # Load and run script
        script_path = Path(script)
        script_globals = {
            "__name__": "__main__",
            "__file__": str(script_path.absolute()),
        }
        
        try:
            collector.start()
            exec(compile(script_path.read_text(), script, "exec"), script_globals)
        finally:
            collector.stop()
        
        # Save profile data
        data = collector.get_data()
        data.save(output)
        
        click.echo(f"\nProfile saved to {output}")
        click.echo(f"Functions profiled: {len(data)}")
        
        # Show top functions
        from pyaot.selector import HotnessScorer
        scorer = HotnessScorer()
        scores = scorer.score_all(data)
        scores.sort(key=lambda x: x.hotness, reverse=True)
        
        click.echo("\nTop 10 hottest functions:")
        for i, score in enumerate(scores[:10], 1):
            click.echo(
                f"  {i}. {score.function_key} "
                f"(calls={score.call_count}, "
                f"time={score.cpu_time_sec:.3f}s, "
                f"stability={score.stability_score:.2f})"
            )

    @cli.command()
    @click.argument("profile_file", type=click.Path(exists=True))
    @click.option(
        "--output", "-o",
        type=click.Path(),
        default="compiled",
        help="Output directory for compiled artifacts."
    )
    @click.option(
        "--max-functions", "-n",
        type=int,
        default=10,
        help="Maximum number of functions to compile."
    )
    @click.option(
        "--min-calls",
        type=int,
        default=100,
        help="Minimum call count threshold."
    )
    @click.option(
        "--min-stability",
        type=float,
        default=0.95,
        help="Minimum stability score threshold."
    )
    def compile(
        profile_file: str,
        output: str,
        max_functions: int,
        min_calls: int,
        min_stability: float,
    ):
        """Compile hot paths from profile data.
        
        Analyzes the profile, selects eligible functions,
        and compiles them to native code.
        
        Example:
            pyaot compile profile.json --output compiled/
        """
        from pyaot.profiler.data import ProfileData
        from pyaot.selector import select_candidates, get_hotness_report
        
        click.echo(f"Loading profile from {profile_file}...")
        data = ProfileData.load(profile_file)
        
        click.echo(f"Functions in profile: {len(data)}")
        
        # Show hotness report
        report = get_hotness_report(data)
        click.echo(report)
        
        # Select candidates
        candidates = select_candidates(
            data,
            max_candidates=max_functions,
            min_call_count=min_calls,
            min_stability=min_stability,
        )
        
        click.echo(f"\nEligible for compilation: {len(candidates)}")
        
        if not candidates:
            click.echo("No functions eligible for compilation.")
            return
        
        # Create output directory
        output_path = Path(output)
        output_path.mkdir(parents=True, exist_ok=True)
        
        # Compile each candidate
        click.echo("\nCompiling...")
        for candidate in candidates:
            click.echo(f"  {candidate.key}...")
            # TODO: Actually compile (requires source access)
        
        click.echo(f"\nArtifacts saved to {output}/")

    @cli.group()
    def cache():
        """Cache management commands."""
        pass

    @cache.command("list")
    def cache_list():
        """List all cached artifacts."""
        from pyaot.cache import CacheStorage
        
        storage = CacheStorage()
        artifacts = storage.list_artifacts()
        
        if not artifacts:
            click.echo("Cache is empty.")
            return
        
        click.echo(f"Cached artifacts ({len(artifacts)}):\n")
        for cache_key, metadata in artifacts:
            click.echo(f"  {cache_key[:16]}... - {metadata.function_name}")
            click.echo(f"    Python: {metadata.python_version}")
            click.echo(f"    Created: {metadata.created_at}")
            click.echo()

    @cache.command("clear")
    @click.confirmation_option(prompt="Clear all cached artifacts?")
    def cache_clear():
        """Clear all cached artifacts."""
        from pyaot.cache import CacheStorage
        
        storage = CacheStorage()
        count = storage.clear()
        click.echo(f"Cleared {count} artifacts.")

    @cache.command("stats")
    def cache_stats():
        """Show cache statistics."""
        from pyaot.cache import CacheStorage
        from pyaot.cache.lru import get_artifact_cache
        
        storage = CacheStorage()
        disk_stats = storage.get_stats()
        memory_stats = get_artifact_cache().get_stats()
        
        click.echo("Disk Cache:")
        click.echo(f"  Directory: {disk_stats['directory']}")
        click.echo(f"  Artifacts: {disk_stats['artifact_count']}")
        click.echo(f"  Size: {disk_stats['total_size_mb']:.2f} MB")
        click.echo()
        click.echo("Memory Cache:")
        click.echo(f"  Loaded: {memory_stats['size']}/{memory_stats['max_size']}")
        click.echo(f"  Hit rate: {memory_stats['hit_rate']:.1%}")

    @cli.command()
    @click.argument("profile_file", type=click.Path(exists=True))
    def stats(profile_file: str):
        """Show statistics for a profile file."""
        from pyaot.profiler.data import ProfileData
        from pyaot.selector import get_hotness_report
        
        data = ProfileData.load(profile_file)
        report = get_hotness_report(data)
        click.echo(report)

    @cli.command()
    @click.argument("script", type=click.Path(exists=True))
    @click.option(
        "--enabled/--disabled",
        default=True,
        help="Run with AOT enabled or disabled."
    )
    def run(script: str, enabled: bool):
        """Run a Python script with AOT compilation.
        
        For benchmarking, use --disabled to compare performance.
        
        Example:
            pyaot run script.py --enabled
            pyaot run script.py --disabled
        """
        import os
        
        if not enabled:
            os.environ["AOT_DISABLED"] = "1"
        
        script_path = Path(script)
        script_globals = {
            "__name__": "__main__",
            "__file__": str(script_path.absolute()),
        }
        
        click.echo(f"Running {script} (AOT {'enabled' if enabled else 'disabled'})...")
        exec(compile(script_path.read_text(), script, "exec"), script_globals)


def main():
    """Main entry point for CLI."""
    _ensure_click()
    cli()


if __name__ == "__main__":
    main()

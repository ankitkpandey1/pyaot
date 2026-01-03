"""Warmup curve benchmark - shows when PyAOT optimization kicks in.

Tracks per-iteration latency to show:
1. Profiling phase (first N calls - learning)
2. Compilation trigger point
3. Native execution phase (optimized)

Run with: python benchmarks/bench_warmup_curve.py
"""

from __future__ import annotations

import time
import matplotlib.pyplot as plt
import numpy as np

from pyaot.pipeline import optimize


# =============================================================================
# Test Functions
# =============================================================================


def compute_baseline(n: int) -> int:
    """Pure Python - no PyAOT."""
    total = 0
    for i in range(n):
        total += i * i
    return total


@optimize(profile_calls=50, stability_threshold=0.9)
def compute_optimized(n: int) -> int:
    """PyAOT optimized - will compile after 50 calls."""
    total = 0
    for i in range(n):
        total += i * i
    return total


# =============================================================================
# Warmup Curve Benchmark
# =============================================================================


def measure_warmup_curve(
    baseline_func,
    optimized_func,
    args: tuple,
    n_iterations: int = 500,
) -> dict:
    """Measure per-iteration latency for both functions.

    Returns:
        Dict with baseline and optimized latency arrays.
    """
    baseline_times = []
    optimized_times = []

    for i in range(n_iterations):
        # Baseline
        start = time.perf_counter_ns()
        baseline_func(*args)
        baseline_times.append(time.perf_counter_ns() - start)

        # Optimized
        start = time.perf_counter_ns()
        optimized_func(*args)
        optimized_times.append(time.perf_counter_ns() - start)

    return {
        "baseline_ns": baseline_times,
        "optimized_ns": optimized_times,
        "iterations": list(range(n_iterations)),
    }


def analyze_warmup(data: dict, profile_calls: int = 50) -> dict:
    """Analyze warmup characteristics."""
    baseline = np.array(data["baseline_ns"])
    optimized = np.array(data["optimized_ns"])

    # Phases
    profile_phase = optimized[:profile_calls]
    compiled_phase = optimized[profile_calls:]
    baseline_avg = np.mean(baseline)

    return {
        "profile_phase_avg_ns": np.mean(profile_phase),
        "compiled_phase_avg_ns": np.mean(compiled_phase),
        "baseline_avg_ns": baseline_avg,
        "profile_overhead_pct": ((np.mean(profile_phase) - baseline_avg) / baseline_avg) * 100,
        "compiled_improvement_pct": ((baseline_avg - np.mean(compiled_phase)) / baseline_avg) * 100,
        "speedup_after_warmup": baseline_avg / np.mean(compiled_phase),
        "warmup_iterations": profile_calls,
    }


def print_analysis(analysis: dict) -> None:
    """Print warmup analysis."""
    print("\n" + "=" * 70)
    print("WARMUP ANALYSIS")
    print("=" * 70)

    print(f"\nWarmup (profiling) iterations: {analysis['warmup_iterations']}")
    print()
    print(f"{'Phase':<25} {'Avg Latency (ns)':<20} {'vs Baseline':<20}")
    print("-" * 65)
    print(f"{'Baseline (no PyAOT)':<25} {analysis['baseline_avg_ns']:<20,.0f} {'—':<20}")
    print(f"{'Profiling (first 50)':<25} {analysis['profile_phase_avg_ns']:<20,.0f} "
          f"{analysis['profile_overhead_pct']:+.1f}%")
    print(f"{'Compiled (after warmup)':<25} {analysis['compiled_phase_avg_ns']:<20,.0f} "
          f"{analysis['compiled_improvement_pct']:+.1f}%")

    print()
    if analysis['speedup_after_warmup'] >= 1:
        print(f"After warmup speedup: {analysis['speedup_after_warmup']:.2f}x FASTER")
    else:
        print(f"After warmup: {1/analysis['speedup_after_warmup']:.2f}x SLOWER")

    # Break-even analysis
    profile_overhead = analysis['profile_phase_avg_ns'] - analysis['baseline_avg_ns']
    if analysis['compiled_improvement_pct'] > 0:
        compiled_savings = analysis['baseline_avg_ns'] - analysis['compiled_phase_avg_ns']
        breakeven = (analysis['warmup_iterations'] * profile_overhead) / compiled_savings
        print(f"\nBreak-even point: ~{breakeven:.0f} calls after warmup")
        print(f"Total calls for net benefit: {analysis['warmup_iterations'] + breakeven:.0f}")
    else:
        print("\nNo speedup observed - compilation did not improve performance")


def generate_graph(data: dict, output_path: str, profile_calls: int = 50) -> None:
    """Generate warmup curve graph."""
    fig, axes = plt.subplots(2, 1, figsize=(12, 8))

    iterations = data["iterations"]
    baseline = np.array(data["baseline_ns"]) / 1000  # Convert to μs
    optimized = np.array(data["optimized_ns"]) / 1000

    # Rolling average for smoother visualization
    window = 10
    baseline_smooth = np.convolve(baseline, np.ones(window)/window, mode='valid')
    optimized_smooth = np.convolve(optimized, np.ones(window)/window, mode='valid')
    iterations_smooth = iterations[window-1:]

    # Plot 1: Per-iteration latency
    ax1 = axes[0]
    ax1.plot(iterations_smooth, baseline_smooth, label="Baseline (Python)", 
             color="#4CAF50", linewidth=1.5)
    ax1.plot(iterations_smooth, optimized_smooth, label="PyAOT @optimize", 
             color="#2196F3", linewidth=1.5)
    ax1.axvline(x=profile_calls, color="red", linestyle="--", 
                label=f"Warmup complete ({profile_calls} calls)", alpha=0.7)

    ax1.set_xlabel("Iteration", fontsize=12)
    ax1.set_ylabel("Latency (μs)", fontsize=12)
    ax1.set_title("Warmup Curve: Latency per Iteration", fontsize=14, fontweight="bold")
    ax1.legend(loc="upper right")
    ax1.grid(True, alpha=0.3)

    # Annotate phases
    ax1.annotate("Profiling\n(learning)", xy=(profile_calls/2, ax1.get_ylim()[1]*0.8),
                 ha="center", fontsize=10, color="orange")
    ax1.annotate("Compiled\n(optimized)", xy=(profile_calls*2, ax1.get_ylim()[1]*0.8),
                 ha="center", fontsize=10, color="green")

    # Plot 2: Cumulative speedup
    ax2 = axes[1]
    cumulative_baseline = np.cumsum(baseline)
    cumulative_optimized = np.cumsum(optimized)
    cumulative_savings = cumulative_baseline - cumulative_optimized

    ax2.plot(iterations, cumulative_savings, color="#9C27B0", linewidth=2)
    ax2.axhline(y=0, color="gray", linestyle="-", alpha=0.5)
    ax2.axvline(x=profile_calls, color="red", linestyle="--", alpha=0.7)

    ax2.set_xlabel("Iteration", fontsize=12)
    ax2.set_ylabel("Cumulative Time Savings (μs)", fontsize=12)
    ax2.set_title("Cumulative Time Savings (positive = PyAOT faster)", 
                  fontsize=14, fontweight="bold")
    ax2.grid(True, alpha=0.3)

    # Find break-even point
    breakeven_idx = np.where(cumulative_savings > 0)[0]
    if len(breakeven_idx) > 0:
        breakeven = breakeven_idx[0]
        ax2.axvline(x=breakeven, color="green", linestyle=":", alpha=0.7)
        ax2.annotate(f"Break-even\n({breakeven} calls)", xy=(breakeven, 0),
                     xytext=(breakeven + 20, ax2.get_ylim()[1]*0.5),
                     arrowprops=dict(arrowstyle="->", color="green"),
                     fontsize=10, color="green")

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    print(f"\n✅ Graph saved to: {output_path}")


def main():
    """Run warmup curve benchmark."""
    print("=" * 70)
    print("PyAOT Warmup Curve Benchmark")
    print("=" * 70)
    print()
    print("This benchmark tracks per-iteration latency to show:")
    print("  1. Profiling phase (first 50 calls - learning types)")
    print("  2. Compilation trigger point")
    print("  3. Native execution phase (optimized)")
    print()

    N = 1000  # Work size
    ITERATIONS = 500  # Total iterations to track
    PROFILE_CALLS = 50  # When optimization triggers

    print(f"Configuration:")
    print(f"  Work size: {N}")
    print(f"  Total iterations: {ITERATIONS}")
    print(f"  Warmup iterations: {PROFILE_CALLS}")
    print()

    # Reset optimized function if possible
    if hasattr(compute_optimized, "reset"):
        compute_optimized.reset()

    print("Running benchmark...")
    data = measure_warmup_curve(
        compute_baseline,
        compute_optimized,
        args=(N,),
        n_iterations=ITERATIONS,
    )

    # Analyze
    analysis = analyze_warmup(data, PROFILE_CALLS)
    print_analysis(analysis)

    # Generate graph
    output_path = "benchmarks/warmup_curve.png"
    generate_graph(data, output_path, PROFILE_CALLS)

    # Summary table
    print("\n" + "=" * 70)
    print("SUMMARY TABLE (for BENCHMARKS.md)")
    print("=" * 70)
    print()
    print("| Phase | Iterations | Avg Latency | vs Baseline |")
    print("|-------|------------|-------------|-------------|")
    print(f"| Profiling | 0-{PROFILE_CALLS} | "
          f"{analysis['profile_phase_avg_ns']/1000:.2f}μs | "
          f"{analysis['profile_overhead_pct']:+.1f}% |")
    print(f"| Compiled | {PROFILE_CALLS}+ | "
          f"{analysis['compiled_phase_avg_ns']/1000:.2f}μs | "
          f"{analysis['compiled_improvement_pct']:+.1f}% |")
    print(f"| Baseline | — | "
          f"{analysis['baseline_avg_ns']/1000:.2f}μs | — |")


if __name__ == "__main__":
    main()

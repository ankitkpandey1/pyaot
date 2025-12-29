"""
Example: Numeric sum with profiling and compilation.

Demonstrates the complete PyAOT workflow:
1. Profile a function
2. Check eligibility
3. (Future) Compile to native code
4. Execute with guards
"""

import time


def sum_array(arr) -> float:
    """Sum all elements in an array.
    
    This is a hot path typical of data analytics workloads.
    """
    total = 0.0
    for x in arr:
        total += x
    return total


def weighted_sum(arr, weights) -> float:
    """Compute weighted sum of elements.
    
    Another common analytics pattern.
    """
    total = 0.0
    for x, w in zip(arr, weights):
        total += x * w
    return total


def moving_average(arr, window: int) -> list:
    """Compute simple moving average.
    
    Demonstrates loop with state.
    """
    result = []
    for i in range(len(arr) - window + 1):
        window_sum = 0.0
        for j in range(window):
            window_sum += arr[i + j]
        result.append(window_sum / window)
    return result


def main():
    """Run the example."""
    try:
        import numpy as np
        arr = np.random.random(1_000_000)
        weights = np.random.random(1_000_000)
        arr_list = arr.tolist()
        weights_list = weights.tolist()
    except ImportError:
        import random
        arr_list = [random.random() for _ in range(1_000_000)]
        weights_list = [random.random() for _ in range(1_000_000)]
    
    print("PyAOT Example: Numeric Sum")
    print("=" * 40)
    
    # Profile the function
    print("\n1. Profiling...")
    from pyaot.profiler import profiling_session
    
    with profiling_session(sample_rate=100) as collector:
        for _ in range(10):
            result = sum_array(arr_list)
    
    data = collector.get_data()
    print(f"   Functions profiled: {len(data)}")
    
    # Show hotness scores
    print("\n2. Analyzing hotness...")
    from pyaot.selector import HotnessScorer
    
    scorer = HotnessScorer()
    for profile in data:
        score = scorer.score_function(profile)
        if score.call_count > 0:
            print(f"   {profile.key}:")
            print(f"     Calls: {score.call_count}")
            print(f"     Time: {score.cpu_time_sec:.3f}s")
            print(f"     Stability: {score.stability_score:.2f}")
            print(f"     Hotness: {score.hotness:.2f}")
    
    # Check eligibility
    print("\n3. Checking eligibility...")
    from pyaot.selector import EligibilityChecker
    
    checker = EligibilityChecker()
    result = checker.check_function(sum_array)
    
    if result.eligible:
        print("   ✓ sum_array is eligible for compilation")
    else:
        print("   ✗ sum_array is not eligible:")
        for reason in result.reasons:
            print(f"     - {reason}")
    
    # Benchmark
    print("\n4. Benchmarking...")
    
    # Python version
    start = time.perf_counter()
    for _ in range(10):
        sum_array(arr_list)
    python_time = (time.perf_counter() - start) / 10
    
    print(f"   Python: {python_time * 1000:.2f} ms per call")
    
    # NumPy comparison
    try:
        import numpy as np
        start = time.perf_counter()
        for _ in range(10):
            np.sum(arr)
        numpy_time = (time.perf_counter() - start) / 10
        
        print(f"   NumPy:  {numpy_time * 1000:.2f} ms per call")
        print(f"   Speedup potential: {python_time / numpy_time:.1f}×")
    except ImportError:
        pass
    
    print("\n" + "=" * 40)
    print("Example complete")


if __name__ == "__main__":
    main()

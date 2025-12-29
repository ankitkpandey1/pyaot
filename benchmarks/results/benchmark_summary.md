# Benchmark Summary

**Date**: 2025-12-29 18:17

## System Information

| Component | Value |
|-----------|-------|
| Python Version | 3.13.3 |
| Platform | Linux-6.6.87.2-microsoft-standard-WSL2-x86_64-with-glibc2.41 |
| Processor | x86_64 |
| Cpu Count | 16 |
| Timestamp | 2025-12-29T18:17:43.369998 |
| Numpy Version | 2.3.5 |
| Numba Version | 0.63.1 |

## Results Summary

| Category | Configuration | Size | Mean (ms) | Speedup |
|----------|--------------|------|-----------|----------|
| Numeric Sum | Python (loop) | 1,000 | 0.012 | 1.00× |
| Numeric Sum | Python (builtin) | 1,000 | 0.004 | 3.10× |
| Numeric Sum | NumPy | 1,000 | 0.001 | 9.21× |
| Numeric Sum | Python (loop) | 10,000 | 0.095 | 1.00× |
| Numeric Sum | Python (builtin) | 10,000 | 0.037 | 2.53× |
| Numeric Sum | NumPy | 10,000 | 0.002 | 43.32× |
| Numeric Sum | Python (loop) | 100,000 | 0.934 | 1.00× |
| Numeric Sum | Python (builtin) | 100,000 | 0.361 | 2.59× |
| Numeric Sum | NumPy | 100,000 | 0.013 | 70.78× |
| Numeric Sum | Python (loop) | 1,000,000 | 9.383 | 1.00× |
| Numeric Sum | Python (builtin) | 1,000,000 | 3.675 | 2.55× |
| Numeric Sum | NumPy | 1,000,000 | 0.106 | 88.43× |
| Call Inner | Python (calls) | 10,000 | 0.211 | 1.00× |
| Call Inner | Inlined | 10,000 | 0.153 | 1.38× |
| Call Inner | Python (calls) | 100,000 | 2.047 | 1.00× |
| Call Inner | Inlined | 100,000 | 1.507 | 1.36× |
| Call Inner | Python (calls) | 1,000,000 | 21.144 | 1.00× |
| Call Inner | Inlined | 1,000,000 | 15.226 | 1.39× |
| Call Chain | Python (calls) | 10,000 | 0.357 | 1.00× |
| Call Chain | Inlined | 10,000 | 0.239 | 1.49× |
| Call Chain | Python (calls) | 100,000 | 3.565 | 1.00× |
| Call Chain | Inlined | 100,000 | 2.416 | 1.48× |
| Monte Carlo | Python (calls) | 100,000 | 7.078 | 1.00× |
| Monte Carlo | Inlined | 100,000 | 5.988 | 1.18× |
| Monte Carlo | Python (calls) | 1,000,000 | 68.099 | 1.00× |
| Monte Carlo | Inlined | 1,000,000 | 60.324 | 1.13× |
| Etl Pipeline | Python (calls) | 100,000 | 3.018 | 1.00× |
| Etl Pipeline | Inlined | 100,000 | 2.293 | 1.32× |
| Etl Pipeline | Python (calls) | 1,000,000 | 35.357 | 1.00× |
| Etl Pipeline | Inlined | 1,000,000 | 25.395 | 1.39× |

## Generated Plots

- Speedup Inlining: `speedup_inlining.png`
- Numeric Sum Comparison: `numeric_sum_comparison.png`
- Time Comparison: `time_comparison.png`
- Overhead Breakdown: `overhead_breakdown.png`

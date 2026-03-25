# Numba JIT Compilation for Numerical Hot Loops

## Problem

Python numerical code with loops that can't be easily vectorized with NumPy (e.g., simulations with loop-carried dependencies, custom reduction logic, iterative algorithms). The metric was computation time. NumPy vectorization doesn't help when the algorithm is inherently iterative or requires conditional logic within the loop.

## What Worked

Using Numba's `@jit(nopython=True)` decorator to compile Python functions to machine code via LLVM. Numba translates a subset of Python and NumPy operations to native code at first call, achieving C-like performance without leaving Python.

For a Monte Carlo simulation with 10M iterations of a loop body containing conditionals and array indexing, Numba achieved 120x speedup over pure Python and matched hand-written C performance within 10%.

Key patterns that Numba handles well:
1. **Explicit loops over NumPy arrays**: Unlike NumPy, Numba makes loops fast — write naturally.
2. **Parallel loops**: `@jit(nopython=True, parallel=True)` with `prange` for embarrassingly parallel loops.
3. **CUDA GPU acceleration**: `@cuda.jit` for GPU kernels without writing CUDA C.

## Experiment Data

| Approach | Time (s) | Relative |
|----------|----------|----------|
| Pure Python loop | 48.2 | 1.0x |
| NumPy (partial vectorization) | 6.1 | 7.9x |
| Numba @jit | 0.40 | 120x |
| Numba @jit(parallel=True) | 0.11 | 438x |
| C (gcc -O3) | 0.37 | 130x |

## What Didn't Work

- **Numba with object mode**: If Numba falls back to "object mode" (when it can't infer types), performance is worse than plain Python due to JIT overhead. Always use `nopython=True` and fix type errors.
- **Numba for string operations or dict-heavy code**: Numba only supports a subset of Python — no dicts, no classes (unless `@jitclass`), limited string support. Use it for numerical array code only.
- **First-call JIT overhead**: The first call compiles the function (~0.5-2s). For short-lived scripts, use `@jit(cache=True)` to persist the compiled version to disk.

## Code Example

```python
from numba import jit, prange
import numpy as np

# Pure Python: 48.2s
def monte_carlo_py(n, arr):
    total = 0.0
    for i in range(n):
        x = arr[i]
        if x > 0.5:
            total += x * x
        else:
            total += x
    return total

# Numba: 0.40s (120x faster)
@jit(nopython=True)
def monte_carlo_numba(n, arr):
    total = 0.0
    for i in range(n):
        x = arr[i]
        if x > 0.5:
            total += x * x
        else:
            total += x
    return total

# Parallel version: 0.11s (438x faster)
@jit(nopython=True, parallel=True)
def monte_carlo_parallel(n, arr):
    total = 0.0
    for i in prange(n):  # prange = parallel range
        x = arr[i]
        if x > 0.5:
            total += x * x
        else:
            total += x
    return total
```

## Environment

Python 3.11, Numba 0.58, NumPy 1.25. Numba requires LLVM (bundled via `llvmlite`). AMD Ryzen 9 5900X (12 cores). `pip install numba`.

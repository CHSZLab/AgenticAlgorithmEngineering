# Cython for C-Speed Hot Loops in Python

## Problem

Python application where profiling identified a specific function consuming >50% of runtime — a tight loop over numerical data with operations that can't be vectorized with NumPy (e.g., graph traversal, custom distance metrics, state-machine parsing). The metric was function execution time. Rewriting the entire application in C/C++ is impractical.

## What Worked

Rewriting only the hot function in Cython — a superset of Python that compiles to C extension modules. Adding C type declarations to variables enables Cython to generate tight C loops that bypass the Python interpreter entirely.

Key steps for maximum speedup:
1. **Type declarations**: `cdef int i`, `cdef double x` — tells Cython to use C types instead of Python objects.
2. **Typed memoryviews**: `double[:] arr` — direct C-level access to NumPy arrays without bounds checking or Python API overhead.
3. **`@cython.boundscheck(False)`**: Disable array bounds checking in the hot loop (after verifying correctness).
4. **`@cython.wraparound(False)`**: Disable negative index handling.

For a pairwise distance matrix computation (N=10K, custom metric), Cython with typed memoryviews achieved 95x speedup over pure Python and matched C within 5%.

## Experiment Data

| Approach | Time (s) | Relative |
|----------|----------|----------|
| Pure Python | 142.0 | 1.0x |
| NumPy (partial vectorization) | 18.4 | 7.7x |
| Cython (no type hints) | 38.2 | 3.7x |
| Cython (typed + memoryviews) | 1.49 | 95x |
| C (gcc -O3) | 1.42 | 100x |

## Code Example

```cython
# distance.pyx
import cython
import numpy as np
cimport numpy as cnp

@cython.boundscheck(False)
@cython.wraparound(False)
def pairwise_distances(double[:, :] X, double[:, :] D):
    """Compute pairwise Euclidean distance matrix."""
    cdef int N = X.shape[0]
    cdef int M = X.shape[1]
    cdef int i, j, k
    cdef double diff, dist

    for i in range(N):
        for j in range(i + 1, N):
            dist = 0.0
            for k in range(M):
                diff = X[i, k] - X[j, k]
                dist += diff * diff
            D[i, j] = dist ** 0.5
            D[j, i] = D[i, j]
```

```python
# setup.py
from setuptools import setup
from Cython.Build import cythonize
import numpy as np
setup(ext_modules=cythonize("distance.pyx"), include_dirs=[np.get_include()])
```

## What Didn't Work

- **Cython without type annotations**: Without `cdef` types, Cython generates Python API calls for every operation — only 2-4x faster than CPython. The type declarations are essential.
- **Cython for I/O-bound code**: Cython optimizes CPU work, not I/O. If the bottleneck is file/network I/O, Cython won't help.
- **Cython with complex Python objects**: Cython is fastest with C types and memoryviews. Operations on Python dicts, sets, or custom objects still go through the Python API.

## Environment

Python 3.8+, Cython 3.0+, NumPy. Requires a C compiler (GCC/Clang/MSVC). `pip install cython`. Build with `python setup.py build_ext --inplace` or use `pyximport` for development.

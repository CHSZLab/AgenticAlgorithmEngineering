# NumPy Vectorization Over Python Loops

## Problem

Python programs processing large numerical arrays element-by-element using `for` loops. The metric was computation time for operations like element-wise math, filtering, and reductions on arrays with 1M+ elements. Python's interpreter overhead (type checks, reference counting, dynamic dispatch per element) makes pure-Python loops 50-100x slower than equivalent C code.

## What Worked

Replacing Python loops with NumPy vectorized operations that execute the entire computation in compiled C/Fortran under the hood. The key insight: each NumPy operation processes the whole array in a single call, amortizing Python interpreter overhead across millions of elements.

For computing Euclidean distances between 1M 3D point pairs, vectorized NumPy was 87x faster than the equivalent Python loop.

## Experiment Data

| Approach | Time (s) | Relative |
|----------|----------|----------|
| Python for loop | 12.4 | 1.0x |
| List comprehension | 8.7 | 1.4x |
| NumPy vectorized | 0.14 | 87x |
| NumPy + in-place ops | 0.11 | 113x |

## What Didn't Work

- **Chaining many small vectorized ops**: Each NumPy op allocates a temporary array for the result. A chain like `np.sqrt(np.sum((a - b)**2, axis=1))` creates 4 temporaries. For memory-bound workloads, this kills performance. Use `np.einsum` or numexpr to fuse operations, or use in-place operators (`np.subtract(a, b, out=temp)`).
- **Vectorizing inherently sequential algorithms**: Algorithms with loop-carried dependencies (e.g., cumulative state machines) can't be trivially vectorized. Consider `np.cumsum`, `np.cumprod` for simple cases, or Numba for complex ones.

## Code Example

```python
import numpy as np

# BAD: Python loop — 12.4s for 1M points
distances = []
for i in range(len(a)):
    d = math.sqrt((a[i,0]-b[i,0])**2 + (a[i,1]-b[i,1])**2 + (a[i,2]-b[i,2])**2)
    distances.append(d)

# GOOD: NumPy vectorized — 0.14s for 1M points
distances = np.linalg.norm(a - b, axis=1)

# BETTER: avoid temporary allocation with einsum
diff = a - b
distances = np.sqrt(np.einsum('ij,ij->i', diff, diff))

# In-place operations to reduce memory allocation
np.subtract(a, b, out=diff)
np.multiply(diff, diff, out=diff)
distances = np.sqrt(diff.sum(axis=1))
```

## Environment

Python 3.11, NumPy 1.25. NumPy uses OpenBLAS/MKL for linear algebra and SIMD-optimized ufuncs for element-wise operations. Performance gains scale with array size; for arrays <100 elements, the function call overhead makes loops competitive.

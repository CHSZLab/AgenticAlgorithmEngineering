# Loop Tiling for Cache-Efficient Matrix Operations

## Problem

Matrix multiplication or similar O(n³) nested-loop computations in C++ where the naive triple loop causes massive cache thrashing. For matrix multiply `C = A × B` with N=2048, the naive `ijk` loop order causes column-wise access to `B`, missing the cache on every access since rows are stored contiguously (row-major).

## What Worked

**Loop tiling** (also called loop blocking) partitions the iteration space into small tiles that fit in L1/L2 cache. Instead of processing entire rows/columns, the algorithm works on `T×T` sub-matrices that remain cache-resident throughout computation.

The optimal tile size `T` depends on cache size: `3 × T² × sizeof(element) ≤ L1_cache_size` (three sub-matrices of A, B, C must fit simultaneously). For 32KB L1 with `double`, T≈36; in practice, T=32 or T=64 works well due to alignment.

For N=2048 double-precision matrix multiply, tiled (T=64) was 4.8x faster than naive `ijk` and 2.1x faster than simply reordering loops to `ikj` (which fixes B's access pattern but still thrashes for large N).

## Experiment Data

| Variant | Time (s) | GFlops |
|---------|----------|--------|
| Naive ijk | 28.4 | 0.60 |
| Reordered ikj | 11.2 | 1.53 |
| Tiled T=32 | 6.8 | 2.52 |
| Tiled T=64 | 5.9 | 2.91 |
| OpenBLAS dgemm | 0.9 | 19.1 |

OpenBLAS is still 6.5x faster due to AVX2 + micro-kernel + multi-level tiling, but loop tiling alone captured most of the cache efficiency gain.

## Code Example

```cpp
constexpr int T = 64; // tile size
for (int ii = 0; ii < N; ii += T)
  for (int jj = 0; jj < N; jj += T)
    for (int kk = 0; kk < N; kk += T)
      for (int i = ii; i < std::min(ii+T, N); i++)
        for (int k = kk; k < std::min(kk+T, N); k++)
          for (int j = jj; j < std::min(jj+T, N); j++)
            C[i][j] += A[i][k] * B[k][j];
```

## What Didn't Work

- **Tile size = cache line (T=8)**: Too small — the overhead of tile boundary logic dominates. Tiles should be sized to fit in L1 cache, not matched to cache line width.
- **Auto-tuning without pinning frequency**: CPU frequency scaling caused inconsistent results during tile size search. Always pin frequency during benchmarking (`cpupower frequency-set -g performance`).

## Environment

C++17, GCC 12.2, `-O3 -march=native`, double-precision (8 bytes). Intel Core i7-12700K, 48KB L1d, 1.25MB L2 per P-core.

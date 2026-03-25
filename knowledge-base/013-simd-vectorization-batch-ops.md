# SIMD Vectorization for Batch Array Operations

## Problem

Processing large arrays of floats/doubles element-wise in C++ (e.g., scaling, dot products, distance computations). The metric was throughput (elements/second). The compiler auto-vectorizes simple loops but fails on anything with conditionals, non-trivial reductions, or non-contiguous access patterns.

## What Worked

Explicit SIMD intrinsics (SSE/AVX2/AVX-512) to process 4-16 elements per instruction. The key insight is that modern CPUs have 256-bit (AVX2) or 512-bit (AVX-512) SIMD registers that can operate on 8 floats or 4 doubles simultaneously, but the compiler often can't prove it's safe to vectorize due to aliasing, alignment, or control flow.

Three-tier approach:
1. **Help auto-vectorization first**: Use `__restrict__`, `#pragma omp simd`, ensure aligned allocations, avoid loop-carried dependencies.
2. **Intrinsics for critical kernels**: Write SSE/AVX2 intrinsics for the top 2-3 hotspot loops identified by profiling.
3. **Use a SIMD wrapper library** (Highway, xsimd, Vc) for portable SIMD across architectures.

For a Euclidean distance matrix computation (10K × 10K, float32), AVX2 intrinsics achieved 6.2x speedup over scalar code and 2.1x over auto-vectorized code (the compiler failed to vectorize the inner reduction).

## Experiment Data

| Variant | Throughput (Gflops) | vs Scalar |
|---------|-------------------|-----------|
| Scalar `-O3` | 2.1 | 1.0x |
| Auto-vectorized (`-O3 -march=native`) | 4.8 | 2.3x |
| AVX2 intrinsics | 13.0 | 6.2x |
| AVX-512 intrinsics | 18.7 | 8.9x |

## Code Example

```cpp
#include <immintrin.h>

// AVX2: process 8 floats at a time
float dot_product_avx2(const float* a, const float* b, size_t n) {
    __m256 sum = _mm256_setzero_ps();
    size_t i = 0;
    for (; i + 8 <= n; i += 8) {
        __m256 va = _mm256_loadu_ps(a + i);
        __m256 vb = _mm256_loadu_ps(b + i);
        sum = _mm256_fmadd_ps(va, vb, sum);  // fused multiply-add
    }
    // Horizontal sum of 8 floats in sum register
    __m128 hi = _mm256_extractf128_ps(sum, 1);
    __m128 lo = _mm256_castps256_ps128(sum);
    __m128 s = _mm_add_ps(lo, hi);
    s = _mm_hadd_ps(s, s);
    s = _mm_hadd_ps(s, s);
    float result = _mm_cvtss_f32(s);
    for (; i < n; i++) result += a[i] * b[i]; // scalar tail
    return result;
}
```

## What Didn't Work

- **AVX-512 on consumer CPUs (Intel 12th-13th gen)**: The CPU downclocks significantly when AVX-512 is used, sometimes making it slower than AVX2 for short bursts. Only beneficial for sustained computation on server chips (Xeon, EPYC).

## Environment

C++17, GCC 13.1, `-O3 -mavx2 -mfma`. Intel Xeon w5-3435X for AVX-512 results. Use `lscpu` to verify SIMD support before deploying.

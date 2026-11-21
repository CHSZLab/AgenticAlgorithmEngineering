# Cache-Friendly Blocked Recursive Sorting

## Problem

Sorting large integer arrays (10M+ elements) in C++. The metric was wall-clock time measured via `std::chrono::high_resolution_clock`. The baseline was `std::sort`, which uses introsort internally.

## What Worked

Replacing the default quicksort partitioning with a blocked approach that processes elements in cache-line-sized blocks (64 elements per block). Instead of scanning left-to-right and right-to-left with pointer swaps, the algorithm fills two buffers of indices that need swapping, then performs the swaps in bulk. This keeps memory accesses sequential within each block and reduces branch mispredictions because the buffer-fill loop has no data-dependent branches.

The improvement was ~20% over `std::sort` on uniformly random 64-bit integers (10M elements, averaged over 10 runs).

## Experiment Data

| Variant | Time (ms) | Relative |
|---------|-----------|----------|
| std::sort baseline | 842 | 1.00x |
| Blocked partition, block size 32 | 713 | 1.18x |
| Blocked partition, block size 64 | 678 | 1.24x |
| Blocked partition, block size 128 | 691 | 1.22x |

Block size 64 was the sweet spot, matching the L1 cache line width.

## What Didn't Work

- **Radix sort**: Faster in theory for integers, but the extra memory allocation and multiple passes made it slower for arrays that fit in L2 cache. Only won for 100M+ elements.
- **SIMD-based partitioning**: The overhead of gather/scatter instructions on the test hardware (Zen 3) negated the theoretical throughput gain. Might work better on Intel with AVX-512.

## Code Example

```cpp
// Core idea: buffer indices that need swapping, then swap in bulk
int buf_l[BLOCK], buf_r[BLOCK];
int nl = 0, nr = 0;
while (left + BLOCK <= right - BLOCK) {
    if (nl == 0) {
        for (int i = 0; i < BLOCK; i++)
            buf_l[nl] = i + (arr[left + i] >= pivot); // branchless
            nl += (arr[left + i] >= pivot);
    }
    if (nr == 0) {
        for (int i = 0; i < BLOCK; i++)
            buf_r[nr] = i + (arr[right - 1 - i] < pivot);
            nr += (arr[right - 1 - i] < pivot);
    }
    int swaps = min(nl, nr);
    for (int i = 0; i < swaps; i++)
        std::swap(arr[left + buf_l[i]], arr[right - 1 - buf_r[i]]);
    // advance pointers...
}
```

## Environment

C++17, GCC 12.2 with `-O3 -march=native`, AMD Ryzen 9 5900X, 64 GB DDR4-3600, Ubuntu 22.04. Array fits entirely in RAM, no disk I/O.

# Compiler Built-in Intrinsics for Bit Operations

## Problem

Algorithms that frequently count set bits (popcount), find leading/trailing zeros (clz/ctz), or perform other bit manipulations in C++. The metric was throughput for operations like Hamming distance, bit-parallel set operations, or bitmap index scans. Baseline used manual loops to count bits.

## What Worked

Using compiler built-ins (`__builtin_popcount`, `__builtin_clz`, `__builtin_ctz`) and C++20 `<bit>` header functions (`std::popcount`, `std::countl_zero`, `std::countr_zero`). These compile to single hardware instructions (x86: `POPCNT`, `LZCNT`, `TZCNT`) that execute in 1 cycle with 1-cycle latency, replacing 10-20 instruction software emulations.

For a Hamming distance computation over 1M 64-bit words, using `__builtin_popcountll` was 8.3x faster than a naive bit-counting loop and 2.1x faster than the Kernighan bit-counting trick (`n &= n - 1`).

## Experiment Data

| Method | Throughput (Gwords/s) | Cycles/word |
|--------|----------------------|-------------|
| Naive loop (check each bit) | 0.12 | ~40 |
| Kernighan trick | 0.47 | ~10 |
| `__builtin_popcountll` | 0.98 | ~5 |
| POPCNT + AVX2 (batch of 4) | 3.41 | ~1.4 |

## Code Example

```cpp
// Hamming distance: count differing bits between two arrays
uint64_t hamming(const uint64_t* a, const uint64_t* b, size_t n) {
    uint64_t dist = 0;
    for (size_t i = 0; i < n; i++)
        dist += __builtin_popcountll(a[i] ^ b[i]); // single POPCNT instruction
    return dist;
}

// Find lowest set bit position (useful for bitmap scanning)
int next_set_bit(uint64_t mask) {
    return __builtin_ctzll(mask); // single TZCNT instruction
}

// C++20 portable equivalents
#include <bit>
int count = std::popcount(x);       // popcount
int lz = std::countl_zero(x);       // clz
int tz = std::countr_zero(x);       // ctz
```

## Environment

Requires hardware support: x86 with `POPCNT` (since Nehalem/Barcelona, ~2008), `LZCNT`/`TZCNT` (since Haswell/Piledriver). Compile with `-mpopcnt` or `-march=native`. C++20 `<bit>` header for portable code.

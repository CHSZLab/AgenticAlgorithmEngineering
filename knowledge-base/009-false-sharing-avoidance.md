# Avoiding False Sharing in Multithreaded Code

## Problem

Multithreaded C++ program with per-thread counters/accumulators showed poor scaling beyond 2 threads. Expected 4x speedup on 4 cores but observed only 1.3x. The metric was parallel speedup vs single-threaded baseline. Profiling with `perf c2c` revealed heavy cross-core cache line contention despite threads writing to independent variables.

## What Worked

False sharing occurs when independent variables used by different threads happen to reside on the same cache line (64 bytes on x86). When any thread writes to the line, the cache coherency protocol (MESI) invalidates the line in all other cores, forcing expensive cache-to-cache transfers (~50-100 cycles on modern hardware vs. ~4 cycles for L1 hit).

The fix: pad per-thread data to cache line boundaries using `alignas(64)` or C++17's `std::hardware_destructive_interference_size`.

After padding, the 4-thread parallel sum achieved 3.82x speedup (vs 1.3x before), matching the theoretical near-linear scaling.

## Experiment Data

| Threads | Speedup (packed) | Speedup (padded) |
|---------|------------------|------------------|
| 1 | 1.00x | 1.00x |
| 2 | 1.21x | 1.97x |
| 4 | 1.31x | 3.82x |
| 8 | 1.28x | 7.41x |

## Code Example

```cpp
// BAD: per-thread counters packed together — false sharing
struct Counters { int64_t count[NUM_THREADS]; };  // all on same/adjacent cache lines

// GOOD: each counter on its own cache line
struct alignas(64) PaddedCounter { int64_t count; };
PaddedCounter counters[NUM_THREADS];  // each on separate cache line

// C++17 portable version
struct alignas(std::hardware_destructive_interference_size) PaddedCounter {
    int64_t count;
};

// Alternative: thread-local accumulation + final reduction
thread_local int64_t local_count = 0;
// ... each thread accumulates locally, then merge once at the end
```

## What Didn't Work

- **Over-padding with page alignment** (4096 bytes): Wasted too much memory and caused TLB pressure, actually hurting performance for >32 threads. Cache line alignment (64 bytes) is the sweet spot.

## Environment

C++17, GCC 12.2, AMD EPYC 7763 (64 cores), Linux 6.1. Diagnosed with `perf c2c record/report`.

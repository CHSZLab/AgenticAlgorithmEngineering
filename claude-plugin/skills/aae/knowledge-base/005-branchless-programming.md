# Branchless Programming to Eliminate Branch Mispredictions

## Problem

Filtering or transforming large arrays in C++ where element-wise decisions depend on data values (e.g., clamping, conditional increment, partitioning). The metric was wall-clock time. Baseline used straightforward `if/else` branches, which suffer from branch misprediction when data is random or has low predictability.

## What Worked

Replacing conditional branches with arithmetic equivalents. Modern CPUs pipeline ~15-20 instructions ahead; a mispredicted branch flushes the entire pipeline (~12-15 cycle penalty on x86). For random data the mispredict rate approaches 50%, making branches extremely expensive in tight loops.

Key patterns:
1. **Conditional move via arithmetic**: `x = (cond) ? a : b` → compiler emits `cmov` if written carefully, but sometimes needs manual help.
2. **Branchless min/max**: Use subtraction + sign-bit masking instead of `std::min`/`std::max` when the compiler doesn't optimize.
3. **Predicated accumulation**: `sum += arr[i] * (arr[i] > threshold)` — the boolean converts to 0/1, no branch needed.

For a partitioning loop on 10M random integers, branchless code ran 2.8x faster than the branching version due to eliminating ~47% misprediction rate.

## Experiment Data

| Variant | Time (ms) | Branch Misses (perf) |
|---------|-----------|---------------------|
| if/else partition | 38.2 | 24.7M |
| Branchless (arithmetic) | 13.6 | 0.02M |
| Branchless + unrolled 4x | 11.1 | 0.01M |

## What Didn't Work

- **Branchless on already-sorted data**: When branch prediction accuracy is >95% (sorted/nearly-sorted input), the branch version is actually faster because `cmov` has a data dependency that serializes execution, while a correctly predicted branch allows speculative execution. Always profile with realistic data distributions.

## Code Example

```cpp
// Branching — ~50% mispredict on random data
for (int i = 0; i < N; i++) {
    if (arr[i] < pivot) out[left++] = arr[i];
    else                out[right--] = arr[i];
}

// Branchless — zero mispredictions
for (int i = 0; i < N; i++) {
    int goes_left = (arr[i] < pivot);    // 0 or 1
    out[left]  = arr[i];
    out[right] = arr[i];
    left  += goes_left;
    right -= (1 - goes_left);
}
```

## Environment

C++17, GCC 12.2 with `-O3 -march=native`, AMD Ryzen 9 5900X, measured with `perf stat -e branch-misses`.

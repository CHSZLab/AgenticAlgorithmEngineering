# Reserve and Preallocate STL Containers

## Problem

C++ programs that build up `std::vector`, `std::string`, or `std::unordered_map` incrementally without knowing the final size upfront. The metric was insertion throughput and peak memory usage. The default growth strategy (typically 2x reallocation) causes O(log N) reallocations, each copying all existing elements, and temporarily doubles memory usage during reallocation.

## What Worked

Calling `.reserve(N)` before bulk insertion when the final size is known or can be estimated. This performs a single allocation upfront, eliminating all intermediate reallocations and copies. For `std::vector<int>` with 10M `push_back` calls, reserving upfront was 2.4x faster and used 33% less peak memory.

Key rules:
1. **`vector::reserve(N)`**: Pre-allocates storage for N elements. Size stays 0; capacity becomes N.
2. **`string::reserve(N)`**: Same for strings. Essential before repeated `+=` concatenation.
3. **`unordered_map::reserve(N)`**: Pre-allocates buckets for N elements, preventing rehashing. Rehashing at high load is very expensive (reconstructs all hash chains).
4. **`resize` vs `reserve`**: Use `resize` when you need default-initialized elements to index into; use `reserve` when you'll `push_back`.

## Experiment Data

| Container | Operation | Without reserve | With reserve | Speedup |
|-----------|-----------|----------------|-------------|---------|
| vector<int> 10M | push_back | 42ms | 17ms | 2.4x |
| string 100MB | += chars | 320ms | 95ms | 3.4x |
| unordered_map 1M | insert | 890ms | 410ms | 2.2x |

## Code Example

```cpp
// BAD: 24 reallocations for 10M elements (log2(10M) ≈ 24)
std::vector<int> v;
for (int i = 0; i < 10'000'000; i++) v.push_back(i);

// GOOD: single allocation
std::vector<int> v;
v.reserve(10'000'000);
for (int i = 0; i < 10'000'000; i++) v.push_back(i);

// For maps: prevent rehashing
std::unordered_map<int, Data> map;
map.reserve(expected_entries);  // allocates buckets for expected_entries

// When size is approximate: over-estimate by 10-20% rather than under-estimate
v.reserve(estimated_size * 1.1);
```

## Environment

Applies to all C++ standard library implementations (libstdc++, libc++, MSVC STL). The growth factor varies (GCC: 2x, MSVC: 1.5x), but `reserve` bypasses it entirely.

# Hot-Cold Data Splitting for Cache Efficiency

## Problem

C++ data structures where each object has frequently-accessed "hot" fields (e.g., key, pointer, status flag) and rarely-accessed "cold" fields (e.g., debug info, statistics, metadata). The metric was lookup throughput in a container of 1M+ objects. Iterating over the container loaded cold fields into cache, evicting useful data.

## What Worked

Splitting each struct into a hot part (stored contiguously in the main array) and a cold part (stored in a parallel array, accessed by index only when needed). This increases the density of useful data per cache line, allowing more hot records to fit in cache simultaneously.

For a routing table with 2M entries where lookups touch only `prefix` and `next_hop` (16 bytes) but the full entry is 128 bytes (includes statistics, timestamps, debug strings), splitting hot/cold improved lookup throughput by 3.1x because 4 hot records fit per cache line instead of 0.5 full records.

## Experiment Data

| Layout | Lookup (Mops/s) | L1 Miss Rate |
|--------|-----------------|-------------|
| Monolithic struct (128B) | 12.4 | 18.2% |
| Hot/cold split (16B hot) | 38.5 | 4.7% |
| Hot/cold + prefetch | 42.1 | 3.1% |

## Code Example

```cpp
// BEFORE: monolithic — cold fields pollute cache
struct RouteEntry {
    uint32_t prefix;          // hot: always read
    uint32_t next_hop;        // hot: always read
    uint64_t packet_count;    // cold: only for stats
    uint64_t byte_count;      // cold: only for stats
    time_t last_update;       // cold: only for monitoring
    char description[80];     // cold: only for debugging
};
std::vector<RouteEntry> table; // 128 bytes per entry

// AFTER: split hot and cold
struct RouteHot {
    uint32_t prefix;
    uint32_t next_hop;
};
struct RouteCold {
    uint64_t packet_count;
    uint64_t byte_count;
    time_t last_update;
    char description[80];
};
std::vector<RouteHot> table_hot;    // 8 bytes per entry — dense
std::vector<RouteCold> table_cold;  // indexed in parallel, accessed rarely
```

## What Didn't Work

- **Splitting when most operations touch all fields**: If >50% of accesses need both hot and cold data, the extra indirection (two memory accesses instead of one) makes it slower. Profile access patterns before splitting.

## Environment

C++17, GCC 13.1, `-O3 -march=native`. AMD EPYC 7763. Verified with `perf stat -e L1-dcache-load-misses`.

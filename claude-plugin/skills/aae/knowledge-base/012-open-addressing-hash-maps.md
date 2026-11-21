# Open-Addressing Hash Maps vs std::unordered_map

## Problem

Lookup-heavy workloads in C++ where `std::unordered_map` is the bottleneck. The metric was lookup throughput (queries per second) for a map with 1M+ entries and random access patterns. `std::unordered_map` uses separate chaining with linked list nodes, causing pointer-chasing cache misses on every lookup.

## What Worked

Replacing `std::unordered_map` with an open-addressing hash map that stores entries inline in a flat array. This eliminates pointer chasing — all probing hits contiguous memory, dramatically improving cache utilization.

Recommended implementations:
- **`absl::flat_hash_map`** (Google): Swiss table design, SIMD-accelerated probing, 1 byte metadata per slot
- **`robin_hood::unordered_map`**: Robin Hood hashing with backward-shift deletion
- **`ankerl::unordered_dense::map`**: Dense storage, very fast for small-to-medium maps

For 10M random lookups in a 2M-entry map of `int64_t → int64_t`, `absl::flat_hash_map` achieved 3.2x the throughput of `std::unordered_map`.

## Experiment Data

| Implementation | Lookup (Mops/s) | Memory (MB) | Insert (Mops/s) |
|---------------|-----------------|-------------|-----------------|
| std::unordered_map | 8.2 | 198 | 5.1 |
| absl::flat_hash_map | 26.4 | 89 | 14.7 |
| robin_hood::unordered_map | 24.1 | 72 | 12.3 |
| ankerl::unordered_dense | 22.8 | 68 | 15.9 |

## What Didn't Work

- **Open addressing with high load factor** (>0.9): Probe chains become long, degrading lookup to near-linear scan. Keep load factor at 0.5-0.7 for open addressing (vs. 1.0+ acceptable for chaining).
- **Flat maps for large values**: If the value type is large (>128 bytes), the flat layout wastes cache bandwidth probing past cold data. Use `absl::node_hash_map` (open addressing for metadata, nodes for values) for large value types.

## Environment

C++17, GCC 12.2, `-O3`. absl from Abseil 20230802, robin_hood v3.11.5. Benchmark: uniform random keys, int64_t → int64_t. AMD Ryzen 9 7950X.

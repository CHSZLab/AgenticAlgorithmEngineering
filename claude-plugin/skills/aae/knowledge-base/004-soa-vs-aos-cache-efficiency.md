# Structure of Arrays vs Array of Structures for Cache Efficiency

## Problem

Processing large collections of objects (1M+ entities) in C++ where each operation touches only a subset of fields. The metric was throughput (operations per second). Baseline used a traditional AoS layout (`std::vector<Particle>` where `Particle` has position, velocity, mass, color, etc.) but the hot loop only read `x, y, z` positions.

## What Worked

Converting the data layout from Array of Structures (AoS) to Structure of Arrays (SoA). Instead of one `struct` with all fields packed together, store each field in its own contiguous array. This ensures that when the hot loop iterates over positions, every cache line contains only position data — no wasted bandwidth loading unused fields like color or material ID.

For a particle simulation update loop touching only `x, y, z` on 4M particles, SoA achieved 2.1x throughput over AoS because each 64-byte cache line carried 8 useful `double` values instead of 2 (the struct was 48 bytes, so only 1.3 structs fit per line, wasting ~60% of fetched memory bandwidth on cold fields).

## Experiment Data

| Layout | Throughput (Mops/s) | L1 Cache Miss Rate |
|--------|--------------------|--------------------|
| AoS (baseline) | 142 | 12.3% |
| SoA | 298 | 3.1% |
| SoA + AVX2 vectorization | 487 | 2.8% |

## What Didn't Work

- **Hybrid AoSoA** (blocking 8 structs into a mini-array): Marginal improvement over AoS (~15%) but added complexity. Only useful when multiple fields are always accessed together.
- **`__attribute__((packed))`** on the struct: Reduced struct size but caused unaligned access penalties that negated the benefit.

## Code Example

```cpp
// AoS — cold fields pollute cache lines
struct Particle { double x, y, z, vx, vy, vz; int material; float color[4]; };
std::vector<Particle> particles(N);
for (auto& p : particles) p.x += p.vx * dt; // loads 80 bytes per particle, uses 16

// SoA — only position data in cache
struct Particles {
    std::vector<double> x, y, z, vx, vy, vz;
    std::vector<int> material;
    std::vector<std::array<float,4>> color;
};
Particles ps(N);
for (size_t i = 0; i < N; i++) ps.x[i] += ps.vx[i] * dt; // loads 16 bytes, uses 16
```

## Environment

C++17, GCC 13.1 with `-O3 -march=native`, Intel Core i7-13700K, 32 GB DDR5-5600, Ubuntu 23.04. Measured with `perf stat` for cache miss rates.

# Speeding up parallel in-place samplesort (IPS4o) on 64-bit keys

## Problem

`ips4o::parallel::sort` (IPS4o, upstream 08a5b92) on `uint64_t` with `std::less`, 16 cores of one socket
(Xeon Silver 4216, Cascade Lake, AVX-512), n = 10^9 keys (8 GB). Metric: geometric mean over 21 instances
(uniform, 10^4 distinct, Zipf, nearly sorted, reversed with swaps, organ pipe, mixed blocks; 3 seeds each) of
time / time(upstream), paired interleaved A/B runs in one process. Rules: comparison-based only (no radix or
arithmetic on keys), in place, generic template must stay correct, held-out gate with five unseen families,
strict keep rule (gain outside the A/A noise band, gate pass, difftest + TSan + ASan/UBSan).

## What Worked

1. **Measure the size distribution of the base case before modelling it.** At n = 10^9 the last-level
   buckets average ~22 keys, but the 21% of base cases with more than 32 keys hold 51% of the keys and 76% of
   the insertion-sort work. Replacing insertion sort for <= 32 keys gave -4.5% and -3.4%; covering the tail
   (64-key register networks plus a branchless merge up to 256, later 1024 keys) gave -8.3%.
2. **Vectorized base case on 256-bit registers** (AVX-512VL `vpminuq`/`vpmaxuq`, 4 lanes column-major, mirror
   merges): GCC compiles a scalar cmov network on 64-bit keys to one key per xmm register with spills; the
   column-major layout is ~2x faster. 512-bit was avoided for the frequency license.
3. **Larger base case once it is cheap** (16 -> 64 keys): one partitioning level less at n = 10^9 (4 -> 3),
   -1.8%; less than modelled because the removed level was cache-resident.
4. **Classifier descent as `cmp mem, reg; adc b, b`** (inline asm, unsigned 64-bit keys only): GCC emits
   `cmp; lea; adc $0` per tree level (3 uops); `adc b, b` computes `2b + CF` in one. 8 levels per key, -8.0%
   on every family, 2.7x the predicted gain: the classification loop is issue-bound, so uop counts per key
   translate almost directly into time.

Training metric 1.000 -> 0.758 (-24.2%) after 10 experiments, gate passed at every kept step, struct key path
unchanged, extra memory 0.11% of the input throughout.

## What Didn't Work

- Early-exit sortedness scan before the merge path of the base case (twice): recovered 3..5% on Zipf
  (all-equal buckets sorted at fixed cost) but only 0.3..0.6% of the training mean.
- Unrolling the adc descent over 8 keys instead of 7: -13% in a micro-benchmark of the descent alone, nothing in
  situ.
- Per-bucket buffer pointers as separate `ptr[]`/`end[]` arrays (saves sign extension and shift per push):
  -1..-6% on random-bucket inputs, but +1..+3.6% on presorted inputs, where consecutive keys go to the same
  bucket. The arrays were exactly 4096 B apart (4K aliasing); padding halved the loss but did not remove it.
- Pilots with a standalone binary (different iterator type and standard level) mispredicted the harness on
  presorted families twice. Pilot with the exact harness build.

## Experiment Data

| step | change | paired ratio | metric |
|------|--------|--------------|--------|
| H1 | scalar Batcher networks, base case <= 32 | 0.955 | 0.956 |
| H2 | AVX-512VL 256-bit base case <= 32 | 0.966 | 0.921 |
| H3 | vector base case up to 256 (64-key registers + branchless merge) | 0.917 | 0.844 |
| H5 | base-case size 64 for vectorized key types | 0.982 | 0.825 |
| H7 | classifier descent as cmp + adc | 0.920 | 0.758 |
| H4, H6, H9, H10 | discarded (inside the noise band) | 0.992..0.998 | |

Noise band: 0.61% in part 1, 2.06% in part 2 (dominated by the struct-path check).

## Code Example

```cpp
// b = 2 * b + (splitter[b] < v), unsigned 64-bit keys, std::less
asm("cmpq %2, (%1,%0,8)\n\tadcq %0, %0"
    : "+r"(b) : "r"(splitters), "r"(v), "m"(splitters) : "cc");
```

## Environment

C++14, GCC 13.3, `-O3 -march=native`, Intel Xeon Silver 4216 (16 cores, one socket, 92 GB), threads pinned
and memory bound to the socket.

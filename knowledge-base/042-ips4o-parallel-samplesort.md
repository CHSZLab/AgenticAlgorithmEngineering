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

5. **Run-aware classification**: probe 64 adjacent pairs per classification call; if at most 1/8 change
   bucket, classify by following the current bucket (two splitter comparisons per key instead of a full
   descent). -4.9% overall, -9..-10% on nearly sorted, reversed and organ-pipe inputs, neutral on random ones.
6. **Base-case merge from both ends**: the front takes the smaller head, the back the larger tail (ties
   consistent), halving the dependent chain of the branchless merge: -3.2%.
7. **Check for 4K aliasing when splitting a struct-of-pairs into parallel arrays.** Separate `ptr[]`/`end[]`
   bucket arrays exactly 4096 B apart lost on presorted inputs; padding halved the loss. After run-aware
   classification took over the presorted inputs, the padded layout was re-proposed (reason logged first)
   and gave -5.3%.
8. **128 keys in 32 ymm registers** (one sort network for 4 x 32 lanes plus the lane merges) instead of two
   64-key register sorts and a merge: -1.3%. Needs `__attribute__((flatten))`: without inlining of the
   network, GCC keeps the register file in memory.
9. **Re-tune the level thresholds after making the base case cheaper.** The upstream single-level limit
   (base-case size x 2^8) was derived for a slow base case; a histogram of (parent size, child size) of the
   sequential recursion showed ~40% of the last-level subproblems just above the limit, split by two 4-bit
   levels or a 5-bit level plus a second partition of every child. Doubling the limit for the vectorized
   key types: -2.1%.
10. **Copy runs instead of classifying them.** In the run-aware classification, a run of keys of one bucket
   is copied in an inner loop specialized for interior, first and last bucket, bounded by the input and
   buffer ends: -7.3%. Presorted families also need a presorted base case (sorted: done, reversed: reverse,
   few descents: insertion) for the buckets of such partitions: -1.3%.
11. **Equality buckets of integer keys need no data movement.** For 8-byte integers under `std::less`
    (equal keys are identical), a full buffer of an equality bucket is reset and counted, and the cleanup
    fills the bucket with the splitter value. The fill must be parallel (split by rank over all threads)
    and use non-temporal stores for long ranges, or the cold lines are read before being written: -1.4%,
    few_unique -7..-12%.
12. **A vector quicksort beats one partitioning level only on warm data.** Random subproblems of <= 64K
    keys sorted by a 256-bit AVX-512VL quicksort (compare mask -> 16-entry LUT permute, full stores at both
    write ends). The subproblem is cold when its sort starts: probe short contiguous chunks, split once by
    a median of 9, then sample in the warm halves; strided probes and a large cold sample ate the gain.
13. **Look at what a subproblem holds before designing a rule for it.** Dumping real buckets of the
    presorted families and simulating candidate rules in a few lines of Python found the three largest wins
    of the session:
    - inputs monotone up to local disorder: probe, reverse if descending, bounded parallel insertion sort per
      stripe, stripe boundaries repaired under the same bound, full sort on any exceeded budget: -16.4%
      (reversed 0.29x); then the reversal fused with the insertion pass while cache resident: -6.3%;
    - nearly sorted subproblems after a partitioning level (owner blocks in order, random blocks of keys
      displaced from other stripes, sorted pieces at the margins): one pass over 256-key windows keeps sorted
      windows in bulk, extracts random ones and decides per key in between; the displaced keys (2.6..4.3%)
      go to a buffer of <= 0.75% of the input, are sorted and merged back from the back: -4.6%.
14. **Check code alignment before trusting a small effect.** Unrelated edits moved untouched families by
    1..5% (a hot loop ending on a 32-byte boundary, JCC erratum on Cascade Lake). 64-byte alignment of the
    hot functions stopped the shifts; pinning insertion sort to 16 mod 64 fixed a kv regression. Micro gains
    of 20..40% in tight scalar loops vanished with `-Wa,-mbranches-within-32B-boundaries`.

15. **Make the presorted cases read-only first.** The outlier case of item 13 compacted the kept keys (one R+W
    pass) and then merged (another). Recording the kept keys as runs of positions in a read-only pass lets the
    merge move each key once: the shift D (outliers before minus holes before) only grows inside a run, so
    runs split into segments merged forward (D <= 0) or backward (D > 0), cut where neither side reads or
    writes across: -2.5%, nearly sorted -15%.
16. **Ask how far each family is from one pass over memory.** Organ pipe took 1.08 s, about 6 passes. A few
    (<= 4) long monotone runs at the top level are now merged pairwise in place in parallel: threads co-rank
    output blocks, merge each into an input block they have already consumed (or one of 12 buffer blocks),
    and a parallel block permutation (paths and cycles cut into equal parts, copies at the cuts) puts the
    blocks in place; descending runs are read backwards: -9.4%, organ pipe -57%.
17. **Check the output instead of the input.** The run detection read (0.09 s) went: runs come from 65536
    probes (a subsequence has at most as many runs as the input, so declining is always safe), and the merge
    checks that each output block is sorted and after the previous one. On failure the threads stop at a
    block boundary and refill their consumed positions from the buffer slots, leaving a permutation for the
    generic sort. Together with merge blocks as large as the memory budget allows (128 KB instead of 16 KB):
    -1.7%, organ pipe -21%.

Training metric 1.000 -> 0.338 (-66.2%, 2.96x) after 48 experiments, gate passed at every kept step, struct
key path within the band of the baseline, extra memory 0.11% of the input (0.70% while the outlier buffers of
item 13 are in use).

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
- Classifier compare-exchange variants: an arithmetic (branch-free, sub + shift) descent was +6% slower than
  `cmp; adc`; unrolling 8 instead of 7 keys gained 2..3% on random families and lost 1..3% on presorted ones
  (net +0.3%); staggering the bucket buffers to avoid set conflicts and a vectorized first tree level were
  neutral.
- Higher oversampling (50%, 100% instead of 20%) for narrower last-level buckets: the cleanup got 3% faster,
  the wall time 1..4% slower (more sample sorting).
- Sorting the sample with the base case instead of a recursive partition: 20% fewer partition calls, but only
  -0.4%.
- Profiling with per-phase timers (`IPS4O_TIMER`) distorted the profile (a fake 12% gap and lock contention);
  per-level atomic counters in a plain build were reliable.
- Non-temporal or inline vector block flushes in the classification: +8..+25% (the permutation re-reads the
  flushed blocks from cache; libc `rep movsb` already avoids the read for ownership).
- More L0 buckets (1024..4096) to save a pass: the 32 KB tree misses L1d and 1 MB of buffers miss L2 (+5.5%
  at 1024).
- A merge of the few monotone runs in subproblems of organ-pipe inputs: -9..-12% on that family, but one
  family in seven moves the geometric mean by under 1%: inside the noise band. A 256-bit bitonic merge was
  no faster than a 4-chain scalar branchless merge (port 5 saturated).
- Counting few distinct keys with hash tables: fast, but not comparison based (rejected by the rules).
- A probe-based run detection alone (organ pipe -12%) did not survive the paired run: the untouched families
  drifted +1..2%, and one family in seven needs ~15% to clear a 1.5% band. Stacking it with the larger merge
  blocks did.
- Splitter thinning under equality buckets (zipf -4%) and an asm equality step: inside the band; a stand-alone
  profiler mispredicted classifier changes of 2..5% on the harness library twice.
- For the struct key path, a rank sort or a smaller last-level bucket instead of insertion sort: <= 1% or
  slower.

**Changing a threshold can move an off-by-one into reachable range.** The two-level bucket count
`(log2(n / base) + 1) / 2` exceeds the maximum of 8 at exactly n = 2-level threshold once the single-level
threshold is above base x 2^8; with the doubled threshold this is n = 2^23 exactly, and buildClassifier writes
past the splitter array. The difftest (random sizes and a fixed size list) did not hit it; a larger threshold
in a prototype crashed on Zipf. Add the exact thresholds to the difftest whenever they change.

## Experiment Data

| step | change | paired ratio | metric |
|------|--------|--------------|--------|
| H1 | scalar Batcher networks, base case <= 32 | 0.955 | 0.956 |
| H2 | AVX-512VL 256-bit base case <= 32 | 0.966 | 0.921 |
| H3 | vector base case up to 256 (64-key registers + branchless merge) | 0.917 | 0.844 |
| H5 | base-case size 64 for vectorized key types | 0.982 | 0.825 |
| H7 | classifier descent as cmp + adc | 0.920 | 0.758 |
| H11 | run-aware classification | 0.951 | 0.721 |
| H12 | base-case merge from both ends | 0.968 | 0.700 |
| H13 | padded separate buffer pointer arrays | 0.947 | 0.661 |
| H26 | 128-key register sort | 0.987 | 0.653 |
| H28 | single-level limit x2 for the vector base case | 0.980 | 0.640 |
| H30 | skip the base case of equality buckets | 0.986 | 0.628 |
| H33 | out-of-place stratified sample at the last level | 0.989 | 0.620 |
| H35 | run copy in the run-aware classification | 0.927 | 0.574 |
| H34r | presorted base case | 0.987 | 0.564 |
| H39r | equality buckets rebuilt from the splitter (+ hot-function alignment) | 0.986 | 0.554 |
| H41r | per-chunk run dispatch in the classification | 0.985 | 0.543 |
| H42 | vector quicksort for random subproblems (kept for a struct-path gain) | 0.999 | 0.542 |
| H44r | inputs monotone up to local disorder | 0.836 | 0.451 |
| H45 | reversal fused with the insertion pass | 0.937 | 0.422 |
| H48 | displaced keys of nearly sorted subproblems extracted and merged back | 0.954 | 0.403 |
| C1 | vector top levels of the classifier + run merge in organ-pipe subproblems | 0.977 | 0.394 |
| H58 | outlier case with a read-only first pass and one segmented merge | 0.975 | 0.383 |
| H59b | top-level in-place parallel merge of <= 4 long runs | 0.906 | 0.348 |
| H62 | runs from probes, checked merge, merge blocks from the memory budget | 0.983 | 0.338 |
| H4, H6, H9, H10, H20, H23, H27, H49, H52, H61 and others | discarded (inside the noise band) | 0.986..1.004 | |

Noise band: 0.61% in part 1, 2.06% in part 2 (dominated by the struct-path check), 0.82% in part 3, 3.47%
in part 5 (one gate outlier), 2.09% in part 6, 1.54% in part 7.

## Code Example

```cpp
// b = 2 * b + (splitter[b] < v), unsigned 64-bit keys, std::less
asm("cmpq %2, (%1,%0,8)\n\tadcq %0, %0"
    : "+r"(b) : "r"(splitters), "r"(v), "m"(splitters) : "cc");
```

## Environment

C++14, GCC 13.3, `-O3 -march=native`, Intel Xeon Silver 4216 (16 cores, one socket, 92 GB), threads pinned
and memory bound to the socket.

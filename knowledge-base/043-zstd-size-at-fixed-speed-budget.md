# Buying compressed size with a fixed speed budget in zstd

## Problem

Reducing the compressed size of the reference Zstandard library at level 1 (`fast` strategy) and
level 19 (`btultra2` optimal parser), starting from a speed-optimized build.

- **Metric:** the geometric mean of the compressed sizes of 8 Silesia files at both levels, relative to
  the starting build. Sizes are deterministic, so one run per change gives exact numbers.
- **Speed limit:** the geometric mean of the four time ratios (compression and decompression at both
  levels; one cold run per process; 0.01 s shift) against the unmodified upstream code must stay at or
  below 1.0. The starting build was at 0.878.
- **Held-out gate:** five unseen files, which must not get slower than the unmodified code (within 0.5%)
  or larger (within 0.1%).
- **Fixed:**
  - The frame format: the unmodified decoder must read every output.
  - The match window: at most 8 MB, the size every decoder is recommended to support. The owner
    rejected a larger window, even for a measured -1% at level 19, because of decoder compatibility.
  - The build flags and the public API.

## What Worked

After 16 experiments (11 kept):

| | before | after |
|---|---|---|
| size, overall | 1.000 | 0.9481 |
| size, level 1 | 1.000 | 0.9007 |
| size, level 19 | 1.000 | 0.9980 |
| speed score | 0.878 | 0.947 |

1. **Price each lever by size gained per unit of time, before spending time.** Level 1 was far from its
   speed/size frontier; level 19 was close to it.
   - Level-1 hash table, 2^14 -> 2^17 entries: -5.5% level-1 size for +22% level-1 time.
   - Level-19 `targetLength` 256 -> 999: only -0.13% for +4% level-19 time.

   A tool that overrides compression parameters (`ZSTD_CCtx_setParameter`) and reports exact sizes in
   parallel, plus interleaved one-core timings, made these exchange rates cheap to measure.

2. **A lazy check in the fastest match finder (the largest single gain).** The `fast` strategy takes
   the first 4-byte match it finds.
   - **One step (-1.6% level-1 size, +2.5% level-1 time):** the hash entry for the next position is
     read anyway just before it is overwritten. Comparing the match there with the current one and
     taking the longer costs one compare, plus one length count when it hits. Counting the first
     match's length once and reusing it was what made it affordable: a naive version cost +7.5%.
   - **Two steps (a further -0.9%):** also try ip+2, with its table entry loaded before the length
     counts so the cache miss overlaps them. It wins when its match ends at least 4 bytes later.
   - **Fewer, longer sequences:** both lazy steps also made decoding 1-2% faster.

3. **Weigh offset cost in the lazy decisions (idea from brotli and xz).** Brotli ranks candidates by
   `135*len - 30*log2(distance)`. xz's fast LZMA parser moves to a much farther match only when it is
   clearly longer (`change_pair`). For zstd's lazy steps the best weight was much smaller than brotli's:
   a quarter byte of length per offset bit (-0.12% level-1 size). Brotli's weight (about one byte per
   4.5 bits) and half a byte per bit both made zstd's output larger.

4. **Insert positions near the end of each match.** After a match the fast finder inserts only two
   positions. Adding ip-1 and ip-4 gave -0.7% level-1 size at no measurable cost: data after a match
   tends to continue an earlier repeat. The middle of the match added -0.2%. Spreading insertions
   evenly over the match was worse.

5. **Window and table size interact.** With a larger table, candidates pointed past the 512 KB level-1
   window. An 8 MB window gave -1.2% and made compression faster, but decompression 3.8% slower: far
   matches miss the cache.

6. **Pay for size with code placement.** On a JCC-erratum core (Cascade Lake), pinning the level-1 loop
   to a 64-byte boundary saved about 2% of level-1 compression time in the harness. That paid for an
   extra insertion. Placement doesn't change size, but it buys budget.

7. **Level-19 parser:**
   - Scale accumulated statistics down more strongly at each block (2^9/2^8 instead of 2^12/2^11), so
     prices follow the block that is actually encoded: -0.05% at level 19.
   - Accept 3-byte matches only within 32 KB: -0.035% at level 19.

## What Didn't Work

- **The tuning-set speed score overstates a hidden-set budget.** The held-out gate passed at 0.9507
  and failed at 0.9542 (a 2^18 table) and at 0.9552. Spend a speed budget in small steps.
- **Changes that move time into the decoder.** A 6-byte hash gave -0.34% level-1 size and was 1%
  faster to compress, but made decoding 3.3% slower and failed the gate. Time decompression in every
  prefilter, not only compression.
- **xz's repeat-match preference:** take a repeat-offset match if it is within 1-3 bytes of the main
  match. It gave only -0.05%, and in zstd a repeat code changes meaning when the literal length before
  it is 0, which broke the round trip in a first version.
- **Choices already near-optimal or without effect:**
  - Level 1: cost-based entropy-table choice (-0.04%), Huffman depth search (0%), minimum-gain
    thresholds (0%), pre-splitting blocks by chunks (-0.19% for +4% time).
  - Level 19: re-tuning the per-match handicap, the literal frequency increment, `searchLog` 8-9.
- **The prefetching decoder for 8 MB windows** (11% slower), and **re-placing the Huffman assembly
  loops** (the default was best).
- **A second parse of each block with that block's own statistics** (the iterated cost model of brotli
  q11 and LZMA): too expensive for the remaining speed budget.

## Environment

C, gcc 14, single-threaded, Intel Xeon Silver 4216 (Cascade Lake, JCC-erratum microcode, 1 MB L2 per
core).

How far the ideas transfer:
- **The lazy check from the overwritten hash slot**, match-end insertion and distance-aware choices
  apply to any single-candidate LZ77 match finder.
- **Exchange-rate pricing** applies to any size-versus-speed trade.
- **Code placement** is specific to the CPU and compiler.

Parameter values were fitted to 8 Silesia files and checked only through the held-out gate.

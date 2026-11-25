# Speeding up zstd's strongest levels and its decoder at equal compressed size

## Problem

Speeding up the reference Zstandard library (upstream `439044e`). Only the C
sources in `lib/common`, `lib/compress` and `lib/decompress` could change. The
build flags, the public API and the frame format were fixed.

- **Metric:** the geometric mean of four time ratios against the unmodified code,
  one cold run per process, with a 0.01 s shift: compression and decompression
  at level 1 (`fast` strategy) and at level 19 (`btultra2` optimal parser).
- **Inputs:** 8 Silesia files, plus a held-out gate on files never used for
  tuning.
- **Hard gates:**
  - Every output round-trips.
  - The unmodified decoder reads every output.
  - Compressed size stays within 0.1% of the unmodified code (geometric mean per
    level).
- **Keep rule:** a change was kept only at score <= 0.995 against the current
  best, followed by ASan/UBSan and `make check`.

Level-19 compression dominates wall time (2-21 s per file). Decompression and
level 1 take 3-160 ms, so the 0.01 s shift damps their ratios.

## What Worked

Score 1.000 -> 0.877 (checkpoint against the unmodified code):

| part | ratio |
|---|---|
| level-19 compression | 0.647 (1.55x faster) |
| level-1 decompression | 0.952 |
| level-19 decompression | 0.957 |
| level-1 compression | 1.004 (unchanged) |

Level-19 output is 0.09% smaller, and level-1 output is byte-identical.

1. **Precompute per-code prices in the optimal parser (-11.7% level-19
   compression, identical output).** `btultra2` prices every candidate length of
   every match. Each price recomputed `ZSTD_highbit32`, a fractional-bit weight
   and a table lookup from the symbol statistics. These statistics only change
   once per block, so per-code tables for literal length, match length and
   offset code are filled once in `ZSTD_setBasePrices`. The inner price then
   becomes two loads and an add. The gain was largest on repetitive inputs (xml
   and nci -21%), where many lengths are scanned per position. A flat profile
   under-weighted this: the price work was spread over many small inlined
   helpers.

2. **The binary-tree match finder is bound by memory latency. Fix the TLB first,
   then prefetch.** One level-19 search walks a 2^25-node tree over an 8 MB
   window, which means two dependent random misses per node (the tree node,
   then the match bytes). Three changes worked, and their order matters:
   - **Pipeline across calls (-3.9%).** At the start of the search for position
     p, prefetch the hash bucket of p+2 and the root node and data of p+1. The
     first misses of each search are fully exposed, so overlapping them with the
     current search pays.
   - **Transparent huge pages for the workspace (-5.7%).**
     `madvise(MADV_HUGEPAGE)` on the 2 MB-aligned interior of workspaces of 8 MB
     or more. This applies only to the default allocator, and only on Linux with
     THP in `madvise` or `always` mode.
   - **Prefetch both children inside the descent (-5.8%).** Which child comes
     next depends on a byte comparison, so prefetch both. Before huge pages, the
     same change gave only -1.6% and was discarded, because a prefetch that
     misses the TLB still waits for the page walk.

   General lesson: **retry discarded memory-latency ideas after a change that
   alters the memory model** (huge pages, a layout change).

3. **Split a loop by its predictable condition instead of making it
   branchless (-6%).** The parser's length scan stores a price for each length
   only if the length improves on the current one. Lengths beyond the last
   reached position always improve, so they get an unconditional loop. The
   remaining lengths keep the conditional loop. A branchless version was slower:
   the branch was predictable, and the cost was in the loop structure.

4. **Spend the size budget through a cost-model parameter, not through a cruder
   search.** Stopping the length scan after k lengths that do not improve on the
   current price is a tunable approximation: k=4 gave -6% time for +0.05% size.
   Raising the parser's per-match handicap from 0.2 bits to 1 bit then *reduced*
   size by 0.14% and made decoding faster (fewer, longer sequences: osdb -3.9%
   decode). That size gain paid for an earlier stop (k=2). The default
   constant was simply too low for this corpus. Check a cost-model constant
   before trading quality for speed elsewhere. One caveat: the size gain was
   concentrated on one file (osdb -1.3%), and text files grew (+0.13% to +0.42%).

5. **Code placement of the decoder's hot loop (-5% to -9% decompression).** On a
   Skylake-derived core with the JCC-erratum microcode, a jump that crosses or
   ends on a 32-byte boundary is not cached as uops. zstd already aligns
   `ZSTD_decompressSequences_body` with an `asm(".p2align ...; nop")` sequence,
   which put the loop start at 40 mod 64. Moving it to 56 mod 64
   (`.p2align 6` + `.skip 56, 0x90`) made decoding 7% faster on mozilla, webster
   and nci at level 1. If a codebase already pins a hot loop with asm padding,
   sweep the padding: the right value depends on the CPU and the compiler.

## Experiment Data

19 experiments: 9 kept (one of them a correctness fix), 10 discarded. Step
scores of the kept changes, each measured against the previous best:

| change | step score | main effect |
|---|---|---|
| per-code price tables | 0.971 | L19 compression -11.7% |
| cross-call BT prefetch | 0.991 | L19 compression -3.9% |
| THP for workspaces of 8 MB or more | 0.986 | L19 compression -5.7% |
| child prefetch in descent and insertion | 0.985 | L19 compression -5.8% |
| split length scan | 0.984 | L19 compression -6.0% |
| bound the prefetch (over-read fix) | 1.005 | correctness |
| stop the scan after 4 misses | 0.986 | L19 compression -6.2%, size +0.05% |
| 1-bit handicap, stop after 2 misses | 0.990 | L19 compression -4%, size -0.14% |
| decoder loop at 56 mod 64 | 0.982 | decompression -5% to -9% |

## What Didn't Work

- **Branchless child selection in the BT descent:** 7-16% slower. Speculating
  down the predicted child starts the next node earlier, which is worth more
  than avoiding mispredictions.
- **Read-only "lockstep" walks of the next search paths,** meant to warm the
  cache for upcoming searches: +45%. Once huge pages and the two prefetch levels
  were in, the descent was bound by per-node work, not by misses, and the
  walks duplicate that work.
- **Deeper cross-call prefetch** (children of the next root): below 1%.
- **Explicit 64-byte alignment of the hot parser functions:** slightly slower.
  Alignment is not monotone: only measured placement works.
- **Incremental literal weight tables:** slower than the existing computation.
- **Level-1 micro-optimizations** (cmov match check, loop placement): -1.5%
  warm (minimum of 9 runs in one process), but +1.7% or only -1.5% in the
  harness's cold one-run-per-process measurement. **Effects of about 1%
  measured warm do not transfer to a cold-start metric;** prefilter with the
  harness's own protocol. The 5-9% decoder placement did transfer.
- **A correctness trap:** the cross-call prefetch hashed p+2 with an 8-byte read
  and over-read the input by up to 2 bytes for `minMatch` >= 5 (levels 16-18).
  It was missed because sanitizer checks ran only at the benchmarked levels.
  Run sanitizers on every code path the change touches, not just the benchmarked
  levels.

## Code Example

Cross-call pipelining at the start of the BT search (no-dictionary path):

```c
if ((dictMode == ZSTD_noDict) && ((mls <= 4) || (ip + 2 + 8 <= iLimit))) {
    /* The parser searches consecutive positions: pipeline their first cache misses.
     * Fetch the hash bucket of ip+2, and the root node and data of ip+1,
     * whose bucket was fetched by the previous call.
     * Hashing reads 4 bytes for mls <= 4 and 8 bytes above, hence the bound. */
    U32 const nextIdx = hashTable[ZSTD_hashPtr(ip+1, hashLog, mls)];
    PREFETCH_L1(hashTable + ZSTD_hashPtr(ip+2, hashLog, mls));
    PREFETCH_L1(bt + 2*(nextIdx & btMask));
    PREFETCH_L1(base + nextIdx);
}
```

## Environment

C, gcc 14 with the project's default `-O3` flags, single-threaded, Intel Xeon
Silver 4216 (Cascade Lake, JCC-erratum microcode), Linux 6.8 with THP in
`madvise` mode.

How far the ideas transfer:
- **Price tables, the split scan and the cost-model recalibration** apply to
  any optimal (dynamic-programming) LZ parser.
- **"Huge pages before prefetch"** applies to any pointer-chasing structure
  larger than the TLB reach.
- **The loop placement is specific to this CPU and compiler;** re-sweep it
  elsewhere.

All tuning was in-sample on 8 files. The held-out gate passed, but the
size-neutral parameters (handicap, scan stop) were chosen on this corpus.
Developed with Agentic Algorithm Engineering.

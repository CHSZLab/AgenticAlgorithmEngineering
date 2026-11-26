# Speeding up parallel induced-sorting suffix array construction (libsais) with identical output

## Problem

Make libsais (SA-IS with induced sorting, the fastest open-source 32-bit suffix array builder) faster on
100 MB texts (english, dna, source code, a repetitive DNA collection) in two modes: serial (`libsais`,
one core) and 8 threads (`libsais_omp`, one thread per physical core of a 16-core Xeon Silver 4216,
6-channel DDR4). Metric: geometric mean of the time ratios of both modes against the unmodified code.
Hard gates: the suffix array is identical (it is unique, so any correct algorithm qualifies), peak RSS at
most +1%, no input assumptions. 30 experiments, 14 kept (several as multi-component changes).

## What Worked

**Score 0.832 (8 threads about 0.73 of the original, serial about 0.96).** The library is heavily
tuned for memory-level parallelism; almost all gains came from removing serial steps that 8 threads
wait on, not from making any loop faster.

1. **Find the serial steps with wall-clock phase timers, not a CPU profiler.** `perf` was unavailable;
   a SIGPROF sampler showed 36% of 8-thread CPU time spinning in libgomp, but only per-call wall timers
   (serial vs 8 threads side by side) showed *which* phases do not scale. Instrument statements inside
   conditionals and ternaries too: a phase costing 7% of one text's run (non-unique LMS-name resolution)
   stayed invisible for 25 experiments because the timer script skipped them.
2. **Split a serial "master" bucket step by symbol ownership (+5.4% score, the largest single gain).**
   Block-parallel induced sorting gathers a block in parallel, then one thread walks every entry to
   update bucket pointers, then places in parallel. Bucket pointers stay inside their bucket, so they
   are monotone in the symbol: the buckets that can still induce *into the current block* form one
   symbol interval found by binary search. A short serial resolve handles only those (and the entries
   they create); all other entries are induced in parallel, each thread owning a contiguous symbol
   range (split by target positions). Then let the owners write `SA[target]` directly instead of
   writing back into the shared block cache, where ~8 owners per cache line caused line ping-pong
   (+1.8%).
3. **Pipeline when the serial step cannot be split.** In the dense partial-sorting scans (every slot
   is an entry, in-block inductions frequent) the owner scheme lost; overlapping the workers' gather of
   block b+1 with the master's sort of block b won 4% at 8 threads. Only the next-block slots that the
   current block's place writes are stale; patch them during the place with the gather's own formula.
4. **Dynamic scheduling of the first phase (2.6% at 8 threads, 3x the phase gain).** With the
   `schedutil` governor idle cores start at 800 MHz: the master finished its static segment of the
   first pass in 14 ms, the workers in 50 ms. Chunks taken dynamically (summed back per segment so all
   downstream per-thread state is unchanged) also sped up later phases.
5. **Hunt every serial loop between parallel phases.** Each was small, together they were ~8%:
   memsets of SA ranges (~535 MB per run), memmoves of per-thread lists by the master, O(k) prefix sums
   at recursion levels with a 3M-symbol alphabet, 2-thread counting with 50 MB private bucket copies
   (replaced by writing per-position bucket codes into free space and letting each thread count its
   own code range), static splits of irregular work (non-unique name groups).
6. **Transparent huge pages in serial runs (2.7%).** With THP in `madvise` mode the caller's buffers
   are on 4 KB pages. `madvise(MADV_COLLAPSE)` on the 2 MB-aligned interior of the text (copy, 0.03 s)
   and of the output array after `MADV_DONTNEED` of all but one page per 2 MB (zero fill instead of
   copy, 0.08 s instead of 0.12 s) pays for itself several times. A fully emptied range cannot be
   collapsed, and after `MADV_DONTNEED` faults stay on 4 KB pages because the page tables remain.
7. **Bundle consistent sub-threshold gains.** With a 0.5% keep threshold many real 1% 8-thread gains
   failed alone; as separate commits measured together (multi-component) and attributed by phase
   timers they were kept.

## What Didn't Work

- Owner-parallel versions of steps whose serial loop is already ~2-3 ns per entry (dense partial
  scans, LMS radix sort): every owner must read every cache line of the block, which costs more.
- Precomputing the symbols the serial step needs (removing dependent random reads from it): out-of-order
  execution already hides them.
- Huge pages for the 8-thread mode: collapse is serialized on the mm lock (8 threads slower than 1)
  and a background collapse in idle worker slots made the run 4-6% slower (TLB shootdowns on all cores).
- Keeping idle workers spinning instead of sleeping, prefetch-distance changes, `prefetcht1`,
  branch-free scans, 4k instead of 6k bucket layout, larger or smaller blocks, store prefetching.
- The 8-bit induction scans at 8 threads run at the machine's random-read ceiling (685M reads/s on
  4 KB pages, measured with a microbenchmark); nothing short of fewer accesses helps there.

## Experiment Data

| | serial | 8 threads |
|---|---|---|
| english | 4.44 -> 4.26 s | 1.79 -> 1.28 s |
| dna | 3.54 -> 3.46 s | 1.30 -> 0.95 s |

Score trajectory (product of kept step scores): 0.946, 0.929, 0.921, 0.908, 0.890, 0.884, 0.877,
0.870, 0.858, 0.852, 0.847, 0.842, 0.838, 0.832.

## Measurement Pitfall

A harness that builds `--control-rev` by `git archive | tar -x` stamps the sources with the commit
time; if the control build directory holds objects compiled later, `make` keeps them and the control
silently stays the previous revision. One result counted an earlier gain twice. Delete the control
build directory before every run, and when a change speeds up a code path it does not touch, compare
the control and candidate binaries byte by byte.

## Environment

C99, GCC 14 with OpenMP (libgomp), `-O3`, SSE2 only; Xeon Silver 4216 (16 cores, 22 MB L3), 92 GB
DDR4, Linux 6.8, THP in madvise mode, `schedutil` governor. Gains 2-6 assume many parallel phases
separated by short serial steps; gain 6 is Linux-specific.

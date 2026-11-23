# Speeding up nested dissection and node separators with bit-identical output, and telling code placement apart from speed

## Problem

Make four programs of KaHIP faster while every output stays byte-identical (ordering, separator and
partition files plus the printed objective values) for every input, seed and option set:
`node_ordering` (multilevel nested dissection with data reductions), `fast_node_ordering`
(reductions plus METIS), `node_separator` (multilevel node separators: FM local search on the
separator, localized FM, flow-based improvement) and `partition_to_vertex_separator` (turns a given
partition into a separator; about 0.25 s per job, mostly reading the graph). All four link the same
partitioner library as `kaffpa`, whose outputs must not change either.

Benchmark: 22 timed jobs on 11 graphs (meshes, road networks, SuiteSparse matrices; 3k to 1.4M
nodes, 0.25 to 20 s per run), base and candidate alternating in one session, 3 repetitions (15 for
the sub-second jobs), 16 jobs in parallel on one 16-core node. Identity is checked separately on a
larger untimed suite of 670 jobs (including 328 `kaffpa` jobs). Metric: shifted geometric mean
(shift 0.01 s) of per-job median ratios, overall and per program; a per-program noise band guards
the programs a change does not target.

## What Worked

After 10 experiments (4 kept): geometric mean about 0.70 of the original overall (chained);
`node_separator` about 0.60, `node_ordering` about 0.63, `fast_node_ordering` about 0.82,
`partition_to_vertex_separator` about 0.98. Every output identical on all 670 jobs.

1. **A stamped array as the index map of the FM priority queue (0.79 overall, `node_ordering`
   0.70, `node_separator` 0.72).** The separator FM uses a max-heap whose node-to-slot index was a
   `std::unordered_map`; the hash operations were 17 to 21% of the run time. A pooled per-node
   array with a generation stamp gives O(1) creation (a new heap per FM pass, thousands per
   level) and a direct lookup. The trap: the FM calls `changeKey` on nodes that were removed from
   only one of its two queues, and `operator[]` of the hash map silently inserted index 0 for
   them, so `changeKey` then modified whatever element sits in slot 0. To stay identical the new map
   must reproduce exactly that (insert 0 on lookup of an absent key), and only the index map can be
   replaced, not the whole heap.
2. **Skip repeated gain updates that are provably no-ops (0.89 on top, `node_separator` 0.84).**
   When a node leaves the separator, every neighbor of every node that enters the separator is
   pushed to an update list, so the same node is often listed several times, and each repeat runs a
   full gain computation over its adjacency plus two `changeKey` calls. All gains in that loop are
   computed against the same partition, so a repeat sets the same key again, which `changeKey`
   ignores. This is only true while the node is a genuine entry of both queues and no update since
   its first one went to an absent node (which, by item 1, overwrites slot 0). A stamp per node plus
   a `holds(node)` test (index present and pointing to this node's element), with a new stamp
   generation after every update of a non-genuine node, skips exactly the no-op repeats.
3. **Reuse buffers and merge setup scans.** Two vectors allocated per FM move, and two scans over
   all nodes per pass for the separator list and block weights; kept across calls and merged into
   one scan (part of item 2's gain).
4. **`fast_node_ordering`: remove the avoidable work around METIS (0.88, then 0.94).** The fill
   computation removed duplicates with `vector::erase` in the middle of a loop; stable compaction
   gives the same remaining entries in the same order. The ordering was written with `std::endl` per
   line; `'\n'` writes the same bytes without a flush per line. Then: the elimination order is the
   inverse permutation (no sort needed, a sort has no ties on a permutation; anything else falls back
   to the reference code), and since every adjacency entry is ordered after its owner, an adjacency
   is final when its node is eliminated, so it is counted and freed there.
5. **Do the work on the slow side of a cheap invariant, not on its labels.** For the flow-based
   separator improvement, a different max-flow solver (Boykov-Kolmogorov) can replace push-relabel
   only if the source set is derived from a BFS on the final residual graph (the minimal source side
   is unique over all maximum flows), never from the solver's own tree labels. It was correct but
   slower on these networks (see below).

## Placement: how to tell a speed change from a layout change

The hardest part of this campaign was not speed but judging it. Changes to the shared library moved
the code of programs that never run the changed code, and those programs then measured 1 to 3%
slower, enough to fail a 0.5% per-program band.

- **Two placement studies give two bands.** (a) An unused function at the end of the library (16 to
  200 bytes) moves nothing that runs: spread at most 0.7%. (b) An unused function marked
  `__attribute__((cold))` (160, 176, 336, 1024 bytes, covering 0, 16, 32, 48 mod 64) moves *all*
  hot code, because GCC puts cold code into `.text.unlikely`, which the linker places before the
  hot text. Spread up to 1.7% for `node_separator` and 1.6% for the reader-bound
  `partition_to_vertex_separator`. Which band applies is decided per binary with `nm`/`objdump`
  (did any hot function move?) and `cmp` (binary unchanged: not judged at all).
- **New file listed last is not placement-neutral if it adds cold code.** Exception paths of the new
  code (vector growth failures, `std::__throw_*` calls) go to `.text.unlikely` and shift every hot
  function by the cold size. Check the address of a hot function in an unrelated program before and
  after.
- **Measure the cause with hardware counters.** With `perf stat` on the 0.25 s
  `partition_to_vertex_separator` job, the version that "regressed" by 2.7% executed the same
  instructions (1.2010e9 vs 1.2017e9), with 3.7% more cycles and 29% more
  `frontend_retired.dsb_miss`; `perf record -e frontend_retired.dsb_miss` attributes the extra
  misses to the graph reader's parse loop (0.96M to 3.38M), not to the code that changed. In
  `fast_node_ordering` the same shift tripled the DSB misses in METIS's `Refine2WayNode` and
  `Match_SHEM` (linked after the KaHIP code). The decoded-uop cache (DSB) holds code by 32-byte
  windows on this microarchitecture, so a hot loop's position modulo 32/64 bytes matters.
- **A program-wide target is diluted by programs that did not change.** A 5.7% gain in the 3 jobs of
  one program is 0.8% over 22 jobs. Judge the overall target over the jobs of the programs whose
  binary changed.

## Experiment Data

| exp | change | result |
|-----|--------|--------|
| 002 | stamped index map in the FM heap | keep, 0.792 (no 0.699, ns 0.717) |
| 003 | FM move buffers and merged scans, edits in place | discard, 0.931 but p2vs 1.019 (placement) |
| 004 | Boykov-Kolmogorov flow with residual BFS source set | discard, 1.057 (ns 1.114), RSS 1.35 |
| 005 | 003 re-measured with 15 reps for p2vs | discard, 0.928, p2vs 1.012 |
| 006 | 003's idea in a new last-listed file | discard, 0.930, p2vs 1.016 (+336 bytes cold code) |
| 007 | compute_fill compaction, no flush per line | keep, 0.985 (fno 0.882) |
| 008 | skip no-op repeated gain updates, persistent buffers | keep, 0.893 (ns 0.842, no 0.896) |
| 009 | FM rounds without a full scan per pass | discard, 0.938 (ns 0.883, fast 0.60 to 0.78), p2vs 1.028, fno 1.013 (DSB placement) |
| 010 | compute_fill by inverse permutation, free at elimination | discard, 0.992 over all jobs (fno 0.943; diluted target); re-measured once as 010b after the rule fix: keep, 0.970 over the changed programs (fno 0.942) |

## What Didn't Work

- **Boykov-Kolmogorov instead of push-relabel** for the separator flow problems: 11% slower on
  `node_separator` and 35% more peak memory; the flow networks are small, dense strips where the
  two-phase push-relabel with global relabeling is already fast.
- **Judging shared-library changes only by a run-to-run noise band.** Three measurements of the
  same FM change gave `partition_to_vertex_separator` +1.2%, +1.2% and +1.6% although it never runs
  FM; only the placement studies and the DSB counters showed it was layout.

## Environment

C++11, GCC 13.3, Release build with the project's default flags (no flag changes allowed), Xeon
Silver 4216 (Cascade Lake, 16 cores), Linux. perf with `frontend_retired.dsb_miss` for the
placement diagnosis; before perf was available, an LD_PRELOAD timer-signal PC sampler plus
`addr2line -i` gave inlined-frame profiles.

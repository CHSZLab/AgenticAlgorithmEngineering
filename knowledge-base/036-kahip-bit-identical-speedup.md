# Speeding up a mature multilevel graph partitioner with bit-identical output (KaHIP kaffpa)

## Problem

Make KaHIP's `kaffpa` (multilevel graph partitioner, C++) faster in whole-process wall time while every partition file stays
byte-identical to the original's for the same seed. That rules out any change to the sequence of random numbers, to the order
of iterated containers, or to tie-breaking. Benchmark: 537 jobs (mesh, road and social graphs; k from 2 to 256; the six
preconfigurations fast, eco, strong, fsocial, esocial, ssocial), 3 repetitions each. The metric is the shifted geometric mean of
median wall-time ratios against the original. Correctness is the sha256 of every partition file plus a separate crosscheck of
864 runs.

## What Worked

1. **Look for algorithmic redundancy, not only data-structure tuning.** The biggest single gain (-7.6% geomean, up to 3.3x
   on single jobs) came from 2-way FM. For every neighbor of a moved node, it recomputed the neighbor's internal and external
   degree by scanning that neighbor's whole adjacency, which is quadratic around hub nodes in the coarse graphs of initial
   partitioning. The fix caches the degrees per FM call (stamp array, reused across calls). Before each move, every neighbor
   in the two blocks is made cached with its pre-move values, then the move's edge weight is added or subtracted per edge, so
   parallel edges also add up exactly. The moved node itself is recomputed. The decision code then reads final values exactly
   as before. callgrind's per-line view (40% of instructions on one partition-index load) pointed straight at it.
2. **Cheap whole-process overheads first.** A hand-written METIS reader (one `fread`, a manual integer scanner, the same
   comment/empty-line semantics), a single buffered write of the partition, and computing the final cut once cut the
   non-partitioning time from 102 s to 34 s in total (27% of a `fast` job had been I/O).
3. **Lookup-only hash maps can be replaced, iterated ones cannot.** Maps that are never iterated (FM "moved" table, heap
   index) were moved to an open-addressing map. Maps whose iteration order feeds the algorithm (boundary sets, block pairs)
   had to stay `std::unordered_map`.
4. **A global small-object allocator** (size classes up to 512 B, bump allocation plus free lists in one reserved range) was
   about -3.5%. It cannot change the output because nothing in the code is keyed or ordered by pointer. Note: reserving 128 GiB
   of address space fails under valgrind, so the allocator silently falls back to malloc there. Build a profiling copy with a
   smaller reservation, or the profile shows a malloc cost that does not exist.
5. **Build the flow graph as CSR** in one pass, and map nodes to flow nodes with a hash map instead of O(n) vectors per call
   (flow refinement -7 to -8%, lower peak memory).
6. **Per-phase timers printed by the binary** (exclusive scopes: coarsening, initial partitioning, refinement, plus detail
   scopes such as flow and multitry) make it possible to judge each hypothesis by the component it targets, when several are
   measured in one full run.

## Experiment Data

| exp | change | geomean vs original | verdict |
|-----|--------|---------------------|---------|
| 001 | baseline | 1.0000 | |
| 002-004 | timers, fast IO, open-addressing lookup maps | 0.8676 | keep |
| 005 | global small-object allocator | 0.8390 | keep |
| 006 | CSR flow graph + hashed flow node map | 0.8106 (with 007) | keep |
| 007 | raw-pointer label-propagation loop | (combined) | keep, prediction refuted (3% vs 10-25%) |
| 008 | pointer cache in front of the block-pair map | 0.8076 | discard (below 1% floor) |
| 009 | exact replica of `unordered_map` iteration order | A/B 0.3-1.5% slower | discard |
| 010 | incremental neighbor degrees in 2-way FM | **0.7489** (total 0.7868) | keep |

Every kept step: 0 incorrect of 537 jobs, crosscheck OK on 864 runs.

## What Didn't Work

- **Trusting callgrind instruction shares for small hash maps.** The block-pair map took 7% of instructions and the boundary
  set about 8%. Removing most of that work changed wall time by less than 1%, because these maps are tiny, stay in L1, and the
  out-of-order core hides the hash and the modulo. Pre-filter such ideas with a quick A/B timing (two binaries, alternating,
  3 reps, a handful of targeted jobs) before spending a full benchmark run.
- **Replaying libstdc++'s `unordered_map` iteration order** with flat arrays (head insertion per bucket, rehash via the
  library's own `std::__detail::_Prime_rehash_policy`, erase bucket fix-ups, `clear()` keeping the bucket count). It is exact
  (partitions identical), so this is a usable trick when an iterated map must be replaced, but here it was slower than the
  real map once allocation was cheap.
- **Micro-optimising the label-propagation inner loop** (raw pointers, hoisted flags): only about 3%. The loop is bound by
  random memory access, not by instructions.

## Environment

C++11/GCC 13, Release with KaHIP's default flags (no flag changes allowed), single-threaded, 16-core x86 machine with one job
per physical core, graphs of up to a few million edges.

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
6. **Remove per-call O(n) setup.** Flow refinement allocated and filled an O(n) BFS depth array per call; reusing one array
   and resetting only the reached entries cut flow time by 8%. Sorting (rating, edge) pairs instead of edge ids with an
   indirect rating comparator gives the same permutation (std::sort only depends on comparison outcomes) and cut matching by
   3 to 5%.
7. **Use a time-based sampler, not only callgrind.** perf was unavailable (perf_event_paranoid 4), so a 40-line
   LD_PRELOAD library (ITIMER_PROF at 1 kHz, `backtrace()` in the handler, addr2line with `-i` for inline frames) gave real
   time per source line and per caller. It showed different hot spots than callgrind (for example, a scan over hub
   adjacencies at 23% of one web-graph job). Start the sampler after `taskset`, not before it: the interval timer survives
   `exec` but the handler does not, so SIGPROF kills the child.
8. **Per-phase timers printed by the binary** (exclusive scopes: coarsening, initial partitioning, refinement, plus detail
   scopes such as flow and multitry) make it possible to judge each hypothesis by the component it targets, when several are
   measured in one full run.
9. **Software prefetch for whole-graph sweeps in random order.** Label propagation visits all nodes in a random
   permutation, so every node, its edge list and its neighbors' cluster ids are cache misses. Prefetching the node entry three
   nodes ahead, its edges two ahead and the neighbors' cluster ids (at most 32) one ahead cut coarsening by 14%. The same
   prefetch in the k-way move loop was 2% slower: those neighborhoods are already cache resident.
10. **Small containers in the max-flow solver.** `std::vector<bool>` flags became `char`, and edges are reached through one
   pointer per node; push-relabel time fell by 8% with the same capacity casts (a `NodeID` accessor truncated a 64-bit
   capacity, and the cast had to be kept for identical flows).
11. **Check every hash map for lookup-only use, including first-occurrence numbering.** The ensemble of clusterings
   numbered each distinct (cluster a, cluster b) pair at its first occurrence via an `unordered_map`; a stable bucket sort by
   the first id plus a stamp array over the second gives the same numbers without hashing (coarsening of the strong social
   configuration -16%, one job -20%). A distribution's output can also be replaced by its closed form when the library's
   algorithm is known: libstdc++'s `uniform_int_distribution(0,1)` on `mt19937` returns the top bit of one draw.

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
| 012 | reuse BFS depth array in flow refinement | 0.7322 (with 013) | keep |
| 013 | sort (rating, edge) pairs in GPA matching | **0.7322** (total 0.7659) | keep |
| 014 | reuse multitry start-node gains, replay tie draws | A/B 0.995 | discard |
| 015/019 | skip repeated no-op boundary updates of the moved node | 0.7309 (with 018) | discard (below floor) |
| 016 | k-way gain loop over raw arrays | A/B 1.007 (slower) | discard |
| 017 | witness hint for the "still adjacent to old block" scan | 0.7331 (with 018) | discard (+1-3% elsewhere) |
| 018 | residual graph reverse-edge lookup via smaller adjacency | 0.7309 (with 019) | discard (web graphs only) |
| 020 | prefetch in the label-propagation sweep | 0.7079 (total 0.7463) | keep |
| 021 | prefetch in the k-way move loop | A/B 1.019 (slower) | discard |
| 022 | push-relabel char flags, one edge pointer per node | **0.6986** (total 0.7317) | keep |
| 023 | push-relabel queues as arrays | A/B 0.998 | discard |
| 024 | `noexcept` hash functors (no cached hash codes) | A/B 0.994 | discard |
| 025 | `nextBool` as the top bit of one `mt19937` draw | 0.6924 (with 026, 027) | keep |
| 026 | ensemble numbering without a hash map | **0.6925** (total 0.7172, confirmed by the 030 run) | keep |
| 027 | SCC with vector stacks in most-balanced min cut | flow time 1.005 | discard |
| 028 | degree node ordering via packed keys | coarsening 0.992 | discard (below floor) |
| 030 | open-addressing index in the bucket queue | multitry 1.007 | discard (A/B gain not reproduced) |

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
- **Fixes for one graph family inside the hottest function.** A hint that removed hub scans gave -10% on a web graph, but
  d_multitry rose 1 to 3% on 17 of 20 graphs where the new branch was never taken (code size and layout in the k-way move
  path). Four variants of the same idea all showed it; stop after two A/B rounds.
- **Below about 2%, component timers are noise.** Phase timers of untouched components moved by +-2% between runs, so a
  component gain must be clearly larger than that, and the overall metric must still clear the floor.
- **Rewriting a latency-bound loop.** The k-way gain loop over raw arrays was 0.7% slower: the compiler already hoisted the
  loads, and the time is in dependent partition loads and unpredictable tie branches.
- **Micro-optimising the label-propagation inner loop** (raw pointers, hoisted flags): only about 3%. The loop is bound by
  random memory access, not by instructions.
- **Removing the cached hash code** (`noexcept` hash functors) keeps the order but gained only 0.6%; the cost of the iterated
  maps is the chain walk and the modulo, not the node size.
- **Trusting a 7-job A/B for small gains.** An open-addressing index in the FM bucket queue showed 0.967 on one job in
  the A/B and 1.017 on the same job in the full run; gains under about 3% in the A/B need the full run before they count.
- **Array-based queues in push-relabel** (instead of `std::queue`) were neutral: the queues are not where the time goes.

## Environment

C++11/GCC 13, Release with KaHIP's default flags (no flag changes allowed), single-threaded, 16-core x86 machine with one job
per physical core, graphs of up to a few million edges.

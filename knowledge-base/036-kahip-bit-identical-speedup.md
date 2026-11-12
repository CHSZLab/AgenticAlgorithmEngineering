# Speeding up a mature multilevel graph partitioner with bit-identical or quality-preserving output (KaHIP kaffpa)

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

12. **Look for work whose result is discarded, not for constant factors.** After six micro-changes in a row were neutral
   (0.997 to 1.031), a cost-center review asked, per configuration, which work is redundant (recomputed, rebuilt, or thrown
   away). Instrumenting the flow refinement showed that 99.6% of max-flow solves end with a cut equal to the current one, after
   which the caller undoes everything. The max flow is bounded by the capacity U of the edges between the two flow regions; when
   U equals the current cut, push-relabel can stop the moment the sink has received U and skip the source-set search. Exact for
   the configurations without most-balanced cuts (no random draws in that path): flow time -15% (eco) and -21% (esocial),
   whole benchmark -1.4% geomean. Where equal cuts with better balance are accepted (most-balanced cuts), the same shortcut is
   not exact.
13. **Reuse a pointer the previous lookup already produced.** The boundary update looked up the block pair twice per edge
   (once inside the node-set update, once for the edge cut); keeping the pair entry from the first lookup cut quotient-graph
   refinement by 3.6% and k-way FM by 5%. Fusing a counting pass with the construction pass of the flow network (one scan of
   each region node instead of two) cut flow time by 4%.
14. **Watch for k*k structures built with a large k.** A flat block-pair index of size k*k sped up the boundary lookups,
   but the same class is also constructed during contraction with k = number of coarse nodes, which made one job 37% slower
   (quadratic memory fill). Allocating the index lazily on first use and only for k <= 1024 kept the gain (-2%).
15. **When bit-identity is relaxed to "same quality", drop work that only feeds random draws.** Later in the session the owner
   allowed changes that alter random decisions if the geometric mean cut over three seeds stays within 0.1% of the original
   (plus balance and no crashes). Three changes then paid: an array-plus-position-index boundary set instead of an iterated
   `unordered_map` (quotient-graph refinement -12%, eco -20%); no gain computation for k-way neighbors that are already moved and
   no longer queued (their gains were computed only so the tie-breaking draws stayed in sync; multitry -10%); and a per-round
   incremental connectivity cache (block, weight) per node, updated on each move, for nodes of degree >= 32 (multitry -3%
   overall, -50 to -75% on social graphs). Quality ratios stayed at 0.9998 to 0.9999.
16. **Per-instance state in an object created per local search costs O(n) per search.** The first version of that cache resized
   an n-sized header array in each refinement core, and the core is constructed once per localized search; road graphs became
   7% slower with identical output. A static store with a global round stamp (never reset, so stale entries from other levels
   can never match) removed it.
17. **Defer a side structure that the search never reads, and replay only the kept moves.** In both the k-way and the 2-way
   FM search every tentative move updated the block-pair boundary sets, and every move rolled back after the best prefix
   updated them again; the searches themselves only read block weights and counts. Undoing the tail by resetting partition and
   weights only, then rolling the kept prefix back and replaying it in order through the same boundary updates, cut multitry
   time by 36% (total -10%) and 2-way refinement on the eco/esocial configs by 43 to 50% (total -11%). A debug build checked,
   every 20th to 50th search, that every cut-edge endpoint is in its pair boundary and every pair cut equals the real cut. The
   boundary order changes, so this is a quality-rule change; the cut ratio went from 1.00049 to 0.99929.
18. **Visit only nodes whose neighborhood changed in label propagation.** A per-node active flag (cleared on visit, set for all
   neighbors when a node changes cluster) plus a stop when an iteration changes nothing cut coarsening of the social configs by
   30% (quality rule, cut ratio 0.9998). Re-activating undecided or size-blocked nodes as well made it slower and worse.
19. **Move deterministic per-graph work out of repetition loops.** The clustering ensemble runs up to 18 label propagations on
   the same graph and sorted the nodes by degree in every run; sorting once per ensemble and numbering clusters through an
   array instead of an `unordered_map` cut ssocial coarsening by 15% with identical output.
20. **Per-search hash maps over node ids can be a pooled stamped array.** The moved-node table and the heap's node-to-slot index
   were open-addressing maps created per local search (grown from 32 slots each time). A per-node array with a generation
   stamp, taken from a pool of four stores (two FM heaps and a moved table can be alive at once; a hash map is the fallback when
   the pool is empty), made creation O(1) and lookups direct: multitry -19%, quality-graph refinement -11%, identical output,
   peak memory +70 MB on the 2.2M-node graph. Together with keeping the push-relabel discharge's distance and excess in locals
   (stores through edge records forced reloads; flow -4%) this gave total -7%.

21. **Measure where an algorithm's work goes, not just which lines are hot.** Counting push-relabel discharges after the last
   change of the sink's excess showed that 35 to 67% of them (road and social stripes) only returned excess to the source:
   KaHIP's single-phase FIFO lets nodes with label >= n creep upward one relabel at a time. A textbook two-phase solver (maximum
   preflow on labels < n, then excess return with labels n + exact distance to the source) cut flow time by 12.5% and total
   time by 5.6%. A line profile had only shown "discharge" and "global relabeling" as hot.
22. **The minimal source side is the same for every maximum flow; use that to change solvers exactly.** When the caller only
   uses the set of nodes reachable from the source in the residual graph (KaHIP without most-balanced cuts), any correct
   maximum-flow algorithm gives bit-identical output. Even the second phase can go: on the reversed network a maximum preflow
   from the original sink already fixes the cut closest to its sink, and the nodes that can reach the original source there
   are exactly that set. Where the caller reads the flow itself (most-balanced cuts from residual SCCs), a different maximum
   flow is a quality-rule change; here it passed at cut ratio 0.99944.
23. **Check that the profiler records full stacks before trusting inclusive shares.** The LD_PRELOAD sampler had its backtrace
   depth fixed at 8 frames, so inside deep recursion (w-cycles plus recursive bisection in initial partitioning) the outer
   frames were missing: initial partitioning showed 12% of samples while its timer said 53% of the run. Leaf shares were
   right; inclusive shares of outer frames were not.

24. **Try a different max-flow algorithm in place, on the real flow problems.** Flow refinement solves many small,
   shallow problems (a stripe around the cut between two big terminals). Boykov-Kolmogorov, with search trees grown from both
   terminals and reused across augmentations, beat the tuned two-phase push-relabel by 17% on whole runs (d_flow 0.58x with
   the next item). The source tree at termination is exactly the set reachable from the source in the residual graph, so callers
   that use only the minimal source side stay bit-identical; most-balanced cuts read the flow and become a quality-rule change.
25. **Model an undirected edge as one edge pair with capacity w both ways.** Two directed edges with zero-capacity partners
   (4 residual edges) become one pair (2 residual edges). For the residual relation used by most-balanced cuts, "f1 < w or
   f2 > 0" over the old pair equals "net f < w" over the new one, so only edge multiplicities change.
26. **Filter before sorting.** The gpa matching permuted and sorted all 2m directed edges and then skipped the ones the grow loop
   cannot use (back direction, rating 0, weight bound). Filtering first halves the sort and needs fewer random draws; the order
   of the usable edges changes with the tie-break draws, so it is a quality-rule change (coarsening 0.59x on strong).
27. **Memoize a quadratic check while its inputs are frozen.** Applying a flow cut updated the boundary per stripe node and per
   neighbor in another block by rescanning that neighbor's adjacency for a neighbor in the old block (deg x deg on hubs; 18% of
   a web-graph run). The partition does not change during the apply loop, so the answer per (node, block) can be cached with a
   stamp for the batch: identical output, one web graph 3.1x faster, total -1.9%. The shortcut "update only moved nodes" was not
   identical: the calls for unmoved nodes also clean up boundary entries.

28. **Put what one lookup reads into one cache line.** A stamped per-node map kept stamps and values in two arrays, and label
   propagation kept the vote counter and the cluster size in two; each lookup touched two random lines. One array of
   {stamp, value} and one of {votes, size} gave -1.1% total (coarsening 0.97x) with identical output. The binary heap without
   its separate element array (entries {key, node}, a stamped map to the heap position, hole-based sifts with the same
   comparisons, so equal keys end at the same positions) gave -1.8% total (multitry 0.956x).
29. **The same std::sort over a smaller, self-contained element type.** std::sort's steps depend only on comparison results, so
   sorting (degree, node) entries with a comparator on the degree gives the same order as sorting node ids with a comparator
   that reads two degrees from the graph: identical output, 1% on social configurations. The same idea was neutral 30
   experiments earlier; it paid once the label propagation around it had become faster.

30. **Profile the configurations with the worst ratio, not the largest jobs.** With a geomean over jobs, the small jobs of
   the fast configurations set the metric. Their profile showed costs outside the partitioner proper: the final cut, boundary
   and communication-volume report in three graph passes (one pass: -1.2% geomean, identical stdout) and zero-filling of
   memory that is overwritten anyway.
31. **Do not zero what is about to be written.** basicGraph value-initialized m edges and m edge ratings in start_construction,
   and contraction sizes them by the finer graph's m and trims later. A default-init allocator for the two edge arrays, with
   new_edge writing the zero weight and rating itself, keeps every created edge identical and never touches the trimmed tail
   (fast 0.93 to 0.97 on small jobs); the same for the graph-file and partition-output buffers. Together -1.2% geomean.

32. **Lay the data out in visiting order when the same sweep repeats over the same graph.** ssocial coarsening intersects up
   to 18 label-propagation clusterings per level, each a 10-iteration sweep in the same degree order. A copy of the graph
   stored in that order, built once per level and shared by all clusterings, makes the node and edge reads sequential. The
   cluster labels become positions; they are only compared for equality and renumbered by first occurrence in node order, so
   the output stays identical. 3-seed A/B 0.923 on ssocial jobs (web-Google 0.82), -3.5% total together with two
   passengers. Five earlier prefetch variants on the scattered layout had only hidden the latency.
33. **Price a parameter reduction per bucket, then keep the cheap buckets (rule b).** Halving the number of ensemble
   clusterings for every k passed the gate exactly at the threshold (Q 1.00100) and broke the per-configuration guard
   (ssocial 1.0051). The same gate data per k bucket showed where the quality went: k=8 cost 0.9% for little time, k=2 cost
   0.17% for a 2x to 5x speedup (fewer clusterings give coarser intersections and far fewer levels). Keeping only k < 8 (Q
   1.00050) and then k >= 32 (Q 1.00078) took -8% total; a 6-seed check on the final binary (Q 1.00030, all configurations
   within 0.35%) covered the bias of choosing buckets from gate data. Measure where the search ends before cutting a search
   limit: 95 to 99% of the localized multitry calls stop after their first round, so the round limit is not a lever.

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
| 029 | cluster-id remap via array | coarsening 0.994 | discard (below floor) |
| 030 | open-addressing index in the bucket queue | multitry 1.007 | discard (A/B gain not reproduced) |
| 031 | edge cut through the already looked-up block-pair entry | 0.6838 (total 0.6989, with 029) | keep |
| 032 | two-entry block-pair cache | A/B 0.997 | discard |
| 033 | one scan per flow-region node (edges and outer-boundary flag) | **0.6849** (total 0.6964) | keep |
| 034 | quotient graph via counting sort | A/B 1.001 | discard |
| 035 | open-addressing start-node dedup sets | A/B 1.004 | discard |
| 036 | label-propagation prefetch one stage deeper | A/B 1.031 (slower) | discard |
| 037 | reverse capacity stored on each flow edge | A/B 0.999 | discard |
| 038 | reuse start-node gains in the k-way queue setup (replay tie draws) | 0.6845 (total 0.6923; k-way FM 0.976) | discard (below floor) |
| 039 | 038 plus gain cache across searches (version stamps) | A/B 0.994 to 1.012 | discard |
| 040 | stop push-relabel when the sink holds the region-cut capacity equal to the current cut | **0.6752** (total 0.6879) | keep |
| 041 | lazy flat k*k block-pair index (k <= 1024) | 0.6723 (total 0.6817) | carried (below floor alone) |
| 042 | 041 + 038 (start-node gains reused) | **0.6694** (total 0.6748) | keep |
| 043-045 | residual back-edge count once per node, weighted degrees once, dense flow node map | **0.6643** (total 0.6613) | keep |
| 046 | (quality rule) boundary set as array + position index | **0.6327** (total 0.6047), cut ratio 0.99986 | keep |
| 047 | (quality rule) no gains for moved, unqueued k-way neighbors; no tie replay | **0.6279** (total 0.5844), cut ratio 0.99981 | keep |
| 048 | (quality rule) incremental gain cache for all nodes, per-instance arrays | 0.6261 (total 0.6017) | discard (roads 1.2 to 1.3x) |
| 049 | 048 with a degree >= 32 gate and a shared static store | **0.6245** (total 0.5783), cut ratio 0.99978 | keep |
| 050 | 049 without the gate | 0.6247 (total 0.5834) | discard (meshes gain, roads lose) |
| 051 | (quality rule) active-node label propagation | **0.5929** (total 0.5722), cut ratio 0.99980 | keep |
| 052 | 051 plus re-activation of undecided nodes | 0.6210 (total 0.5752), cut ratio 1.00079 | discard |
| 053 | (quality rule) k-way rounds: boundaries updated only for kept moves | **0.5739** (total 0.5140), cut ratio 1.00049 | keep |
| 054 | (quality rule) 2-way FM: boundaries updated only for kept moves | **0.5152** (total 0.4562), cut ratio 0.99929 | keep |
| 055 | degree order once per clustering ensemble, array cluster-id remap | **0.5060** (total 0.4447), identical | keep |
| 056 | degree sort on packed (degree, node) keys | A/B 1.004 | discard |
| 057-060 | pooled stamped per-node maps (moved table, heap index), push-relabel discharge with locals | **0.4819** (total 0.4124), identical | keep |

| 061-063 | counting buckets for the cluster-contraction quotient graph, flow-graph buffers reused across flow problems | **0.4769** (total 0.4077), identical | keep |
| 062 | 24-byte flow edges with the partner's capacity (global relabeling without the partner read) | A/B 0.988, same as 061 alone | discard |
| 065 | gpa matching: grow paths over the sorted (rating, edge) pairs | A/B no gain | discard |
| 064-067 | two-phase push-relabel (quality rule for most-balanced cuts), node-state record, k-way neighbor prefetch | **0.4637** (total 0.3850), cut ratio 0.99944 | keep |
| 068-070 | no phase 2 without most-balanced cuts (reversed preflow), pooled solver buffers, stamped start-node sets | **0.4571** (total 0.3771), identical | keep |
| 071-073 | Boykov-Kolmogorov max flow, one edge pair per undirected stripe edge, no unused source set | **0.4219** (total 0.3222), cut ratio 0.99932 | keep |
| 074 | SCC stacks on std::vector instead of std::deque | A/B 1.004 | discard |
| 075-077 | gpa: filter usable edges before permute and sort (quality rule), prefetched random permutation, grow-loop prefetch | **0.4055** (total 0.3133), cut ratio 1.00045 (six seeds 0.99988) | keep |
| 078 | memoized neighbor-in-block test while applying a flow cut | **0.4025** (total 0.3075), identical | keep |
| 079-080 | more prefetches in the k-way move and label-propagation loops | A/B 1.007 and 1.014 | discard |
| 081-082 | BK: reverse residual read from the edge itself for symmetric stripe pairs; heap without element array | **0.3965** (total 0.3020), identical | keep |
| 083 | stripe membership bitmap in the flow-graph build | A/B 1.002 | discard |
| 084-085 | {votes, size} cluster slots in label propagation, {stamp, value} slots in stamped maps | **0.3927** (total 0.2986), identical | keep |
| 086, 090 | k-way and 2-way FM moves templated on the queue type (no virtual calls on the heap) | A/B 0.998 each | carried |
| 087 | label-propagation active flags as a bitset over visiting positions | A/B 0.998 | discard |
| 088 | degree sort over (degree, node) entries, same comparisons | A/B 0.989 | carried |
| 089 | two-stage prefetch in label propagation (repeat of a recorded negative) | A/B 1.039 | discard |
| 086-090 | full run of the three exact passengers | 0.3897 (total 0.2962), identical, below the 1% floor | carried |
| 091-092 | quotient graph of a clustering and extracted blocks built with their real edge counts (with 086-090) | **0.3842** (total 0.2939), identical | keep |
| 093 | matching contraction: coarse edges collected first, real edge count | A/B 1.020 | discard |
| 094 | final cut, boundary nodes and max communication volume in one pass | **0.3797** (total 0.2933), identical | keep |
| 095 | cache of degree orders keyed by the verified degree sequence | A/B 0.998 | discard |
| 096, 098 | graph edge arrays and IO buffers not zeroed before they are written | **0.3752** (total 0.2920), identical | keep |
| 097 | matching contraction without the precomputed coarse-target array | A/B 1.009 | discard |
| 099 | label-propagation prefetch only for the next node if active | A/B 1.001 | discard |
| 100 | cluster contraction builds the quotient graph from the coarse mapping directly | A/B 0.997 | carried |
| 101 | random matching built without zero fill (reserve + push_back) | A/B 1.000 | discard |
| 102 | one boundary insert per (node, target block) instead of per cut edge | A/B 1.003 | discard |
| 103 | exact replay of recorded gain events for hub nodes in the multitry start-node scan | A/B 1.038 | discard |
| 104 | most balanced minimum cut on arrays from the flow graph, vector-stack SCC, bucketed components | A/B 0.996 | carried |
| 105 | ensemble label propagation on a copy of the graph in visiting order (with 100, 104) | **0.3712** (total 0.2818), identical | keep |
| 106 | parameter reduction: ensemble clusterings halved for every k | gate Q 1.00100, ssocial 1.0051 over the guard | discard |
| 107 | parameter reduction: ssocial label-propagation iterations 10 to 5 | screen Q +0.6%, time 0.96 | discard |
| 108 | parameter reduction: 9 ensemble clusterings for k < 8 (were 18, 17) | **0.3657** (total 0.2738), Q 1.00050 | keep |
| 109 | parameter reduction: 2 ensemble clusterings for k >= 32 (were 3) | **0.3601** (total 0.2588), Q 1.00078, 6-seed 1.00030 | keep |
| 110 | parameter reduction: strong multitry search limit alpha 10 to 5 | screen Q +0.15%, time 0.95 to 0.97 | discard |
Every kept step: 0 incorrect of 537 jobs; bit-identical steps also crosscheck OK on 864 runs, quality-rule steps passed the
three-seed cut gate (A/A noise sd 0.0011).

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
- **Deeper software prefetch.** Adding a second prefetch stage in the label-propagation sweep (cluster ids two nodes ahead,
  the cluster weights one ahead) was 3% slower: the extra loops over up to 32 edges cost more than the misses they hide.
- **Caching gains across local searches.** A per-node version stamp (bumped for a moved node and all its neighbors) to reuse
  gain computations across consecutive k-way searches almost never hit: the hubs that dominate the cost have a neighbor move
  in nearly every search, and the stamping slowed the move loop.
- **Caching repeated flow problems.** Consecutive flow iterations on the same block pair never had identical regions (the
  region search starts from randomly permuted boundary nodes), so there was nothing to cache; the waste was in the solve itself.

- **Cache-everything for a per-node quantity that is read about once.** The incremental gain cache gave 0.84 to 0.86 multitry
  time on FE meshes but 1.06 to 1.10 on road graphs (degree about 2.5): each node is queried about once per round, so the
  build plus the per-move updates are pure overhead. A three-seed A/B on five jobs (two FE meshes, one road) predicted 0.963
  and the full run gave 1.005; pick A/B jobs per graph class in proportion to the benchmark.
- **Single-seed A/B under the quality rule.** Once random decisions may change, one seed of one job can be 1.2x slower or
  faster from a different trajectory alone (144 strong 64: 1.21 on seed 1, 0.90 on seeds 2 and 3). Sum several seeds.
- **Keeping more nodes active in label propagation to buy back quality.** Re-flagging nodes whose vote was tied or blocked by
  the size bound kept most nodes active (coarsening 1.21x) and the cut ratio got worse (ssocial 1.0047 to 1.0058), not better.
- **Packing the sort key next to the node id for a degree sort** gave nothing (A/B 1.004): one sort of n entries per level is
  cheap next to the label propagation that follows; the same trick did pay for the edge-rating sort earlier (2m entries).
- **Reading per-config cut ratios from three seeds.** After 053 the eco ratio moved from 0.9998 to 1.0039; seeds 4 to 6 gave
  0.9938 and six seeds 0.9992. Per-config ratios over three seeds swing by about +-0.4%.
- **Compacting the residual edges to give global relabeling the partner's capacity locally** (24 instead of 32 bytes, no
  partner read per scanned edge) gained nothing on top of the other changes (A/B 0.988 either way).
- **Small prefetches and carried-over sort keys in coarsening matching** (gpa grow loop over the sorted pairs, prefetch of
  neighbor adjacencies in the k-way gain update) gave 0 to 0.5% each: below the 1% floor, only worth carrying as passengers.
- **More software prefetch in loops that already have some.** Prefetching partition entries, heap slots and stamps of the
  first 32 neighbors in the k-way move, and cluster ids 16 edges ahead in label propagation for high-degree nodes, were both
  slower (1-seed A/B 1.007 and 1.014 cumulative, 7 of 8 jobs worse): the hardware prefetcher or the existing per-node prefetch
  already covers these accesses.
- **Plain std::vector instead of std::deque for SCC stacks** gave nothing (A/B 1.004); the SCC is a small part of the flow time.
- **Skipping inactive nodes word-wise in label propagation.** With 66% of scanned positions inactive, a bitset over visiting
  positions (with a node-to-position map) skips them without touching the node, but finding the next three active positions for
  the prefetches cost as much as the skipped tests (A/B 0.998).
- **Re-trying a recorded negative.** A two-stage prefetch in label propagation (cluster ids two nodes ahead, cluster slots one
  ahead) was 3.9% slower, as this entry already said for the same idea; read the negatives list before starting an idea.
- **A stripe-membership bitmap in the flow-graph build** (n bits instead of the partition array) was neutral (A/B 1.002): the
  cost on hub nodes is the edge stream itself, not the partition lookups.
- **Restructuring the matching contraction.** Collecting coarse edges first to build with the real edge count (A/B 1.020)
  and reading coarse targets inside the visit loop instead of a precomputed m-sized array (A/B 1.009) were both slower: the
  separate sequential pass hides latency that the dependent load in the loop exposes. Removing the zero fill around it paid.
- **Caching degree orders across calls** (keyed by the full degree sequence, verified on reuse) was neutral (A/B 0.998): the
  repeated sorts are not on identical graphs often enough.
- **Replaying recorded gain events for hub nodes** in the multitry start-node scan (exact, A/B 1.038): one of a hub's many
  neighbors moves in almost every round, so the recorded events are invalidated before reuse and recording is extra cost.
- **Removing per-job fixed costs below 0.5%** (zero fill of two n-sized arrays in the random matching, one boundary insert per
  node and block): all at 1.000 +- 0.003; the total is set by the large jobs.
- **Cutting the label-propagation iterations or the multitry search limit** under rule (b): 4 to 5% faster on the affected
  configurations for 0.15 to 0.6% of cut, far fewer seconds per unit of quality than the clustering count.

## Environment

C++11/GCC 13, Release with KaHIP's default flags (no flag changes allowed), single-threaded, 16-core x86 machine with one job
per physical core, graphs of up to a few million edges.

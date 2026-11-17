# Speeding up a distributed (MPI) multilevel graph partitioner with bit-identical output

## Problem

Make ParHIP, the MPI graph partitioner of KaHIP (multilevel: label propagation (LP) coarsening,
distributed contraction, evolutionary initial partitioning on the coarsest graph, projection and LP
refinement), faster while every partition file stays byte-identical to the original for the same
graph, k, preset, seed and number of processes. Metric: shifted geometric mean of per-job ratios of
the whole mpirun wall time (reading the graph and writing the partition included) over 180 jobs on
20 graphs (social, web and mesh, 0.3M to 23M nodes), k = 8 and 64, 1 to 32 processes, fast,
ultrafast and eco presets.

## What Worked

Chained over nine benchmark rounds (20 experiments): **0.624 of the original wall time (1.60x)**,
every partition identical (seed 1 in every timed run, seed 2 checked separately after each keep).

1. **Per-phase timers first, then one hypothesis per phase per run.** A small RAII timer per phase
   (io, coarsening LP, contraction, initial partitioning, projection, refinement LP, ghost exchange,
   write), reduced to max and mean over ranks and printed by rank 0, costs nothing measurable and
   lets several independent changes (one per phase, one commit each) share one 30-minute benchmark
   run. Each change is judged by its own phase. Cross-cutting changes (shared data structures,
   allocator) are run alone.
2. **Output writing was 12% of total wall time.** The text partition was written with one
   `std::endl` (flush, so one write system call) per node, process after process behind a barrier
   chain. Formatting each process's labels into one buffer and writing it once, with the same barrier
   chain, took the write phase from 109 s to 0.7 s (25% of total time at 32 processes).
3. **Evaluate side-effect-free conditions lazily in the LP edge loop.** The loop computed a size
   constraint (`getBlockSize`, a virtual call plus a hash lookup during coarsening) and other tests
   for every edge, although they only matter if the candidate block is an improvement. Testing
   `improvement` first and `continue` otherwise gave LP 16 to 19% faster and 8% overall. The
   random tie-breaking draw must stay exactly where it was (it is consumed whenever the weight ties
   the current maximum), otherwise the output changes.
4. **Replace std::unordered_map where order is never observed.** Coarsening block weights per
   cluster id, the LP neighbor-weight map, the label mapping and coarse node weights in contraction,
   and the global-to-local ghost id map: all are pure lookup tables (or iterated where the order is
   irrelevant: request lists whose replies are index-aligned, additive weight messages). Open
   addressing with a power-of-two table, multiplicative hash and a vector of used slots gives
   identical values. A missing key must behave like the original (weight 0).
5. **Keep the maps whose iteration order defines the output.** The contraction's hashed edge map is
   iterated to build the coarse graph, so its iteration order fixes the coarse edge order and with it
   every later LP decision. It was left unchanged (no `reserve()`, no hash change).
6. **Parse text input by hand.** mmap, memchr for line ends and a hand-written strtol-equivalent
   into flat arrays (io phase 0.76); every process still scans the file to its first line.
7. **Projection grouping by sort.** Sorting (coarse node, fine node) pairs and grouping replaces an
   unordered_map of vectors and keeps the message and update order (project 0.91).
8. **Stamp arrays instead of reset scans.** Two places scanned a node's edges a second time only to
   reset per-PE "already sent" flags: `addLabel` (called on every label change of an interface node,
   in both LP phases and in projection) and the contraction's ghost mapping. A per-PE mark that holds
   a per-call counter (or node + 1 where each node is visited once) removes the second scan and sends
   the same entries in the same order. `addLabel` alone: coarsen LP 0.97, ghost exchange 0.95,
   projection 0.88, refinement 0.97, overall 0.985. Use a counter, not the node id, where the same
   node can be processed twice.
9. **Skip work that provably does nothing.** The global ghost update after each projection scanned
   all local nodes; only interface nodes can have ghost neighbors (projection 0.93 total, 0.79
   geomean). One lookup per LP edge instead of read, add and re-read (coarsen LP 0.96). Reserving the
   local edge array at the average share 2m/p before reading (io 0.94).
10. **Prefetch in the LP edge loop.** `__builtin_prefetch` of the target's node data eight edges
   ahead: coarsening LP 0.95 total, up to 11% faster overall on the largest graphs, up to 4% slower on
   small ones (net geomean 0.998). A prefetch never changes a value.

### Keep rule for multi-component runs

Judge each component commit by its own phase, not by the overall geomean against a fixed threshold:
keep it if (1) its phase improves beyond that phase's run-to-run noise, (2) the overall time is not
worse beyond noise, (3) the output is identical, and (4) the code is not disproportionately complex
for the gain. A phase that is 5% of the run can improve by 20% and still move the overall geomean by
only 0.3%; with a fixed overall threshold such clean wins (here: the interface-only ghost update) are
lost. Measure the per-phase noise as the largest deviation from 1 when the same binary is measured in
two separate runs (instrumented builds; we used four such pairs of full runs). Worst A/A deviations
(phase total / geomean of per-job phase ratios), full set of 180 jobs:

| wall | coarsen LP | ghost exchange | contraction | io | initial part. | projection | refinement LP |
|---|---|---|---|---|---|---|---|
| 0.2% / 0.8% | 0.2% / 0.8% | 0.5% / 1.6% | 0.2% / 0.7% | 0.1% / 0.4% | 0.9% / 1.0% | 0.2% / 0.4% | 0.2% / 1.2% |

On the 29-job quick set the bands are 2 to 4 times wider (0.4% to 1.4% total, 0.9% to 3.3%
geomean), so a screen only selects candidates and a full run decides. When two commits of one batch
can touch the same phase, run three binaries (control, first commit, both) in one alternating run.

## Experiment Data

| Round | Change (phase) | Phase ratio | Full geomean | Verdict |
|---|---|---|---|---|
| 1 | buffered writer (write); block weight map (coarsen LP); mmap reader (io) | 0.006; 0.76; 0.76 | 0.738 | keep all |
| 2 | LP neighbor map; projection sort grouping; contraction maps | 0.97; 0.91; 0.94 | 0.972 | keep all |
| 3 | ghost id open-addressing map plus binary search for the owner PE (cross-cutting) | io 0.92, comm 0.93 | 0.983 | keep |
| 4 | small-block allocator for operator new (cross-cutting) | contract 0.96 | 0.995 (quick) | discard |
| 5 | LP lazy size constraint; contraction flat adjacency | 0.84/0.81; 0.99 | 0.921 | keep; discard |
| 6 | LP one map access per edge; refinement touched-entry reset | 0.96; 1.035 | 0.986 (first alone) | keep; discard |
| 7 | packed-key degree sort; interface-only global ghost update | refine 1.14; project 0.93 | 0.998 (second alone) | discard; keep (per-component rule) |
| 8 | reused receive buffer; reader reserve; contraction stamp | comm 0.99 (gm 1.00); io 0.94; contract 0.98 | 0.994 | discard; keep; keep |
| 9 | addLabel stamp; LP prefetch | see 8. and 10. above | 0.985; 0.998 | keep; keep |

Noise between two passes of the original: geomean drift 0.4%, per-job sd of log ratio 0.027.
Per-phase noise: see the keep rule above.

## What Didn't Work

- A small-block allocator replacing global new/delete (worked for sequential KaHIP) gave only 0.5%
  here: after the hash maps were replaced, ParHIP's allocations are mostly large vectors.
- Turning the contraction's vector-of-vectors adjacency into a flat array changed contraction by
  only 1%; the order-defining hash maps dominate that phase.
- Sorting nodes by degree on packed (degree << 32 | node) keys gives the same permutation (same
  comparison results) but was slower: the per-call key vector and two copy passes cost more than the
  cheaper comparisons (refinement 1.14x slower).
- Resetting only the touched entries of the refinement LP's k-entry weight array (k = 64) was slower
  (1.035) than clearing all k entries.
- Reusing one receive buffer in the ghost exchange: no gain beyond noise; the small, short-lived
  vectors are cheap for glibc malloc.
- valgrind/callgrind failed (illegal instruction) on the `-march=native` build; a separate
  profiling-only build without native flags was needed.

## Code Example

```cpp
// LP edge loop: draw the tie-break exactly as before, then test cheap conditions first
bool improvement = cur_value > max_value;
improvement |= cur_value == max_value && random_functions::nextBool();
if (!improvement) continue;                       // nothing below has side effects
bool cycle = !config.vcycle || G.getSecondPartitionIndex(node) == G.getSecondPartitionIndex(target);
bool balancing = own_block_balanced || cur_block != old_block;
if (!(cycle && balancing)) continue;
if (cur_block == old_block || G.getBlockSize(cur_block) + node_weight <= cluster_upperbound) {
        max_value = cur_value; max_block = cur_block;
}
```

## Environment

C++ (GCC 13, -O3 -march=native), Open MPI 5, one process per core, Intel Xeon w5-3435X
(16 cores / 32 threads). Graphs from SNAP, DIMACS 10 and the Florida collection (METIS text).

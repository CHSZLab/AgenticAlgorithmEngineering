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

Chained over five benchmark rounds: **0.650 of the original wall time (1.54x)**, every partition
identical (seed 1 in every timed run, seed 2 checked separately).

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

## Experiment Data

| Round | Change (phase) | Phase ratio | Full geomean | Verdict |
|---|---|---|---|---|
| 1 | buffered writer (write); block weight map (coarsen LP); mmap reader (io) | 0.006; 0.76; 0.76 | 0.738 | keep all |
| 2 | LP neighbor map; projection sort grouping; contraction maps | 0.97; 0.91; 0.94 | 0.972 | keep all |
| 3 | ghost id open-addressing map plus binary search for the owner PE (cross-cutting) | io 0.92, comm 0.93 | 0.983 | keep |
| 4 | small-block allocator for operator new (cross-cutting) | contract 0.96 | 0.995 (quick) | discard |
| 5 | LP lazy size constraint; contraction flat adjacency | 0.84/0.81; 0.99 | 0.921 | keep; discard |

Noise between two passes of the original: geomean drift 0.4%, per-job sd of log ratio 0.027.

## What Didn't Work

- A small-block allocator replacing global new/delete (worked for sequential KaHIP) gave only 0.5%
  here: after the hash maps were replaced, ParHIP's allocations are mostly large vectors.
- Turning the contraction's vector-of-vectors adjacency into a flat array changed contraction by
  only 1%; the order-defining hash maps dominate that phase.
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

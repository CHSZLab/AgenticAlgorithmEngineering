# Speeding up a distributed (MPI) multilevel graph partitioner with bit-identical output

## Problem

Make ParHIP, the MPI graph partitioner of KaHIP (multilevel: label propagation (LP) coarsening,
distributed contraction, evolutionary initial partitioning on the coarsest graph, projection and LP
refinement), faster while every partition file stays byte-identical to the original for the same
graph, k, preset, seed and number of processes. Benchmark: 180 jobs on 20 graphs (social, web and mesh, 0.3M to
23M nodes), k = 8 and 64, 1 to 32 processes, fast, ultrafast and eco presets. Metric up to experiment
029: shifted geometric mean of per-job ratios of the whole mpirun wall time (reading the graph and
writing the partition included). From experiment 030 on (owner's decision): ParHIP's own "total
partitioning time" (part, shift 0.01 s) as primary and its IO time as second headline; the wall time
only as a check.

## What Worked

After 29 benchmark rounds (49 experiments, 29 kept, 19 discarded): **part time about 0.62 of the original
(1.61x), IO time 0.565 (1.77x)**, every partition identical (seed 1 in every
timed run, seed 2 checked separately after each keep, from experiment 030 on also clang + libstdc++
builds). Up to round 14 the decisions used the wall time (chained 0.609); the trajectory was later
recomputed on part directly against the stored master medians.

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
11. **Devirtualize both implementations or neither.** Block weights are accessed through a virtual
   base with one implementation for coarsening and one for refinement. Keeping a typed pointer to
   each and calling `ptr->Concrete::getBlockSize(b)` (qualified, so non-virtual and inlinable) behind
   one null test gave coarsen LP 0.99, refinement LP 0.98, ghost exchange 0.99, overall 0.991. A
   first version that devirtualized only the coarsening path (typed pointer or virtual fallback) made
   refinement 8% slower: the extra branch plus the remaining virtual call cost more than it saved.
12. **A pool allocator for one container type, not for the program.** The contraction's hashed edge
   map (`std::unordered_map`, iteration order defines the output) allocates one node per coarse edge.
   A stateless allocator for this one map (single nodes from a free list in 64 KiB chunks, bucket
   arrays from operator new) gave contraction 0.979 total and 0.944 geomean, overall 0.992, peak memory
   slightly lower. Iteration order of `std::unordered_map` depends on hash and insertion order, not on
   node addresses, so the output is unchanged. The global new/delete replacement of round 4 had
   reached a similar contraction gain but was rejected as too invasive for a 4% gain in one phase;
   the type-local form keeps the gain with one header and one typedef.
13. **More provably-empty work.** A per-call stamp also in the global ghost update (projection 0.90
   total, 0.94 geomean); returning early from the ghost block balance update when the label did not
   change (ghost exchange 0.96).

14. **Reproduce the iteration order of `std::unordered_map` instead of using it.** The coarse edge
   order is the iteration order of the contraction's hashed edge map. libstdc++ keeps one singly
   linked list: a new key goes to the front of its bucket's run if the bucket is occupied, else to the
   front of the list, and a rehash re-inserts the list in order with the same rule. So for an
   insertion sequence into B buckets the order is: bucket runs by first-use time descending, each run
   by insertion time descending, computed epoch by epoch with the container's own
   `std::__detail::_Prime_rehash_policy` (initial bucket count 1). An open-addressing array map plus a
   counting sort per rehash epoch gives the identical order: contraction 0.718 total (0.842 geomean),
   overall wall 0.963 / total 0.938, part 0.956 / total 0.929. Conditions for keeping such an emulation of library
   internals: a randomized equivalence test against the real container as a test target, a
   compile-time guard that enables it only for library releases on which the test ran (here
   libstdc++ 11, 13, 15 with g++ and clang++) and falls back to the container everywhere else, the
   identity check with a second compiler, and a gain of at least about 2% overall.
15. **Dense array for the locally owned part of a sparse key range.** Coarsening block ids are global
   node ids; most blocks seen by a process are its own nodes' ids. A dense array for the local id
   range in front of the hash map for the rest: coarsening LP 0.911 total (0.904 geomean).
16. **Find the first line of a process without scanning the prefix.** Each process counts the node
   lines starting in its own byte chunk of the file, one Allgather of the counts, and each process
   starts at the chunk holding its first node: IO 0.919 total (0.899 geomean).
17. **Small things that still count:** one reused receive buffer and an `MPI_Request` vector with one
   `MPI_Waitall` instead of a heap request per Isend (ghost exchange 0.988), and a linear scan over a
   16-entry inline array instead of the hash table for nodes of degree at most 16 in the LP
   (coarsening LP 0.987; the weight per label and every tie break stay the same).
18. **Prefetch the hash map slot of the lookups that integrate a received message.** The ghost
   exchange, which runs inside both LPs every few hundred nodes, looks up every received global id in
   an open-addressing ghost id map with a multiplicative hash, so each update of a large message
   waits for a cache miss. Prefetching the slot eight updates ahead: ghost exchange 0.929 total
   (0.966 geomean), and with it coarsening LP 0.969 and refinement LP 0.989, part 0.984 (0.980 at
   p = 16). The same trick in the contraction's label mapping: contraction 0.986. The exchange had
   been read as "waiting for slower processes" from a profile; part of it was this integration work.
   A prefetch changes no result, so it is the cheapest kind of change under a bit-identity
   constraint.

### Profiling a latency-bound loop

perf was not available; an `LD_PRELOAD` time sampler (ITIMER_PROF at 1 kHz, `backtrace`, symbolized
afterwards with `addr2line -i`) gave per-function and per-line shares with each job weighted equally.
It attributed 39% of the samples to the LP's hash table frames, yet replacing the table for small
degrees gained only 1.3%, and moving the labels into their own dense array gained nothing: in a loop
bound by a random load, samples land on the instruction that consumes the load (the hash of the
loaded label), not on the load. Before building on an inline-attributed share, test it with a cheap
change of the presumed cause.

### Code layout as a confound in per-phase judgments

A contraction change (038) gained 2% in its own phase and lost 3.7% in the refinement LP, whose
code it did not touch. The coarse graphs were bit-identical (hash of every level), the slowdown was
reproducible to 0.5% over 20 timed runs, and it came from a 16-byte move of the refinement
function: code linked earlier in the binary had changed size. A timed padding sweep (a dummy
function of 0, 16, 32 or 48 bytes in front of it) showed that the refinement LP is 1.18 to 1.33x
slower on single-process k = 64 jobs (1.02 to 1.06x for k = 8) when the function starts 48 bytes
past a 64-byte boundary, and equally fast at the other three offsets. So roughly one change in four
draws a large false penalty (or a false gain, when it leaves the slow offset) in a phase it does not
touch. Remedy: `__attribute__((aligned(64)))` on that one hot function, behind a macro that is
empty on other compilers; with it all four paddings measured the same, and the change itself was
neutral. Procedure when a phase whose code did not change moves beyond its band: compare the hot
functions' addresses modulo 64 in both binaries (`nm`), bisect the commit, and run a padding sweep
before judging. Untimed runs on a loaded machine are useless for this (they suggested a random,
stack-address effect; under exclusive the effect was strictly per binary). Retesting two earlier
refinement-side discards with the alignment fixed confirmed one of them as a real loss.

### Leaving fresh memory uninitialized, and checking it

The largest io gain of the later rounds came from not zero-filling the edge array before the graph
is built: an allocator whose default `construct` does nothing (`std::vector<Edge,
uninitialized_allocator<Edge>>`) makes `resize` leave new trivial elements uninitialized, and the
builder writes every entry once. io 0.848 total (0.871 geomean), peak memory 1445 to 912 MB. The
gain is a first-touch effect: the fill touched hundreds of MB of fresh pages ahead of the parser,
which then wrote them a second time. The same trick on short-lived, reused receive buffers gave
nothing measurable (glibc hands back pages that are already mapped), and on the much smaller node
array it lost more in the builder (a per-node branch) than it saved.

Two pitfalls. (1) `resize` keeps old entries, and a caller can depend on that: ParHIP rebuilds a
graph in place on top of an old one and later reads fields that the rebuild does not write. Zeroing
"fresh" entries in the builder must therefore zero only the entries beyond the previous size; the
first version zeroed all of them and changed the output (caught at once by the quick hash check).
(2) Bit-identical output on one machine cannot prove that no byte is read before it is written; a
latent read can pass here and differ elsewhere. Check with valgrind memcheck
(`--track-origins=yes`) on a build without `-march=native` (valgrind cannot decode AVX-512), at
p = 1 and p = 4, on social and mesh graphs, fast and deterministic eco presets. Run the p = 4 cases
a second time over TCP (`--mca pml ob1 --mca btl tcp,self`): data that crosses process boundaries
through shared memory is not checked, but bytes passed to `writev`/`sendto` are. Expect noise from
the MPI library itself (uninitialised bytes in Open MPI and PMIx headers, origin in libmpi,
libopen-pal or libpmix) and classify every error by its origin stack; here all 214 reported errors
in 72 rank logs were of that kind, with 0 invalid accesses and 0 uses of uninitialised values
originating in ParHIP allocations.

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
| 10 | std::fill to clear the refinement weight array | refine 0.994 (gm 0.987) | 1.000 (quick) | discard (inside quick noise) |
| 11 | global ghost update stamp; skip unchanged ghost balance | project 0.90; comm 0.96 | 0.993 (both) | keep; keep |
| 12 | newline-sentinel number parser in the reader | io 0.99 | 1.001 (quick) | discard (inside quick noise) |
| 13 | coarsening-only devirtualization; both balance types devirtualized | refine 1.08; see 11. above | 1.007; 0.991 | discard; keep |
| 14 | node pool allocator for the hashed coarse graph | contract 0.979 (gm 0.944) | 0.992 | keep |
| 15 | dense local block weights (coarsen LP); per-chunk line counts (io) | 0.911; 0.919 | 0.960 (both) | keep; keep |
| 16 | array map with reproduced unordered_map order (contract); degree-sized LP table | 0.718; coarsen 0.988 (gm 1.004) | 0.963 (part 0.956); 1.006 | keep; discard |
| 17 | node labels in their own array (cross-cutting) | coarsen 1.010, refine 1.024 | part 1.002 | discard |
| 18 | refinement touched-entry reset; Iallreduce overlapped with the ghost receive | refine 1.140; comm 1.054 | part 1.017; 1.002 | discard; discard |
| 19 | no allocation per ghost message; small-degree linear scan in LP | comm 0.988; coarsen 0.987 | part 0.998; 0.995 | keep; keep |
| 20 | MADV_POPULATE_READ on the reader chunk; contraction adjacency as one array plus message swaps | io 0.991; contract 0.982 but refine 1.037 | part 1.001; 1.005 | discard; discard (layout, see above) |
| 21 | contraction adjacency as one array without the swaps | contract 0.994 (gm 0.986) | part 1.001 | keep |
| 22 | 64-byte alignment of the LP function; refinement touched-entry reset retested | all phases in band; refine 1.140 | part 1.000; 1.028 | keep (hygiene); discard |
| 23 | retest of the separate label array with the fixed alignment | coarsen gm 0.986, project 1.033 | part 1.010 total | discard |
| 24 | edge array not zero-filled before the build (io) | io 0.848 (gm 0.871), peak RSS 1445 to 912 MB | part 0.999 | keep |
| 25 | contraction receive buffers without fill, swap (contract); projection receive buffers without fill (project) | contract 1.002; project 0.984 (gm 0.996) | part 1.000 | discard; keep |
| 26 | node data array not zero-filled (io, contract) | io 0.989 (noise), contract 1.006 | part 1.001 | discard |
| 27 | degree sort on packed keys, retested with the fixed alignment | coarsen 1.004 (gm 1.013), refine in band | part 1.002 | discard (the earlier refinement loss was layout, the verdict stands) |
| 28 | prefetch in the ghost exchange (comm); prefetch in the contraction's label mapping (contract) | comm 0.929 (gm 0.966); contract 0.986 | part 0.984; 0.997 | keep; keep |

From round 17 on the full-geomean column is the part time. Cross-run A/A of the same binary: part
0.9% geomean / 0.2% total, IO 0.5% / 0.4%; within one alternating run, IO moved by up to 1.6%
between two binaries with identical reader code, so IO differences below about 2% are noise.

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
- `std::fill` instead of a hand loop to clear the k-entry refinement array, and a sentinel-based
  number parser in the reader: both inside the noise of their phase (the compiler already vectorizes
  the loop; the reader is bound by scanning, not by digit parsing).
- Devirtualizing only one of two implementations behind a branch (see 11.).
- Sizing the LP neighbor table per node by its degree (power-of-two prefix of the table): coarsening
  LP total 0.988 but geomean 1.004; the per-node sizing costs the small mesh jobs more than it saves.
- Moving the node labels out of the 32-byte node struct into a dense array (hot/cold split): no gain
  (coarsening 1.010, refinement 1.024). The prefetch already hides the label loads; the edge array is
  the larger stream.
- Resetting only the touched entries of the refinement weight array, tried a second time with a
  first-use test per access, and a third time with the function alignment fixed: 1.14x slower each
  time. A full reset of 8 to 64 entries is a few sequential
  stores.
- `MPI_Iallreduce` started before the ghost receive and completed after it: ghost exchange 1.054.
  The reduction was never the cost; the waiting is imbalance between processes, and the
  non-blocking collective adds progress overhead.
- The wall time includes a fixed launch cost (trivial MPI program: 0.11 s at p = 1 to 0.21 s at
  p = 32), which caps the wall-time ratio of jobs that run under one second (floor 0.39 for those
  39 jobs); a program-internal timer avoids this.
- `madvise(MADV_POPULATE_READ)` over the reader's own byte chunk of the memory-mapped file: io
  0.991, inside the spread of the io timer between two binaries with identical reader code.
- Sorting nodes by degree on packed (degree, node) keys, retested after the layout fix: the
  refinement loss of the first test was the layout draw, but coarsening is still 1.3% slower
  (geomean): the key vector and two copy passes cost more than the cheaper comparisons save.
- Not zero-filling the node data array (much smaller than the edge array): io in noise, contraction
  1.006 (the per-node branch in the builder costs more than the fill).
- Not zero-filling the contraction's receive buffers: contract 1.002; short-lived buffers of
  moderate size come from already mapped pages.
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

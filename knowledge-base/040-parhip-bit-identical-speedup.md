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

### Relaxing identity to a quality budget: measure the cut noise first

After 52 experiments (30 kept) the owner relaxed the identity rule: output may change if the average
cut moves by at most 0.1% (Q = geomean over jobs of (mean cut + 1) / (master mean cut + 1) over the
same seeds, cumulative against the original, Q <= 1.001; balance, determinism of the deterministic
build and the interface stay fixed). Freeze the bit-identical best first (tag plus patch series) as
its own deliverable. Then measure the cut noise before any experiment: on this benchmark, original
seeds 1 to 5 against seeds 6 to 10 gave Q = 0.9926, and the sd of log Q over random 5/5 splits was
0.44%, so a 0.1% budget is far below what a few seeds can resolve (uniform seeds would need about 40
per side for SE 0.1% and 150 for 0.05%). The variance sits in a few jobs (one social graph at k = 8
with sd 53% of the log cut at p = 1; the median job 1.3%, mesh graphs below 1%), and those jobs are
cheap, so a Neyman allocation of seeds per job (S_j proportional to cv_j / sqrt(cost_j)) cuts the
cost about tenfold: SE 0.05% for about 2.6 CPU-hours per candidate on 16 cores. The delta-method SE
from 5 seeds underestimates (0.27% against 0.44% observed) because the cut distribution has heavy
tails; validate the protocol with an A/A split of a large master reference before trusting it. Even
the original goes over the imbalance bound on 2% of the runs (social graphs, k = 64, 16 to 32
processes), so a balance rule must compare against the original job by job.

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

### Phase 2 (0.1% quality budget): output-changing speedups

Once the output may change within a cut budget, the largest single gain came from balancing the
work per process at the finest level, not from local code changes. The per-round block-weight
Allreduce of label propagation was about 2/3 waiting at 16 to 32 processes; a per-process counter
showed equal node counts but up to 7.9 times the mean edge count on one process (social graphs
stored with hubs first). Splitting the input so that each process gets about the same
`adjacency entries + node lines * average degree` (counted per 1/1024 of each process's byte
chunk, one Allgather) gave part 0.945 geomean (social graphs 0.87 to 0.92 at p >= 4, meshes
neutral), ghost-exchange time 0.74, IO 0.90, and a slightly better cut (Q 0.998). Lessons:

- Bytes are a biased proxy for edges: later lines hold longer node IDs, so a byte split gave the
  first processes of a geometrically ordered mesh more work (meshes 1.04 slower). Count entries.
- Half node, half edge balance was as fast as pure edge balance (edge max/mean 1.9 instead of 1.2)
  and avoids processes with almost no nodes.
- A counting pass in the reader must be branch-free (vectorized) and skipped with one process: the
  first, branchy version cost 29% of IO at p = 1.
- Coarsening order: visiting nodes of a degree class in node order (counting sort) is cache
  friendly (coarsening 0.88) but sweeps mesh geometry and costs mesh cut (+0.3%); shuffling chunks
  of 128 consecutive nodes keeps most of the speed (0.91) with neutral mesh cut. About 2/3 of that
  gain depends on the given node numbering (randomly permuted inputs: part 0.986 instead of 0.96).
- Quality gate that held up: Neyman-allocated seeds per job (cv of the cut over sqrt of cost), a
  master reference with twice the seeds, Q = geomean of (cut + 1) ratios on paired seeds, A/A SE
  0.05%; screen on a quarter of the seeds, discard above Q 1.003; balance as one-sided Fisher tests
  of over-bound rates per job with Bonferroni, plus a pooled test.

### Phase 2: coarse-level rebalancing, fresh seeds, and measuring on a second host

The finest-level split left the coarse levels with equal node ranges per process, so hub-heavy
graphs got up to 2.9 times the mean edge count per process again after contraction. Four attempts:

- Rebalancing every coarse level by edge cost: part 0.995 overall, youtube 0.84, but meshes 1.012
  (p = 32 1.028). Moving coarse ranges costs locality where the split was already even.
- Rebalancing only when the equal split puts max > 2 x mean cost, with an extra pass over the
  coarse edges to count: on held-out graphs 0.85 to 0.97, but one graph 1.078 with identical
  output (the pass itself).
- Cost from fine degrees summed per bucket of coarse IDs during contraction: no extra pass, but a
  256 KB Allreduce per level and a 64-bit division per node: output-identical p = 32 jobs 1.011.
- Two-stage reduction: each process sums its local buckets per equal range, an Allreduce of p
  values decides, and the full histogram is reduced only on levels that fire; power-of-two
  buckets (shift instead of division). Output-identical p = 32 jobs 1.003, part 0.989 / 0.982,
  unseen hub-heavy graphs 0.956 with a road-network control at 1.003. Kept.

Lessons: measure the overhead on output-identical jobs with repetitions before judging gains;
decide from a small summary and reduce the full data only when needed; graphs looked at while
tuning stop being held-out (confirm on unseen graphs plus a control that cannot fire).

Selection bias check: after four kept output-changing changes, the cumulative best and master
were both run on seeds no earlier run had used (beyond the 2x master reference): Q 0.9939 against
0.9953 to 0.9958 on the selection seeds, so the noise picked while selecting did not flatter the
result. One balance flag with 3 seeds (1/3 vs 0/3) disappeared with 200 more seeds per side.

A second machine (Xeon Silver 4216, same core numbering, about 1.6x slower) inflates speedups: the
same pair of binaries gave 0.956 there and 0.989 on the main host, and the direct master ratio
0.49 instead of 0.55. Keep one host per trajectory, report the other host's figure with its label,
and build both sides of a timed pair on the same host (`-march=native` binaries from the other
host are a different code generation).

A byte-counting loop that gcc vectorizes is still slow with 64-bit accumulators (every flag is
widened); 8-bit counters over blocks of 255 bytes run 2.6x faster (1.96 to 5.1 GB/s per core) with
identical counts, and IO improved 2 to 3.5% at p >= 4.

Process lessons from running unattended chains: gate every step on the command's exit status, not
on grepping a log (a failed cmake left a chain waiting 3.5 hours), and give every wait a timeout
that raises an alert; kill only by a looked-up process ID, never by pattern (a `pkill -f` matched
the shell that issued it); record which MPI build each run used, and compare against master only
from a direct rerun with the same MPI on both sides (a ratio chained through an intermediate
binary was 0.6205 against 0.6155 direct); do no heavy work on a shared host while another user's
exclusive job runs there, including checksums and report builds.

### Phase 3: completing nonblocking sends, rebasing, and the input graph build

An audit of ParHIP's nonblocking sends (MPI 4.1: every request must be completed, and a send buffer
must not be touched before completion) found requests that were never waited on. A PMPI wrapper
that counts outstanding requests at `MPI_Finalize` is the reliable detector: MPICH's
"pending references" message misses requests on duplicated communicators. Counts at p = 4 grew
linearly with the number of partitioner calls (164 to 820 per rank for 1 to 5 calls) before the
upstream fix, and one remaining case (the evolutionary partitioner sending a population size that
it then changes) needed `MPI_Waitall` before the buffer is reused. An apparent hang was the eco
preset's evolutionary time limit (2048 / p seconds), not a deadlock; use a deterministic build for
leak tests. After each upstream merge, rebase, check partition identity of new master vs old master
and of the rebased branch vs the branch before, keep a map of old to new commit ids next to the
results table (its ids stay as recorded), and run one timed neutrality check.

Input graph build: per-phase timers (12 phases) plus per-process counts showed that the build, not
the parse, was the largest phase on meshes and social graphs, and that its time followed the number
of new ghost nodes per process (delaunay_n22 p = 16: 1.25M ghosts on one process, 0.253 s, against
89k and 0.065 s elsewhere). The cost was growth: 18 rehashes of the ghost map and doubling of three
arrays. An exact distinct-ghost count from a bitmap over global ids (only when the bitmap is not
larger than the local target array) and one reservation cut io by 14% in total on meshes at
p >= 16 (delaunay_n22 0.73, social p = 32 0.90) with identical output. Two alternatives lost: the
ghost-edge count as a bound over-reserves 4 to 14x on social graphs, and key/value slots in the
open-addressing map (one cache line per probe) made the build 5 to 7% slower.

Code layout also moves IO: on the second host, five binaries with the same reader code path at
p = 1 gave stable, binary-specific reader times differing by up to 8% (eu-2005 0.920 to 1.000 s,
spread within a binary about 1%); two of them differed only in communication code. The run order
inside a pair matters too (the second run's IO is 3 to 6% faster), but alternating the order cancels
it; layout does not cancel. Use p = 1 jobs, where a parallel-only change does not run, as the
layout calibrator: report IO claims below about 5% net of the p = 1 band, and confirm them on the
main host.

Number parsing in the reader: once the build was cheap, the parse was about 12 ns per adjacency
entry, dominated by the per-digit branch of the strtol-like loop (number lengths vary, so it
mispredicts about once per number). Reading the 8 bytes at the number start (`memcpy` into a
64-bit word), finding the run length with a branch-free byte mask and converting up to 7 digits
with three multiplications, with everything else falling through to the old routine, made the
parse 1.7 to 1.9x faster single-core and io 0.902 in total (social 0.89 to 0.93, p = 1 on large
files 0.82 to 0.86) with identical output; a fuzz test against the old routine (also under
address and undefined-behaviour sanitizers, inputs in exact-size heap buffers) guards the
equivalence. The in-run gain at p = 16 was about half of the single-core one (shared memory
bandwidth, page faults of the fresh target array). An earlier sentinel parser that kept the
per-digit loop had shown nothing (round 12): the digit loop, not the scan, was the cost.

### Phase 3: splitting LP time into local work and waiting

After the reader work, io is about 5% of the total and the part phases are the lever (coarsening LP
197 s, refinement LP 102 s, contraction 90 s, ghost exchange 83 s inside the LP phases, over the
180 jobs). Two contraction experiments failed on wrong premises, and a per-rank split of the LP
time changed the target.

- Contraction: per-rank sub-step timers showed that the order-preserving edge map (local build,
  ordered iteration, the second map on the receiver) is 60 to 80% of contraction on the slowest
  rank. Putting the key and the weight into the probe slot (one cache line per lookup instead of up
  to four) made contraction 2.3% slower: ids are handed out in insertion order and lookups come in
  runs of the same coarse source, so the id-indexed side arrays were already cached; the 4x larger
  slot array and a gather pass cost more. An exact multiply-based modulo in the order computation
  saves only 6 to 16% of that step: the order computation is bound by its random scatter.
- Coarse rebalancing from the exact edge copies each owner receives (instead of fine degrees):
  a firing table (one diagnostic line per contraction, every job, seed 1) showed it fires on fewer
  levels than the fine-degree rule (24 vs 41 social jobs) and not at all on the motivating job.
  The excess of the slowest rank was on the sending side (its hubs create 4.5x more local coarse
  edges), which no choice of coarse ranges moves. Lesson: check the firing table, which costs
  minutes, before redesigning a decision rule.
- LP split (per rank: total, block-weight allreduce, probe wait, receive and integrate, Isend
  Waitall, final barrier): refinement is imbalance-bound. On enwiki-2013 (16 PEs) 9.6 of 15.9 s
  are the per-round block-weight allreduce, while the total compute differs by only 10% between
  ranks: a round is a fixed number of nodes in random order, so its edge work varies with the
  hubs it draws, and every round costs the maximum over ranks. Social and web graphs: 50 to 74% of
  refinement is this wait; meshes 20 to 25%. Coarsening is compute-bound (local LP plus 38% for
  integrating ghost updates). Meshes show a separate, large compute imbalance in coarsening
  (one rank 3.2 s, most others near 0) that is not yet explained.
- Rounds of equal work instead of equal node counts: a round ends once the visited nodes'
  degree + 1 add up to (local edges + local nodes) / rounds. In both LP phases this cut the
  refinement wait as intended (enwiki 9.6 to 2.5 s), but cost 0.23% cut (fast presets 0.6%, one
  job 20%): in coarsening, a process with many low-degree nodes now visits far more nodes between
  exchanges, so the labels it sees are staler while clusters form. Applied to refinement only
  (moves between k blocks under a bound are insensitive to one round of staleness), the cut is
  unchanged (0.9998, held-out 0.997, unseen 0.998) and part time drops 4.3% total (refinement
  0.79; social graphs at 16 and 32 processes 0.90). Round boundaries are part of the coarsening
  algorithm, not only a communication schedule.
- A branch on a loop-invariant flag in the LP node loop cost about 1% of coarsening (first
  V-cycle, identical work, three alternating repetitions); one template instantiation per value
  removed it. Measure such costs on the first V-cycle: later cycles see a different partition.
- Count what the ghost exchange receives before tuning how it is processed. A third of the
  coarsening updates and 96% of the refinement updates (enwiki, 16 processes) changed no label:
  every interface label set outside label propagation (projection, V-cycle reset, initial
  assignment) was buffered and sent in the next LP's first round, although those callers already
  leave ghosts consistent. Recording only while the LP runs removed them with identical output;
  part time 0.942 total (16 and 32 processes 0.95 gm, projection 0.76).
- On one process the timed gain of dropping the work counter was 2.4% of refinement, against 11%
  in an untimed single-core screen; in the same run, unchanged p1 coarsening moved by 3.7%.
- An allocation that lives across phases can cost an untouched phase as much as code layout: a
  per-node list of adjacent processes, built at a graph's first label propagation and kept until
  the graph is freed, sped up coarsening (0.94 at 16 and 32 processes) but made refinement 3.5 to
  9% slower (timed) with identical output. Untimed variants (3 repetitions, spread under 0.4%)
  separated the causes: moving the new code out of line did not help, while building the lists
  without ever reading them reproduced the refinement loss (up to 11% more refinement work). The
  mechanism is unproven (likely the address shift of everything allocated after the lists). Treat
  any longer-lived or larger allocation, such as a bigger hash table reserve, as a footprint change
  and measure the other phases too, not only the one it targets.
  Follow-up: freeing the lists when the coarsening label propagation ends brought refinement back
  on the social graphs (enwiki 1.047 to 1.010, youtube 1.052 to 1.028), and a reserve of 2 or 4
  times the needed hash table size also slowed refinement by 1 to 8%. On the mesh (hugetrace) the
  loss stayed, and a run-time switch that never built the lists, in the same binary, still showed
  7% more refinement work than the base, while two diag binaries that differ by one getenv call
  differed by 3%. So part of such a loss is a binary effect, not memory: separate the two with a
  run-time switch in one binary before concluding footprint, and let the timed net on the full set
  decide.
- Split a hot spot before optimizing it: of the ghost update integration in coarsening, 96% was
  the block weight hash map (random keys: the labels of the updates), not the label stores. A
  software prefetch ring over the incoming message (ghost id slot 8 updates ahead, ghost lookup,
  node data and the new label's weight slot 4 ahead, the old label's slot 2 ahead) cut that loop
  from 3.7 to 2.8 s on the critical rank, with identical output; part time 0.976 total on the
  full set (16 processes 0.964, coarsening LP 0.946, refinement unchanged: no new allocation).
  Reserving the map to its final size instead lost (doubling the zeroing, refinement up to 8%).
- An optimization that crashed once in a deterministic build and then never again was parked, not
  called a flake: per-node lists of adjacent processes (about 1% net) segfaulted on one 4-process
  job and hung another in one packed, oversubscribed identity batch; 6 plain repeats, sanitizer
  (address, undefined, libstdc++ assertions, an explicit range check on the list path), valgrind
  and three reruns of the batch all passed, and so did the base. Keep the failing batch, core dumps
  and per-rank stderr when a run fails; a rerun loop without them only shows that it is rare.
- UndefinedBehaviorSanitizer stops at an upstream line (uncoarsening.cpp binds a reference to a
  null complete_boundary) before reaching ParHIP's own code; suppress that line to get further.
- Split the label propagation node loop by degree class before guessing: per edge about 90 to 140
  cycles, and the short linear-search path (degree up to 16) cost more per edge than the hash
  path, so the cost was not the hash table but the first misses of every node (its record, first
  edges, own data and first target labels; the in-node prefetch 8 edges ahead never covers short
  nodes). Prefetching these a few nodes ahead in the visiting order (record 4, first edge line 2,
  data and up to 8 first targets 1 ahead) cut coarsening LP by 11% (178 to 158 s) and refinement
  LP by 7% on the full set, part 0.938 total, identical output. The untimed diag gain (13% over 8
  jobs) carried over; trust such a diag over a guess.
- Sizing the hash table prefix per node (pow2 >= 2 * degree instead of 2 * max degree, 8 MiB for
  enwiki) gave 2.7% of coarsening LP but only 0.7% of part time: inside the 1% band, not kept.
- Collecting a moved node's adjacent processes during the scan (a bitmask) to skip the send
  rescan lost 3.6%: every ghost edge of every interface node pays the process lookup, but only
  moved nodes save the rescan, and in refinement few nodes move (refinement LP +18%). The diag had
  only measured the coarsening phase; when a change touches code shared by both LP phases, measure
  both.
- Projection was mostly the global ghost label update (enwiki 3.0 of 3.1 s), and its time was
  work, not waiting: the first message arrived at once, but each received (global id, label) pair
  is a random lookup in the ghost hash map. The same prefetch ring as in the ghost exchange (hash
  slot 8 pairs ahead, lookup and node data 4 ahead) cut projection from 25.1 to 16.5 s on the full
  set, part 0.979 total, identical output.
- A prefetch ring must be larger than its lookahead: a first diagnostic version with 4 slots at
  distance 4 overwrote each slot before reading it, gave wrong ghost labels and crashed later in
  refinement. Name the distances and the ring size as constants and `static_assert(lookahead <
  ring_size)`.
- Run the sanitizer build with libstdc++ assertions on prefetch code too: `&v[i]` for a prefetch
  of the first edge of a node a few ahead hit `i == size` (a trailing node without edges). It is
  harmless at run time (a prefetch never faults) but out of range; form the address as
  `v.data() + i`. Only one graph (enwiki) and both process counts triggered it, the mesh did not.
- After projection, every ghost needs the label its owner projected, which is the coarse label of
  the ghost's coarse node; contraction had already stored that coarse node on every rank. Taking
  the ghost labels from the projection's own request round instead of a global exchange of
  (id, label) pairs cut projection from 16.5 to 8.5 s on the full set (part 0.979, identical
  output; social graphs 10.6 to 3.8 s, meshes 5.9 to 4.7 s). The first version, which grouped the
  ghosts by sorting (coarse node, ghost) pairs, was slower than the exchange: the work is per
  ghost (7.7M per process on enwiki over all levels, about the exchanged pair volume), only the
  message volume shrank. A small hash table of the distinct coarse nodes (one lookup per ghost,
  no sort) made it pay. Keep a barrier at the end: the request loops count messages, not
  senders, so without it a fast process could deliver the next level's request early when
  refinement is skipped.
- A diag mode that runs the old and the new path side by side and compares every field of every
  ghost (and first checks the stored coarse node ids against the owners' with one extra
  exchange) proves identity directly; it found 0 differences over all levels of 8 jobs.

### Phase 3: an input split that also counts far edges (round 50)

- On meshes stored in an order where the first processes own the outer layer, the first ranks hold
  9 to 14 times the ghosts of the others with equal nodes and edges (delaunay_n22 p16: rank 0 1.25M
  ghosts on 262k nodes, ranks 4 to 15 about 89k), on every level. Per-rank coarsening compute fits
  (n + m) + 3 x ghosts. Adding 3 x the entries that leave the provisional range to the split cost,
  estimated from a sampled sub-chunk per group, cut the mesh part time by 5 to 15% (delaunay_n22
  0.875, hugetrace 0.845) and was quality neutral (Q 1.0000 +- 0.0005).
- It was still discarded twice, both times on io, the second headline. Ungated (1 in 32) it changed
  every social job's coarse graph and lost the unseen set (one job's initial partitioning hit an
  unlucky coarse graph). Gated on the sampled per-process max/mean of leaving entries (> 1.85, fixed
  offline: meshes about 2.0 to 2.4, social at most 1.73 with a 1-in-64 sample) it fixed the unseen
  set but lost the full-set io band (1.016): the sample and gate cost about 0.02 s on every job with
  p > 1, and the io band is a sum over 150 such jobs. An untimed per-rank parse time (0.004 to
  0.011 s) understated that cost. Any reader-side estimate must be nearly free or come from data the
  reader already produces.
- Gate thresholds chosen offline transfer badly to inputs not in the design set: the mesh gate also
  fired on web graphs, random geometric graphs and a packing mesh (77 of 180 jobs instead of 30).
  Run the gate on every input of every set before the expensive stages, and report where it fires.
- Reader io follows the bytes of the slowest rank, not its entries: on uk-2002 the ids grow along the
  file, so the last rank parses 338 MB against a mean of 278 MB (1.13 vs 0.74 s) and sets the io
  time. Splits that balance entries and lines (060, 087, 088) move io by luck: the same idea gave
  +3.5% (1 in 32) and -2.0% (1 in 64) on that input, depending on where the boundaries fell.
- Do not project a discard from a related variant's per-job numbers: the 088 io projection reused
  087's io and was refuted by a direct untimed measurement on the critical input.

### Phase 3: contraction arithmetic, round coupling and skipping converged nodes (round 51)

- Contraction redistribution: replacing a modulo and a division in the per-triple owner and order
  computation by multiply-based exact forms (fastmod, 32-bit fastdiv), prefetching the edge map slot
  8 triples ahead in the insert loop and moving received messages instead of copying them gave
  contraction 0.939 and part 0.985 on the full set, output identical. Four follow-ups on the
  contraction build (key next to the id in the probe slot, per-node aggregation before the edge map,
  two-stage prefetch, coarse ranges balanced on received edges) each lost or missed a fixed gate in an
  untimed A/B before any timed run: the remaining build time is a random scatter into the edge map,
  and what is left in the redistribution is mostly waiting at its Allreduce and final barrier.
- An offline cost model must be checked within a job before it projects a gain. A per-rank LP cost
  fitted across jobs (R2 0.96) had a negative R2 inside every job, because the sweep timer contains
  the waiting inside the sweep; model per-rank compute on the node-scan timer. The same input-split
  change, judged on measurement, balanced the scan (max-rank scan 0.94) but not the waits, and lost
  on a packing mesh at 32 processes (1.107).
- Balancing totals does not balance rounds. A per-round record of every ghost exchange (gap, pack,
  receive, probe, Waitall) showed that the LP phase wall equals the sum of per-round maxima, not the
  maximum of per-rank sums (enwiki 16 processes: 14.8 vs 14.0 s in coarsening, 7.6 vs 6.4 s in
  refinement). A rank finishing early waits in every round, so moving work between ranks without
  changing each round's maximum does nothing.
- Deferring the send completion by one round (a third send buffer) reached only a third of what a
  rendezvous model predicted: the removed Waitall time came back as probe time (enwiki coarsening:
  Waitall 2.1 to 0.0 s, probe 0.2 to 1.9 s per rank). Most of the coupling is data dependence on the
  slowest sender, not the send protocol. The extra buffer also raised peak memory by up to 6%.
- An output-identical skip for converged nodes: in refinement a node with no ghost neighbour whose
  last scan saw only its own label and drew no random number, and whose local neighbours have not
  moved since, provably stays without consuming randomness, so its scan can be skipped (its round
  work still counted). A counting diag that scanned every would-skip node anyway found 0
  violations. The skip saved about half of refinement on one-process and packing-mesh jobs (part
  0.84 to 0.93), but cost 2 to 14% of refinement at 16 processes, where almost every node with edge
  work has ghost neighbours. Gating it on the share of non-interface nodes did not bring the 16-process
  jobs within 1%; part of the remaining loss was code layout of the extra loop instance. Require the
  predicate to be the node's own label: a single foreign label may have been refused by a size limit
  that loosens later.
- Untimed screens on a shared host move 2 to 3% on unchanged code (initial partitioning, projection),
  so a 1% screen rule cannot be resolved there. Run a base-versus-base control alternated in the same
  round on the same jobs, and stop only if a ratio exceeds both the rule and the control's spread.
- Separate a regression's causes with one binary and run-time modes before redesigning: off (same
  binary, no new code path), off plus the new allocation, and on. Here the allocation cost nothing,
  the predicate cost 1 to 5% on most losing jobs, and on one job the off mode alone was 7% slower.

### Phase 3: a parked crash retested, and a gain lost to code placement (round 52)

- A change parked after one crash and one hang in a packed, oversubscribed identity batch (per-node
  lists of adjacent processes for the coarsening ghost sends) was first read against the symptoms:
  the lists depend only on graph structure fixed at build, they are never handed to MPI (the pairs
  are copied into the send buffers), and the exchange sends one message per adjacent process per
  round whatever the buffers hold, so no list error can change the message count. Then 20 packed
  batches of the base and the change, alternated, with core dumps on (1040 runs) were all clean on
  both binaries: the failure did not reproduce and is not attributable to the change.
- The coarsening gain was real (coarsening 0.951, enwiki 16 processes -1.5 s of 15 s, part 0.974 on
  10 screen jobs), but refinement, which ran the unchanged edge-scan path, lost 3.6% on a one-process
  job (where the new code never runs) and 6.3% on youtube at 16 processes, tight across reps and well
  outside a base-versus-base control. A shared inline function with one new branch moves the code of
  every caller; to change one phase only, give that phase its own instance and check with a
  disassembly that the other phase's code is unchanged.

### Phase 3: identical code, different placement (round 53)

- The coarsening gain of round 52 was retried with the other phase's code left exactly as it was:
  the list path in a coarsening-only template instance and separate functions, the new members at
  the end of the class. A disassembly check confirmed that every function the refinement LP reaches
  is instruction-identical to the base (only the caller that inlines both LP setups differs). The
  coarsening gain stayed (coarsening 0.947, part 0.982 on 10 screen jobs), the two earlier refinement
  losses vanished (1.036 to 1.006, 1.063 to 1.008), but one 16-process job still read 1.017 against a
  control spread of 1.012, while initial partitioning and projection, whose code is untouched, moved
  by 2 to 3.5%. With identical instructions this is placement, and code shape cannot remove it.
- With 3 repetitions, a per-job stop rule at 1.01 has a real false-stop rate (here it fired on
  overlapping ranges at part 0.982). Use a per-job threshold of 1.02 plus a phase-total threshold of
  1.01, each also above a base-versus-base control, and fix them before the data; do not rerun after
  a stop.

### Phase 3: a skip in its own translation unit, and a gate that admits the wrong jobs (round 54)

- The converged-node skip of round 51 was retried with the base code left untouched: the skipping
  loop and its gate in a new source file listed last in the build, the header only declaring the
  gate. Two shapes inside the header failed the disassembly check first (a second template
  parameter, and a separate loop behind a non-inlined gate): both changed the register allocation
  of the unchanged loop instances, because inlining is decided per translation unit. Only the
  separate file kept every loop instance instruction-identical and at its old address; the
  exchange functions moved by 16 bytes, so data references must be checked for pointing to the same
  bytes rather than compared by offset.
- The skip itself works: refinement 0.55 to 0.59 on one- and four-process mesh and social jobs,
  part 0.83 to 0.93 there, refinement total 0.896, part 0.985. But the gate (at least half of the
  local nodes without a ghost neighbour) also admits mesh jobs at 16 processes, where few nodes can
  be skipped; there the flag upkeep cost 2.8% of refinement and the stop rule fired. A gate should
  follow the quantity that pays (the skippable share), not a proxy that happens to correlate with it
  on the target jobs.

### Phase 3: the contraction build is latency-bound, and placement sets a floor (round 55)

- Hardware counters are not available to unprivileged users on the benchmark host, so the
  contraction build loop was measured by replay: its input was dumped per call and the loop re-run
  offline in variants (full, scan only, map only, hits only, an L2-sized key set), single-core and
  four at once to share memory bandwidth as four ranks do. The loop is latency-bound: chains of
  dependent loads (coarse node of the target, slot, id, key arrays, weight). Where the edge map
  exceeds L3 (social graph, four ranks), hits pay about half a memory latency per cut edge; where
  keys repeat (mesh, one rank), the chain's cache latency plus L3 contention with the coarse-node
  array dominate. It is not bandwidth-bound (at most about 1.5 GB/s per core, unchanged with four
  replays at once) and not compute-bound. This explains why earlier fat slots, fewer calls and
  prefetching did not pay. The remaining lever found, reserving the map's per-key arrays up front,
  has a measured ceiling of about 1% of the part time and is parked.
- The converged-node skip, gated on a single process only, passed every untimed rule (refinement
  0.909, part 0.983 on the screen) and kept its gain in the timed run (single-process part 0.926),
  but multi-process jobs running identical instructions lost 0.5 to 0.8% and the full-set part
  ended at 0.9907, inside the tie band. On this binary, placement costs about 0.5 to 1% on untouched
  jobs per change, so a single output-identical item below about 2% cannot pass even when its gain
  is real. Bundle such items into one change with one placement cost, and check each item's own
  share so that none rides along.

### Phase 3: a bundle of parked items, stopped by memory (round 56)

- The parked output-identical items were bundled into one change with one placement cost: the
  one-process refinement skip, plus reuse of the contraction's ghost send lists when the same input
  graph is contracted again at each V-cycle restart (the graph object is the same across restarts,
  and its adjacency is fixed after construction, so the lists never go stale). The edge-map reserve
  was measured again in the form that can actually be built (vectors only, bounded by the edge
  count); it was worth about 0.3% and was dropped rather than carried as a passenger.
- Moving the new code out of the contraction file into its own translation unit was again needed
  for instruction identity: one extra call to a small vector helper made the compiler stop inlining
  it into an unrelated function of the same file. The objdump check was extended to resolve moved
  data references symbolically (named object and offset, or the relocation of a GOT slot), because
  vtable and GOT bytes hold relocated code addresses; a positive and a negative control validated it.
- The screen showed the largest untimed gain so far (part 0.974, contraction 0.953, about 0.8 s of
  contraction on the large social graph with 16 processes), but the stored lists cost about 7 MB per
  process and one mesh job crossed the 2% peak-memory stop (1.022). The rule was applied as fired:
  discard, no rerun. Lesson: a cache that lives for the whole run must be sized against the memory
  rule at design time, from the buffer it mirrors; store the narrowest index type and reserve exactly.

### Phase 3: a peak-memory median cannot resolve 1% (round 57)

- Storing the reused send lists as 32-bit local ids halved them, and on the social graph with 16
  processes the peak-memory rise fell from 1.4% to 0.8% as predicted. The mesh job that had stopped
  the previous round stopped again at 1.021, but its three base runs spanned 2.8% and its base median
  moved by 5 MB between the two rounds: the expected 1.1% rise was below the noise of the measure.
  The change was discarded under the rule as it stood.
- The memory rule was replaced for all later experiments: exact accounting in the check build (the
  bytes the change keeps allocated, per rank, at most 1.5% of that rank's base peak memory) plus peak
  memory as a coarse guard (stop above 3%, or above 2% when beyond the control's spread). Lesson:
  a gate must resolve the effect it judges; check the measure's own spread on the base before using
  it as a threshold, and count what can be counted.

### Phase 3: a bimodal job defeats a fixed guard (round 58)

- The halved send-list reuse was re-entered under the replaced memory rule. This time a different
  mesh job stopped it: peak memory 1.034 against the 1.03 guard. That job's peak memory is bimodal
  (runs land near 397 or near 408 MB; b91 alone spanned 3.4% over three rounds), and in this round
  all three new runs landed high while two of three base runs landed low. A control paired per
  repetition did not catch it because base and control fell on the same level in every repetition.
  Exact accounting on the same job showed 2 MiB of lists on the measured process (0.5% of its peak)
  against a 13 MB median rise, so the rise was noise. The change was discarded as the rule stood,
  and the memory gate went to the owner.
- Lesson: before fixing any threshold on a measured quantity, measure the base alone with enough
  repetitions to see its distribution (spread, and whether it is bimodal); three repetitions cannot
  show a bimodal distribution, and a guard inside the noise rejects changes at random.

### Phase 3: base memory noise, and a deterministic receive lag that loses downstream (round 59)

- Before any further memory threshold, the base binary was run alone, 10 times per job, on the 10
  screen jobs and on the social job a later guard fired on (peak memory of the largest process,
  untimed). Six jobs vary by at most 1.8%. Four vary by 2.6 to 4.1%, and three of these are
  bimodal: a mesh job at 16 processes lands on 386 or 399 MB (5 runs each), another mesh job on
  300 or 306 MB, and the social job (as-skitter, 16 processes) on 103 or 111 MB (7 and 3 runs,
  range 9.7%). On that last job a 3-run median of the base against itself exceeds a 1.05 guard
  about once in seven comparisons. The largest process is the same in every run of a job, and its
  peak equals what the launcher reports.
- The last output-changing idea from the round-model diagnostic was then tested. In the
  coarsening label propagation, every process integrated its neighbours' ghost labels two rounds
  late instead of one, with five send buffer sets in rotation and each round's sends completed
  four rounds later. This lets a process run up to two rounds ahead of its slowest neighbour. The
  result stays deterministic: the lag is a fixed number of rounds, not a timing decision.
  Identity, quality and balance all passed. The cut was unchanged within its error
  (0.99977 +- 0.00048 against the base), better than the prior estimate of +0.2 to +0.5%.
  Exact accounting of the extra buffers stayed below 0.5% of each process's peak.
- Timed, the coarsening phase gained as the round model projected (social job at 16 processes:
  -0.37 s of 15.3 s). But the full set got slower: part time 1.005, unseen inputs 1.041. The
  changed coarse hierarchy made initial partitioning (+3.8%), contraction (+1.4%) and projection
  (+3.0%) more expensive than the coarsening saving. Peak memory also rose by up to 15% on the
  full set and 40% on one unseen job, far beyond the counted buffers. The change was discarded.
- Lessons: an output-changing coarsening change must be judged on the whole pipeline, since its
  phase gain can be eaten downstream. Exact accounting of the change's own allocations does not
  see memory held inside the message layer. A plausible but unverified reading: with more
  messages in flight, the receiver's MPI buffers them before the receive is posted. So any change
  that raises the number of messages in flight needs a measured peak-memory check before the
  timed run, in addition to the accounting.

### Phase 3: adjacent-process lists for coarsening sends, stopped by exact memory accounting (round 60)

- Coarsening LP sends a moved interface node's new label to every adjacent process. The base
  finds these processes by scanning the node's edges at every move. Two earlier attempts
  (rounds 52 and 53) built per-node lists of the adjacent processes instead. They saved about 5%
  of the coarsening time, but they changed or moved the refinement code and were stopped by its
  noise rule. This time the list path was put in its own translation unit linked last, as a copy
  of the coarsening sweep. Every other function stayed instruction-identical and at the same
  address (checked by a closure compare of the binaries). The lists were local to one coarsening
  call and freed after it, and the messages were the same bytes by construction.
- Identity passed (deterministic twice, clang, sanitizers), and a check build that compared every
  list with the edge scan and every round's pairs per process found no mismatch on 11 jobs.
  The memory gate then stopped it before any timing. Exact accounting of the lists peaked at
  2.37% of one process's peak memory, above the 1.5% limit, on 25 processes. The accounting
  counted the build's transient peak: a vector grown by push_back holds its old and new blocks
  at once during each doubling.
- A pre-registered follow-up with an exact-size two-pass build (count, then fill) was judged
  offline first. The per-process node and list counts were computed from the input files with
  the base's input split. Replaying the round's accounting from them reproduced the logged peak
  of all 108 processes exactly. The projection still reached 1.74% (and 1.20 to 1.25% on six
  processes of a mesh job), above the 1.2% margin set for it. Here the 4 bytes of offsets per
  local node dominate, on processes whose own peak memory is small. The idea was closed with no
  timing data.
- Lessons: under an exact-bytes memory gate, per-node side structures of 4 to 6 bytes per node
  are at the limit on small processes. Project the gate offline from the input split before
  writing code; a replay that reproduces the logged accounting exactly makes the projection
  trustworthy. Give a diagnostic's own assertions a precondition. Here one fired on every push,
  not only on reallocating ones, and cost a rerun (not counted as a failed rule).

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
| 29 | early stop of refinement LP when moves plateau (output-changing) | cut +0.2 to 0.3% | about 0.2% part per 0.01% cut | discard (late sweeps carry the cut) |
| 30 | degree order by counting sort, then random 128-node chunks per degree class (coarsen) | coarsen 0.865 | part 0.956 | keep (Q 0.998, mesh 1.000) |
| 31 | Iallreduce of block weights with one round lag (refine) | wait moves into MPI_Wait | part 1.00 | discard (load imbalance, not latency) |
| 32 | input split balancing entries + node lines (io, all LP phases) | comm 0.743, io 0.896 | part 0.945 | keep (Q 0.998 vs previous) |
| 33 | coarse PE ranges rebalanced by edge cost at every level (contract, all coarse LP) | youtube 0.84, mesh p32 1.028 | part 0.995 | discard (locality) |
| 34 | the same, guarded by max/mean > 2 with a counting pass; then cost from fine degrees per coarse-ID bucket | identical-output jobs 1.078 (one graph); 1.011 at p32 | part 0.995 / 0.983 | discard (overhead) |
| 35 | guarded rebalancing with a two-stage reduction and power-of-two buckets | identical-output p32 1.003; unseen 0.956 | part 0.989 | keep (Q 0.9958; fresh seeds 0.9939) |
| 36 | 8-bit block counters in the reader's counting pass (io) | io 0.978 (p >= 4: 0.95 to 0.97 total) | part 0.998 | keep (identical output; second host) |
| 37 | ghost map and arrays reserved to the exact ghost count (io build) | io 0.949 (mesh p16/p32 0.86 total; net of p = 1 band about 0.92) | part 1.003 | keep (identical output; second host) |
| 38 | adjacency numbers of up to 7 digits from one 8-byte load (io parse) | io 0.930 (gm) / 0.902 (total) | part 1.001 | keep (identical output; second host) |
| 39 | contraction edge map: key and weight in a 32-byte probe slot (contract) | contract 1.023 (untimed screen, 6 jobs) | part 1.006 | discard (no timed run) |
| 40 | coarse PE ranges decided from the exact edge copies per owner (contract) | fires on 24 vs 41 social jobs | n/a | discard (falsified by the firing table) |
| 41 | LP rounds of equal edge work in coarsening and refinement | refine 0.56 (enwiki), cut 1.0023 | n/a | discard (quality: stale labels in coarsening) |
| 42 | the same in refinement only, node loop instantiated per round rule | refine 0.788 total; social p16/p32 part 0.90 | part 0.957 (gm 0.974); unseen 0.938 | keep (Q 0.9998) |
| 43 | one process: refinement LP without the work counter | p1 refine 0.976 (gm) | p1 part 0.972 (gm, about 3% placement) | keep (identical output; timed with 44) |
| 44 | ghost labels recorded only while LP runs (no buffered no-op updates) | project 0.76, comm 0.91, refine 0.94, coarsen 0.95 | part 0.942 (gm 0.953); unseen 0.956 | keep (identical output) |
| 45 | per-node list of adjacent processes for the ghost label sends (lists freed after coarsening) | coarsen 0.96, refine 1.03 (lists kept) | not timed as the freed variant | parked (one unexplained crash and hang in an identity batch) |
| 46 | coarsening block weight map: prefetch ring over incoming ghost updates | coarsen 0.946, comm 0.855, refine 0.997 | part 0.976 (gm 0.984); unseen 0.986 | keep (identical output) |
| 47 | label propagation: prefetch across nodes in visiting order | coarsen 0.888, refine 0.928 | part 0.938 (gm 0.944); unseen 0.974 | keep (identical output) |
| 47 | LP hash table prefix sized per node degree (on 47) | coarsen 0.973 | part 0.993; unseen 0.987 | not kept (inside the 1% band) |
| 47 | moved node's adjacent processes collected in the scan (on the above) | coarsen 1.006, refine 1.183 | part 1.036; unseen 1.020 | discard |
| 48 | global ghost label update: prefetch ring over the received pairs (project) | project 0.660 | part 0.979 (gm 0.987); unseen 0.988 | keep (identical output) |
| 49 | ghost labels from the projection's request round (sort of the ghosts by coarse node) | diag: project 1.06 (enwiki), 1.75 (delaunay) | n/a | replaced by the hash version |
| 49 | the same with a hash table of distinct coarse nodes (no sort), barrier kept | project 0.514 | part 0.979 (gm 0.981); unseen 0.980 | keep (identical output) |
| 50 | input split cost + 3 x sampled entries leaving the provisional range, 1 in 32, ungated | mesh part 0.80 to 0.82, io 0.978 | part 0.977; unseen 1.036, unseen io 1.022 | discard (unseen io band) |
| 50 | the same gated on sampled leaving max/mean > 1.85, 1 in 64 | mesh part 0.950 (delaunay_n22 0.875) | part 0.982; io 1.016; unseen 0.992 | discard (full-set io band) |
| 50 | coarsening LP: cache hint for the hash slot of the label four edges ahead (degree > 16) | coarsen 0.975 (enwiki only), 1.01 to 1.05 elsewhere | untimed A/B neutral (8 jobs 75.0 to 74.9 s) | discard (no timed run) |
| 51 | contraction redistribution: multiply-based modulo and division, insert prefetch, moved messages | contract 0.939 | part 0.985 (gm 0.987) | keep (identical output) |
| 51 | contraction build: wide probe slot; per-node aggregation; two-stage prefetch; ranges on received edges | untimed contract 0.976 / 1.020 / 0.977; offline 1 to 2% | n/a | discard (missed the fixed gates) |
| 51 | input split on entries + lines (node term 1) | max-rank scan 0.94, io 0.93 (10 jobs) | untimed part 1.001; packing p32 1.107 | discard (stop rule) |
| 51 | ghost exchange: send completion deferred one round (third buffer) | coarsen 0.988 (untimed) | part 0.994 (untimed) | discard (peak RSS +6%) |
| 51 | refinement LP skips provably converged nodes; then gated on the non-interface share | refine p1/packing 0.54 to 0.61, p16 1.02 to 1.14 | untimed part 0.992 / 0.993 | discard (16-process rule) |
| 52 | coarsening ghost sends from per-node lists of adjacent processes, freed after the coarsening LP | coarsen 0.951, refine 1.036 (p1) / 1.063 (youtube p16) | untimed part 0.974 | discard (refinement stop rule; crash not reproduced in 1040 runs) |
| 53 | the same with the refinement code instruction-identical to the base (coarsening-only instance) | coarsen 0.947, refine 1.011 (one job 1.017) | untimed part 0.982 | discard (per-job refinement rule; placement) |
| 54 | refinement LP skip in its own source file, gated on the non-interface share (base code identical) | refine 0.896 (p1/p4 0.55 to 0.59), hugetrace p16 1.028 | untimed part 0.985 | discard (per-job refinement rule) |
| 55 | contraction build mechanism by offline replay (diag) | latency-bound dependent loads; reserve ceiling about 1% | n/a | closed (no lever at 2%) |
| 55 | refinement LP skip gated on one process only (fourth attempt) | refine 0.909, p1 part 0.926 (timed) | part 0.9907; unseen 1.015 | discard (tie band; placement on p > 1) |
| 56 | bundle: one-PE refinement skip + ghost send-list reuse on V-cycle restarts | part 0.974, contract 0.953 (screen) | peak RSS +2.2% on one mesh job | discard (memory rule) |
| 57 | send lists halved (32-bit local ids) | part 0.973, contract 0.957 (screen) | peak RSS 1.021 on one mesh job, inside its 2.8% base spread | discard (old memory rule); rule replaced |
| 58 | round-57 code re-entered under the new memory rule | part 0.968, contract 0.953 (screen); accounting 0.5% | peak RSS guard 1.034 on a bimodal mesh job | discard (guard); gate to the owner |
| 59 | diagnostic: peak memory of the base alone, 10 runs on 11 jobs | ranges 0.03 to 9.7%; three jobs bimodal | n/a | input for memory guards |
| 59 | coarsening LP: deterministic receive lag of 2 rounds, sends completed 4 rounds later | coarsen 0.992 (social p16 -0.37 s); ip 1.038, contract 1.014 | part 1.005; unseen 1.041; cut 0.9998; peak RSS up to +15% (unseen +40%) | discard (keep rule; memory guard) |
| 60 | coarsening sends from per-node adjacent-process lists, in a TU linked last (same messages) | no timing (stopped before the screen) | exact list accounting 2.37% of a process peak (limit 1.5%) | discard (memory gate (a)) |
| 60 | same with an exact-size two-pass build, projected offline (replay exact on 108 processes) | n/a | projected 1.74% (margin 1.2%) | discard offline; idea closed |

From round 17 on the full-geomean column is the part time. Cross-run A/A of the same binary: part
0.9% geomean / 0.2% total, IO 0.5% / 0.4%; within one alternating run, IO moved by up to 1.6%
between two binaries with identical reader code, so IO differences below about 2% are noise.

Noise between two passes of the original: geomean drift 0.4%, per-job sd of log ratio 0.027.
Per-phase noise: see the keep rule above.

## What Didn't Work

- Overlapping the per-round block-weight Allreduce (Iallreduce, one round lag): the wait just
  moved into MPI_Wait, because it is load imbalance between processes, not latency.
- Stopping refinement label propagation early when moves plateau: the late sweeps are worth 0.2 to
  0.3% of the cut, so the trade (0.2% time per 0.01% cut) is poor.
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
- Inlining the key into the probe slots of an insertion-ordered hash map whose lookups come in
  runs: the side arrays it replaces were cache-resident, so the 4x larger slots only cost.
- LP hash table misses only pay off when the table is far larger than the cache. Both fixes of the
  same misses (sizing the table prefix per node degree, and a cache hint for the slot of the label
  four edges ahead) gained 2.5% coarsening on enwiki (max degree 432260, 16 MiB table) and cost 1 to
  3% on inputs whose table fits the cache (youtube 1 MiB and smaller); the net was inside the band.
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

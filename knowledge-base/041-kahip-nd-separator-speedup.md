# Speeding up nested dissection and node separators: bit-identical changes, quality-gated early stops, and telling code placement apart from speed

## Problem

Make four programs of KaHIP faster while every output stays byte-identical (ordering, separator and
partition files plus the printed objective values) for every input, seed and option set:
`node_ordering` (multilevel nested dissection with data reductions), `fast_node_ordering`
(reductions plus METIS), `node_separator` (multilevel node separators: FM local search on the
separator, localized FM, flow-based improvement) and `partition_to_vertex_separator` (turns a given
partition into a separator; about 0.25 s per job, mostly reading the graph). All four link the same
partitioner library as `kaffpa`, whose outputs must not change either.

From experiment 012 on, the rule was relaxed for `node_separator` and `node_ordering` (the
focus): their outputs may change (tie order, hashing, random decisions) as long as the quality
(separator weight, ordering fill) stays within 0.1% of the original, while `kaffpa`,
`fast_node_ordering` and `partition_to_vertex_separator` stay byte-identical. Every change is
still either byte-identical (checked on the identity suite, no quality test needed) or passes a
quality gate against the original (see below).

Benchmark: 22 timed jobs on 11 graphs (meshes, road networks, SuiteSparse matrices; 3k to 1.4M
nodes, 0.25 to 20 s per run), base and candidate alternating in one session, 3 repetitions (15 for
the sub-second jobs), 16 jobs in parallel on one 16-core node. Identity is checked separately on a
larger untimed suite of 670 jobs (including 328 `kaffpa` jobs). Metric: shifted geometric mean
(shift 0.01 s) of per-job median ratios, overall and per program; a per-program noise band guards
the programs a change does not target.

## What Worked

Status after 22 experiments (11 kept, 2 of them waiting for the final quality gate): chained per-program
ratios `node_separator` about 0.36 of the original and `node_ordering` about 0.21 (0.37 without
the pending experiment 015). These are products of the per-experiment session ratios, not one
direct measurement.

Items 1 to 5 come from the first 10 experiments (all byte-identical). After those 10 experiments (4 kept): geometric mean about 0.70 of the original overall (chained);
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

6. **Stop FM rounds that have stopped paying (014, 0.77 on `node_separator`, 0.66 on
   `node_ordering`; quality-gated).** The eco and strong presets repeat the separator FM for a fixed
   number of rounds; most of the late rounds find nothing. Stopping after 50 rounds without a smaller
   separator keeps the quality: the geometric mean of per-instance seed-mean ratios was 1.0002 on
   `node_separator` (22 low-variance instances, bound 1.001 on R times exp(2 se)) and 0.99998 on
   `node_ordering`. The same stop in the fast preset (013) lost 0.7 to 1.5% on fast instances at any
   K tried (10, 20, 50), so fast keeps its full budget. A tighter per-pass budget in fast (020: U =
   1000, 500, 200) also failed screening (primary R 1.0014 to 1.020).
7. **`node_ordering`: stop the initial separator tries after 10 unsuccessful ones (015, 0.58 on
   `node_ordering`; quality-gated, final gate pending).** On the 0..49 master seeds the loss was
   R 1.00056 with 2 se 0.00069, all of it on the fast preset (3elt +0.22%, PGP +0.23%), so it sits
   at the edge of the 0.1% budget, which 014 and 015 share.
8. **Replace hash maps and two-pass graph construction in the flow problem (016, 0.95; 018, 0.99;
   byte-identical).** The backward mapping of the flow network became a node-indexed vector kept
   across calls. The split-node network is now laid out directly from its degrees (the region
   degree of each node is known before the edges are added), with the edges placed in the same
   order as the old two-pass construction, so the solver sees the same CSR.
9. **Cached neighbour weight sums for FM gains (019, 0.92 on `node_separator`, 0.96 on
   `node_ordering`; byte-identical).** A node's gain is the weight of its neighbours on the other
   side; it was recomputed over the adjacency six times per move. A per-node record (stamp, sum to
   side 0, sum to side 1) is filled on first use in a pass and adjusted on every move, with a new
   stamp generation per pass, so the rollback needs no adjustment. The heap sifts became loops with
   the same comparisons (ties included). Cost: 12 bytes per node (+17 MB peak on belgium.osm). A
   compact 4-byte slot plus a per-pass array (021) was identical but 1% slower and was dropped.
10. **Global relabelling without reading the reverse edge (022, pending).** In push-relabel the BFS
    from the sink reads the residual capacity of each reverse arc, one random access per arc. In
    this CSR an edge's flow and its reverse's flow are always opposite, so the reverse residual is
    the stored reverse capacity plus the edge's own flow; storing the reverse capacity next to the
    edge makes the BFS sequential.

## Quality gate for output-changing changes

- **Statistic.** R = geometric mean over instances of the ratio of seed means (candidate over
  original), with se(log R) = (1/I) sqrt(sum over instances of cv_c^2/S_c + cv_m^2/S_m). Pass if
  R exp(2 se) <= 1.001 on the primary (low-variance) instances, and <= 1.01 on the high-variance
  ones. One original record with seeds 0..199 serves every candidate.
- **Pre-register, screen on other seeds, never re-gate a chosen variant on the gate seeds.**
  Variants (K, U) are screened on seeds 1000+ against seed-matched original runs; only the chosen
  one is gated. Picking a fallback from the gate rows and gating it on the same rows would select
  on the test set; a fallback gets fresh gate seeds and the budget stays cumulative.
- **A per-instance limit at 10 seeds is noise.** On high-variance instances (email-EuAll, CV 0.3 to
  0.5) the se of a 10-seed mean is 10 to 15%, so "no instance above 1.01" fails even the original
  against itself; the per-instance check applies to primary instances only.

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
| 012 | 009's FM rounds under the separator-only gate (ns + no) | keep, 0.903 (ns 0.883, no 0.984) |
| 013 | FM round stop after K unsuccessful rounds, all presets | discard in screening: ns primary R 1.0016 to 1.0031 (loss in fast) |
| 014 | FM round stop after 50 unsuccessful rounds, eco and strong only | keep, 0.746 (ns 0.770, no 0.659); quality R 1.0002 ns, 0.99998 no; final gate at 200 original seeds pending |
| 015 | initial separator tries in node_ordering stop after 10 unsuccessful | keep pending quality, 0.898 (no 0.583); R 1.00056, bound 1.00125 at 50 original seeds |
| 016 | flow backward mapping as a vector | keep, 0.954 (byte-identical) |
| 017 | prototype: implicit split-node Boykov-Kolmogorov next to push-relabel | discard, BK/PR 1.19 (ns eco), 1.29 (no eco); same flow and source set in about 96000 calls |
| 018 | split-node network built directly from degrees | keep, 0.987 (byte-identical) |
| 019 | cached neighbour weight sums for FM gains, loop sifts | keep, 0.930 (ns 0.923, no 0.960); RSS +8.7% on belgium.osm |
| 020 | fast preset: per-pass FM budget U = 1000, 500, 200 | discard in screening (primary R 1.0014, 1.0091, 1.0201) |
| 021 | compact gain cache (4-byte slot) | discard, 1.011 (byte-identical but slower) |

## What Didn't Work

- **Boykov-Kolmogorov instead of push-relabel** for the separator flow problems: 11% slower on
  `node_separator` and 35% more peak memory; the flow networks are small, dense strips where the
  two-phase push-relabel with global relabeling is already fast.
- **Boykov-Kolmogorov on the split-node network, even without building it (017).** The prototype
  ran BK on the region graph with implicit in/out nodes and agreed with push-relabel in every call,
  but was 19% slower on `node_separator` eco (sum 1.93 times, thermal2 not done in 900 s) and 29%
  on `node_ordering` eco. The cause is the orphan count: belgium.osm had 67867 augmentations and
  312.7 M orphans (311.5 M freed). An out-node has only two possible parents in the source tree
  (its in-node by the node arc, or an in-node by cancelling flow), so when the node arc saturates it
  usually finds neither and its whole subtree is freed and regrown. On edge-cut networks (kaffpa) BK
  had won; the split-node structure is what breaks adoption.
- **Dropping phase 2 of push-relabel.** The separator reads the minimal source side (BFS from the
  source in the final residual graph). After phase 1 nodes with stuck excess still hold flow that
  makes source arcs look saturated, so the source-reachable set of the preflow is not a min cut;
  the sink-side cut after phase 1 is a min cut but the maximal source side, a different separator.
- **Judging shared-library changes only by a run-to-run noise band.** Three measurements of the
  same FM change gave `partition_to_vertex_separator` +1.2%, +1.2% and +1.6% although it never runs
  FM; only the placement studies and the DSB counters showed it was layout.

## Harness lessons

- **A failed launch can look like success.** A session script without the executable bit made the
  job scheduler print an exec error and return 0, and the driver logged the rc of `tail`. A wrapper
  now checks the bit, logs the session's own rc (`pipefail`) and requires a done marker in the log;
  each check was tested with a dummy session.
- **Check that a screening actually ran.** A disabled command-line option made 480 screening runs
  exit 0 without output, and an empty group gave "worst ratio 0.0000, go on". Count invalid rows
  and treat an empty group as a stop; patch the preset in a screening build instead of relying on a
  flag the program may ignore.
- **Phase shares measured with 8 runs in parallel are skewed** by the shared L3 and memory
  bandwidth; label them as such and confirm any decision with one sequential run.

## Environment

C++11, GCC 13.3, Release build with the project's default flags (no flag changes allowed), Xeon
Silver 4216 (Cascade Lake, 16 cores), Linux. perf with `frontend_retired.dsb_miss` for the
placement diagnosis; before perf was available, an LD_PRELOAD timer-signal PC sampler plus
`addr2line -i` gave inlined-frame profiles.

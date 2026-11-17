# Cascading data-reduction rules instead of batch reductions on a frozen graph

## Problem

Exact minimum cut on undirected weighted graphs (VieCut's Nagamochi-Ibaraki
capforest solver, with a Padberg-Rinaldi (PR) reduction pre-run). Metric:
wall-clock time to the exact cut over a 53-instance benchmark (33 generated
Chekuri-Goldberg-Karger-Levine-Stein families plus 20 real-world k-cores of
large web and social graphs), under a hard invariant that the computed cut
value never changes. On the dense, cycle-structured generated families the
solver was slower than a classical 1997 sequential implementation. Profiling
showed the capforest contracting roughly one vertex per round, i.e. quadratic
in the number of rounds, on graphs where a reduction rule should have collapsed
them in a single pass.

## What Worked

Reduction rules (Padberg-Rinaldi here, but the lesson generalizes to any data
reduction / kernelization rule set) are usually written as a **batch**: scan
the whole graph once, mark everything the rules fire on, contract, repeat. On
these instances the batch found almost nothing, because each PR test compares an
edge weight against vertex **degrees**, and a test only becomes true *after* a
neighbouring contraction has raised those degrees. A batch measures a frozen
graph, so the first pass fires on nothing and the phase stops.

The fix is to **cascade**: contract on the spot and immediately re-read the
degrees the contraction just changed, pushing the merged supervertex back onto a
worklist so its neighbours are retested. One reduction enables the next, and
whole cycle families collapse in a fraction of a second where the capforest
needed a round per vertex. This is exactly how the original 1997 implementation
rode the chain (its internal passes remove about 87% of a million-vertex random
graph); a later batch reimplementation had quietly lost that property, and that
single lost property was the whole performance gap on those families.

Two implementation choices make the cascade cheap enough to leave switched on:

1. **Lazy adjacency over a union-find.** Hold each supervertex's neighbourhood
   as a plain vector of `(target, weight)` and let entries go stale. Redirect a
   target through the union-find only when it is read, and combine parallel
   edges only when that vertex is tested, via a stamped (epoch-counter)
   aggregation pass over its list. A merge splices the shorter list onto the
   longer and updates one degree arithmetically (`deg = deg_u + deg_v - 2w`); it
   touches neither the neighbours nor the longer list. An earlier version kept a
   hash map per supervertex, and the maps *were* the cost: a million
   supervertices meant a million allocations per call, and the run came out
   slower than leaving the reductions off entirely.
2. **Run it only where it pays** (sparse rounds) and **retire it** once a pass
   stops being productive, so it never taxes the rounds it cannot help.

## Experiment Data

Whole-campaign result. The cascade was one of about a dozen kept changes and the
specific one that closed the gap on the generated families. Exact algorithm,
geometric mean over the 53 instances, cut value identical on every instance:

| configuration | before | after | speedup |
|---|---|---|---|
| 1 thread  | 25.0 s | 2.80 s | 8.9x |
| 32 threads | 5.76 s | 0.65 s | 8.8x |

I do not have an isolated single-change microbenchmark for the cascade alone,
but it is the change that turned the cycle families from "slower than the 1997
sequential code" into sub-second, by replacing an O(rounds^2) capforest phase
with a near-linear reduction that removes most of the graph before the capforest
runs at all.

## What Didn't Work / Gotchas

- **Per-supervertex hash maps for the neighbourhood.** Correct, but slower than
  running no reductions at all at scale. The lazy-vector plus stamped-aggregation
  representation is what made the cascade a net win rather than a net loss. If a
  reduction phase is slower than skipping it, suspect per-element allocation
  before you suspect the rules.
- **Soundness under equality tests.** The PR tests fire at equality, and
  equality is only sound if the degree of every vertex the cascade removes is
  first recorded as a cut (an upper bound): contracting `u` into `v` because
  twice the edge weight reaches `deg(u)` argues that `u` can cross the cut, and
  that argument fails for the cut that isolates `u`. Maintaining that bound is
  part of correctness, not an optimization, and it is easy to drop when you port
  a batch rule to an incremental one.
- **Lazy aggregation combined with a min.** The test that sums
  `min(w2, w3)` over the common neighbourhood can be fed stale entries that split
  one true edge weight across several records; taking the per-entry minimum
  overstates the sum (`min(3,5) + min(3,5) = 6` where the true `min(6,5) = 5`),
  which contracts an edge the rule does not justify. Aggregate each
  neighbourhood *before* taking any minimum.

## Code Example

Worklist loop, pseudocode:

```
worklist = all vertices
while worklist:
    v = worklist.pop()
    if find(v) != v: continue              # already merged away
    aggregate v's neighbourhood by current representative (one stamped scan)
    for (x, w) in neighbourhood(v):
        if pr_test_fires(w, deg[v], deg[x], shared_nbhd):   # PR 1-4, at equality
            bound = min(bound, deg[small])  # record removed degree as a cut FIRST
            splice smaller adjacency list into larger
            deg[big] = deg[v] + deg[x] - 2*w                # arithmetic, no rescan
            union(small, big)
            push big back onto worklist      # <-- let the change cascade
            break
```

The one line that distinguishes this from a batch is `push big back onto
worklist`: the contraction that just happened is allowed to re-trigger the rules
on the vertex it changed.

## Environment

C++17, 64-core AMD EPYC. The technique is language-agnostic and applies to any
solver whose local reduction rules have preconditions that depend on the graph
state the reductions themselves change: minimum cut, vertex-cover and other
branch-and-reduce kernelizations, and constraint propagation. Developed with
Agentic Algorithm Engineering while speeding up VieCut's exact minimum cut; the
study is described in the AAE paper (13th DIMACS Implementation Challenge, 2027)
and the released code is KaHIP/VieCut.

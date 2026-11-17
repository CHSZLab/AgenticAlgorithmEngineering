# Choosing the solve direction in pseudoflow / push-relabel maximum flow

## Problem

Speeding up an established maximum-flow code: the highest-label FIFO variant of
Hochbaum's pseudoflow (version 3.23), kept single-threaded under a fixed build
(`gcc -O4`), with the flow value required to stay correct. Metric: solve time
(user CPU from the end of input to the end of flow recovery) over 164 DIMACS
max-flow instances (rmf-wide/long, wash-rlg, polygon, road-graph punch, computer
-vision stereo/segmentation, graph bisection), reported as the shifted geometric
mean (10 ms shift) of per-instance median time ratios. Every kept change had to
pass three checks on all instances: flow value equals HIPR, the program's own
check, and an independent checker of capacities, conservation, and the absence
of an augmenting path.

## What Worked

Three transferable ideas, headlined by the direction rule.

1. **Pick the solve direction.** Maximum flow by pseudoflow (and push-relabel
   generally) is *not symmetric* in s-t orientation: solving the reverse graph
   can be dramatically cheaper, because the algorithm's work depends on where the
   excess has to travel. Before building the adjacency lists, cheaply estimate
   the excess reachable from the source against the deficit at the sink, and
   solve the **reversed** graph when the source side carries clearly more excess
   than the sink side has deficit. The decision costs microseconds and is made on
   the solve clock. It fired on 71 of the 164 instances; on the segmentation
   (ALE) instances it cut solve time from 3-39 s to 0.01-0.02 s. Measured in
   isolation (the original run on reversed input files), the orientation alone
   explains about three quarters of the gain on the instances where it fires. It
   was the single largest change of the campaign (chained factor 0.66).

2. **Flow recovery is a real phase; profile it, do not assume the push loop
   dominates.** The biggest single cost here was *not* in the main loop: the
   original recovered the flow by sorting each node's arcs by flow with a
   quicksort that goes quadratic on equal keys, decomposing paths, and scanning
   all arcs. Replacing it with cycle cancellation and excess return in
   topological order, over lists of positive-flow arcs only, was a 0.82x factor
   overall and down to 0.26x on one vision family. "Sort by key" hides a
   quadratic whenever keys tie, and post-processing/recovery phases are routinely
   left unprofiled.

3. **Verify a textbook optimization is not already satisfied before importing
   it.** Exact initial distance labels, global relabeling, and lifting trees that
   cannot reach a deficit all *failed*. An instrumented run showed why: in the
   highest-label code the labels already equal the exact tree distances, so none
   of these can save a single relabel. Instrument the quantity an optimization
   targets before spending days implementing it; the standard trick may be a
   no-op for your variant.

A correctness note that is also a general trap: the original stored node excess
in a 32-bit `int`, which overflows on two large rmf-wide instances, silently
violating conservation. A 64-bit excess fixes it. On large instances, audit the
width of every accumulator.

## Experiment Data

164-instance DIMACS max-flow benchmark, single thread, median of three
repetitions, flow value verified on every instance:

- Total solve time 2283 s -> 761 s (3.00x); shifted geometric mean of the
  per-instance ratios 3.18x (2.80x excluding the four ALE instances the direction
  rule makes trivial). No instance got slower. Peak memory 23.1 -> 14.2 GB.
- 132 hypotheses tested, 29 kept (one of them the correctness fix). Final code
  ~1800 lines vs ~1300 original.
- Kept-change factors, chained geometric mean over the respective control:

| kind | factor | main effect |
|---|---|---|
| direction rule (excess vs deficit) | 0.66 | stereo 0.42, polygon 0.47, bisection 0.46-0.52 |
| memory layout + huge pages | 0.77 | all large instances; rmf-wide 0.82 |
| flow recovery (sort, cycles, arc lists) | 0.82 | vision-surface 0.26, ALE 0.31 |
| hot path inlined; split roots to front | 0.83 | all groups ~0.93 |
| prefetch in bucket and child walk | 0.95 | punch 0.92 |
| path segments for long pushes | 0.98 | rmf-wide 0.85/step |
| 64-bit excess (correctness) | 1.01 | two rmf-wide instances become correct |

## What Didn't Work

- **LIFO buckets:** help vision by up to 30% but slow rmf by 1.4-2.4x, and no
  per-instance signal separated the two regimes, so it could not be adopted.
- **Merge along the largest-capacity candidate arc:** halves rmf-long pushes
  (242M -> 81M) but is 1.6-6x slower on rmf-wide; again no cheap regime signal.
- **Exact initial labels / global relabeling / lifting trees:** no-ops in
  highest-label pseudoflow (labels already exact), as above.
- **Compiler-level tricks** (PGO, `-march=native`) were deliberately out of scope
  (source-only goal), so they are not part of the result; worth remembering that
  a fair "engineering" comparison usually holds the build fixed.
- The last ~10 hypotheses cleared nothing above noise; profiles put the remaining
  time in the relabel scans, bound by memory latency on large instances and
  branch mispredictions on small ones. A useful stopping signal.

## Code Example

Direction rule, pseudocode (run before adjacency lists are built):

```
src_excess   = sum of capacities of arcs leaving the source
sink_deficit = sum of capacities of arcs entering the sink
if (src_excess > 1.5 * sink_deficit)    // threshold fitted in-sample
    solve with s and t swapped (arcs reversed)
else
    solve as given
```

## Environment

C, `gcc -O4`, single-threaded, Intel Xeon w5-3435X. Target: Hochbaum pseudoflow
3.23, highest-label FIFO. The direction idea transfers to any
augmenting/preflow max-flow or min-cut solver whose cost is asymmetric in s-t
orientation; the "profile the recovery phase" and "instrument before importing a
textbook optimization" lessons are general. **Caveat:** all tuning was in-sample
and the thresholds (1.5 excess ratio, 1% terminal-node rule for split roots,
segment length 32) were fitted on this instance set, so re-tune per benchmark.
Developed with Agentic Algorithm Engineering; the study is described in the AAE
paper (13th DIMACS Implementation Challenge, 2027).

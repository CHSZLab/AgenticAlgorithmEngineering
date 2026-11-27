# Grid Dijkstra flow fields under an unoptimizing managed runtime (C#, Unity editor Mono)

## Problem

A tower-defense game builds one flow field per destination on every map change: an
8-connected grid Dijkstra (orthogonal step 10, diagonal step 14, no corner cutting) that
writes an integer cost-to-go and a "best neighbor" direction byte for every cell. A
recompute runs 5 floods (3 single-source, 2 multi-source) over one obstacle grid.

Metric: wall time of one recompute, as the geometric mean of per-case medians over 9
synthetic grids (64², 128², 256² × open, 30% random obstacles, serpentine maze).
Correctness: costs had to match the original exactly. Equal-cost ties in the direction
byte were allowed to change, provided every direction still points one step along a
shortest path.

Starting point: idiomatic C# with a `Vector2Int` struct per neighbor, an obstacle
interface called per neighbor (`InBounds`, `IsHardBlocked`), a static direction table,
and a binary heap of `(int, Vector2Int)`.

## What Worked

Baseline 40.02 ms to 2.86 ms (-92.9%) in 10 experiments. In order of size:

1. **Flat-index kernel (-79%).** Replace `Vector2Int` neighbors, interface calls and the
   direction table with fixed offsets (`i ± 1`, `i ± w`, `i ± w ± 1`) over a flat `bool[]`.
   I predicted -50%. The unoptimizing JIT made per-neighbor struct construction and
   calls far more expensive than expected.
2. **Dial's bucket queue (-46%).** Step costs are two small integers, so every live key
   lies in `[g, g + max(step)]`, and a ring of `max(step) + 1` LIFO buckets gives O(1) push and
   pop. Buckets only ever hold the frontier, so the per-flood O(n) heap allocation
   disappears too. This changes equal-cost pop order, so you need correctness assertions
   that allow ties to change.
3. **Write helpers out by hand (-14%, then -6%).** The runtime did not inline small
   static helpers. Writing the relax step out for each of the 8 directions gave -14%;
   moving the queue push into the kernel gave another -6%.
4. **Drain a bucket in one pass (-12%).** With positive step costs, nothing is pushed
   into the bucket being drained. Its array and length, `g + ortho`, `g + diag`, and both
   target buckets are constant for the whole drain, so compute them once per bucket, not
   once per pop. I predicted -5%. The runtime hoists nothing, so every invariant load
   shows up in the timing.
5. **Per-grid neighbor mask, built without branches (-4.8%, then -3.8%).** One byte per
   cell, where bit d means "step d stays in bounds, lands on a passable cell, and doesn't
   cut a corner". It is built once per grid and shared by all floods, and it removes the
   per-pop `idx / w` division plus up to 12 bounds and obstacle reads. The first build
   used `&&` chains and made random-obstacle grids *slower* (branch mispredictions on
   obstacle data). Block-copying the `bool[]` into `byte[]` (0/1) and combining bits with
   `&`, `|` and `<<` for interior cells fixed that.
6. **Fill output arrays with doubling `Array.Copy` (-5%).** `log2(n)` block copies instead
   of an n-step loop to set Unreachable and 0xFF.

Method notes that saved time:
- **Time each part separately in the harness, not in the code under test.** Timing
  single-source floods, multi-source floods and the grid copy on their own made each
  multi-component experiment readable. The part whose code didn't change served as a
  contamination control: one run where it read 2.7x its usual value (host load average
  of 13 on 10 cores) was thrown out and rerun.
- **A part that skips a cost is a natural control.** The multi-source part reused a
  cached mask across reps, so it stayed flat when only the mask build changed. That
  confirmed the build was where the gain came from.

## Experiment Data

| exp | change | ms | vs previous |
|---|---|---|---|
| 001 | baseline | 40.02 | |
| 002 | flat-index kernel (2 components) | 8.46 | -78.9% |
| 003 | relax step written out per direction | 7.32 | -13.5% |
| 004 | Dial bucket queue | 3.95 | -46.0% |
| 005 | doubling Array.Copy fill (2 components) | 3.74 | -5.3% |
| 006 | queue push written into the kernel | 3.52 | -6.0% |
| 007 | per-grid neighbor mask (branchy build) | 3.36 | -4.8% |
| 008 | branch-free mask build | 3.23 | -3.8% |
| 009 | dead-code removal (simplification) | 3.25 | neutral |
| 010 | drain each bucket in one pass | 2.86 | -12.0% |

Run-to-run noise was about ±2.5%. Results under 5% were rerun, and kept only when two
readings agreed within 0.5%.

## What Didn't Work

- The first mask build, with `&&` chains on obstacle data: random-obstacle grids
  regressed 2-7% until the build was made branch-free (see 5 above).
- My predictions undershot the call and invariant-hoisting wins every time (002, 004,
  010). On an unoptimizing JIT, assume overhead is bigger than a native intuition
  suggests.

Rejected without running:
- A fast path for grid copies when the source is already a snapshot. It only helps
  the benchmark's input type; production passes a different obstacle source. That's
  overfitting to the harness.
- Threading the floods across fields. The deployment target (WebGL) is single-threaded.

## Code Example

```text
// mask[i] bit d: step d from cell i is in bounds, passable, and not a corner cut.
while (count > 0):
    if len[cb] == 0: key++; cb = (cb + 1) % span; continue
    cur = bucket[cb]; l = len[cb]; len[cb] = 0; count -= l
    go = key + ortho; gd = key + diag              // constant for the drain
    bo = (cb + ortho) % span; bd = (cb + diag) % span
    while l > 0:
        ci = cur[--l]
        if key > cost[ci]: continue                // stale
        m = mask[ci]
        if m & E:  relax(ci + 1, go, bo)           // written out, not called
        if m & NE: relax(ci + w + 1, gd, bd)
        ... 6 more directions
```

## Environment

C# in the Unity 6 editor (Mono JIT, batch mode, very likely Debug code optimization),
Apple M1 Max. The shipped build is IL2CPP to WebAssembly, where an optimizing compiler
should shrink the call and invariant-hoisting wins (3, 4, 6 above). The algorithmic wins
(1 partly, 2, 5) should carry over.

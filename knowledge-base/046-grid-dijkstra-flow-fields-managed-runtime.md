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

Baseline 40.02 ms to 2.45 ms (-93.9%, 16.4x) in 15 experiments. In order of size:

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
6. **Prune relaxations the parent already covered (-5.6%, then -3.6%).** If a popped
   cell's back-pointer is direction b, then directions b-1, b and b+1 lead to the parent
   or to cells the parent (finalized earlier) already relaxed at a strictly lower cost.
   After a diagonal arrival, with ortho <= diag, b-2 and b+2 go too: the no-corner-cut
   rule means both shared-edge cells are passable, and each reaches that far corner at
   parent + 2*ortho. One 256-entry table lookup per pop (`mask & keep[best]`) replaces up
   to 5 failing checks. The output is exactly unchanged, ties included.
7. **Fill output arrays with doubling `Array.Copy` (-5%).** `log2(n)` block copies instead
   of an n-step loop to set Unreachable and 0xFF.
8. **Build the neighbor mask 8 cells per `ulong` (-3.3%).** Block-copy the 8 shifted
   neighbor views of each row into `ulong[]` and run the same AND/OR/shift formula on 8
   cells at once. Bytes stay 0/1 and shifts are at most 7, so no bit crosses into the next
   cell's byte. The build fell about 40%, not the 8x the operation count suggested,
   because the per-row copies cost too.

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
| 011 | ref locals for target buckets | 3.18 | +11.2% (discarded) |
| 012 | snapshot copy: hoist interface bounds | 2.78 | -2.9% |
| 013 | prune b-1..b+1 toward the parent | 2.62 | -5.6% |
| 014 | also prune b+-2 after diagonal arrival | 2.53 | -3.6% |
| 015 | word-parallel mask build | 2.45 | -3.3% |

Run-to-run noise was about ±2.5%. Results under 5% were rerun, and kept only when two
readings agreed within 0.5%.

## What Didn't Work

- **Ref locals (+11%, discarded).** Holding `ref int[]` / `ref int` to the two target
  buckets for a drain, so each push becomes a dereference, made things slower. Under
  this runtime a managed-pointer dereference costs more than a bounds-checked element
  access on a local array. Hoisting into plain locals pays; hoisting into refs doesn't.
- The first mask build, with `&&` chains on obstacle data: random-obstacle grids
  regressed 2-7% until the build was made branch-free (see 5 above).
- My predictions undershot the call and invariant-hoisting wins every time (002, 004,
  010). On an unoptimizing JIT, assume overhead is bigger than a native intuition
  suggests.

- A contaminated run: once, the unchanged-code control read 2.7x its usual value under
  host load, and the run was discarded. Rule adopted afterwards: rerun whenever the
  control moves by more than 20%.

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
should shrink the call and invariant-hoisting wins (3, 4, 7, 8 above). The algorithmic wins
(1 partly, 2, 5, 6) should carry over. These numbers come from the editor, not from a
WebAssembly build.

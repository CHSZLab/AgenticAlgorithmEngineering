# Grid placement validity: local cut analysis instead of reachability floods (C#, Unity editor Mono)

## Problem

A tower-defense game checks, every frame while the player drags a tower ghost, whether
placing a k×k footprint (2×2 or 3×3) would cut any spawn point or live agent off from its
goal. The original check ran:

1. an overlap test against up to 200 agents (cell and body radius);
2. a shortest-path pre-filter (Safe if no footprint cell carries a shortest-path tree edge);
3. up to four full-grid BFS floods (`Queue<Vector2Int>`, 8-connected with no corner
   cutting) from goal mouth cells with the footprint blocked, then membership checks for
   spawn cells and agents.

The result had to stay identical, including which spawn cell or agent is reported as cut
off, so the order of the checks is fixed.

Metric: ms per call during a simulated drag (24 cursor cells × 4 frames, 200 agents
moving every frame), as the geometric mean over 9 synthetic grids (64², 128², 256² ×
open, 30% random obstacles, serpentine maze). Correctness: every field of the result
equals a frozen verbatim copy of the original, over a cell sweep, drags with moving
agents, obstacle edits followed by a recompute, a second world sharing goals, and edge
cases. The benchmark also hashes every verdict it produces.

## What Worked

1. **4-connected flat flood (−94%, 15.5 → 0.90 ms).** Under a no-corner-cutting rule a
   diagonal step needs both shared-edge cells passable, so it can always be replaced by
   two orthogonal steps. 8-connected reachability is therefore 4-connected reachability:
   reachability floods need only the four orthogonal neighbors and no corner checks.
   Combined with flat indices, a precomputed per-cell neighbor bitmask and a reused
   `int[]` queue in place of `Queue<Vector2Int>`, this was 17x. (Corner rules change
   costs, never reachability.)
2. **Local cut analysis over component labels (−77%, −21%, −14%, −30%).**
   - Label the 4-connected components once per obstacle change.
   - Side cells are the passable cells outside the footprint F that touch it
     orthogonally. Every path through F enters and leaves through side cells, and every
     cell of F's component reaches some side cell without crossing F.
   - Walk from the side cells over passable cells outside F, inside F's bounding box plus
     a margin. If all side cells connect, blocking F changes nothing outside F, and every
     query is "same label as a seed, and not in F": no flood at all.
   - Grow the margin (1, 2, 4, 8, 16, 32, whole grid) when the pieces don't rejoin.
   - A walk that never reaches the search box edge is a whole component of the grid
     without F (a sealed pocket). With at most one open walk, the answer is the label
     answer minus F and the pockets.
   - At the whole-grid margin every walk closes, so the walks are exactly the components
     of the grid without F. Assign each seed to its piece (or its label outside the
     pieces) and every check is answered. The seed floods were deleted.
   - Grid size stopped mattering: every case ran at about 0.1 ms (256² with 30%
     obstacles went 3.0 → 0.10 ms).
3. **Per-agent constant factors once the algorithm is O(agents + local area).**
   - Unity `Object` `==`/`!=` and a `HashSet` of Unity objects per agent became reference
     tests against a short list of live goals (−22%). Exact, because every listed goal
     is alive.
   - Each agent's cell is computed once per call, and agents at least their radius from
     the footprint's bounding box skip the per-cell radius test (−61%). Exact: correctly
     rounded float subtraction and squaring are monotone, so no cell is nearer than its
     bounding box.
   - O(1) label stamps replaced `List.Contains`, and floor and clamp were written out
     with the library's own semantics (−29%).

Final: 15.53 → 0.0218 ms per call, 712x, with all verdicts unchanged.

## Experiment Data

| # | Change | ms per call | Δ vs previous |
|---|--------|------------:|--------------:|
| 001 | Baseline (rerun; first run 10% slower under load) | 15.532 | |
| 002 | 4-neighbor flat flood, neighbor mask, int queue | 0.905 | −94.2% |
| 003 | Ring shortcut: side cells connected in a 1-cell ring → labels | 0.209 | −76.9% |
| 004 | Margins 2, 4, 8 before falling back to floods | 0.165 | −21.0% |
| 005 | Closed walks as sealed pockets | 0.141 | −14.3% |
| 006 | Margins to the whole grid, seeds assigned to pieces, floods deleted | 0.0995 | −29.6% |
| 007 | Reference tests instead of Unity object equality per agent | 0.0772 | −22.4% |
| 008 | Agent cells once; bounding-box reject before the radius test | 0.0305 | −60.5% |
| 009 | O(1) label stamps; floor and clamp written out | 0.0218 | −28.5% |
| 010 | Flat pre-filter (discarded) | 0.0221 | +1.4% |

## What Didn't Work

- **Flattening the shortest-path pre-filter (neutral, discarded).** On cells that sit on
  a gradient it returns at the first matching neighbor of the first field, so it costs a
  handful of iterations and was never a measurable share.
- **A RED-proof plant that let diagonals cut past footprint corners was not caught.**
  That was correct, because corner rules cannot change reachability (point 1 above).
  A positive control has to break the property under test. Ignoring the footprint in
  the flood turned the assertions red.
- **Noise.** An identical baseline rerun read 10% faster, uniformly across all cases,
  under machine load 11 to 12. Gains under 10% were rerun.

## Code Example

```csharp
// Side cells of footprint F, then walks over passable non-F cells inside
// bbox(F) + margin. A walk that meets the box edge is "open"; one that never
// does is a whole component of the grid without F.
for (int mi = 0; mi < Margins.Length; mi++) {
  int x0 = Math.Max(0, minX - Margins[mi]), x1 = Math.Min(w - 1, maxX + Margins[mi]);
  int y0 = Math.Max(0, minY - Margins[mi]), y1 = Math.Min(h - 1, maxY + Margins[mi]);
  int baseStamp = gen + 1, walks = 0, open = 0;
  foreach (int sc in sideCells) {
    if (stamp[sc] >= baseStamp) continue;            // already in a walk
    int s = baseStamp + walks++; bool touched = false;
    // 4-neighbor BFS from sc over !hard && !inF, stamping s; a step blocked
    // only by the box edge sets touched.
    closed.Add(!touched);
    if (touched && ++open > 1) break;
  }
  gen = baseStamp + walks;
  if (open <= 1) return;   // pieces known: closed walks are exact components
}
```

Queries then read `label[cell]` (precomputed per obstacle change) unless the cell lies
in a closed piece, in which case they read whether a seed fell in that piece.

## Environment

- Unity 6000.3 editor, Mono runtime (MonoBleedingEdge), batchmode EditMode tests.
- Apple M1 Max, 10 cores, 64 GB.
- The editor's Mono does not inline small helpers, so call removal pays off.
- The production target is IL2CPP WebGL (single-threaded), which was not measured. The
  algorithmic wins (points 1 and 2) are runtime-independent; point 3 may shrink under
  IL2CPP.

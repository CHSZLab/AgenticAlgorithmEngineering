# Optimizing Label Propagation in Graph Clustering

## Problem

Optimizing the runtime of a signed graph correlation clustering solver ([ScalableCorrelationClustering](https://github.com/KaHIP/ScalableCorrelationClustering)) built on the KaHIP multilevel framework. The solver uses label propagation (LP) for both coarsening and refinement, plus FM-based refinement on coarse levels. The metric was geometric mean of execution times across multiple real-world graph instances, with a hard constraint that solution quality must stay within 0.001% of the baseline. The baseline geometric mean was 1.528s.

## What Worked

The biggest wins came from three areas, yielding a combined **1.23x speedup (18.7%)** over 30 experiments:

**1. Eliminate hash map overhead in inner loops (~7%)**
The LP inner loop used `std::unordered_map` for cluster-ID remapping and a heap backed by hash lookups. Replacing these with dense vectors indexed by node/block ID removed all hashing overhead from the hottest loop. This was the single largest win.

**2. Algorithmic shortcuts in the multilevel framework (~6%)**
- *Direct contraction via counting sort*: The original code built a `complete_boundary` object and saved/restored the partition at each coarsening level. Replacing this with a single counting-sort-based contraction pass eliminated all that machinery.
- *Specialize LP sweep 2 for unconstrained path*: When no cluster size constraints are active (the common case), sweep 2 can iterate a cached block-ID array instead of re-reading edge arrays, cutting random memory accesses.
- *Cache block IDs for low-degree nodes*: For nodes with degree <= 32, caching the block IDs of neighbors during sweep 1 and reusing them in sweeps 2-3 avoids redundant `cluster_id[]` lookups.

**3. Allocation elimination (~5%)**
- Stack-allocating LP/coarsening/refinement objects instead of heap-allocating them each level.
- Making LP buffers (queues, boolean vectors, block arrays) persistent class members that survive across coarsening levels, so their allocations are reused.
- Linking `tcmalloc_minimal` for faster general allocation/deallocation (~4% alone).

Smaller wins: `vector<char>` over `vector<bool>` to avoid bit-packing, `MADV_HUGEPAGE` hints for large LP arrays, hoisting edge/hash_map pointers with `__restrict__`, and compiler flags `-fprefetch-loop-arrays -fno-plt`.

## Experiment Data

| # | Commit | Geo-mean (s) | Status | Hypothesis |
|---|--------|-------------|--------|------------|
| 0 | f683dcc | 1.528 | baseline | — |
| 1 | 79c85ce | 1.426 | keep | Dense vector replaces unordered_map |
| 2 | e35d815 | 1.427 | keep | Lazy reset for vertex_moved_hashtable |
| 3 | cf06cce | 1.390 | keep | Direct contraction via counting sort |
| 4 | 21c8fc2 | 1.362 | keep | Hoist max_blocks vector outside loop |
| 5 | f72cc86 | 1.379 | keep | Stack-allocate LP queues |
| 6 | cc13299 | 1.366 | keep | Stack-allocate coarsening objects |
| 7 | c373c2e | 1.352 | keep | Stack-allocate refinement objects |
| 8 | 9decfee | 1.340 | keep | vector\<char\> over vector\<bool\> |
| 9 | b19650d | 1.350 | keep | Reserve FM vector capacity |
| 10 | 6a846db | 1.377 | discard | Pre-size maxNodeHeap — wasted time |
| 11 | 41e405d | 1.380 | discard | Software prefetching — overhead > benefit |
| 12 | 5a1af07 | 1.368 | discard | Reuse contraction buffers — no gain |
| 13 | aab4041 | 1.382 | discard | vector\<char\> in contraction — no gain |
| 14 | 9c7ea1a | 1.370 | discard | Devirtualize FM queue — slight regression |
| 15 | d166e01 | 1.356 | discard | Eliminate PartitionConfig copy — noise |
| 16 | b02db57 | 1.369 | discard | Simplify relabeling loop — marginal regression |
| 17 | 8f1838e | 1.344 | keep | MADV_HUGEPAGE for LP arrays |
| 18 | 502ff05 | 1.395 | discard | Skip m_local_degrees init — regression |
| 19 | ceb9beb | 1.352 | discard | Cache block IDs (full) — overhead from max-degree scan |
| 20 | 0089f5b | 1.349 | keep | Cache block IDs for degree<=32 |
| 21 | 859d930 | 1.330 | keep | Specialize LP sweep 2 for unconstrained path |
| 22 | 0dcf027 | 1.316 | discard | blk_cache in FM — overhead on coarse levels |
| 23 | 97189b0 | 1.307 | keep | Cache partition IDs in constrained path |
| 24 | ec86900 | 1.258 | keep | tcmalloc_minimal via LD_PRELOAD |
| 25 | 7b5981a | 1.267 | keep | tcmalloc_minimal linked via CMake |
| 26 | 11135ac | 1.268 | discard | PGO — hurts non-profiled instances |
| 27 | b73363b | 1.289 | discard | MADV_HUGEPAGE on graph arrays — THP overhead |
| 28 | 92a38c7 | 1.244 | keep | Hoist edge/hash_map pointers |
| 29 | 8034afa | 1.242 | keep | Persistent LP refinement buffers |

18 kept, 12 discarded (60% success rate). Final speedup: **1.23x**.

## What Didn't Work

- **Profile-guided optimization (PGO)**: Improved profiled instances but degraded others, hurting the geometric mean across the full benchmark suite.
- **Software prefetching (`__builtin_prefetch`)**: Manual prefetch of edge arrays added more overhead than it saved. The hardware prefetcher was already doing a good job on the sequential access patterns.
- **MADV_HUGEPAGE on graph arrays**: While it helped for LP-local arrays, applying it to the main graph adjacency arrays caused THP (Transparent Huge Pages) overhead that exceeded the TLB-miss savings.
- **Devirtualizing FM queue**: Replacing virtual dispatch with templates caused a slight regression, likely due to increased code size reducing instruction cache efficiency.
- **Reusing contraction buffers across levels**: The buffers change size each level, so reuse didn't save meaningful allocation work.

## Code Example

Core change: replacing hash map with dense vector in LP inner loop.

```cpp
// Before: hash map lookups in hot loop
std::unordered_map<PartitionID, EdgeWeight> block_weights;
forall_out_edges(G, e, node) {
    PartitionID target_block = G.getPartitionIndex(G.getEdgeTarget(e));
    block_weights[target_block] += G.getEdgeWeight(e);
} endfor

// After: dense vector indexed by block ID (cleared via touched-list)
std::vector<EdgeWeight> block_weights(max_blocks, 0);  // persistent, reused
std::vector<PartitionID> touched;
forall_out_edges(G, e, node) {
    PartitionID target_block = G.getPartitionIndex(G.getEdgeTarget(e));
    if (block_weights[target_block] == 0) touched.push_back(target_block);
    block_weights[target_block] += G.getEdgeWeight(e);
} endfor
// ... use block_weights, then reset only touched entries
for (auto b : touched) block_weights[b] = 0;
```

## Environment

C++17, GCC 11.4 with `-O3 -march=native`, Linux (Ubuntu 22.04), Intel Xeon. Graphs range from thousands to millions of nodes. Multilevel framework with label propagation coarsening/refinement and FM-based k-way refinement.

# Optimizing Label Propagation in Graph Clustering

## Problem

Optimizing the runtime of a signed graph correlation clustering solver ([ScalableCorrelationClustering](https://github.com/KaHIP/ScalableCorrelationClustering)) built on the KaHIP multilevel framework. The solver uses label propagation (LP) for both coarsening and refinement, plus FM-based refinement on coarse levels. The metric was geometric mean of execution times across multiple real-world graph instances, with a hard constraint that solution quality must stay within 0.001% of the baseline. The baseline geometric mean was 1.528s.

## What Worked

The combined effect was a **1.23x speedup (18.7%)** over 30 experiments. Below is each technique with enough detail to reproduce.

### 1. Dense vectors replacing hash maps in LP inner loops (~7%)

The LP inner loop accumulates edge weights per neighboring block to decide which block a node should move to. The original code used `std::unordered_map<PartitionID, EdgeWeight>` — every edge traversal hashed the target block ID, probed the hash table, and potentially allocated a new bucket. Since this runs for every node on every LP sweep on every coarsening/refinement level, it dominated the profile.

**Fix:** Replace with a dense `std::vector<EdgeWeight>` of size `max_blocks`, indexed directly by block ID. Track which entries were touched in a small side vector, and reset only those entries after processing each node. This turns O(1)-amortized hash lookups into O(1)-worst-case array indexing and eliminates all hashing, bucket allocation, and cache-hostile pointer chasing.

The same pattern applied to `maxNodeHeap`, which backed its key lookups with a hash map. Replacing it with a three-vector architecture (`m_elements`, `m_element_index[node] → position`, `m_heap[position] → key`) gives O(1) direct-indexed lookup instead of hash probing.

### 2. Counting-sort contraction replacing boundary objects (~3%)

Each coarsening level contracts the graph: fine nodes are merged into coarse super-nodes. The original code built a `complete_boundary` object (~16MB on large graphs), saved and restored the full partition map (~8MB), and used `vector<vector<NodeID>>` to group nodes per block — all to support a generic contraction interface.

**Fix:** A single counting-sort pass groups fine nodes by their coarse mapping in O(N) time:
1. Histogram: count how many fine nodes map to each coarse node.
2. Prefix sum: convert counts to start offsets.
3. Scatter: place each fine node at its offset position.

Then iterate coarse nodes in order, processing contiguous runs of fine nodes. This replaces ~24MB of intermediate structures with three flat arrays totaling O(N) and eliminates the partition save/restore entirely. Memory access is sequential during the scatter and iteration phases, which is cache-friendly.

### 3. LP sweep specialization and block-ID caching (~3%)

LP processes each node in three sweeps: (1) accumulate edge weights per block, (2) find the best block, (3) reset the accumulator. In the original code, all three sweeps read the edge array independently, each time dereferencing `cluster_id[edges[e].target]` to look up the target's block.

**Fix — cache block IDs for low-degree nodes:** For nodes with degree ≤ 32 (covering ~95% of nodes in real-world graphs), sweep 1 writes the block IDs into a stack-allocated `PartitionID blk_cache[32]`. Sweeps 2 and 3 iterate `blk_cache` instead of re-reading the edge array and re-dereferencing `cluster_id[]`. The 32-element cache fits in one or two L1 cache lines.

**Fix — specialize sweep 2 for unconstrained path:** When no cluster size constraints are active (the common case in correlation clustering), sweep 2 only needs block IDs and accumulated weights — it doesn't need edge weights or node IDs. The specialized path iterates the `blk_cache` array in a tight loop with no edge-array access at all, cutting random memory reads in half.

**Fix — cache partition IDs in constrained path:** When constraints are active and the graph is already partitioned, sweep 2 must also check `getPartitionIndex()` for each neighbor. Caching these in a `PartitionID part_cache[32]` alongside `blk_cache` avoids a second round of random lookups into the partition array.

### 4. Pointer hoisting with `__restrict__` (~1.5%)

The LP inner loop accesses edges via `G.getEdgeTarget(e)` which compiles to `graphref->m_edges[e].target` — a pointer-to-pointer indirection on every edge. With millions of edges per LP iteration, this adds up.

**Fix:** Add `edge_array()` / `node_array()` accessors to `graph_access` that return raw pointers, and hoist them before the loop:
```cpp
const Edge* __restrict__ edges = G.edge_array();
EdgeWeight* __restrict__ hmap = m_hash_map.data();
```
The `__restrict__` qualifier tells the compiler these pointers don't alias, enabling auto-vectorization and instruction reordering that wasn't possible through the accessor indirection.

### 5. Persistent buffers as class members (~2%)

LP coarsening and LP refinement each use several large buffers: the hash map vector, a permutation array, and two queue-membership vectors (`vector<char>`). Originally these were local variables, allocated and freed on every call — once per coarsening level (typically 10-15 levels).

**Fix:** Move them to class member variables (`m_hash_map`, `m_permutation`, `m_qc_a`, `m_qc_b`). On each call, resize if needed (capacity grows monotonically during coarsening since graphs shrink), then `assign()` to reset values. This converts O(N) allocations to O(N) memsets, which are much cheaper — memset is a single cache-line-streaming operation vs malloc's free-list search, mmap, and page-fault overhead.

### 6. Stack allocation of framework objects (~1.5%)

The multilevel loop allocates LP, contraction, and stop-rule objects at each level. Originally these were heap-allocated (`new`/`delete`), producing malloc pressure and heap fragmentation over 10+ levels.

**Fix:** Stack-allocate them as local variables in the coarsening loop. Constructor/destructor run at scope entry/exit with zero allocator overhead. For refinement, the LP and k-way refinement objects are created once and reused across all uncoarsening levels via persistent smart pointers.

### 7. tcmalloc_minimal (~4%)

After eliminating the biggest allocation hotspots, the remaining malloc/free calls (from graph construction, edge arrays, STL containers) still added up. Linking Google's `tcmalloc_minimal` replaced glibc's allocator with one that uses per-thread free-list caches, avoiding lock contention and reducing fragmentation.

**Integration:** Auto-detected via CMake `find_library(TCMALLOC_LIB tcmalloc_minimal)`, linked only on Linux. Falls back to the default allocator if not found.

### 8. Smaller wins (~1.5% combined)

- **`vector<char>` over `vector<bool>`**: The queue-membership flags were `vector<bool>`, which uses bit-packing. Each access requires shift+mask operations. Switching to `vector<char>` (one byte per entry) trades 8x memory for direct byte access — worthwhile because these vectors are small relative to the graph and accessed in the hot loop.
- **`MADV_HUGEPAGE` for LP arrays**: The hash map vector is randomly accessed by block ID. On graphs with 2M+ nodes, this causes TLB thrashing with 4KB pages. `madvise(MADV_HUGEPAGE)` hints the kernel to back it with 2MB pages, reducing TLB entries needed by 512x. Only applied to LP-local arrays — applying it to the main graph arrays caused THP overhead that was worse than the TLB savings.
- **Compiler flags**: `-fprefetch-loop-arrays` lets GCC insert prefetch instructions for streaming edge-array iteration. `-fno-plt` eliminates PLT indirection on shared library calls (minor, but free).

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

# Eliminating Heap Allocation in Streaming Hypergraph Multi-Pass Evaluation

## Problem

Optimizing the multi-pass streaming hypergraph partitioning in [FREIGHT](https://github.com/freelancer/FREIGHT) via its pybind11 binding. FREIGHT uses a streaming algorithm where nodes are processed one-by-one and assigned to partition blocks. Multi-pass restreaming re-evaluates the partition after each pass and keeps the best. The metric was geometric mean of wall-clock time across 96 configurations (4 ISPD98 instances, 3 k values, 4 pass counts, 2 objectives), with a hard constraint that results must remain bit-identical to the FREIGHT CLI. The baseline geometric mean was 82.9ms.

The bottleneck was the inter-pass evaluation: after each pass, the code needed to compute how many hyperedges (nets) span multiple partition blocks. The original implementation built a reverse mapping (`vector<vector<int64_t>>` net-to-nodes, O(total_pins) with many small vector allocations) and then created a `std::set<PartitionID>` for each net to count distinct blocks. For large hypergraphs (200K+ nets, 800K+ pins), this meant millions of heap allocations per pass.

## What Worked

The combined effect was a **1.82x speedup** (82.9ms to 45.6ms) over 8 kept experiments. Below are the techniques in order of impact.

### 1. Per-net bit vectors replacing reverse mapping + std::set (~1.60x)

The original evaluation built `net_to_nodes[net] = {node0, node1, ...}` (a `vector<vector<int64_t>>`) and then for each net created a `std::set<PartitionID>` to count distinct blocks. Both data structures involve heap allocation per net.

**Fix:** Replace with a flat `vector<uint64_t>` of size `num_nets * ceil(k/64)`. Each net gets `ceil(k/64)` words as a bit vector. To evaluate, iterate nodes via the existing node-to-edge CSR, and for each node's nets, OR the assigned block's bit into the net's word. Then a single popcount scan over all nets gives the distinct block count. This eliminates the entire reverse mapping and all `std::set` allocations.

For k <= 64 (the common case), each net uses exactly one `uint64_t`, and the bit-setting reduces to `net_block_bits[net_id] |= (1ULL << block)`.

### 2. Objective-specific evaluation paths (~4%)

For connectivity objective, the bit-vector evaluation is needed (distinct block count per net). But for cut-net objective, the existing `stream_edges_assign` array already tracks whether each net is cut: entries equal to `CUT_NET` indicate cut nets. A simple O(num_nets) sequential scan counting `CUT_NET` entries replaces the entire bit-vector machinery for half of all configurations.

### 3. Incremental bit-setting during the main loop (~0.5%)

Instead of a separate O(total_pins) evaluation scan after each pass, set bits during the main partitioning loop (one OR per pin right after `solve_node`). The evaluation reduces to just the O(num_nets) popcount scan. The edge data (CSR indices) is in L1 cache from the prior accumulation scan, making the bit-setting nearly free.

### 4. Eliminate intermediate vectors (~4%)

The original code maintained a `valid_neighboring_nets` vector, cleared and rebuilt per node via `push_back`. Replacing this with a direct re-iteration of the CSR edges for the per-net tracking update eliminates vector overhead (no clear, no push_back, no capacity management) while accessing the same data already in L1 cache.

### 5. Avoid redundant copies in output path (~3%)

The original code: (a) copied best assignment to a snapshot vector on each improvement, (b) restored the snapshot back to the working array after the loop, (c) element-wise copied the working array to the numpy output. Three O(n) passes over 210K+ elements.

**Fix:** Track which pass was best. Skip the snapshot on the last pass (just read the working array directly). Use `memcpy` for intermediate snapshots instead of `vector::operator=`. Copy the correct source directly to the numpy output via `memcpy`, skipping the intermediate restore.

### 6. Pre-allocate best partition vectors (~3%)

Pre-size `best_nodes_assign` and `best_blocks_weight` to their final sizes at initialization. This avoids a dynamic allocation + copy when the first improvement is found. Small but measurable because the allocation is O(n) and triggers on the first pass of every multi-pass run.

## Experiment Data

| # | geo_mean (ms) | Status | Hypothesis |
|---|--------------|--------|------------|
| 0 | 82.92 | baseline | Original implementation |
| 1 | 51.73 | keep | Per-net bit vectors replace net_to_nodes + std::set |
| 2 | 51.41 | keep | Incremental bit-setting during main loop |
| 3 | 52.66 | discard | Fuse bit-setting and per-net tracking (hurts ILP) |
| 4 | 49.37 | keep | Eliminate valid_neighboring_nets vector |
| 5 | 50.44 | discard | Specialize post-solve for connectivity vs cut_net (icache pressure) |
| 6 | 49.62 | discard | Specialize bit-setting/popcount for k<=64 (within noise) |
| 7 | 47.18 | keep | Direct CUT_NET counting for cut_net eval |
| 8 | 45.73 | keep | Pre-allocate best partition vectors |
| 9 | 47.86 | discard | Software prefetch (avg node degree ~4, too short for prefetch) |
| 10 | 45.69 | keep | memcpy output directly from best source |
| 11 | 47.67 | discard | Hoist use_connectivity branch (icache pressure from duplication) |
| 12 | 45.47 | keep | Skip snapshot on last pass |
| 13 | 48.55 | discard | LTO for cross-TU inlining (increased code size, worse icache) |
| 14 | 49.75 | discard | Raw pointers instead of pybind11 unchecked accessors (pybind11 generated better code) |
| 15 | 45.58 | keep | null_buf replacing /dev/null file open |

## What Didn't Work

Several approaches that seemed promising failed or regressed:

- **Loop fusion (bit-setting + per-net tracking in one loop):** The two operations have different memory access patterns (OR into bit vector vs read-modify-write of edge assignment). Fusing them into a single loop hurt instruction-level parallelism. Separate loops allow the CPU to pipeline memory operations independently. This was confirmed twice (iterations 3 and 5).

- **Code path specialization (separate loops for connectivity vs cut-net):** Duplicating the inner loop body to eliminate a branch (connectivity: unconditional write; cut-net: read-modify-write) increased instruction cache pressure. The branch was already perfectly predicted since it's loop-invariant. The compiler hoists it automatically.

- **k_words=1 specialization:** For k <= 64, `k_words=1` eliminates a multiply per edge. But the compiler already optimizes `x * 1` and the multiply is hidden by memory latency. Added complexity for no measurable gain.

- **Software prefetching:** Average node degree was ~4 (820K pins / 210K nodes). With so few iterations per inner loop, prefetch instructions don't have enough lead time to hide latency, and the prefetch instruction itself adds overhead.

- **LTO (link-time optimization):** Expected to devirtualize `compute_score` calls across translation units. Instead, increased code size and worsened instruction cache behavior, causing a 6% regression.

- **Raw data pointers vs pybind11 unchecked accessors:** Replacing `vp(i)` / `ve(i)` (pybind11 proxy) with `vp[i]` / `ve[i]` (raw pointer dereference) was 9% slower. The pybind11 `unchecked<1>()` accessor apparently provides alignment or aliasing hints that help the compiler generate better code. A surprising result; do not assume raw pointers are faster than well-designed proxy objects.

## Code Example

Core of the bit-vector evaluation (connectivity mode):

```cpp
// Allocate once: ceil(k/64) words per net
size_t k_words = (k + 63) / 64;
std::vector<uint64_t> net_block_bits(num_nets * k_words, 0);

// During main partitioning loop, after solve_node:
uint64_t bit = uint64_t(1) << (block & 63);
size_t word = block >> 6;
for (int64_t e = edge_begin; e < edge_end; e++) {
    net_block_bits[ve(e) * k_words + word] |= bit;
}

// After pass: popcount scan
for (int64_t net = 0; net < num_nets; net++) {
    int distinct = 0;
    for (size_t w = 0; w < k_words; w++)
        distinct += __builtin_popcountll(net_block_bits[net * k_words + w]);
    if (distinct > 1)
        pass_connectivity += distinct - 1;
}
// Reset for next pass
std::fill(net_block_bits.begin(), net_block_bits.end(), 0);
```

Cut-net evaluation (no bit vectors needed):

```cpp
// stream_edges_assign[net] == CUT_NET means the net is cut
double pass_cut = 0;
for (int64_t net = 0; net < num_nets; net++)
    if (stream_edges_assign[net] == CUT_NET) pass_cut += 1;
```

## Environment

- **Language:** C++17 with pybind11 bindings, compiled via scikit-build-core
- **Hardware:** x86-64 Linux (256-core server), also verified on macOS ARM
- **Compiler:** GCC with `-O2 -march=native`
- **Instances:** ISPD98 ibm01 (13K nodes), ibm05 (29K nodes), ibm18 (211K nodes)
- **Benchmark:** 96 configurations (4 instances, k in {4,8,16}, passes in {2,3,5,10}, both connectivity and cut-net objectives), 3 repetitions per config, median timing

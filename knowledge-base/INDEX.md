# Knowledge Base Index

Optimization techniques, experiment results, and lessons learned from AAE sessions contributed by the community. Agents should read this index to find entries relevant to their current problem, then read the linked files for details.

| # | Title | Problem Domain | Key Technique | File |
|---|-------|---------------|---------------|------|
| 001 | Cache-friendly blocked recursive sorting | Sorting, large arrays | Blocked partitioning with cache-line-sized buffers | [001-blocked-recursive-sorting.md](001-blocked-recursive-sorting.md) |
| 002 | Gradient accumulation as batch size proxy | Transformer training, limited VRAM | Gradient accumulation to simulate large batches | [002-batch-size-tuning-transformer.md](002-batch-size-tuning-transformer.md) |
| 003 | Arena allocation for JSON parsing | Parsing, memory allocation | Arena allocator to eliminate per-node heap allocation | [003-arena-allocation-json-parsing.md](003-arena-allocation-json-parsing.md) |
| 004 | SoA vs AoS for cache efficiency | Data layout, particle simulation | Structure of Arrays to maximize cache line utilization | [004-soa-vs-aos-cache-efficiency.md](004-soa-vs-aos-cache-efficiency.md) |
| 005 | Branchless programming | Array processing, partitioning | Arithmetic substitution for conditional branches | [005-branchless-programming.md](005-branchless-programming.md) |
| 006 | Small buffer optimization | String/container allocation | Inline buffer to avoid heap allocation for small objects | [006-small-buffer-optimization.md](006-small-buffer-optimization.md) |
| 007 | Move semantics avoiding deep copies | Container transfers, pipelines | RVO/NRVO and std::move for O(1) ownership transfer | [007-move-semantics-avoiding-copies.md](007-move-semantics-avoiding-copies.md) |
| 008 | constexpr compile-time computation | Lookup tables, constants | Compile-time evaluation to eliminate runtime initialization | [008-constexpr-compile-time-computation.md](008-constexpr-compile-time-computation.md) |
| 009 | False sharing avoidance | Multithreaded counters, parallel scaling | Cache line padding to prevent cross-core invalidation | [009-false-sharing-avoidance.md](009-false-sharing-avoidance.md) |
| 010 | PGO + LTO compiler optimizations | Whole-program optimization | Profile-guided and link-time optimization for 20%+ gains | [010-pgo-lto-compiler-optimizations.md](010-pgo-lto-compiler-optimizations.md) |
| 011 | Memory-mapped I/O for large files | File processing, large datasets | mmap for zero-copy lazy file access | [011-mmap-large-file-processing.md](011-mmap-large-file-processing.md) |
| 012 | Open-addressing hash maps | Lookup-heavy workloads | Flat hash maps (absl/robin_hood) vs std::unordered_map | [012-open-addressing-hash-maps.md](012-open-addressing-hash-maps.md) |
| 013 | SIMD vectorization for batch operations | Array math, distance computation | Explicit AVX2/SSE intrinsics for 4-16x element parallelism | [013-simd-vectorization-batch-ops.md](013-simd-vectorization-batch-ops.md) |
| 014 | Loop tiling for matrix operations | Matrix multiply, cache thrashing | Blocking iteration into cache-resident tiles | [014-loop-tiling-matrix-operations.md](014-loop-tiling-matrix-operations.md) |
| 015 | Compiler intrinsics for bit operations | Popcount, clz/ctz, Hamming distance | Hardware bit instructions via builtins/C++20 <bit> | [015-builtin-intrinsics-bit-operations.md](015-builtin-intrinsics-bit-operations.md) |
| 016 | Reserve and preallocate containers | STL containers, bulk insertion | reserve() to eliminate reallocations and copies | [016-reserve-preallocate-containers.md](016-reserve-preallocate-containers.md) |
| 017 | Hot-cold data splitting | Routing tables, large structs | Separate hot fields into dense array for cache density | [017-hot-cold-data-splitting.md](017-hot-cold-data-splitting.md) |
| 018 | std::string_view avoiding copies | Text parsing, function parameters | Non-owning string references to eliminate allocations | [018-string-view-avoiding-copies.md](018-string-view-avoiding-copies.md) |
| 019 | NumPy vectorization over Python loops | Array math, distance computation | Vectorized NumPy ops to bypass interpreter overhead | [019-numpy-vectorization-over-loops.md](019-numpy-vectorization-over-loops.md) |
| 020 | __slots__ for memory reduction | Object-heavy programs, graphs | Eliminate per-instance __dict__ for 69% memory savings | [020-slots-memory-reduction.md](020-slots-memory-reduction.md) |
| 021 | Generator expressions for memory efficiency | Data pipelines, streaming | Lazy evaluation with O(1) memory per pipeline stage | [021-generator-expressions-memory.md](021-generator-expressions-memory.md) |
| 022 | Numba JIT for numerical computation | Monte Carlo, simulations | LLVM JIT compilation for C-speed Python loops | [022-numba-jit-numerical-computation.md](022-numba-jit-numerical-computation.md) |
| 023 | multiprocessing for CPU-bound work | Image processing, batch computation | OS processes to bypass GIL for true parallelism | [023-multiprocessing-cpu-bound.md](023-multiprocessing-cpu-bound.md) |
| 024 | dict/set O(1) lookup vs list search | Membership testing, filtering | Hash-based containers for constant-time lookups | [024-dict-set-lookup-vs-list.md](024-dict-set-lookup-vs-list.md) |
| 025 | Memory-mapped files in Python | Large file processing, log search | mmap/np.memmap for lazy file access without full load | [025-mmap-large-datasets-python.md](025-mmap-large-datasets-python.md) |
| 026 | Local variable caching | Hot loops, attribute access | Cache globals/attributes as locals for faster bytecode | [026-local-variable-caching.md](026-local-variable-caching.md) |
| 027 | itertools for lazy pipelines | Data processing, combinatorics | C-speed lazy iterators for memory-efficient pipelines | [027-itertools-lazy-pipelines.md](027-itertools-lazy-pipelines.md) |
| 028 | struct module for binary data | Network protocols, file formats | Pack/unpack binary records without object overhead | [028-struct-binary-data-packing.md](028-struct-binary-data-packing.md) |
| 029 | Preallocation patterns | List/array construction | Preallocate at final size to avoid O(N²) resizing | [029-preallocation-patterns.md](029-preallocation-patterns.md) |
| 030 | String join vs + concatenation | String building, log formatting | join() for O(N) string assembly vs O(N²) += | [030-string-join-vs-concatenation.md](030-string-join-vs-concatenation.md) |
| 031 | deque vs list for queue operations | BFS, FIFO queues | collections.deque for O(1) popleft vs list O(N) | [031-deque-vs-list-queue-ops.md](031-deque-vs-list-queue-ops.md) |
| 032 | array module for typed numerical data | Compact storage, binary I/O | array.array for 72% memory reduction vs list | [032-array-module-typed-data.md](032-array-module-typed-data.md) |
| 033 | Cython for C-speed hot loops | Custom metrics, graph traversal | Typed Cython with memoryviews for 95x speedup | [033-cython-c-speed-hot-loops.md](033-cython-c-speed-hot-loops.md) |
| 034 | Optimizing label propagation in graph clustering | Multilevel graph clustering, LP refinement | Dense vectors, counting-sort contraction, sweep specialization, allocation elimination | [034-graph-clustering-lp-refinement.md](034-graph-clustering-lp-refinement.md) |
| 035 | Eliminating heap allocation in streaming hypergraph multi-pass evaluation | Streaming hypergraph partitioning, multi-pass evaluation | Per-net bit vectors with popcount, objective-specific eval paths, incremental bit-setting | [035-streaming-hypergraph-multipass-eval.md](035-streaming-hypergraph-multipass-eval.md) |

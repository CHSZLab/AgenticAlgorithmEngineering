# Small Buffer Optimization to Avoid Heap Allocations

## Problem

High-frequency allocation and deallocation of small, variable-sized objects in C++ (e.g., short strings, small vectors, temporary buffers). The metric was throughput of an operation that creates and destroys thousands of small containers per call. Baseline used `std::string` and `std::vector` which heap-allocate even for tiny sizes, causing allocator contention and cache misses from pointer chasing.

## What Worked

Small Buffer Optimization (SBO) embeds a fixed-size buffer directly inside the object. If the data fits in the inline buffer, no heap allocation occurs. This is the technique behind `std::string`'s SSO (Short String Optimization, typically 15-22 bytes inline depending on implementation) and can be applied to any container.

For a tokenizer producing millions of short tokens (avg. 8 bytes), switching from `std::string` to a custom SBO string with 32-byte inline buffer eliminated 94% of heap allocations and improved throughput by 1.7x. The key insight: even when SSO is already active in `std::string`, the default inline size (typically 15 bytes on libstdc++) may be too small for the workload. A custom SBO with a tuned buffer size can outperform.

## Experiment Data

| Variant | Tokens/sec (M) | Heap Allocs (millions) |
|---------|----------------|----------------------|
| std::string (SSO=15) | 4.2 | 3.1 |
| SBO string (inline=32) | 7.1 | 0.19 |
| SBO string (inline=64) | 6.8 | 0.04 |

Inline 64 had slightly lower throughput than 32 because the larger object size reduced cache density for the token array itself.

## Code Example

```cpp
template<size_t InlineSize = 32>
class SmallString {
    size_t size_;
    union {
        char inline_buf_[InlineSize];
        char* heap_ptr_;
    };
    bool is_heap() const { return size_ >= InlineSize; }
public:
    char* data() { return is_heap() ? heap_ptr_ : inline_buf_; }
    // ... constructor allocates on heap only when size >= InlineSize
};
// Same pattern applies to SmallVector<T, N>: inline storage for N elements
```

## Environment

C++17, GCC 13.1 with `-O3`, libstdc++, Intel Core i7-12700K, Ubuntu 22.04.

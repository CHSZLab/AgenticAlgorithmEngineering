# constexpr for Compile-Time Computation

## Problem

C++ programs that repeatedly compute fixed lookup tables, mathematical constants, or configuration-derived values at runtime. The metric was startup latency and hot-loop throughput. Baseline computed sine/cosine tables, CRC tables, and hash seeds on every program start or once-per-call with static locals.

## What Worked

Moving deterministic computations to compile time using `constexpr` (and `consteval` in C++20). The compiler evaluates the expressions during compilation, embedding the results directly into the binary as constants. This eliminates:
- Runtime initialization cost (especially for large tables)
- Branch/guard overhead for lazy static initialization
- Cache misses from touching cold memory during init

A 256-entry CRC32 lookup table computed at compile time saved 1.2μs of startup time per instantiation and allowed the table to live in `.rodata` (read-only, shareable across processes). For a packet processing loop using this table, throughput improved 8% because the optimizer could see the table contents and optimize access patterns.

## Code Example

```cpp
// C++17: constexpr lookup table generation
constexpr std::array<uint32_t, 256> make_crc_table() {
    std::array<uint32_t, 256> table{};
    for (uint32_t i = 0; i < 256; i++) {
        uint32_t crc = i;
        for (int j = 0; j < 8; j++)
            crc = (crc >> 1) ^ (0xEDB88320 & (-(crc & 1)));
        table[i] = crc;
    }
    return table;
}
constexpr auto crc_table = make_crc_table(); // computed at compile time

// C++20: consteval guarantees compile-time evaluation
consteval auto make_sin_table() { /* ... */ }
```

## What Didn't Work

- **Very large constexpr tables** (>64KB): Some compilers hit constexpr evaluation step limits or produce enormous compile times. GCC's `-fconstexpr-ops-limit` may need increasing. For huge tables, code generation (offline script writing a `.cpp` file) is more practical.

## Environment

C++17 minimum (`constexpr` functions), C++20 for `consteval`. GCC 12+, Clang 15+, MSVC 19.30+.

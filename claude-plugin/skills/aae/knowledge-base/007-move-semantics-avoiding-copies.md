# Move Semantics to Eliminate Expensive Deep Copies

## Problem

C++ programs that return or transfer ownership of large containers (vectors, strings, maps) from functions, causing unnecessary deep copies. The metric was function call overhead for routines returning `std::vector<double>` with 1M+ elements.

## What Worked

Three techniques at different levels:

1. **Return value optimization (RVO/NRVO)**: The compiler elides the copy entirely when a function returns a local variable by name. This is guaranteed in C++17 for prvalues (copy elision). Ensure the function has a single, named return variable — multiple return paths can prevent NRVO.

2. **`std::move` for transfers**: When moving an object to a new owner (e.g., pushing into a container or passing to a constructor), `std::move` converts the lvalue to an rvalue reference, triggering the move constructor. A moved `std::vector` transfers pointer ownership in O(1) instead of copying N elements.

3. **Emplace instead of insert**: `container.emplace_back(args...)` constructs the object in-place, avoiding both copy and move. Particularly impactful when the object is expensive to construct.

For a pipeline that passed `vector<double>(1M)` through 5 transformation stages, ensuring moves instead of copies reduced stage-transition overhead from 4.2ms to <0.001ms per transfer.

## What Didn't Work

- **Moving from `const` references**: `std::move(const_ref)` silently falls back to a copy because the move constructor requires a non-const rvalue reference. This is a common silent performance bug — no compiler warning by default.
- **Moving small types**: For types smaller than two pointers (e.g., `std::pair<int,int>`), move is identical to copy. The overhead of thinking about moves is wasted.

## Code Example

```cpp
// BAD: forces copy if NRVO fails (multiple return paths)
std::vector<double> compute(bool flag) {
    std::vector<double> a = heavy_compute_a();
    std::vector<double> b = heavy_compute_b();
    if (flag) return a; // NRVO may fail — two candidates
    return b;
}

// GOOD: single return variable, guaranteed NRVO
std::vector<double> compute(bool flag) {
    std::vector<double> result;
    if (flag) result = heavy_compute_a();
    else      result = heavy_compute_b();
    return result; // NRVO: single named variable returned
}

// Transfer ownership explicitly
pipeline.add_stage(std::move(large_vector)); // O(1) pointer swap
```

## Environment

C++17 or later (mandatory copy elision for prvalues). Applies to all major compilers (GCC, Clang, MSVC).

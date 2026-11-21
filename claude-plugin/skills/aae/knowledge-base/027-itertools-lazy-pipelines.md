# itertools for Lazy Evaluation Pipelines

## Problem

Python data processing pipelines that create intermediate lists when chaining operations (filter, map, group, take). The metric was peak memory and throughput for streaming-style processing of large sequences. Each intermediate list doubles memory usage and requires a full pass before the next stage begins.

## What Worked

Using `itertools` functions to build lazy pipelines that process one element at a time through all stages. Key functions and their use cases:

- **`itertools.chain`**: Concatenate multiple iterables without materializing. `chain(iter_a, iter_b)` instead of `list_a + list_b`.
- **`itertools.islice`**: Take first N items from any iterable without materializing. `islice(huge_iter, 100)` instead of `list(huge_iter)[:100]`.
- **`itertools.groupby`**: Group consecutive elements by key, lazily. Requires sorted input.
- **`itertools.compress`**: Filter with a boolean selector array. Faster than list comprehension for pre-computed masks.
- **`itertools.accumulate`**: Running reduction (cumulative sum, product, etc.) as a lazy iterator.
- **`itertools.product`/`combinations`/`permutations`**: Generate combinatorial sequences lazily instead of materializing all possibilities.

For a pipeline reading 100M records, filtering to 1%, and taking top 1000, `itertools.islice(filter(...), 1000)` processed only ~100K records (early termination) vs the list approach materializing all 100M.

## Code Example

```python
from itertools import chain, islice, groupby, compress, accumulate

# BAD: materializes everything, even though we only want 10 items
results = [transform(x) for x in data if predicate(x)][:10]  # processes ALL of data

# GOOD: stops after finding 10 matches
results = list(islice(
    (transform(x) for x in data if predicate(x)),
    10
))  # processes only enough data to find 10 matches

# Concatenate large iterables without copying
all_data = chain(file1_iter, file2_iter, file3_iter)  # zero memory

# Cartesian product — lazy, doesn't build the full matrix
from itertools import product
for params in product(learning_rates, batch_sizes, seeds):
    run_experiment(*params)

# Running statistics
cumsum = list(accumulate(data))  # cumulative sum, O(1) extra memory
```

## Environment

Python 3.8+. `itertools` is a C-extension stdlib module — its functions run at near-C speed. No external dependencies.

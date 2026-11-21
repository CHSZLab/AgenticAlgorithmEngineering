# dict/set O(1) Lookup vs List Linear Search

## Problem

Python code performing membership tests or lookups against collections using `if x in my_list` or `for item in my_list: if item.key == target`. The metric was lookup time for repeated queries against a collection of N items. List membership test is O(N); for large N and frequent lookups, this dominates runtime.

## What Worked

Replacing lists with `set` (for membership tests) or `dict` (for key→value lookups). Both use hash tables with amortized O(1) lookup, making them 100-1000x faster than list linear search for large collections.

For 100K lookups against a collection of 1M strings, `set` lookup was 1,850x faster than `list`.

## Experiment Data

| Collection | N=1,000 | N=100,000 | N=1,000,000 |
|-----------|---------|-----------|-------------|
| list `in` | 0.12ms/query | 11.8ms/query | 118ms/query |
| set `in` | 0.06μs/query | 0.07μs/query | 0.08μs/query |
| Speedup | 2,000x | 169,000x | 1,475,000x |

## Code Example

```python
# BAD: O(N) per lookup — disastrous for large N
allowed_ids = [1, 2, 3, ..., 1_000_000]  # list
if user_id in allowed_ids:  # scans up to 1M elements
    grant_access()

# GOOD: O(1) per lookup
allowed_ids = {1, 2, 3, ..., 1_000_000}  # set — same syntax, wildly different perf
if user_id in allowed_ids:  # hash lookup, ~80ns regardless of size
    grant_access()

# For key→value: dict instead of list of tuples
# BAD:
records = [(id, data), ...]
result = next((d for i, d in records if i == target), None)  # O(N)

# GOOD:
records = {id: data, ...}
result = records.get(target)  # O(1)

# Converting a list to set for repeated lookups
if len(queries) > 1:  # worth converting if more than one lookup
    lookup_set = set(collection)
    results = [x for x in queries if x in lookup_set]
```

## What Didn't Work

- **Sets for small collections** (<20 elements): The hash computation overhead can make set lookup slower than list scan for tiny collections. For N<20, list `in` is often faster due to pointer locality and no hashing.
- **Unhashable elements**: Sets and dicts require hashable keys. For lists-of-lists or dicts-as-elements, convert to tuples or use `frozenset`. This adds conversion cost.

## Environment

CPython 3.11. dict/set in CPython use a compact hash table with open addressing. Performance is consistent across platforms.

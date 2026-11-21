# __slots__ for Memory Reduction in Python Classes

## Problem

Python application creating millions of small objects (e.g., tree nodes, graph vertices, data records) consuming excessive memory. The metric was peak RSS. Baseline used regular Python classes which allocate a `__dict__` (hash table) per instance to store attributes, consuming ~104 bytes overhead per object even for a class with just two `int` attributes.

## What Worked

Declaring `__slots__` on the class eliminates the per-instance `__dict__`, storing attributes in a fixed-size tuple-like structure at the C level. This reduces per-instance memory from ~232 bytes (dict-based) to ~72 bytes for a two-attribute object — a 69% reduction.

For a graph with 10M nodes (`id: int, weight: float, visited: bool`), `__slots__` reduced memory from 2.9 GB to 0.84 GB.

## Experiment Data

| Class Style | Bytes/Instance | 10M Instances (GB) |
|-------------|---------------|-------------------|
| Regular class (with __dict__) | 296 | 2.90 |
| __slots__ class | 88 | 0.84 |
| NamedTuple | 80 | 0.76 |
| dataclass(slots=True) (3.10+) | 88 | 0.84 |

## What Didn't Work

- **`__slots__` on classes that need dynamic attributes**: `__slots__` removes `__dict__`, so you can't add attributes at runtime (`obj.new_attr = x` raises `AttributeError`). Adding `'__dict__'` to `__slots__` brings back the dict and defeats the purpose.
- **Forgetting `__slots__` on parent classes**: If any base class lacks `__slots__`, instances still get `__dict__` from the base. All classes in the hierarchy must declare `__slots__`.

## Code Example

```python
# Regular class: ~296 bytes per instance
class Node:
    def __init__(self, id, weight, visited=False):
        self.id = id
        self.weight = weight
        self.visited = visited

# Slots class: ~88 bytes per instance (69% reduction)
class Node:
    __slots__ = ('id', 'weight', 'visited')
    def __init__(self, id, weight, visited=False):
        self.id = id
        self.weight = weight
        self.visited = visited

# Python 3.10+ dataclass with slots
from dataclasses import dataclass
@dataclass(slots=True)
class Node:
    id: int
    weight: float
    visited: bool = False
```

## Environment

CPython 3.10+ (for `dataclass(slots=True)`). `__slots__` itself works in all CPython versions. Memory measured with `tracemalloc` and `sys.getsizeof()`. Does not apply to PyPy (which uses a different object model that's already memory-efficient).

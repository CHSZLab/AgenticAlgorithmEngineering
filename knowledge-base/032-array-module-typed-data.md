# array Module vs Lists for Typed Numerical Data

## Problem

Python programs storing large sequences of homogeneous numerical values (e.g., sensor readings, pixel values, coordinates) using Python `list`. The metric was memory usage. A Python `list` of 1M `float` values consumes ~28 MB because each element is a boxed Python float object (24 bytes) plus a pointer (8 bytes), plus list overhead.

## What Worked

Using the `array` module from the stdlib to store typed numerical data. `array.array` stores values in a contiguous C-style array with no per-element boxing — a `float` takes 8 bytes (C `double`) instead of 24+8 bytes.

For 1M floats, `array.array('d', data)` used 8.0 MB vs 28.4 MB for `list` — a 72% memory reduction. For `int8` data (e.g., byte values), the savings are even larger: 1 byte vs 28 bytes per element.

## Experiment Data

| Container | 1M floats (MB) | 1M int8 (MB) | 1M int64 (MB) |
|-----------|----------------|---------------|----------------|
| list | 28.4 | 28.4 | 28.4 |
| array.array | 8.0 | 1.0 | 8.0 |
| numpy.ndarray | 8.0 | 1.0 | 8.0 |

## Code Example

```python
import array

# Python list: 28.4 MB for 1M floats
data_list = [0.0] * 1_000_000

# array.array: 8.0 MB for 1M floats (72% less memory)
data_arr = array.array('d', [0.0] * 1_000_000)  # 'd' = C double (float64)

# Common type codes:
# 'b' = signed char (1 byte), 'B' = unsigned char
# 'i' = signed int (2-4 bytes), 'I' = unsigned int
# 'l' = signed long (4-8 bytes), 'q' = signed long long (8 bytes)
# 'f' = float (4 bytes), 'd' = double (8 bytes)

# array supports the same interface as list for append/extend/pop:
data_arr.append(1.5)
data_arr.extend([2.0, 3.0])

# Efficient I/O: read/write binary directly (no serialization)
with open('data.bin', 'wb') as f:
    data_arr.tofile(f)
with open('data.bin', 'rb') as f:
    loaded = array.array('d')
    loaded.fromfile(f, 1_000_000)  # reads 8MB in one syscall
```

## What Didn't Work

- **array.array for computation**: Unlike NumPy, `array.array` has no vectorized operations. Arithmetic still requires Python loops (`for i in range(len(arr)): arr[i] *= 2`). If you need computation, use NumPy. Use `array.array` when you just need compact storage and I/O.
- **array.array with mixed types**: Each array stores a single type. For records with mixed types, use `struct` module or NumPy structured arrays.

## Environment

Python 3.8+. `array` is a stdlib C extension, no dependencies. For numerical computation, NumPy is strictly better. Use `array.array` when you want minimal dependencies (e.g., embedded systems, microservices) or for binary I/O.

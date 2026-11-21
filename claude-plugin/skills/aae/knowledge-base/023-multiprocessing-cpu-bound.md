# multiprocessing for CPU-Bound Parallel Work in Python

## Problem

CPU-bound Python workloads (compression, hashing, image processing, numerical computation) where `threading` provides no speedup due to the Global Interpreter Lock (GIL). The metric was wall-clock time for processing a batch of independent work items. With `threading`, all threads contend for the GIL, resulting in serial execution with context-switch overhead.

## What Worked

Using `multiprocessing.Pool` (or `concurrent.futures.ProcessPoolExecutor`) to distribute work across OS processes, each with its own Python interpreter and GIL. For CPU-bound work, this achieves true parallelism proportional to the number of cores.

Key implementation details:
1. **`Pool.map` / `Pool.imap_unordered`**: For batch processing of independent items. `imap_unordered` returns results as they complete, improving responsiveness.
2. **Chunk size tuning**: Large chunks reduce IPC overhead. Default chunk size is often too small — set `chunksize=len(items)//num_workers` as a starting point.
3. **`shared_memory`** (Python 3.8+): For sharing large arrays between processes without serialization. Avoids the cost of pickling large inputs.

For image resizing of 10K JPEG files, `ProcessPoolExecutor` with 8 workers achieved 7.1x speedup on 8 cores (vs 0.95x with `ThreadPoolExecutor`).

## Experiment Data

| Approach | Time (s) | Speedup | Notes |
|----------|----------|---------|-------|
| Sequential | 84.0 | 1.0x | Single core |
| ThreadPoolExecutor (8 workers) | 88.2 | 0.95x | GIL contention makes it worse |
| ProcessPoolExecutor (8 workers) | 11.8 | 7.1x | True parallelism |
| ProcessPoolExecutor (8, chunksize=100) | 10.2 | 8.2x | Reduced IPC overhead |

## What Didn't Work

- **Large objects as arguments**: Each process argument is pickled and sent over a pipe. Passing a 500MB NumPy array per call killed performance with serialization overhead. Solution: use `multiprocessing.shared_memory` or `mmap` to share large data.
- **Too many processes**: Spawning more processes than physical cores causes context-switch overhead and cache thrashing. Match process count to core count (`os.cpu_count()`).
- **Short tasks**: If each work item takes <1ms, the IPC overhead dominates. Batch small items into chunks.

## Code Example

```python
from concurrent.futures import ProcessPoolExecutor
import os

def process_image(path):
    img = load(path)
    return resize(img, (224, 224))

# BAD: threading — GIL prevents parallelism
from concurrent.futures import ThreadPoolExecutor
with ThreadPoolExecutor(8) as pool:
    results = list(pool.map(process_image, paths))  # ~0.95x speedup

# GOOD: multiprocessing — true parallelism
with ProcessPoolExecutor(max_workers=os.cpu_count()) as pool:
    results = list(pool.map(process_image, paths, chunksize=100))  # ~8x speedup

# For shared large data (Python 3.8+):
from multiprocessing import shared_memory
shm = shared_memory.SharedMemory(create=True, size=big_array.nbytes)
shared_arr = np.ndarray(big_array.shape, dtype=big_array.dtype, buffer=shm.buf)
shared_arr[:] = big_array[:]  # copy once, share across processes
```

## Environment

CPython 3.8+ (for `shared_memory`). Note: Python 3.13 introduces a free-threaded mode (no-GIL) that may make `threading` viable for CPU-bound work in the future. Tested on Linux (fork-based spawning is faster than Windows spawn).

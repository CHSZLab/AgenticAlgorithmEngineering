# Memory-Mapped Files for Large Datasets in Python

## Problem

Python programs that load entire large files (1GB+) into memory using `open().read()` or `pandas.read_csv()`, causing high RSS and long startup times. The metric was peak memory usage and time-to-first-result. Loading a 4GB file required 4GB+ of RAM before any processing could begin.

## What Worked

Using Python's `mmap` module to map files directly into virtual address space, allowing file content to be accessed as a byte array without loading it all into physical memory. The OS pages in data on demand and can evict pages under memory pressure.

For searching a 4GB log file for pattern matches, `mmap` reduced peak RSS from 4.2GB to 12MB and returned the first match in 0.1s instead of 18s (time to load the entire file).

NumPy also supports memory-mapped arrays via `np.memmap` for numerical data, enabling computation on datasets larger than RAM.

## Experiment Data

| Approach | Peak RSS | Time to First Result | Total Time |
|----------|----------|---------------------|------------|
| `open().read()` | 4.2 GB | 18.2s | 24.1s |
| `mmap` | 12 MB | 0.1s | 22.8s |
| `np.memmap` (for .npy) | 8 MB | 0.01s | 19.4s |

## Code Example

```python
import mmap

# Memory-mapped file search — constant memory regardless of file size
with open('huge_log.txt', 'r') as f:
    mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
    # Use like a bytes object
    idx = mm.find(b'ERROR')
    while idx != -1:
        line_start = mm.rfind(b'\n', 0, idx) + 1
        line_end = mm.find(b'\n', idx)
        print(mm[line_start:line_end].decode())
        idx = mm.find(b'ERROR', idx + 1)
    mm.close()

# NumPy memory-mapped array for large numerical datasets
import numpy as np

# Create a memory-mapped array (writes to disk)
fp = np.memmap('large_matrix.dat', dtype='float64', mode='w+', shape=(100000, 1000))
fp[:] = compute_data()  # writes directly to disk
del fp

# Read it back — no RAM needed for storage
data = np.memmap('large_matrix.dat', dtype='float64', mode='r', shape=(100000, 1000))
result = data[5000:5100].mean(axis=0)  # only loads 100 rows into RAM
```

## What Didn't Work

- **mmap for sequential-only processing**: If you process a file strictly front-to-back and never revisit earlier data, simple buffered `read()` with small chunks is equally fast and simpler. mmap shines for random access and search patterns.
- **mmap on network filesystems (NFS)**: Page faults over the network are orders of magnitude slower than local disk. Copy the file locally first.

## Environment

Python 3.8+, `mmap` is a stdlib module. Works on Linux, macOS, Windows. `np.memmap` requires NumPy. Tested on Linux 6.1, NVMe SSD.

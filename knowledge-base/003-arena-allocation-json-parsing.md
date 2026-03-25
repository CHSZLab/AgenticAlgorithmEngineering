# Arena Allocation for JSON Parsing

## Problem

Parsing large JSON files (100 MB+) in a Rust service. The metric was throughput in MB/s. The baseline used `serde_json::from_str` which allocates individually for every string and object in the JSON tree, causing heavy allocator pressure.

## What Worked

Switching from per-node heap allocation to an arena allocator (`bumpalo`). All parsed nodes, strings, and intermediate structures are allocated from a single contiguous memory region that is freed in one shot after processing. This eliminated thousands of individual `malloc`/`free` calls per parse and improved cache locality because related nodes end up adjacent in memory.

Throughput improved from 380 MB/s to 620 MB/s (~63% improvement) on a 150 MB JSON file with deeply nested objects.

## Environment

Rust 1.74, `bumpalo` 3.14, AMD EPYC 7763 (server), 256 GB RAM, Linux 6.1. Input files are API response dumps with 3-5 levels of nesting and many small string values.

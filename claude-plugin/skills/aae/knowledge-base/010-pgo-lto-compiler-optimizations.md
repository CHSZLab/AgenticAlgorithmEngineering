# Profile-Guided Optimization and Link-Time Optimization

## Problem

C++ application with complex control flow (many branches, virtual calls, deep call trees) where `-O3` alone leaves significant performance on the table. The metric was end-to-end throughput of a compiler-like workload (parsing + optimization + code generation). The optimizer makes guesses about branch probabilities and inlining without runtime data, often getting it wrong.

## What Worked

**PGO (Profile-Guided Optimization)** feeds actual runtime profiling data back into the compiler, enabling:
- Accurate branch probability annotations (hot paths get fall-through layout)
- Informed inlining decisions (inline functions on hot paths, skip cold ones)
- Hot/cold code splitting (frequently executed code packed together for better I-cache utilization)
- Better register allocation along hot paths

**LTO (Link-Time Optimization)** performs whole-program optimization across translation units, enabling cross-module inlining, dead code elimination, and interprocedural constant propagation.

Combined PGO+LTO achieved 22% throughput improvement on a real-world workload. PGO alone gave ~15%, LTO alone ~8%, but they compound because LTO exposes more inlining opportunities for PGO-guided decisions.

## Experiment Data

| Configuration | Throughput (ops/s) | Binary Size |
|--------------|-------------------|-------------|
| -O3 baseline | 1,000 | 12.1 MB |
| -O3 + LTO | 1,082 | 10.8 MB |
| -O3 + PGO | 1,148 | 12.4 MB |
| -O3 + PGO + LTO | 1,221 | 11.2 MB |

## Code Example

```bash
# GCC PGO workflow (three-step):
# 1. Build instrumented binary
g++ -O3 -fprofile-generate=./profdata -flto -o app_instrumented *.cpp

# 2. Run with representative workload to collect profile
./app_instrumented < representative_input.txt

# 3. Rebuild using profile data
g++ -O3 -fprofile-use=./profdata -flto -o app_optimized *.cpp

# Clang uses -fprofile-instr-generate / -fprofile-instr-use instead
```

## What Didn't Work

- **Non-representative training data**: PGO with synthetic benchmarks that don't match production traffic led to *worse* performance than baseline (-3%) because the optimizer optimized for the wrong hot paths. The training workload must closely match production.
- **PGO on very small programs**: The overhead of instrumentation and the three-step build process isn't worth it for programs under ~10K lines where `-O3` already does well.

## Environment

GCC 13.1 / Clang 17, Linux. PGO is supported by all major compilers. LTO requires all translation units to be compiled with the same compiler.

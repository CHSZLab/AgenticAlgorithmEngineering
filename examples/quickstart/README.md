# Quick-start example: try AAE in about 10 minutes

A small, correct but deliberately slow C++ program to try Agentic Algorithm Engineering on before you run it on your own code. `src/sssp.cpp` computes shortest paths (Dijkstra) from four sources on two graphs: a road-like grid (90,000 nodes) and a random graph (100,000 nodes, 400,000 edges). It takes about 6 seconds, and there is a lot of room for improvement.

| File | Purpose |
|---|---|
| `src/sssp.cpp` | the code to optimize |
| `bench.sh` | builds, runs both graphs, prints `time_s: <seconds>` (lower is better), and fails if the output differs from `expected/` |
| `gen_graphs.py` | generates the two graphs (deterministic; `bench.sh` calls it on first use) |
| `expected/` | the correct output, verified with an independent implementation |

Requirements: `g++` with C++17, Python 3, and `awk`.

## Run it

Copy the example into its own Git repository, since AAE commits every accepted change:

```bash
cp -r examples/quickstart ~/aae-quickstart && cd ~/aae-quickstart
git init -q && git add -A && git commit -qm "baseline"
./bench.sh
```

Then start Claude Code in that directory and type:

```
/aae:aae make src/sssp.cpp faster. Benchmark: ./bench.sh, metric time_s, lower is better.
Correctness: bench.sh must succeed (the output must stay identical to expected/).
Do not change bench.sh, gen_graphs.py or expected/. Budget: 10 experiments.
```

With Codex, use `$aae` instead of `/aae:aae`.

The agent formulates a hypothesis for every change, measures it, and keeps it only if it is faster and still correct. At the end you get the optimized code, one patch per accepted change in `patches/`, and a PDF report in `report/` (if LaTeX is installed) with one page per hypothesis.

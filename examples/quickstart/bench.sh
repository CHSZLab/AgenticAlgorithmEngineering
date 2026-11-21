#!/usr/bin/env bash
# Benchmark of the AAE quick-start example.
# Builds src/sssp.cpp, runs it on both graphs and checks the output against expected/.
# Prints "time_s: <seconds>" (lower is better). Exits non-zero if the build fails or the
# output differs, so a wrong result can never count as a speedup.
set -euo pipefail
cd "$(dirname "$0")"

[ -f data/grid.graph ] && [ -f data/random.graph ] || python3 gen_graphs.py
mkdir -p out
g++ -O2 -std=c++17 -o sssp src/sssp.cpp

start=$(date +%s.%N)
for g in grid random; do
    ./sssp "data/$g.graph" > "out/$g.txt"
done
end=$(date +%s.%N)

for g in grid random; do
    if ! cmp -s "out/$g.txt" "expected/$g.txt"; then
        echo "WRONG RESULT on $g (see out/$g.txt vs expected/$g.txt)" >&2
        exit 1
    fi
done
awk -v s="$start" -v e="$end" 'BEGIN { printf "time_s: %.3f\n", e - s }'

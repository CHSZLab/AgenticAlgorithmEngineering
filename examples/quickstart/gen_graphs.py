"""Generate the benchmark graphs of the AAE quick-start example (deterministic).

data/grid.graph:   road-like 2D grid with random edge weights
data/random.graph: random graph with average degree 8
"""
import os
import random


def write(path, n, edges):
    with open(path, "w") as f:
        f.write(f"{n} {len(edges)}\n")
        f.writelines(f"{u} {v} {w}\n" for u, v, w in edges)


def grid(side, rng):
    edges = []
    for r in range(side):
        for c in range(side):
            u = r * side + c
            if c + 1 < side:
                edges.append((u, u + 1, rng.randint(1, 100)))
            if r + 1 < side:
                edges.append((u, u + side, rng.randint(1, 100)))
    return side * side, edges


def random_graph(n, m, rng):
    edges = []
    for _ in range(m):
        u, v = rng.randrange(n), rng.randrange(n)
        if u != v:
            edges.append((u, v, rng.randint(1, 1000)))
    return n, edges


if __name__ == "__main__":
    os.makedirs("data", exist_ok=True)
    rng = random.Random(1)
    write("data/grid.graph", *grid(300, rng))
    write("data/random.graph", *random_graph(100000, 400000, rng))

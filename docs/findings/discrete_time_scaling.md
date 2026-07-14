# Discrete-Time Sparse Scaling

Date: 2026-05-12

Relevant implementation history:

```text
492b34d Add sparse MILP strategy and progress logging
974f508 Speed up sparse MILP model construction
```

## Experiment

The full-horizon sparse reachability builder was run for:

```text
horizon steps: 2,400
cabins: 23
strategy: sparse_reachability
machine: Apple M3 Pro
```

The initial implementation spent about `702.4s` in Python while constructing
the sparse variable index. The resulting model still contained approximately:

```text
40.1 million binary variables
43.7 million rows
240.2 million nonzeros
```

Gurobi presolve reduced it to about `566,681` binaries and `3.93 million` rows.

## Finding

Sparse reachability loses much of its sparsity over long horizons. Wait arcs and
alternative routes eventually make most graph states reachable, so a sparse
state enumeration can converge toward the dense model size. Before solver time
becomes relevant, Python object creation, hashing, and repeated graph traversal
can dominate runtime.

Precomputing allowed outgoing arcs and targets, caching reachability
transitions, building conflict participants during reachability, flattening
flow indices, and batching solution extraction reduced the isolated sparse
index build to about `16.6s` on the same machine.

## Interpretation

The roughly 42-fold construction speedup fixes avoidable Python overhead but
does not solve the underlying long-horizon state-space growth. Sparse
reachability remains effective for short horizons and useful as a prototype,
while full-horizon scaling requires a more structural formulation change.

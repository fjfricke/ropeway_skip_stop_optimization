# EAN Formulation and Search Roadmap

Status: **future work**

## Goal

Improve incumbent quality and proof progress of the integrated EAN passenger
MILP without changing its integer optimum. The current default remains:

```text
candidate_horizon_pruning
single_ring_dominated_ride_pruning
slot_time_relaxation_strengthening
```

`tight_big_m_bounds` is implemented but remains opt-in. The single-ring ride
reduction is exact dominance pruning: a passenger can alight at the first
matching destination visit, so remaining onboard for an additional full loop
cannot improve waiting or journey time and occupies capacity for longer.

The horizon corrections and exact model reductions in
`ean_structural_reformulation.md` precede this roadmap. In particular, repeated
stop/skip Big-M experiments are needed only if the affine timing formulation is
not adopted.

## Ordered Work

### 1. Conditional Repeated Tight Big-M Benchmarks

Compare `all` against `all + tight_big_m_bounds` with repeated seeds or runs and
fixed 5-, 10-, and 15-minute limits. Record incumbent, bound, gap, node count,
time-to-gap, and served passengers.

Promote the toggle into the default only if the stronger bound is reproducible
and incumbent quality is not consistently worse for export-oriented runs.
Skip this work if affine stop/skip timing replaces the corresponding Big-M
constraints.

### 2. Candidate Earliest Board-Time Bounds

Add a conservative physical lower bound for every ride candidate:

```text
slot_board_time >= earliest_physical_board_time(candidate) * slot
```

Derive it from the cabin start, visit chain, route minimum durations, and the
boarding time reference. It must not use an incumbent or assume undecided
stop/skip choices. This is especially relevant for waiting-time objectives with
release time zero.

### 3. Candidate Latest Board and Alight Bounds

Derive expression-specific upper bounds:

```text
latest_board_time(candidate)
latest_alight_time(candidate)
```

Use them to tighten slot activation and horizon Big-M constraints. Do not infer
these values merely from the switch-time upper bound because boarding and
alighting expressions include route constants and possibly waiting. Prove each
bound for both waiting and no-waiting modes before enabling it.

### 4. Better MIP Starts

Improve the primal side before testing more reformulations:

- retain the accepted earliest all-stop start;
- create a capacity-aware greedy passenger assignment;
- skip visits that are unnecessary for that assignment;
- consider multiple Gurobi starts for distinct service patterns.

Benchmark first-incumbent time and objective separately from best-bound
progress. Starts may change time-limited output but not the true optimum.

### 5. Safe Headway Pair Classification

Introduce a benchmark toggle and classify only pairs whose order is proven:

```text
same cabin + same checkpoint:
  lower visit index is the leader
```

A fixed pair gets one activation-relaxed directed headway constraint and no
ordering binary. All different-cabin pairs remain variable in the first phase.
Log total, fixed, variable, and omitted pairs plus ordering-binary count.

### 6. Conservative Reordering and Time-Window Rules

After the same-cabin rule is validated, investigate:

- fixed order in unique-path, no-skip, no-wait segments;
- graph-based detection of possible overtaking or merge reordering;
- redundant pairs proven by conservative earliest/latest time windows.

Any uncertain pair stays variable. A false fixed-order classification can
silently remove feasible solutions.

### 7. Headway Reformulation Experiments

Benchmark, independently:

- per-pair tight Big-M bounds;
- `AND` activation plus forward/reverse indicators;
- stop/skip or slot indicators only where they replace an identical implication.

Keep slot-time valid inequalities even when indicators are used. Cleaner
Gurobi syntax is not sufficient evidence of better performance.

### 8. Small Debug Instances

Add tiny fixtures using the production EAN builder and optimizer paths:

- short horizon;
- few cabins;
- one or two demand groups;
- waiting and no-waiting variants;
- exact solves suitable for objective-equivalence tests.

## Acceptance Rule

Every formulation toggle needs unit tests for its bound/classification logic,
an exact small-instance comparison with the toggle off, and a fixed-protocol
benchmark. Long benchmarks remain outside pytest.

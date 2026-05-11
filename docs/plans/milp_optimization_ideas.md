# MILP Optimization Ideas

Status: **ideas / backlog**

This document collects optimization ideas that are not part of the immediate sparse MILP v0 implementation.

## Arc-Only Formulation

Eliminate explicit position variables:

```text
y[c,t,a]
```

and derive node occupancy from incoming/outgoing arc flow.

Potential benefit:

- fewer variable families

Potential cost:

- node conflict constraints become less direct
- `t=0` needs special handling
- debugging against `MovementPlan` becomes less transparent

This should only be considered after sparse `x/y` variables have been tested.

## Rolling Horizon

Instead of solving the full horizon:

```text
H = 2400
```

solve smaller windows:

```text
solve window 0..W
fix first F steps
roll forward
```

Potential benefit:

- much smaller model per solve
- natural fit for local operational control

Risks:

- myopic decisions
- needs terminal-state handling
- passenger queues and cabin loads must carry over between windows

## Periodic Pattern Optimization

For a cyclic ropeway, solve a repeated pattern:

```text
pattern length P
repeat pattern over the day
```

Potential benefit:

- very small model for steady-state operations
- good for schedule design

Risks:

- less suitable for time-varying demand
- startup/shutdown transients need separate handling

## Path-Based Formulation

Use precomputed route/path alternatives instead of node/arc movement decisions.

Examples:

- all-stop path
- skip M path
- service/skip combinations

Potential benefit:

- drastically fewer variables
- easier to attach passenger service semantics

Risks:

- less flexible around waiting and local conflicts
- path generation becomes its own problem
- may miss useful operational patterns unless the path set is rich

## Block Aggregation / Capacity Arcs

Aggregate long chains of equivalent discrete nodes/arcs into larger transit blocks.

Current exact discretization represents a long segment as:

```text
v1 -> v2 -> v3 -> v4 -> v5
```

with roughly one cabin per cell/headway zone.

An aggregated model could represent this as:

```text
block B
duration = 5 time steps
capacity = 5 cabins
```

or as a transit arc/resource:

```text
enter[c,t,B] = 1
exit[c,t+duration,B] = 1
```

with occupancy:

```text
sum_{tau=t-duration+1..t} enter[*,tau,B] <= capacity(B)
```

Potential benefit:

- dramatically fewer nodes, variables, and flow constraints
- very useful for long rope sections, skip sections, and constant-speed deterministic travel

Main modeling questions:

- how to preserve FIFO/no-overtaking inside a block
- how to handle blockage or waiting at the block exit
- how to represent cross-segment headway near switches
- how to couple block entry/exit with adjacent fine-grained station/switch nodes
- whether capacity is exact or an approximation

Likely long-term structure:

```text
hybrid model = fine-grained near switches/stations + aggregated transit blocks on long homogeneous sections
```

This should not be mixed into the immediate sparse MILP v0 work. Sparse v0 keeps the exact discrete semantics and only removes unreachable variables/constraints. Block aggregation is a later modeling layer that intentionally changes the graph abstraction.

## Symmetry Breaking

Cabins are often interchangeable. Add ordering constraints to reduce symmetric solutions.

Possible rule:

```text
cabin order around the loop is preserved
```

Potential benefit:

- fewer equivalent solutions

Risks:

- must not remove valid overtake/switch behavior if later modeled
- needs a robust notion of cyclic order

## Warm Starts

Use the greedy all-stop baseline as a Gurobi start solution:

```text
x.Start = ...
y.Start = ...
```

Potential benefit:

- useful once objectives make the model nontrivial
- provides a known feasible solution

Risks:

- little value for pure feasibility if presolve already solves the model
- start must match sparse variable keys exactly

## Arc/Wait Policy Tightening

Restrict where waiting is allowed and which arcs can be used.

Examples:

- no waiting on rope sections
- waiting only at platform or exit-holding nodes
- skip arcs only at true switch decisions
- max waiting time per station or node

Potential benefit:

- smaller search space
- fewer operationally meaningless plans

Risks:

- too much tightening can make feasible recovery impossible
- policies need to remain physical, not just cosmetic

## Lexicographic Objectives

For passenger-aware optimization, use staged objectives instead of a single naive objective.

Candidate order:

```text
1. maximize served passengers
2. minimize passenger-hours of queueing
3. minimize unnecessary cabin waiting
4. penalize excessive skipping or unfair service
```

Reason:

```text
minimize queueing time
```

alone can behave badly if unserved passengers or ignored demand are not modeled correctly.

## Lazy Or Separated Conflict Constraints

Add some conflict constraints only when violated.

Potential benefit:

- fewer initial constraints

Risks:

- requires callback/lazy-constraint discipline
- correctness depends on exact violation separation
- harder to debug than explicit constraints

This is not needed until sparse explicit constraints become too large.

# EAN Root-Bound Improvement Plan

Status: **next implementation work**

## Motivation

The passenger-optimized all-stop MIP start materially improved the
`five_station_v0` incumbent but left the final lower bound unchanged:

```text
greedy all-stop gap:     49.16%
optimized all-stop gap:  17.62%
lower bound in both:     1,604,228 passenger-seconds
```

Both integrated runs remained at the root and performed essentially identical
root work. The fixed-movement passenger solve is fast enough to generate the
improved start. The immediate bottleneck is therefore no longer the initial
primal solution; it is the integrated root relaxation and the coupling between
movement, timing, headway, and passenger decisions.

The implemented root diagnostic shows severe fractionality in the raw
continuous relaxation, while Gurobi substantially strengthens the bound during
MIP root processing. The exact post-cut variable vector is not available on
`five_station_v0` within five minutes because root processing does not reach an
optimal `MIPNODE` state. Detailed measurements are recorded in
`docs/findings/ean_passenger_optimization_benchmarks.md`.

## Goals

1. Test inexpensive exact strengthening before introducing decomposition.
2. Distinguish raw-LP improvements from post-cut MIP-bound improvements.
3. Select later work from measured evidence rather than model size alone.

The plan does not assume that the current incumbent is globally near-optimal.
A strong feasible solution and a weak lower bound do not establish that.

## Phase 1: Current Default Versus Tight Big-M

Before adding new constraints, compare exactly two integrated cases on
`five_station_v0`:

```text
current production default
current production default + tight_big_m_bounds
```

Use the optimized all-stop start for both. Compare root-bound development,
fractionality by family, final incumbent, final bound, gap, nodes, memory, and
setup time. Repeat with controlled solver seeds if the runner supports them.

Keep `tight_big_m_bounds` opt-in unless it reproducibly improves the root bound
without an unacceptable regression in incumbent search or runtime.

If family-level metrics do not explain a changed bound, extend the diagnostic
only for the active families: passenger slots by demand group, OD pair, cabin,
and ride candidate; headway orders by checkpoint kind and same-cabin versus
different-cabin pairs.

## Phase 2: Candidate-Specific Passenger-Time Bounds

If passenger slots, unserved counts, or selected-time variables dominate the
root fractionality, implement the exact bounds in this order:

1. candidate-specific earliest-board lower bounds;
2. candidate-specific latest-board upper bounds;
3. candidate-specific latest-alight upper bounds.

Each bound must follow from physical route and timing bounds, not from an
incumbent. Prove it for both waiting modes and for every supported horizon and
board-time formulation. Benchmark each step separately against the best result
from Phase 1.

## Phase 3: Headway Precedence Reduction

If headway-order and movement variables dominate, first classify safe
same-cabin precedence:

```text
same cabin + same checkpoint:
  lower visit index precedes higher visit index
```

Replace the corresponding two-direction disjunction and order binary with the
correct activation-relaxed directed headway constraint. Record fixed, variable,
and omitted pair counts. Continue to conservative time-window classification
only if the exact same-cabin reduction has a measurable effect.

## Phase 4: Algorithmic Branch

Use the diagnostic evidence to choose between two separate objectives.

For better feasible solutions:

- test local branching or large-neighborhood search around the optimized
  all-stop solution;
- release bounded sets of stop/skip and waiting decisions;
- validate every accepted movement with the canonical passenger model.

For stronger bounds or exact certification:

- build the fixed-movement destination-layered passenger evaluator;
- measure LP integrality before selecting a decomposition method;
- consider classical Benders only with demonstrated integrality and valid dual
  cuts;
- otherwise evaluate branch-and-Benders or logic-based Benders.

Delayed headway generation is considered only if diagnostics show that eager
headway materialization or movement search remains dominant. It is not the
default next step while root coupling is the observed bottleneck.

## Decision Rules

Choose the next implementation from the diagnostic and Phase-1 result:

| Observation | Next work |
|---|---|
| Passenger slots or selected times carry most fractional mass | Candidate-specific passenger-time bounds |
| Unserved variables are strongly fractional | Passenger assignment strengthening and fixed-movement evaluator |
| Headway orders dominate | Safe precedence classification |
| Stop/activation and passenger variables are jointly fractional | Coupling reformulation or decomposition |
| Bound is adequate but incumbent remains poor | Neighborhood search or multiple structural starts |
| Python construction or memory dominates | Compact materialization rather than MILP reformulation |

Multiple families may be active. In that case, implement the cheapest exact
change first and rerun the same diagnosis.

## Correctness and Acceptance

The diagnostic itself must not change model semantics. Every exact
reformulation requires:

- algebraic or classification unit tests;
- exact objective agreement on tiny production-path instances;
- waiting-time and journey-time coverage where applicable;
- both waiting modes and supported horizon formulations;
- valid extracted movement and passenger plans;
- a matched `five_station_v0` benchmark;
- separate reporting of incumbent and bound effects.

Heuristics such as neighborhood search may improve incumbents but must not be
reported as stronger optimality evidence. Thesis changes should describe a
method only after implementation and should report empirical conclusions only
after the corresponding controlled experiment.

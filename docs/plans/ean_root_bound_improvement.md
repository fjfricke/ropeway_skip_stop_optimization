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

This plan determines which part of that relaxation is weak before implementing
another substantial reformulation.

## Goals

1. Identify the variable and constraint families responsible for the weak root
   bound.
2. Test inexpensive exact strengthening before introducing decomposition.
3. Select later work from measured evidence rather than model size alone.
4. Keep the production optimizer free of benchmark-specific policy decisions.

The plan does not assume that the current incumbent is globally near-optimal.
A strong feasible solution and a weak lower bound do not establish that.

## Phase 1: Root-Relaxation Diagnosis

Add a benchmark-only diagnostic that observes the canonical integrated model at
the root node. Reuse `EanMovementModel` and `EanPassengerModel`; do not rebuild
or duplicate the mathematical formulation.

### Recorded variable families

At minimum, classify and measure:

- stop/skip binaries;
- visit and checkpoint activation variables;
- headway-order binaries;
- passenger slot variables;
- unserved passenger variables;
- waiting and event-time variables;
- selected board/alight time variables where present.

For every integer family, record:

```text
variable count
fractional variable count
fractional share
sum of distance to the nearest integer
maximum distance to the nearest integer
```

For passenger slots, additionally aggregate fractional mass by demand group,
ride candidate, cabin, and origin/destination pair. For headways, aggregate by
checkpoint kind and by same-cabin versus different-cabin pairs.

### Recorded root development

Use callback values instead of parsing the textual Gurobi log. Record repeated
root samples because presolve, cuts, and root heuristics can change the
relaxation before branching:

```text
runtime
root relaxation objective or best bound
incumbent objective
gap
simplex/barrier work where available
total cut count where available
fractionality summary
linear objective contribution by variable family
```

Keep the final available root sample as the principal comparison point. A
standalone continuous relaxation should be used as a secondary structural
diagnostic for constraint-family metrics:

```text
constraint count by name prefix
active or nearly active constraint count
slack distribution
dual-value magnitude where available
```

These metrics identify constraints associated with the relaxed objective, but
do not by themselves prove which reformulation will improve the MIP root.
Label the standalone relaxation separately because it is not necessarily the
post-presolve, post-cut MIP root relaxation used by Gurobi. Do not parse the
solver log to manufacture cut categories that are unavailable through the
callback API.

### Code structure

Keep diagnostics typed and separate from optimization behavior:

```text
benchmarking/ean_root_relaxation.py
  EanRootRelaxationRecorder
  EanRootRelaxationSample
  EanVariableFamilyMetrics
  EanRootRelaxationDiagnosticResult
```

The optimizer may expose a narrow observer hook or typed variable-family view
needed by the recorder. It must not gain formulation branches or objective
changes for diagnostics. Existing progress and checkpoint behavior must remain
unchanged when no diagnostic recorder is supplied.

Write one machine-readable JSON result per run and provide compact plots for:

- bound and incumbent over root runtime;
- fractional count and fractional mass by variable family;
- passenger fractionality by demand group or OD pair;
- headway-order fractionality by checkpoint category.

### Initial experiment

Run the diagnostic on:

```text
example: five_station_v0
objective: journey_time
formulation: current production default
MIP start: optimized_all_stop
solver policy: exact_optimality
time limit: 300 seconds
```

Run the existing movement-only and fixed-movement cases with matching inputs as
controls. Their objective bounds are not directly comparable, but their
fractionality, construction cost, and solve behavior help isolate coupling.

## Phase 2: Current Default Versus Tight Big-M

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

## Phase 3: Candidate-Specific Passenger-Time Bounds

If passenger slots, unserved counts, or selected-time variables dominate the
root fractionality, implement the exact bounds in this order:

1. candidate-specific earliest-board lower bounds;
2. candidate-specific latest-board upper bounds;
3. candidate-specific latest-alight upper bounds.

Each bound must follow from physical route and timing bounds, not from an
incumbent. Prove it for both waiting modes and for every supported horizon and
board-time formulation. Benchmark each step separately against the best result
from Phase 2.

## Phase 4: Headway Precedence Reduction

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

## Phase 5: Algorithmic Branch

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

Choose the next implementation from the Phase-1 result:

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

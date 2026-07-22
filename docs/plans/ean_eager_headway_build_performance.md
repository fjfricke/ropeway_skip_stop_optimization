# Exact Eager Headway Build-Performance Plan

Status: **future work**

## Goal

Reduce the wall-clock time and peak memory required to construct the exact
eager headway formulation, especially for optimized-initial-placement (OIP)
five-station ring instances with skip and waiting. The resulting model must
have the same feasible set and objective as the current eager all-pairs model.

This plan targets the period before Gurobi starts optimization. It does not
claim that a faster build will make the resulting large MIP easy to solve.
Build performance and solve performance must be measured separately.

## Motivation

The current builder materializes headway candidates, pair objects, order
binaries, and two Big-M rows per disjunctive pair before optimization begins.
The dominant dimension is not merely the cabin count. With \(R\) physical
checkpoints, \(K\) cabins, and \(U\) modeled occurrences per cabin, eager pair
generation is approximately

\[
O\!\left(RK^2U^2\right).
\]

Existing measurements already show the practical consequence:

- an OIP instance with 76 cabins and no waiting produced 3,116 visits, 6,232
  candidates, and 1,943,396 headway pairs;
- retaining the Python artifact for that case required roughly 763 MB;
- a larger sparse OIP construction reached about 100,000 variables, 4 million
  rows, 15.8 million nonzeros, and 1.6 GB before useful MIP search;
- serializing a large EAN artifact can itself take tens of seconds.

Skip and end-of-platform waiting can increase the number of relevant
checkpoint candidates further. The first objective is therefore to avoid
Python object amplification and provably unnecessary disjunctions, then feed
the remaining exact formulation to Gurobi efficiently.

## Scope and Correctness Contract

All production changes in this plan are exact. For every current instance,
they must preserve:

- every feasible movement and passenger solution;
- the selected passenger objective and its optimum;
- stop/skip activation semantics;
- end-of-platform waiting occupancy;
- exact horizon and boundary-clearance semantics;
- all overtaking and reordering possibilities currently permitted by the
  model.

In particular, this plan introduces no global cabin order, adjacent-only
headways, or assumption that cabins cannot exchange order after a stop/skip
merge. A pair may be removed or directed only when a valid bound or topology
proof makes its disjunction unnecessary. If a proof is inconclusive, the full
disjunction remains.

The following ideas are explicitly outside the implementation scope:

- starting with a headway-free model and separating violations afterwards;
- heuristic pair sampling or distance cutoffs;
- a merge-sequencing or cumulative-resource reformulation;
- Logic-Based Benders cuts;
- CP-SAT or another solver backend.

Those remain research or later formulation alternatives. They must not be
reported as equivalent build optimizations for the eager model.

## Phase 0: Instrument and Reproduce the Baseline

Add structured timings and peak-memory observations for every major build
stage:

1. movement artifact and visits;
2. headway candidates;
3. pair classification or pair materialization;
4. movement variables and affine time expressions;
5. order variables and headway rows;
6. passenger variables and constraints;
7. MIP-start application;
8. final model update;
9. JSON/export serialization.

Expose these measurements in benchmark metadata and progress output. Progress
must advance during long construction stages rather than remain silent until
`optimize()` starts. Report candidate count, processed checkpoint count,
classified pair count, retained disjunction count, row count, variable count,
elapsed time, and available memory data where supported.

Add an `--ean-build-only` CLI mode. It must build the selected artifact and
Gurobi model, report statistics, optionally write the configured artifacts,
and exit before optimization. This keeps construction experiments independent
of a 30-minute or longer solve.

Record reproducible baselines for at least:

- the small one-station regression case;
- the three-station ring;
- the five-station OIP ring with the all-stop fleet size;
- the five-station OIP ring with twice the all-stop fleet size, skip enabled,
  and waiting enabled.

## Phase 1: Exact Pair Classification

Replace the assumption that every candidate combination needs an order binary
with a four-way exact classification:

```text
REDUNDANT
FIXED_FORWARD
FIXED_REVERSE
DISJUNCTIVE
```

For candidate \(i\), derive a valid occurrence interval

\[
t_i \in [\ell_i, u_i].
\]

For a required headway \(h_{ij}\):

- classify the pair as `FIXED_FORWARD` when
  \(u_i + h_{ij} \le \ell_j\);
- classify it as `FIXED_REVERSE` when
  \(u_j + h_{ji} \le \ell_i\);
- classify it as `REDUNDANT` when activation or horizon semantics prove the
  candidates cannot conflict in the same active solution;
- retain a `DISJUNCTIVE` pair otherwise.

A fixed direction creates only its implied headway row and no order binary.
A redundant pair creates neither. A disjunctive pair retains the existing
order binary and both existing Big-M rows.

Classification must use the actual candidate time expression, including
platform occupancy under waiting. It must also preserve conditional activation
and horizon logic. Same-cabin pairs may be removed only when route timing and
minimum recurrence prove that the required separation is automatic; cabin ID
alone is not a sufficient proof.

## Phase 2: Strong, Safe OIP Time Bounds

Derive candidate occurrence bounds for every allowed optimized initial
boundary state rather than using one nominal start. Propagate bounds through:

- rope travel;
- service and skip alternatives;
- permitted end-of-platform waiting;
- generated rotations;
- operational-horizon activation;
- required post-horizon clearance.

Bounds must be conservative over all feasible initial placements. A loose
bound merely retains an unnecessary disjunction; an invalid tight bound can
remove a feasible schedule and is therefore a correctness defect.

Implement bound derivation as a separate tested component returning both the
numeric interval and its provenance. If any required input is unavailable or
the proof is inconclusive, fall back to the legacy disjunction.

## Phase 3: Compact Conflict Representation

Stop constructing a graph of heavyweight Python `HeadwayPair` objects before
the solver needs it. At each checkpoint:

- assign candidates stable integer indices;
- store candidate metadata in columnar arrays or compact records;
- emit fixed directions and disjunctive index pairs into contiguous batches;
- maintain counts and diagnostics without retaining duplicate object graphs;
- preserve deterministic ordering by checkpoint and candidate ID.

Introduce two explicit construction modes during verification:

```text
LEGACY_OBJECT_PAIRS
PRUNED_COMPACT_EAGER
```

The compact mode remains eager: every non-prunable original disjunction is
present before optimization. It is distinct from the existing delayed
violation-generation experiment.

Where downstream code needs pair-level diagnostics, provide an iterator or
debug materialization path instead of making full pair persistence the normal
representation.

## Phase 4: Batched Gurobi Construction

Build the classified conflicts in bounded-size chunks:

- create order binaries as one block per chunk;
- add fixed-direction rows in batches;
- add the two disjunctive rows from numeric coefficient data;
- avoid repeated model synchronization;
- update progress and release temporary chunk memory after insertion.

Benchmark two implementation paths:

1. `addVars` plus `addLConstr`/batched expression construction;
2. direct sparse-matrix construction through Gurobi's matrix API.

Adopt the matrix path only if it materially improves build time or memory and
does not make extraction, MIP starts, or debugging fragile. Do not add a large
new dependency solely for assembly until the benchmark demonstrates a benefit.

The batch size must be configurable for experiments but have one deterministic
production default. Different batch sizes must generate equivalent models.

## Phase 5: Naming and Checkpoint Compatibility

Support two naming policies:

```text
FULL_DEBUG_NAMES
COMPACT_NAMES
```

In compact mode, omit constraint names and use stable compact variable names
only where extraction or checkpoint recovery requires them. Evaluate Gurobi's
`IgnoreNames` only after `.sol`/`.mst` write-and-resume tests prove that the
current checkpoint workflow still works.

Do not trade away resumability silently. If compact naming changes checkpoint
compatibility, encode the construction and naming mode in checkpoint metadata
and reject incompatible resumes with a clear error.

## Phase 6: Separate Solver Data from Export Data

The frontend does not need millions of individual headway pairs for normal
visualization. Make compact export the default for large EANs:

- retain candidate, checkpoint, and aggregate conflict statistics;
- include total classified, redundant, directed, and disjunctive counts;
- omit the full pair list unless explicitly requested;
- preserve movement, passenger, validation, and solution data required by the
  frontend.

Add an explicit diagnostic option such as
`--ean-export-full-headway-pairs`. Validate the manifest and frontend reader
against both schemas. Export reduction must not change the solver model.

## Phase 7: Verification

### Unit Tests

Cover:

- forward and reverse fixed-order proofs;
- overlapping intervals that must remain disjunctive;
- stop/skip activation;
- waiting-dependent platform occupancy;
- horizon and boundary-clearance filtering;
- same-cabin recurrence;
- inactive OIP cabins;
- deterministic checkpoint and pair ordering;
- duplicate prevention across chunks;
- conservative fallback when bounds are unavailable.

### Model Equivalence Tests

On exhaustive or tightly bounded small cases, compare
`LEGACY_OBJECT_PAIRS` and `PRUNED_COMPACT_EAGER` for:

- feasible/infeasible classification;
- objective value;
- extracted movement and passenger validity;
- complete post-solve headway separation;
- active-cabin behavior;
- model fingerprints after normalizing names and row order where practical.

Run the existing test suite unchanged in legacy mode during development. The
compact eager mode may become the default only after all equivalence tests and
the complete regression suite pass.

### Checkpoint and Export Tests

Write and reload MIP starts under both naming policies, verify rejection of
incompatible checkpoint metadata, and load compact exports in the frontend.

## Phase 8: Performance Acceptance

Benchmark on the same machine and configuration using:

1. legacy object pairs;
2. compact eager construction with pruning disabled;
3. compact eager construction with exact pruning enabled.

This separates benefits from representation, batching, and mathematical
classification. Report:

- artifact time;
- Gurobi construction time;
- export time;
- total pre-optimize time;
- peak resident memory;
- candidates, classified pairs, fixed rows, disjunctions, variables, rows, and
  nonzeros;
- root-bound and incumbent behavior after a fixed short solve budget.

Target, but do not treat as a correctness gate:

- at least a 3x reduction in pre-optimize time for the five-station OIP
  double-all-stop Skip+Wait case;
- at least a 40% reduction in peak build memory;
- no regression in objective, feasibility classification, root bound, or
  complete headway validation.

Correctness acceptance is exact equivalence and complete validation. If the
performance targets are missed, retain the measurements and use them to decide
whether a structural merge/sequence formulation is warranted.

## Phase 9: Thesis and Documentation

After implementation and measurement, document:

- why eager checkpoint pair generation scales as
  (O(RK^2U^2));
- the interval proof for redundant and fixed-order conflicts;
- the distinction between exact eager pruning and delayed
  row-and-column generation;
- the effect of compact representation, batching, and export suppression on
  setup time and memory;
- the measured change in retained disjunctions and solver behavior;
- the limitation that faster construction does not remove the underlying
  combinatorial MIP difficulty.

Do not present target numbers as results. Add measured tables only after the
benchmark harness produces reproducible data.

## Implementation Order

Execute the work in this order:

1. instrumentation, progress, and build-only CLI;
2. safe candidate time-bound component;
3. exact pair classifier and focused tests;
4. compact conflict representation behind an explicit mode;
5. batched Gurobi construction;
6. compact naming and checkpoint compatibility;
7. compact export and frontend compatibility;
8. equivalence suite and full regression suite;
9. performance benchmark and default-mode decision;
10. thesis and architecture documentation.

Each phase must remain independently measurable. Do not combine pruning,
representation, and matrix construction into one un-attributable benchmark.

## Risks and Fallbacks

- **OIP time bounds remain too loose.** Correctness is preserved, but little is
  pruned. Compact representation and batching can still reduce setup cost.
- **Matrix assembly complicates maintenance.** Keep the simpler batched API if
  its performance is adequate.
- **Compact names break resume behavior.** Retain stable variable names and
  omit only constraint names, or keep full names for checkpointed runs.
- **Compact JSON breaks consumers.** Version the export schema and retain the
  explicit full diagnostic export.
- **Construction becomes fast but solving remains intractable.** Use the new
  profile as evidence for a later exact merge/sequence formulation or a
  decomposition experiment; do not weaken headway correctness silently.

## Exit Condition

The plan is complete when the compact eager builder is proven equivalent to
the legacy all-pairs model, the full regression suite passes, build-only and
progress reporting expose all major setup stages, checkpoint and frontend
workflows remain valid, and reproducible five-station OIP benchmarks quantify
the time and memory effects.

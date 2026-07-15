# EAN Formulation and Search Roadmap

Status: **future work**

## Goal

Improve incumbent quality and proof progress of the integrated EAN passenger
MILP without changing its integer optimum. Do not apply the remaining ideas in
one fixed sequence: first stabilize the immediate baseline, then measure which
part of the model is limiting performance, and select the matching branch.

The current production passenger configuration uses:

```text
candidate_horizon_pruning
single_ring_dominated_ride_pruning
slot_time_relaxation_strengthening
stop_skip_timing_affine
slot_activation_first_slot
board_time_projected_journey_time for Journey-Time
board_time_explicit for Waiting-Time
```

`tight_big_m_bounds` remains opt-in. Big-M timing, per-slot activation, and
explicit Journey-Time boarding time remain selectable as controlled historical
comparators. Full-ring ride pruning is exact dominance pruning: a passenger
can alight at the first matching destination visit, so remaining onboard for an
additional full loop cannot improve waiting or journey time and occupies
capacity for longer.

Semantic extensions such as optional fleet activation, depots, cyclic days,
and turnbacks are outside this solver-preserving roadmap.

## Prerequisite: Exact Debug Instances

Before adding another formulation toggle, maintain tiny fixtures that use the
production EAN builder and optimizer paths:

- a short horizon and few cabins;
- one or two demand groups;
- waiting and no-waiting variants;
- waiting-time and journey-time objectives;
- exact solves suitable for objective-equivalence tests.

These instances are the correctness gate for every later reduction,
classification, or reformulation. They are infrastructure, not a separate
performance experiment.

## Step 1: Continue Validation of the Selected Timing Default

The combined Journey-Time formulation has already been promoted to the
production default. The following runs are continued validation and variance
measurement, not a prerequisite for selecting the baseline.

### Repeated Affine Timing Validation

Repeat the combined Journey-Time default against the historical Big-M,
per-slot, explicit comparator with controlled solver seeds. Add longer runs
and `five_station_v0` construction or bounded-solve checks. Compare:

- model size and construction time;
- root relaxation and best-bound progress;
- first and final incumbent quality;
- final gap, node count, and memory.

Keep the promoted defaults unless their observed advantage fails to reproduce.
Preserve the historical formulation choices for controlled benchmarks; do not
infer a Waiting-Time advantage from the Journey-Time projection result.

### Conditional Tight Big-M Validation

Repeat the current default against the same configuration plus
`tight_big_m_bounds` only for constraints that remain Big-M based. Skip tests
for rows replaced by affine timing. Use repeated seeds and fixed 5-, 10-, and
15-minute limits; record incumbent, bound, gap, nodes, time-to-gap, and served
passengers.

Keep the option opt-in unless it produces a reproducible net improvement.

## Step 2: Locate the Active Bottleneck

Run the Phase-0 scaling diagnosis from `ean_decomposition.md` before choosing
the next substantial reformulation. At each useful problem size compare:

```text
integrated movement and passenger model
movement and headways without passenger assignment
passenger optimization for a fixed movement plan
```

Also separate Python construction, presolve, root relaxation, incumbent search,
and proof progress. Treat the zero-objective movement-only solve as a
feasibility and construction diagnostic rather than comparing its gap with the
passenger objective. The result selects one or more branches below:

- movement/headway bottleneck -> Branch A;
- weak or late incumbents -> Branch B;
- passenger relaxation or fixed-movement assignment bottleneck -> Branch C;
- construction or artifact bottleneck -> compact materialization work in
  `ean_structural_reformulation.md`.

Do not require every speculative structural idea to be implemented before this
diagnosis. Re-run the diagnosis after a branch produces a material change.

## Branch A: Movement and Headways Dominate

### A1. Safe Same-Cabin Precedence

Classify only pairs whose order is proven by the current fixed route:

```text
same cabin + same checkpoint:
  lower visit index is the leader
```

Replace each such pair's order binary and two-direction disjunction with one
activation-relaxed directed headway constraint. Keep all different-cabin pairs
variable in this first experiment. Log total, fixed, variable, and omitted
pairs plus the resulting ordering-binary count.

### A2. Conservative Time-Window and Reordering Classification

After A1 is exact and beneficial, investigate:

- fixed order in unique-path, no-skip, no-wait segments;
- graph-based detection of possible overtaking or merge reordering;
- pairs whose conservative earliest/latest windows cannot conflict.

Any uncertain pair remains variable. A false fixed-order classification can
silently remove feasible solutions.

### A3. Shared Physical Precedence

Only after the route-level ordering proof from A1 and A2 is available,
investigate sharing one precedence decision across platform entry, platform
exit, and exit-switch checkpoints of the same physical visit pair. The proof
must cover skip overtaking, merge topology, activation, and end-of-platform
waiting.

### A4. Delayed Headway Generation

If eager headway materialization remains dominant after safe classifications,
continue with the external solve-and-verify experiment in
`ean_decomposition.md`. Do not start with callback-only separation because
omitted disjunctions may require new precedence variables.

## Branch B: Incumbent Search Is Weak

### B1. Better and Multiple MIP Starts

Improve the primal side before testing lower-priority solver syntax changes:

- retain the accepted earliest all-stop start;
- create a capacity-aware greedy passenger assignment;
- skip visits that are unnecessary for that assignment;
- provide multiple starts for distinct service patterns where supported.

Benchmark first-incumbent time and objective separately from best-bound
progress. A start may change a time-limited result but not the true optimum.

### B2. Progressive Waiting

If waiting creates a difficult primal search, test the same-artifact staged
strategy from `ean_decomposition.md`: first fix existing wait variables to
zero, optionally allow a small cap, then release the full configured bound.
Treat this as a search strategy, not an exact formulation reduction.

## Branch C: Passenger Relaxation or Assignment Dominates

### C1. Candidate-Specific Earliest Board Bounds

Derive a conservative physical lower bound for each ride candidate:

```text
slot_board_time >= earliest_physical_board_time(candidate) * slot
```

Use the cabin start, visit chain, route minimum durations, and boarding-time
reference. The bound must not depend on an incumbent or assume undecided
stop/skip choices.

### C2. Candidate-Specific Latest Board and Alight Bounds

Derive expression-specific upper bounds:

```text
latest_board_time(candidate)
latest_alight_time(candidate)
```

Use them to tighten activation and horizon implications. Do not derive them
merely from a switch-time upper bound because boarding and alighting expressions
include route constants and possibly waiting. Prove each bound for both waiting
modes.

### C3. Fixed-Movement Passenger Evaluator

If the isolated passenger problem remains material, build the destination-
layered evaluator from `ean_decomposition.md`, measure its LP integrality, and
choose exact repair or decomposition only from those measurements.

## Low-Priority Experiments

Run these only when the relevant branch remains a bottleneck after the safer
changes:

- per-pair tight Big-M values for remaining headway disjunctions;
- `AND` activation plus forward/reverse indicators;
- indicators that replace an identical stop/skip or slot implication;
- binary passenger-count encodings;
- slot-time ordering cuts.

Keep existing valid inequalities when testing indicators. Cleaner solver syntax
alone is not evidence of a stronger or faster formulation.

## Acceptance Protocol

Every exact formulation toggle requires:

- focused unit tests for its algebra or classification;
- exact objective agreement on tiny production-path instances;
- checks for both objectives and both waiting modes;
- extraction and validator checks;
- a fixed-protocol benchmark against the selected baseline;
- separate reporting of construction, incumbent, and bound effects.

Long benchmarks remain outside pytest. Promote a change only when correctness
is established and its intended metric improves reproducibly without an
unacceptable regression elsewhere.

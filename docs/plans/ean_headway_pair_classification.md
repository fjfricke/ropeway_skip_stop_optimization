# EAN Headway Pair Classification

Status: **concept plan**

## Goal

Reduce the number of Gurobi ordering binaries created for EAN headway
constraints without changing the projected integer optimum.

The current implementation builds all unordered candidate pairs per headway
checkpoint and creates one binary ordering variable for every pair. This is
safe, but it treats pairs with physically fixed order the same as pairs where
both orders can actually occur.

This plan introduces a conservative classification step:

```text
fixed-order pair       -> directed headway constraint, no ordering binary
variable-order pair    -> current disjunctive formulation with ordering binary
redundant pair         -> omitted only when violation is provably impossible
```

The first implementation should only classify pairs as fixed when the proof is
local and unambiguous. All uncertain pairs must remain variable-order pairs.

## Current State

Implemented EAN optimizations:

- `candidate_horizon_pruning`
- `single_ring_dominated_ride_pruning`
- `slot_time_relaxation_strengthening`
- `tight_big_m_bounds` behind an opt-in toggle

Current headway generation:

- `SwitchVisitHeadwayCandidateBuilder` creates candidates per checkpoint and
  switch visit.
- `AllPairsHeadwayPairBuilder` creates every unordered pair of candidates that
  share a checkpoint.
- `passenger_service._add_headway_constraints` creates one binary `order_*`
  variable and two Big-M constraints for every headway pair.

Current generated artifacts show that headway pairs are still large:

```text
five_station_v0:
  headway candidates: 2,719
  headway pairs:      166,692
    platform_entry:    60,648
    platform_exit:     45,396
    exit_switch:       60,648

five_station_no_wait_v0:
  headway candidates: 3,894
  headway pairs:      471,950
```

For `five_station_v0`, 4,077 pairs compare different visits of the same cabin.
Those pairs have a fixed visit-index order and do not need an ordering binary.
This is a small but very safe first reduction.

## Non-Goals

- Do not add successor-selection variables.
- Do not impose a new global FIFO policy at exit switches.
- Do not infer aggressive waiting upper bounds from the next cabin.
- Do not remove variable-order pairs at service/skip merges unless reordering
  is provably impossible.
- Do not change passenger assignment semantics.

## Pair Classes

### Variable-Order Pair

Use this when both temporal orders may occur because stop/skip or waiting can
change the ordering before the checkpoint.

Examples:

- service-vs-skip candidates at an exit switch,
- pairs downstream of a service/skip merge when upstream order can be inverted,
- any pair whose order classifier cannot prove a fixed order.

Modeling stays unchanged:

```text
order_pair in {0,1}
first clears before second enters, or second clears before first enters
```

### Fixed-Order Pair

Use this when one candidate must precede the other whenever both candidates are
active.

Initial safe cases:

- same cabin, same checkpoint, lower `visit_index` before higher `visit_index`;
- no-skip/no-wait artifacts where generated switch visits preserve a single
  directed ring order and the checkpoint is not downstream of a reordering
  resource.

Modeling:

```text
leader_clear_time + headway <= follower_enter_time + activation_relaxation
```

No ordering binary is created.

### Redundant Pair

Use this only when conservative time windows prove that the pair can never
violate the headway.

Example condition:

```text
leader_latest_clear_time + headway <= follower_earliest_enter_time
```

This class should not be part of the first implementation unless robust
earliest/latest bounds are already available. The initial implementation should
prefer fixed-order pairs over omitted pairs.

## Data Model Options

### Option A: Extend `HeadwayPair`

Add fields:

```python
order_mode: HeadwayPairOrderMode
leader_candidate_id: str | None
follower_candidate_id: str | None
```

For `VARIABLE`, keep `first_candidate_id` and `second_candidate_id` unordered.
For `FIXED`, use `leader_candidate_id` and `follower_candidate_id`.

Pros:

- minimal artifact shape change
- one collection in `EanBuildArtifact`

Cons:

- optional fields make validation more complex

### Option B: Separate Pair Types

Introduce:

```python
VariableHeadwayPair
FixedHeadwayPair
```

and store separate tuples in `EanBuildArtifact`.

Pros:

- cleaner validation
- optimizer loops are explicit
- no optional leader/follower fields

Cons:

- larger artifact schema change
- more frontend/export compatibility work

Recommendation: start with **Option A** for a small implementation, then split
types later if the schema grows.

## Proposed Implementation

### 1. Add Pair Order Mode

File:

```text
src/ropeway_skip_stop_optimization/optimization/ean/models.py
```

Add:

```python
class HeadwayPairOrderMode(Enum):
    VARIABLE = "variable"
    FIXED = "fixed"
```

Extend `HeadwayPair` with enough information to represent a directed fixed
pair. Validation must reject invalid combinations.

### 2. Add Classifier

New file:

```text
src/ropeway_skip_stop_optimization/optimization/ean/builders/headway_pair_classifier.py
```

Responsibilities:

- receive two candidates and the checkpoint definition;
- return `VARIABLE` or `FIXED`;
- for `FIXED`, return the leader and follower candidate ids;
- never classify as fixed unless the proof is explicit.

Initial rules:

```text
same checkpoint and same cabin:
  lower visit_index is leader

otherwise:
  variable
```

This first rule is exact because a cabin's own generated switch-visit sequence
is ordered by construction.

### 3. Replace Pair Builder Internals

File:

```text
src/ropeway_skip_stop_optimization/optimization/ean/builders/headway_pair_builder.py
```

Keep the public builder interface. Replace blind pair construction with:

```text
for first_candidate, second_candidate in combinations(...):
    classification = classifier.classify(...)
    build fixed or variable HeadwayPair
```

Keep `AllPairsHeadwayPairBuilder` as the conservative implementation name only
if all pairs are still emitted. If the name becomes misleading, add:

```python
ClassifiedHeadwayPairBuilder
```

and switch `RingEanBuildArtifactBuilder` to use it by default.

### 4. Split Optimizer Constraint Generation

Files:

```text
src/ropeway_skip_stop_optimization/optimization/ean/optimizers/passenger_service.py
src/ropeway_skip_stop_optimization/optimization/ean/optimizers/skip_stop_feasibility.py
```

Current behavior:

```text
every pair -> order binary + forward constraint + reverse constraint
```

New behavior:

```text
VARIABLE:
  current disjunctive formulation

FIXED:
  one directed constraint
  no order binary
```

The fixed constraint must still be activation-relaxed when candidates can be
inactive:

```text
leader_clear_time + h
  <= follower_enter_time + M * (leader_inactive + follower_inactive)
```

### 5. Add Build Statistics

Expose and log:

```text
headway_pairs_total
headway_pairs_fixed
headway_pairs_variable
headway_pairs_redundant
ordering_binaries
```

The optimizer log should distinguish `headway_pairs` from `ordering_binaries`,
because after this change they are no longer equal.

### 6. Add Tests

Unit tests:

```text
tests/test_optimization_ean_headway_pair_classifier.py
```

Required cases:

- same cabin, same checkpoint, lower visit index classified as fixed leader;
- same cabin with reversed input order still returns lower visit index leader;
- different cabins classified as variable in v1;
- duplicate same-cabin same-visit pair remains invalid;
- artifact validation rejects malformed fixed pairs.

Optimizer tests:

- small artifact with one fixed pair creates no `order_*` variable for that
  pair;
- fixed pair adds one directed headway constraint;
- variable pair behavior remains unchanged.

Regression tests:

- existing EAN artifact builders still validate;
- passenger optimizer gives the same objective on a tiny exact instance with
  classification enabled and disabled.

### 7. Benchmark

Run at least:

```text
five_station_v0 / ean_passenger_waiting_time / quick_good_solution
five_station_v0 / ean_passenger_journey_time / quick_good_solution
three_station_v0 / ean_passenger_waiting_time / exact or short proof mode
```

Compare:

- model variables,
- binary variables,
- constraints,
- ordering binaries,
- root relaxation objective,
- incumbent after fixed time limit,
- best bound after fixed time limit,
- MIP gap,
- wall time to first incumbent.

Expected first effect is modest because same-cabin fixed pairs are only a few
thousand pairs in the five-station artifact. The main value is establishing the
classification mechanism safely, so stronger rules can be added later.

## Later Conservative Rules

After the same-cabin rule is implemented and benchmarked, consider:

1. **No-skip/no-wait fixed ring order**
   For artifacts where every station has a unique path and no waiting mode can
   invert order, classify all checkpoint pairs by generated ring order.

2. **Same-route service FIFO**
   For platform resources where both candidates require service and the
   physical service route has no overtaking opportunity, classify by entry
   order. This needs a precise definition of the upstream order point.

3. **Time-window redundant pairs**
   Use conservative earliest/latest bounds to omit pairs that cannot violate
   headway. This requires robust bounds and careful tests.

4. **Graph-based reordering analysis**
   Analyze whether alternative paths between an upstream fixed-order point and
   the checkpoint can invert order. Fall back to variable whenever uncertain.

## Risk Assessment

Main risk:

```text
classifying a truly variable pair as fixed
```

This would remove feasible solutions and can change the optimum silently.

Mitigation:

- start with only same-cabin fixed pairs;
- keep all different-cabin pairs variable in v1;
- add classifier statistics;
- validate tiny instances against the current all-variable model;
- keep a config toggle to disable classification during benchmarking.

## Suggested Toggle

Add a new EAN optimization name:

```text
headway_pair_classification
```

Default recommendation:

- off during first implementation and benchmark;
- on by default only after same objective results are confirmed on small exact
  instances and larger benchmark results are non-regressive.


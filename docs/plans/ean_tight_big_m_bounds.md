# EAN Tight Big-M Bounds Plan

Status: **Phase 1 implemented**

## Goal

Add a benchmarkable `tight_big_m_bounds` optimization for the EAN passenger
service MILP.

The current passenger optimizer uses one broad global Big-M value:

```text
big_m = time_upper_bound + max_headway + 1
```

This is safe, but weak. In the LP relaxation, fractional binary variables can
partially deactivate time constraints with a very large slack term. That lets
the root relaxation contain unrealistic fractional timing and passenger-service
solutions, which slows MIP gap closure.

The goal is to replace selected uses of the global Big-M with conservative
constraint-specific bounds while preserving the exact integer feasible set.

## Expected Effects

Expected improvements:

```text
stronger root relaxation
higher best bound earlier
faster MIP gap reduction
better numerical behavior
possibly fewer branch-and-bound nodes
```

Possible downsides:

```text
extra implementation complexity
extra bound-calculation cost during model build
risk of cutting off feasible integer solutions if a bound is too tight
little or no benefit for some constraint families
```

This optimization should be measured against the existing benchmark baseline,
not assumed beneficial.

## Optimization Toggle

Add a new EAN optimization name:

```text
tight_big_m_bounds
```

The existing benchmark CLI should then support:

```bash
--ean-optimizations all
--ean-optimizations candidate_horizon_pruning,single_ring_dominated_ride_pruning,slot_time_relaxation_strengthening,tight_big_m_bounds
```

Decision before defaulting:

```text
tight_big_m_bounds should remain opt-in until validated by tests and benchmark.
```

After validation, decide whether `all` should include it. Until then, `all`
means the current proven default optimizations.

## Implementation Strategy

Implement in small, isolated scopes. Do not rewrite all Big-M constraints at
once.

### Phase 1: Passenger Slot Activation Big-M

First target the passenger slot constraints in:

```text
src/ropeway_skip_stop_optimization/optimization/ean/optimizers/passenger_service.py
```

Initial constraints include:

```text
board_time >= release_time - M * (1 - slot)
board_time <= horizon_seconds + M * (1 - slot)
alight_time <= horizon_seconds + M * (1 - slot)
slot_board_time >= board_time - M * (1 - slot)
slot_alight_time >= alight_time - M * (1 - slot)
```

These are a good first target because they are candidate-specific and numerous.
For the first implementation, keep the bounds deliberately conservative and
derive them only from bounds that are valid for the exact expression used in
the constraint.

```text
slot_board_time, slot_alight_time in [0, time_upper_bound]
switch_time, exit_switch_time, wait_time in [0, time_upper_bound]
```

Do not introduce candidate-specific latest board/alight time calculations in
Phase 1. Those could be useful later, but they require more careful reasoning
about visit-specific timing windows and stop/skip choices.

Potential future helper shape:

```python
@dataclass(frozen=True)
class CandidateTimeBounds:
    earliest_board_time: float
    earliest_alight_time: float
    latest_board_time: float
    latest_alight_time: float
```

Potential Big-M helper shape:

```python
def _slot_big_m_bounds(
    ride_candidate: EanRideCandidate,
    group: EanDemandGroup,
    artifact_time_bounds: ...,
) -> SlotBigMBounds:
    ...
```

Keep the first version conservative. It is better to retain a larger M than to
remove valid solutions.

Phase 1 safe values:

```text
release lower-bound M: group.release_time_seconds
```

Implementation status:

```text
implemented behind opt-in toggle tight_big_m_bounds
not included in --ean-optimizations all yet
```

This is safe for:

```text
board_time >= release_time - M * (1 - slot)
```

because when `slot = 0`, `M = release_time` relaxes the constraint to:

```text
board_time >= 0
```

which is already implied by nonnegative switch/wait variables and nonnegative
timing constants.

Do **not** tighten the horizon constraints in Phase 1 with:

```text
max(0, time_upper_bound - horizon_seconds)
```

for:

```text
board_time <= horizon_seconds + M * (1 - slot)
alight_time <= horizon_seconds + M * (1 - slot)
```

That value would only be safe if `board_time` and `alight_time` themselves were
bounded above by `time_upper_bound`. In the current model they are expressions,
not standalone bounded variables:

```text
board_time  = switch_time + entry/platform constants + wait_time
alight_time = switch_time + entry/platform constants
```

So `switch_time <= time_upper_bound` does not by itself imply
`board_time <= time_upper_bound` or `alight_time <= time_upper_bound`.
Tightening these horizon constraints requires expression-specific upper bounds,
or candidate-specific latest board/alight times, and should remain a future
step.

Also do not tighten the existing slot-time link constraints in Phase 1 beyond
their current `time_upper_bound` value unless a helper proves an upper bound for
the exact `board_time` / `alight_time` expression used there.

### Phase 2: Stop/Skip Timing Big-M

Implementation status:

```text
implemented behind opt-in toggle tight_big_m_bounds
not included in --ean-optimizations all yet
```

Phase 2 targets stop/skip timing implications:

```text
stop = 1 -> exit_time = entry_time + service_time + wait_time
stop = 0 -> exit_time = entry_time + skip_time
stop = 0 -> wait_time = 0
```

The implementation derives each M from the opposite active branch, preserving
the integer feasible set while cutting fractional relaxation slack:

```text
service constraints inactive -> skip timing active
skip constraints inactive    -> service timing active
```

Detailed derivation and benchmark instructions are in:

```text
docs/plans/ean_stop_skip_big_m_bounds.md
```

### Phase 3: Headway Constraints

Headway constraints should come last.

They combine candidate activation and ordering:

```text
if both candidates are active:
  either first + headway <= second
  or     second + headway <= first
```

Tightening these Big-M values requires careful per-pair bounds. Too-tight
values can silently remove feasible orderings. Benchmark per-pair tighter
Big-Ms before considering indicator or AND reformulations.

## Bound Safety Rules

Every tighter M must satisfy:

```text
M >= maximum possible violation of the inactive constraint
M >= 0
M must be finite
```

Do not derive M from incumbent solutions or heuristic schedules. Bounds must be
valid for the full feasible region of the model.

Allowed sources:

```text
global horizon and tail
visit index ordering
known minimum travel/service times
known maximum time upper bounds from variable domains
candidate board/alight visit structure
```

Avoid:

```text
using expected all-stop timings as hard bounds
using demand release times as an upper bound
assuming a stop/skip decision before it is decided
using a bound that depends on the objective
```

## Testing Plan

### Unit Tests

Add tests for each bound helper:

```text
computed M is positive
computed M is no larger than the global M when expected
computed M remains conservative on minimal ring examples
computed M handles waiting and no-waiting station modes
```

### Solver Regression Tests

Use small examples where Gurobi can solve quickly:

```text
tight_big_m_bounds off/on both solve optimal
objective values match
served/unserved counts match
movement plan validates
passenger plan validates
```

For Phase 1, compare:

```text
EanOptimizationConfig(... tight_big_m_bounds=False)
EanOptimizationConfig(... tight_big_m_bounds=True)
```

### Benchmark Tests

Do not add long benchmarks to pytest. Use the benchmark runner.

Initial benchmark:

```bash
uv run python benchmarks/run_ean_passenger_benchmark.py \
  --example three_station_v0 \
  --artifact-set ean_passenger_journey_time \
  --ean-solver-policy exact_optimality \
  --time-limit 300 \
  --sample-interval 5 \
  --ean-optimizations all \
  --label opt_all_5min

uv run python benchmarks/run_ean_passenger_benchmark.py \
  --example three_station_v0 \
  --artifact-set ean_passenger_journey_time \
  --ean-solver-policy exact_optimality \
  --time-limit 300 \
  --sample-interval 5 \
  --ean-optimizations candidate_horizon_pruning,single_ring_dominated_ride_pruning,slot_time_relaxation_strengthening,tight_big_m_bounds \
  --label tight_big_m_5min
```

Compare:

```text
best_bound
mip_gap
objective
runtime
node_count
constraint_count
time to 10%, 8%, 7% gap
```

## Metadata

The benchmark JSON already records:

```text
ean_optimizations
ean_optimization_config
```

If tight Big-M bounds become complex, add optional solver metadata:

```text
global_big_m
slot_big_m_min
slot_big_m_max
slot_big_m_median
stop_skip_big_m_min
stop_skip_big_m_max
```

This metadata is diagnostic only. It should not affect frontend exports.

## Acceptance Criteria

Phase 1 can be considered successful if:

```text
all existing relevant tests pass
small solver regression tests match objective and feasibility
benchmark final gap improves or time-to-gap improves without worsening objective
no material model-build slowdown is observed
```

If benchmark results are neutral or worse, keep the toggle available for
diagnostics but do not include it in `all`.

## Non-Goals

Do not:

```text
replace the MILP with a different model
change passenger semantics
change candidate pruning semantics
change frontend export defaults
add long Gurobi runs to pytest
compute candidate-specific latest board/alight times in Phase 1
switch headway constraints to indicators in Phase 1
```

Indicator reformulations remain a separate experiment after tighter Big-M
values are understood.

## Future Ideas

Candidate-specific latest board/alight times could tighten Phase 1 further.
This would replace the domain-only bounds with visit/candidate-specific upper
bounds such as:

```text
latest_board_time(candidate)
latest_alight_time(candidate)
```

That may improve the relaxation more than the initial safe bounds, but it needs
separate proof and tests because overly aggressive latest-time bounds can remove
valid schedules when stop/skip timing and waiting decisions shift within the
horizon.

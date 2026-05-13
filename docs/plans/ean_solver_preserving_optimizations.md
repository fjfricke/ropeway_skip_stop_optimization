# EAN Solver-Preserving Optimizations

Status: **in progress**

## Goal

Collect optimizer implementation changes that should not change the mathematical
optimum of the EAN passenger problem. These changes may affect runtime,
numerical behavior, LP relaxation strength, incumbents, or exported diagnostics,
but they must not change which integer solution is optimal for the same scenario,
demand, horizon, and objective.

## Classification

Use this split when deciding whether a change belongs here or in the main model
plan.

**Adjustments** preserve the same projected integer solution set and objective:

```text
tighter valid inequalities
tighter Big-M values
indicator reformulations of existing implications
multiple MIP starts
variable hints
branch priorities
solver parameter presets
non-exported benchmark logging
```

**Additions** extend the model surface, output surface, or scenario set:

```text
new objective definitions
new waiting modes
new passenger demand semantics
new artifact types
new debug or benchmark scenarios
new frontend views
new exported metadata fields
```

Some changes sit on the boundary. Exact candidate pruning is an adjustment only
when every removed candidate is provably infeasible or dominated without changing
the optimum. Heuristic pruning is an addition because it changes the solved
problem.

The "no full-cycle passenger ride" rule is not just a speed optimization. It is
a candidate-semantics restriction: passengers may not ride one or more complete
ring cycles before alighting. It belongs in the passenger-candidate plan, not in
this solver-preserving file, although it will reduce model size.

## Slot-Time Strengthening

Priority: **highest formulation adjustment**

Status: **implemented**

Current slot-time constraints encode:

```text
slot_time = board_time  if slot = 1
slot_time = 0           if slot = 0
```

For integer solutions this is fine. In the LP relaxation, fractional slots can
make service artificially cheap. Add safe lower-bound constraints for each ride
candidate and slot:

```text
slot_board_time >= release_time * slot
slot_alight_time >= earliest_possible_alight_time * slot
slot_alight_time - slot_board_time >= min_trip_time * slot
```

Where:

```text
min_trip_time = lower bound from board platform exit to alight platform entry
earliest_possible_alight_time = release_time + min_trip_time
```

This does not remove any valid integer solution if the trip-time bound is
conservative. It strengthens the relaxation directly, so it should stay even if
slot activation is later expressed with indicators.

Likely files:

```text
src/ropeway_skip_stop_optimization/optimization/ean/optimizers/passenger_service.py
tests/test_optimization_ean_passenger_service.py
```

Implementation note:

```text
The implemented helper is documented as a slot-time relaxation strengthening
optimization. It preserves the integer feasible set and only adds valid lower
bounds for active slot-time variables.
```

## Big-M Tightening

Priority: **high formulation adjustment**

Status: **planned**

Current Big-M uses a broad global value:

```text
time_upper_bound + max_headway + 1
```

Replace broad constants with per-constraint bounds where practical:

```text
M_time_link[candidate] = latest_time_a - earliest_time_b + headway
M_slot[candidate] = candidate-specific time upper bound
M_stop_visit = visit-specific latest - earliest
```

This preserves the optimum only if every bound is proven conservative. Too-tight
Big-M values silently remove feasible integer solutions, so tests must compare
known feasible scenarios before and after the change.

## Indicator Reformulations

Priority: **high implementation adjustment, benchmark required**

Status: **next formulation experiment after metadata and benchmark**

Use Gurobi general constraints where an existing Big-M block is just a clean
binary implication.

Best first candidate:

```text
stop = 1 -> exit_time = entry_time + service_time + wait_time
stop = 0 -> exit_time = entry_time + skip_time
stop = 0 -> wait_time = 0
```

This maps directly to `addGenConstrIndicator` and removes four broad Big-M
constraints per visit in the stop/skip timing block.

Slot activation can also use indicators:

```text
slot = 1 -> board_time/alight_time obey release and horizon bounds
slot = 1 -> slot_time = actual board/alight time
slot = 0 -> slot_time = 0
```

Keep the slot-time strengthening constraints from above. Indicators make the
conditional semantics cleaner, but they do not replace the valid inequalities
that improve the LP relaxation.

Headway disjunctions are more delicate. They currently encode:

```text
if both candidates are active:
  either first + headway <= second
  or     second + headway <= first
```

This cannot be replaced by a single indicator because the trigger is a
conjunction of candidate activity and ordering. A Gurobi-specific formulation
would need helper binaries such as:

```text
pair_active = AND(first_active, second_active)
forward + reverse = pair_active
forward = 1 -> first + headway <= second
reverse = 1 -> second + headway <= first
```

Use `addGenConstrAnd` and `addGenConstrIndicator` only as an experiment here.
Benchmark it against tighter per-pair Big-M values because it removes time
Big-M coefficients but adds extra binary structure.

Likely files:

```text
src/ropeway_skip_stop_optimization/optimization/ean/optimizers/passenger_service.py
src/ropeway_skip_stop_optimization/optimization/ean/optimizers/skip_stop_feasibility.py
```

## MIP Starts, Hints, and Branching

Priority: **incumbent/search adjustment**

Status: **planned after first indicator benchmark**

The all-stop MIP start is accepted and gives a valid incumbent. Improve it or
add additional starts:

```text
all-stop no-wait earliest plan
skip station visits with no boarding/alighting in the greedy assignment
serve middle station only around active demand windows
greedy journey-time assignment with capacity tracking
```

Gurobi-specific mechanisms:

```text
multiple MIP starts through NumStart / StartNumber
VarHintVal for likely stop/skip and slot decisions
BranchPriority for important stop variables before passenger slot variables
```

Use MIP starts for concrete feasible solutions. Use variable hints when the
pattern is plausible but not a complete feasible solution. These do not change
the optimal solution, but they can change which feasible solution is found under
a time limit.

## Solver Policy Presets

Priority: **runtime policy adjustment**

Status: **implemented**

Expose solver policy through config/CLI instead of hardcoding only `MIPGap`.

Useful knobs:

```text
MIPGap
TimeLimit
Threads
MIPFocus
Heuristics
NoRelHeurTime
ImproveStartGap
Cuts
Presolve
```

Implemented presets:

```text
default:
  no explicit Gurobi parameters

debug_short:
  MIPGap = 0.20
  TimeLimit = 60
  Method = 3

quick_good_solution:
  MIPGap = 0.10
  Method = 3
  MIPFocus = 1

paper_benchmark:
  MIPGap = 0.01
  Method = 3
  MIPFocus = 2
```

Parameter presets do not change the true optimum. They do change when the solver
stops and therefore may change the best returned incumbent for incomplete runs.
The export CLI exposes them through `--ean-solver-policy`.

## Metadata

Priority: **observability addition with no optimization effect**

Status: **implemented**

Metadata does not affect the solve, but it should live near solver work because
it is needed to compare formulation changes. It is still an output-surface
addition, not a formulation adjustment.

Add fields such as:

```text
runtime_seconds
mip_gap
best_bound
objective_value_seconds
solution_count
node_count
mip_gap_target
time_limit_seconds
solver_status
```

The frontend surfaces the core diagnostics in the EAN artifact, EAN replay, and
graph views so incomplete/time-limited runs are visible without inspecting raw
JSON.

## Benchmark Rule

For every formulation-preserving change, compare:

```text
model vars / constraints
first accepted incumbent
root relaxation best bound
time to first incumbent
time to target gap
final objective
served / unserved passengers
visible skips
waits
```

Keep a previous formulation available until the new one is measured. Especially
for indicators, cleaner modeling is not automatically faster.

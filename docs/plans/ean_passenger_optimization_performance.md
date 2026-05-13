# EAN Passenger Optimization Performance Plan

Status: **in progress**

## Goal

Make the continuous EAN passenger optimizer produce good feasible solutions
faster, and make the reported MIP gap meaningful enough that a target such as
`10%` is reachable on the three-station passenger example.

The current model is functionally useful, but the first journey-time runs show
that the LP relaxation is weak:

```text
initial MIP start objective:  ~3.52M seconds
later incumbent:             ~1.75M seconds
root relaxation initially:   near 0
slot variables:              61k+
ride candidates:             7.7k+
model size:                  ~420k vars / ~1.2M constraints
```

This plan focuses on exact model improvements first. Solver parameter tuning
and cloud execution are useful, but they should not hide a weak formulation.

Solver-preserving implementation optimizations are tracked separately in
`docs/plans/ean_solver_preserving_optimizations.md`. This file keeps the
priority order and benchmark protocol.

## Non-Goals

- Do not replace the continuous EAN with a discrete-time model.
- Do not use rolling horizon for the main exact benchmark.
- Do not add slow full-scenario Gurobi tests.
- Do not prune candidates unless the pruning is either exact or explicitly
  marked as heuristic.
- Do not implement FIFO station-buffer waits here. They remain a separate
  physical projection problem.

## Priority 1: Strengthen Slot-Time Relaxation

Status: **implemented**

Current slot-time constraints encode:

```text
slot_time = board_time  if slot = 1
slot_time = 0           if slot = 0
```

For integer solutions this is fine. In the LP relaxation, however, fractional
slots can make service artificially cheap. That explains why the root
relaxation can be close to zero even though any real service plan has a large
positive journey-time objective.

Add safe lower-bound constraints for each ride candidate and slot:

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

The bound must be conservative. It may be weaker than the true trip time, but
must never exceed the minimum physically possible trip time for that candidate.

Expected effect:

- much stronger root bound
- faster gap closure
- no valid integer solution removed
- very small implementation risk

Likely files:

```text
src/ropeway_skip_stop_optimization/optimization/ean/optimizers/passenger_service.py
tests/test_optimization_ean_passenger_service.py
```

Implementation sketch:

```python
min_trip_time = _min_candidate_trip_time_seconds(...)
model.addConstr(slot_board_time[key] >= group.release_time_seconds * slot_var)
model.addConstr(slot_alight_time[key] >= (group.release_time_seconds + min_trip_time) * slot_var)
model.addConstr(slot_alight_time[key] - slot_board_time[key] >= min_trip_time * slot_var)
```

For the waiting-time objective, only `slot_board_time` exists. The board-time
lower bound still applies.

Solver note: keep these explicit lower bounds even if slot activation is later
rewritten with Gurobi indicators. The lower bounds strengthen the relaxation.

Implementation status:

```text
implemented in passenger_service.py
covered by tests/test_optimization_ean_passenger_service.py
```

## Priority 2: Exact Ride Candidate Pruning

Status: **implemented**

Candidate generation currently keeps structural OD candidates and lets the MILP
decide stop/skip feasibility. This is correct but broad.

Add exact pruning in the passenger candidate builder before Gurobi variables
are created.

Safe pruning examples:

```text
earliest_possible_board_time > horizon_seconds
earliest_possible_alight_time > horizon_seconds
candidate cannot reach destination after origin within model_end_seconds
candidate requires a station that cannot be stopped at
passenger would stay onboard for a full ring cycle or more before alighting
```

Do not remove candidates just because they are unlikely. Dominance pruning can
come later and must be documented as exact or heuristic.

Ring-cycle restriction:

For the current single directed ring EAN, a passenger ride candidate must not
span a full `switch_cycle`. In code terms:

```text
0 < alight_visit_index - board_visit_index < len(artifact.switch_cycle)
```

This enforces "at most one cycle minus one station" for the current examples and
prevents artifacts where passengers board, ride one or more full loops, and only
then alight at the destination. This is generic for the current immutable ring
builder. If we later support multiple switches per station, branches, or
non-ring topologies, the rule must move from raw `visit_index` span to an
explicit route/topology distance. The current limitation is documented in the
passenger candidate builder docstring.

Expected effect:

- fewer slot binaries
- fewer slot-time variables
- fewer passenger constraints
- faster model construction and presolve

Likely files:

```text
src/ropeway_skip_stop_optimization/optimization/ean/builders/passenger_builder.py
tests/test_optimization_ean_passenger_builder.py
```

Implementation status:

```text
implemented in passenger_builder.py
covered by tests/test_optimization_ean_passenger_builder.py
```

Current exact pruning includes horizon pruning and the single-ring ride-span
restriction. If an artifact is not recognized as a single directed ring, the
ring-span restriction is skipped and a warning is logged so benchmark output
shows that the optimization did not apply.

## Priority 3: Better MIP Starts

Status: **planned after metadata and first indicator benchmark**

The all-stop MIP start is accepted by Gurobi and gives a valid incumbent. Add
additional starts or improve the existing one so the first incumbent is closer
to the useful region.

Candidate starts:

```text
all-stop no-wait earliest plan
skip station visits with no boarding/alighting in the greedy assignment
serve middle station only around active demand windows
greedy journey-time assignment with capacity tracking
```

Gurobi-specific starts, hints, and branch priorities are tracked in
`ean_solver_preserving_optimizations.md`.

Expected effect:

- better incumbent earlier
- frontend replay becomes useful sooner
- less time spent discovering obvious feasible plans

Important distinction:

This improves the incumbent, not necessarily the best bound. It should be
combined with Priority 1.

Likely file:

```text
src/ropeway_skip_stop_optimization/optimization/ean/optimizers/passenger_service.py
```

## Priority 4: Solver-Preserving Formulation Improvements

Status: **next formulation step after metadata and benchmark**

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

Also evaluate Gurobi indicator reformulations for clean conditional blocks,
especially stop/skip timing. Details and the headway caveat live in
`ean_solver_preserving_optimizations.md`.

Expected effect:

- stronger relaxation
- better numerical behavior
- fewer fractional artifacts in root relaxation

Risk:

- moderate implementation risk if bounds are too tight
- requires tests that compare feasibility on known scenarios
- headway indicator reformulation may increase model size; benchmark before
  keeping it

## Priority 5: Solver Policy Presets

Status: **implemented**

Expose solver policy through config/CLI instead of hardcoding only `MIPGap`.

Useful knobs include `MIPGap`, `TimeLimit`, `Threads`, `MIPFocus`,
`Heuristics`, `NoRelHeurTime`, `ImproveStartGap`, `Cuts`, and `Presolve`.

Recommended presets are defined in
`ean_solver_preserving_optimizations.md`.

Expected effect:

- easier experimentation
- better control over export runtime
- useful for frontend artifact generation

This should come after formulation improvements, because parameters cannot fix
a fundamentally weak relaxation.

Likely files:

```text
src/ropeway_skip_stop_optimization/optimization/ean/optimizers/passenger_service.py
src/ropeway_skip_stop_optimization/exports/cli.py
src/ropeway_skip_stop_optimization/exports/artifacts.py
```

Implementation status:

```text
implemented in optimization/ean/optimizers/solver_policy.py
export CLI exposes --ean-solver-policy
default export policy is quick_good_solution
covered by tests/test_optimization_ean_solver_policy.py
```

## Priority 6: Performance Metadata

Status: **implemented**

Store solve diagnostics in export metadata so frontend and JSON inspection can
show whether a result is optimal, gap-limited, or time-limited.

Add metadata fields:

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

Expected effect:

- easier comparison between runs
- clear frontend/debug reporting
- prevents confusing "optimized" vs. "best available" language

Implementation status:

```text
metadata is collected directly from the Gurobi model after optimize()
frontend EAN, EAN Replay, and Graph views display solver status/gap/runtime
covered by tests/test_optimization_ean_passenger_service.py
```

## Priority 7: Smaller Debug Scenarios

Status: **supporting work**

Keep the full three-station scenario as the main benchmark, but add smaller
developer scenarios for fast iteration:

```text
short horizon
fewer cabins
one or two demand groups
same physical station geometry
same EAN code path
```

Expected effect:

- faster test-driven development
- safer refactors
- no need to run the full export for every formulation change

Do not replace the full example with this. It is only a debug fixture.

## Priority 8: Compute Server / Cloud

Status: **optional infrastructure**

Gurobi already uses all local Mac cores when available. A Compute Server can
help if we have a stronger machine available, but it does not reduce the model
size or improve the relaxation.

Use cloud only after:

```text
slot relaxation is strengthened  (done)
candidate pruning is in place    (done)
solver metadata is exported
```

Expected effect:

- potentially faster wall-clock time
- no modeling improvement
- extra setup complexity

## Measurement Protocol

For every significant change, run the same export command:

```bash
uv run python -m ropeway_skip_stop_optimization.exports.cli \
  --artifact-set ean_passenger_journey_time \
  --output-root frontend/public/generated/examples \
  --progress
```

Compare:

```text
model vars / constraints
ride candidates
slot variables
first accepted incumbent
root relaxation best bound
time to first incumbent
time to 10% gap
final objective
visible skips
waits
served / unserved passengers
```

After export, inspect the result JSON:

```bash
python - <<'PY'
import json
from pathlib import Path

p = Path("frontend/public/generated/examples/three_station_v0/ean_passenger_service_journey_time.json")
data = json.loads(p.read_text())
print(json.dumps(data["metadata"], indent=2))

plan = data["movement_plan"]
waits = [
    (v["cabin_id"], v["visit_index"], v["station_id"], v["switch_id"], v["wait_seconds"])
    for tr in plan["trajectories"]
    for v in tr["visits"]
    if v["wait_seconds"] > 1e-6
]
skips = [
    (v["cabin_id"], v["visit_index"], v["station_id"], v["switch_id"], v["switch_time_seconds"])
    for tr in plan["trajectories"]
    for v in tr["visits"]
    if v["decision"] == "skip" and v["switch_time_seconds"] <= plan["horizon_seconds"]
]
print("waits", len(waits), waits[:20])
print("visible skips", len(skips), skips[:20])
PY
```

## Proposed Implementation Order

1. Done: add slot-time lower bounds and min-trip-time helper.
2. Done: add exact candidate pruning and verify candidate/slot counts decrease.
3. Done: add CLI/config presets for MIP gap, time limit, and solution focus.
4. Done: add solver metadata to exported result JSON and frontend solver cards.
5. Next: run a fixed benchmark export with `--ean-solver-policy quick_good_solution`.
6. Then: replace stop/skip timing Big-M constraints with `addGenConstrIndicator` and
   benchmark against the current formulation.
7. Optionally replace slot activation Big-M constraints with indicators while
   keeping the Priority 1 strengthening inequalities.
8. Improve MIP start quality, then add multiple starts or hints if useful.
9. Add smaller debug fixtures if formulation changes need faster iteration.
10. Experiment with headway indicator/AND reformulation only after the smaller
    formulation changes are measured.

# MILP v1 Minimize Total Passenger Waiting Time

Status: **partially implemented**

## Goal

Extend the current cabin movement MILP so it can optimize a passenger-facing objective:

```text
minimize total passenger waiting time
```

The first implementation should be correct and inspectable for the current three-station example. It should not replace the v0 movement feasibility solver. Instead, it should live next to v0 as a new passenger-aware MILP variant.

## Current Baseline

MILP v0 models only cabin movement:

```text
x[c,t,v] = 1 if cabin c is at discrete node v at time t
y[c,t,a] = 1 if cabin c uses discrete arc a from t to t+1
```

It enforces:

- exactly one position per cabin and time
- movement flow conservation
- fixed cabin start nodes
- node occupancy and discrete conflict constraints

It currently has objective:

```text
minimize 0
```

So any collision-free movement plan is optimal.

## New Objective

For v1, the objective should be:

```text
minimize sum_{t=0}^{H-1} sum_od q[t,od] * delta_seconds / 3600
```

Where:

```text
q[t,od] = passengers waiting at the end of time step t for origin-destination pair od
```

The value is measured in **passenger-hours**.

For optimization, dividing by 3600 is optional because it does not change the argmin. For reporting and metadata, passenger-hours should be used.

The objective should sum `q[t]` only for `t=0..H-1`. With the convention that `q[t]` is the queue after arrivals and boardings at time `t`, `q[t]` represents passengers waiting during interval `[t,t+1]`.

## Scope v1

Implement an aggregate passenger-flow model:

- demand is aggregated by OD pair and time step
- no individual passenger IDs inside the MILP
- cabin capacity is enforced with aggregate onboard counts
- boarding is instantaneous at valid platform boarding nodes
- alighting is instantaneous at valid platform alighting nodes
- waiting passengers board greedily only in replay, but in MILP boarding is optimized by variables
- passengers may only board if they can alight within the modeled horizon
- no backward arcs
- no rolling horizon
- no periodic pattern
- no passenger walking/boarding service time

The model should support all OD pairs present in `DiscreteDemand`, but it may start with the current three-station example.

## Key Semantics

### Time Indexing

Use the same discrete time grid as `DiscreteScenario`.

Demand with:

```text
demand.time_step = t
```

becomes available for boarding at time `t`.

Queue balance should be explicit about end-of-step semantics:

```text
q[t,od] = passengers still waiting after arrivals and boardings at time t
```

Recommended initial convention:

```text
q[0,od] = demand[0,od] - boarded[0,od]
q[t,od] = q[t-1,od] + demand[t,od] - boarded[t,od] for t > 0
```

The objective then counts the passengers left waiting after each time step.

### Boarding

Passengers can board cabin `c` for OD pair `(o,d)` at time `t` only if:

- cabin `c` is at a discrete node that allows boarding
- that node belongs to station `o`
- the cabin can still reach a valid alighting node for destination `d` within the modeled horizon
- the cabin has free capacity

For v1, do not model direction explicitly. The optimizer should infer service feasibility from the directed discrete graph, valid boarding/alighting nodes, and the selected `x/y` movement variables.

### Alighting

Passengers with destination `d` alight from cabin `c` at time `t` only if:

- cabin `c` is at a discrete node that allows alighting
- that node belongs to station `d`

For the current discretization, this means boarding/alighting should happen only at nodes explicitly marked by the service route endpoint logic, not on brake/accelerate/connector nodes.

### Waiting Locations

Cabin waiting is still governed by the movement graph.

Currently, the example permits cabin wait arcs only at:

```text
pn::L_platform_exit
pn::R_platform_exit
```

The passenger objective can therefore only improve service by selecting movement/waiting decisions allowed by those arcs. If we later need holding at `M`, we must add that physically in the scenario, not hide it in the objective model.

## New Variables

Reuse v0 movement variables:

```text
x[c,t,v] binary
y[c,t,a] binary
```

Add aggregate passenger variables.

### Queue

```text
q[t,o,d] integer >= 0
```

Passengers waiting at origin `o` for destination `d` after boarding decisions at time `t`.

### Boarding

```text
b[c,t,o,d] integer >= 0
```

Passengers with OD `(o,d)` boarding cabin `c` at time `t`.

Only create this variable if at least one boarding node for origin `o` is reachable by cabin `c` at time `t`.

### Onboard

```text
z[c,t,d] integer >= 0
```

Passengers onboard cabin `c` after time `t` whose destination is `d`.

Tracking by destination is enough for alighting and capacity. We do not need origin onboard after boarding.

### Alighting

```text
e[c,t,d] integer >= 0
```

Passengers alighting from cabin `c` at destination `d` at time `t`.

Only create this variable if at least one alighting node for destination `d` is reachable by cabin `c` at time `t`.

## New Constraints

### Queue Balance

For each OD pair `(o,d)`:

```text
q[t,o,d] = q[t-1,o,d] + demand[t,o,d] - sum_c b[c,t,o,d]
```

With the `t=0` special case:

```text
q[0,o,d] = demand[0,o,d] - sum_c b[c,0,o,d]
```

This automatically prevents boarding more passengers than have arrived because `q[t,o,d] >= 0`.

### Boarding Only At Origin Platform

Let:

```text
B[o] = discrete nodes where station_id=o and allows_boarding=True
```

Then:

```text
b[c,t,o,d] <= demand_big_m[o,d] * sum_{v in B[o]} x[c,t,v]
```

`demand_big_m[o,d]` can be the total demand for that OD pair over the horizon.

If the sum is zero, boarding is forced to zero.

### Alighting Only At Destination Platform

Let:

```text
E[d] = discrete nodes where station_id=d and allows_alighting=True
```

Then:

```text
e[c,t,d] <= capacity * sum_{v in E[d]} x[c,t,v]
```

If the cabin is not at a valid destination platform node, alighting is forced to zero.

### Onboard Balance

For each cabin `c` and destination `d`:

```text
z[c,t,d] = z[c,t-1,d] + sum_o b[c,t,o,d] - e[c,t,d]
```

With initial state:

```text
z[c,0,d] = sum_o b[c,0,o,d] - e[c,0,d]
```

If we later support cabins that start with passengers, initial onboard state must be added to config.

### Alighting Cannot Exceed Onboard

The onboard balance with nonnegative `z` helps, but it is clearer and often tighter to add:

```text
e[c,t,d] <= z[c,t-1,d] + sum_o b[c,t,o,d]
```

For v1, same-step board-and-alight for the same destination should be impossible because `o != d`, but the explicit bound is still useful.

### Cabin Capacity

For each cabin and time:

```text
sum_d z[c,t,d] <= cabin_capacity
```

### Empty Cabin At Horizon

For v1, passengers should not be allowed to board merely to reduce queue time if they cannot alight inside the modeled horizon.

Require:

```text
z[c,H,d] = 0
```

for every cabin `c` and destination `d`.

This is intentionally strict. It means the optimizer may leave passengers waiting near the end of the horizon instead of boarding them into a trip that is not completed within the model.

### Destination Reachability Cut

Boarding should be disallowed if the cabin cannot reach any alighting node for destination `d` after time `t`.

Precompute:

```text
can_reach_destination[c,t,d] = true/false
```

This should be a required sparse cut for v1, not an optional optimization. It prevents useless boarding variables and protects the end-of-horizon semantics.

Build it with reverse reachability:

- start from every discrete node with `station_id=d` and `allows_alighting=True`
- walk backward over allowed directed arcs
- respect the remaining time from `t` to `H`
- include only `(c,t,d)` combinations where a destination alighting node can still be reached

Then:

```text
b[c,t,o,d] variable exists only if can_reach_destination[c,t,d]
```

This is important for non-obvious routes and future ring/skip cases. It should use the directed discrete graph, not hard-coded left/right direction.

## Objective Details

Primary v1:

```text
minimize sum_{t=0}^{H-1} sum_od q[t,o,d] * delta_seconds / 3600
```

Tie-breakers should not be added initially unless the model returns strange but equivalent plans. Candidate later tie-breakers:

- minimize total waits by cabins
- minimize skipped service routes
- minimize total passenger time in cabin

These must be low-weight or lexicographic, because total waiting time is the real objective.

## Required Code Changes

### New Config/Result Models

Add a separate config instead of overloading `MilpV0Config`:

```python
@dataclass(frozen=True)
class MilpV1PassengerWaitingConfig:
    horizon_steps: int
    fixed_starts: tuple[FixedCabinStart, ...]
    allow_move_arcs: bool = True
    allow_wait_arcs: bool = True
    allow_skip_arcs: bool = True
    variable_strategy: MilpV0VariableStrategy = MilpV0VariableStrategy.SPARSE_REACHABILITY
```

Result metadata should include:

```text
objective_passenger_hours
total_boarded
total_unserved_at_horizon
movement_variable_count
passenger_variable_count
constraint_count
```

### New Solver Module

Add:

```text
src/ropeway_skip_stop_optimization/optimization/milp_v1_passenger_waiting.py
```

Recommended main function:

```python
solve_milp_v1_min_waiting_time(discrete_scenario, config, *, progress=None)
```

It should reuse:

- `build_discrete_graph_index`
- `_allowed_arc_ids`
- sparse/dense `MilpV0VariableIndex`
- movement constraints from v0, ideally extracted into helper functions

### Refactor Shared Movement Builder

To avoid copying v0 solver logic, extract shared functions from `milp_v0.py`:

```text
build_movement_variables(...)
add_position_constraints(...)
add_flow_constraints(...)
add_initial_constraints(...)
add_conflict_constraints(...)
extract_movement_plan(...)
```

v0 can keep its public API but call these helpers.

v1 then adds passenger variables and constraints before optimizing.

### Passenger Index Builder

Add a small index module or helper:

```text
optimization/passenger_index.py
```

It should precompute:

```text
od_pairs
demand_count_by_time_od
boarding_node_ids_by_station
alighting_node_ids_by_station
boarding_candidates_by_cabin_time_od
alighting_candidates_by_cabin_time_destination
can_reach_destination_by_cabin_time_destination
```

This should be sparse and derived from `MilpV0VariableIndex`.

The reachability data should be computed before creating passenger variables, so invalid `b[c,t,o,d]` variables are never materialized.

### Export

Add an export mode for the passenger-aware plan:

```text
three_station_v0__dt_0p5__milp_v1_min_waiting_plan_c{C}_h{H}.json
```

For initial testing, use smaller horizons:

```text
horizon=240
horizon=600
```

Do not commit large `horizon=2400` output artifacts unless explicitly needed.

## Test Plan

### Unit Tests

Add tests for:

- OD aggregation from `DiscreteDemand`
- boarding node index uses only `allows_boarding=True`
- alighting node index uses only `allows_alighting=True`
- no boarding variable is created for unreachable origin/time/cabin combinations
- no alighting variable is created for unreachable destination/time/cabin combinations
- no boarding variable is created if destination alighting is impossible before horizon end
- horizon-end onboard counts are forced to zero
- queue balance on a tiny one-cabin fixture
- capacity constraint prevents overboarding

### Solver Tests

Small synthetic cases:

1. One station pair, one demand batch, one cabin arrives once:
   - all demand boards if capacity is enough
   - objective equals expected passenger-hours

2. Demand exceeds cabin capacity:
   - only capacity boards
   - remaining passengers wait

3. Cabin not at boarding platform:
   - boarding is zero

4. Destination platform reached:
   - onboard destination count alights

### Integration Test

Run the three-station example with:

```text
cabins=23
horizon=240
variable_strategy=sparse_reachability
```

Validate:

- movement plan passes existing movement validation
- passenger queues are nonnegative
- onboard counts never exceed capacity
- onboard counts are zero at horizon end
- reported objective matches queue time sum

## Implementation Order

1. Create passenger index builder and tests. **Done.**
2. Extract shared v0 movement MILP helper functions. **Done.**
3. Add v1 config/result metadata. **Done.**
4. Add passenger variables without objective, with constraints only. **Done.**
5. Add passenger-hours objective. **Done.**
6. Add extraction of passenger summary metrics.
7. Add JSON export.
8. Run short-horizon integration benchmark.

## Implementation Notes

Current implementation supports:

- `--milp-mode movement --milp-objective feasibility`
- `--milp-mode passenger --milp-objective feasibility`
- `--milp-mode passenger --milp-objective waiting_time`

The waiting-time objective is:

```text
minimize sum_{t=0}^{H-1} sum_od q[t,o,d] * delta_seconds / 3600
```

The current `horizon=240`, `cabins=23`, `sparse_reachability` benchmark solves with objective `108.4211111111` passenger-hours, boards/alights 360 passengers, leaves 3120 unserved at horizon, and keeps zero passengers onboard at horizon.

## Open Decisions

- Whether `q[t]` should count waiting after boarding at `t` or before boarding at `t`. Recommended for v1: after boarding, because demand arriving at `t` can board immediately if a cabin is present.
- Whether all demand must eventually be served by horizon end. Recommended for v1: no hard requirement; report unserved passengers instead.
- Whether passengers can board a cabin that reaches the destination only after the horizon. Decision for v1: no. Require horizon-end onboard counts to be zero.
- Whether alighting can happen at `t=0` for initially loaded cabins. Recommended for v1: no initially loaded passengers in v1.

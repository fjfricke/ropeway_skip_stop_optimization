# Discretizer v0 Plan

## Purpose

Build the first deterministic converter from physical `Scenario` to `DiscreteScenario`.

The goal is not optimization yet. The goal is to produce a one-step movement graph that later supports:

- baseline all-stop path generation
- replay
- MILP path choices
- headway and shared-resource constraints

The discretizer should make approximation decisions explicit and testable.

## Scope

v0 input:

- physical `Scenario`
- `DiscretizationConfig`

v0 output:

- `DiscreteScenario`

v0 does not include:

- Gurobi/MILP model construction
- passenger replay
- cabin start-position mapping
- cycle-calibrated rounding
- exact physical feasibility validation
- capacity optimization

## Module Location

```text
src/ropeway_skip_stop_optimization/mapping/
  __init__.py
  physical_to_discrete.py
```

Public API:

```python
discretize_scenario(
    scenario: Scenario,
    config: DiscretizationConfig | None = None,
) -> DiscreteScenario
```

## Configuration

```python
@dataclass(frozen=True)
class DiscretizationConfig:
    delta_seconds: float = 0.5
    rounding_policy: RoundingPolicy = RoundingPolicy.CEIL
```

For v0, only `CEIL` should be implemented.

Reason:

- it prevents a movement from becoming faster than the physical travel time
- it matches the conservative approximation described in `discretization_notes.md`
- it keeps first tests simple

`delta_seconds = 0.5` is the default because:

- `required_cabin_spacing_m = 3.0 + 0.5 = 3.5`
- `rope_speed_m_per_s = 5.0`
- strict maximum step size from spacing and rope speed is `3.5 / 5.0 = 0.7s`
- `0.5s` is below this and aligns cleanly with clock times

## Travel Time Calculation

Travel time is derived from physical segment length and speed profile.

For constant speed:

```text
travel_seconds = length_m / speed_m_per_s
```

For linear speed profile over distance:

```text
average_speed = (start_speed_m_per_s + end_speed_m_per_s) / 2
travel_seconds = length_m / average_speed
```

For v0, linear profiles are treated through this average-speed formula.

Then:

```text
duration_steps = ceil(travel_seconds / delta_seconds)
rounding_slack_seconds = duration_steps * delta_seconds - travel_seconds
```

The discretizer should retain enough source metadata to inspect this later, but v0 does not need a separate report object yet.

## Segment Splitting

Each `TrackSegment` becomes:

- one sequence from the discrete physical start node to the discrete physical end node
- `duration_steps - 1` interior segment-position nodes when `duration_steps > 1`
- `duration_steps` one-step movement arcs

Each movement arc has:

- `kind = MOVE`
- `source_segment_id`
- `source_route_id` when the segment belongs to a station route

The generated interior segment-position nodes should carry:

- `source_segment_id`
- `station_id`
- `resource_id`
- `position_m`
- `allows_boarding`
- `allows_alighting`
- `allows_waiting=False`

For v0, interior positions are placed uniformly along the physical segment:

```text
position_m = length_m * i / duration_steps
for i = 1 .. duration_steps - 1
```

This is an approximation for linear acceleration/braking. Later we can place positions according to distance traveled per equal time step.

## Physical Node Representation

The current `DiscreteNode` can reference either a physical node or a segment position.

v0 should create explicit discrete nodes for physical nodes too:

```text
pn::<physical_node_id>
```

Segment sequences then connect:

```text
pn::<from_node>
  -> seg::<segment_id>::1
  -> ...
  -> seg::<segment_id>::n-1
  -> pn::<to_node>
```

This avoids duplicate endpoint nodes and makes route concatenation possible without artificial gaps.

If `duration_steps = 1`, the segment creates one arc directly:

```text
pn::<from_node> -> pn::<to_node>
```

## Route Mapping

The discretizer should build movement arcs from all physical segments, then annotate arcs with `source_route_id` for each station route that uses the source segment.

Important:

- route geometry is defined by segment ids
- route choices later become choices over the corresponding arc sequences
- stop/skip is not stored as a separate action

For v0, if one segment belongs to multiple station routes, this should raise an error unless we explicitly need sharing later. Shared physical segments can be supported later with richer metadata.

## Demand Conversion

Clock time is converted relative to the scenario start:

```text
raw_step = (clock_time - service_start_time) / delta_seconds
time_step = int(raw_step)
```

For v0:

- use exact integer conversion when possible
- raise if the time is not representable as an integer number of steps

This avoids hidden time rounding in demand.

Demand:

```text
time_step = converted arrival_time
origin = station id
destination = station id
count = unchanged
```

Horizon:

```text
horizon_steps = exact step difference from service_start_time to service_end_time
```

## Cabins In v0

Do not map cabins in Discretizer v0.

The output should deliberately contain:

```python
cabins=()
cabin_initial_states=()
```

Reason:

- v0 should validate the infrastructure graph first
- cabin starts raise separate questions about initial spacing and mid-segment positions
- replay/plan logic can introduce cabin initial states later with clearer requirements

The existing `DiscreteScenario.validate()` accepts this because the set of cabins and the set of initial states are both empty.

## Waiting Arcs

For each physical node with `allows_waiting=True`, v0 should create:

```text
wait::<discrete_node_id>
```

as a one-step `WAIT` arc from that node to itself.

No implicit waiting should be created on movement segments.

## Boarding And Alighting Flags

For v0:

- discrete physical platform nodes inherit service capability when they belong to a service route
- segment-position nodes on station platform segments may also be marked as service-capable if their source segment belongs to a boarding/alighting service route

This is enough for later replay to identify where passengers may board or alight.

The exact boarding/alighting mechanics are not part of the discretizer.

## Conflicts V0

Keep conflict logic deliberately simple.

Generate `DiscreteConflict(reason=HEADWAY)` between nodes that are on the same resource and whose physical distance proxy is less than `required_cabin_spacing_m`.

For v0, this can be limited to nodes created from the same `source_segment_id`.

Rules:

- never generate a conflict between a node and itself
- conflicts are unordered pairs
- do not yet generate cross-segment merge/switch conflicts

Limitations:

- this does not fully protect spacing across segment boundaries
- this does not model switch occupancy exactly
- this is acceptable for the first graph construction slice

Later versions should add:

- conflicts across adjacent segments in the operating cycle
- switch conflicts
- shared station resource conflicts
- skip/service merge conflicts

## Expected Counts For `three_station_v0`

With `delta_seconds = 0.5`:

Main rope:

```text
150 m / 5 m/s = 30s = 60 steps
```

M service route segments:

```text
approach_fast: 5 m / 1.0 m/s = 5s = 10 steps
brake: 3 m / 0.75 m/s = 4s = 8 steps
platform: 5 m / 0.5 m/s = 10s = 20 steps
accelerate: 3 m / 0.75 m/s = 4s = 8 steps
depart_fast: 5 m / 1.0 m/s = 5s = 10 steps
```

M skip:

```text
70 m / 5 m/s = 14s = 28 steps
```

Terminal turnaround:

```text
decelerate: 3 m / 0.75 m/s = 4s = 8 steps
platform: 5 m / 0.5 m/s = 10s = 20 steps
accelerate: 3 m / 0.75 m/s = 4s = 8 steps
```

The all-stop circulating cycle should be connected and closed.

## Tests

Create `tests/test_discretize.py`.

Required tests:

- `build_three_station_scenario()` discretizes without errors
- output validates via `DiscreteScenario.validate()`
- horizon from 08:00 to 08:20 at 0.5s is `2400` steps
- output has no cabins and no cabin initial states
- each 150 m rope segment creates 60 movement arcs
- each terminal platform segment creates 20 movement arcs
- each M skip segment creates 28 movement arcs
- demand times convert exactly
- waiting arcs exist only at nodes whose physical node allows waiting
- all movement arcs have valid endpoints
- all-stop service cycle can be followed as connected arc sequences

## Implementation Order

1. Add `mapping/physical_to_discrete.py` with config, time conversion, and travel-time helpers.
2. Generate physical-node discrete nodes.
3. Generate segment-position nodes and movement arcs.
4. Add route-id annotations.
5. Convert demands.
6. Add wait arcs.
7. Add same-segment headway conflicts.
8. Add tests.

## Known Limitations

- conservative `ceil` rounding creates drift over repeated cycles
- linear speed positions are uniform in space, not exact equal-time positions
- cabin start states are not represented yet
- conflicts do not yet span segment boundaries
- switch conflicts are not modeled yet
- route-duration distortion is not measured yet

These limitations should be acceptable for the first discrete graph because it establishes the data pipeline and gives replay/MILP a concrete graph to consume.

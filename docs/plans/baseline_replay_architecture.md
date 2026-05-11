# Baseline Replay Architecture Plan

## Goal

Build a small, shared project core before implementing optimization.

The first implementation step is a deterministic replay model with an all-stop baseline. This is not a separate side simulation. It is the common foundation that later Gurobi MILP code should use for input data, output plans, validation, and evaluation.

## Core Principle

The optimizer should not get its own separate model of the ropeway system.

Instead, the project should use one shared representation:

```text
Scenario -> DiscreteScenario -> Plan -> ReplayResult
```

Later:

```text
Scenario -> DiscreteScenario -> Gurobi MILP -> Plan -> ReplayResult
```

This keeps assumptions about stations, cabins, capacity, demand, stop events, queue handling, and metrics in one place.

## Initial Scope

The first version should be deliberately narrow:

- single ropeway line
- both directions where physical track segments are provided
- topology represented by stations, physical nodes, and directed track segments
- physical input data converted to a discrete time grid
- deterministic travel times
- identical cabins
- fixed cabin capacity
- fixed cabin initial states
- origin-destination demand by clock time
- first-come-first-served queues within each OD pair
- all cabins stop at all stations in the first baseline

Out of scope for the first version:

- Gurobi optimization
- station switching
- rolling horizon
- stochastic demand
- continuous-time optimization
- passenger route choice
- MATSim or real-world data integration

## Proposed File Structure

```text
src/ropeway_skip_stop_optimization/
  models/
    __init__.py
    scenario.py
    discrete_scenario.py
    plan.py
    result.py
  preprocessing/
    __init__.py
    discretize.py
  baseline.py
  replay.py
  metrics.py
  examples.py
```

Later additions:

```text
src/ropeway_skip_stop_optimization/
  optimizer/
    gurobi_milp.py
```

## File Responsibilities

### `models/`

Defines the shared data structures.

This should be a small package rather than one large `model.py` file. The exact split should be reviewed before implementation, but the current intended structure is:

```text
models/
  __init__.py
  scenario.py
  discrete_scenario.py
  plan.py
  result.py
```

The purpose is to separate four concepts:

- the physical input problem description
- the discretized replay/MILP problem description
- a concrete operating plan
- the replay output

Expected contents:

- `Station`
- `StationKind`
- `PhysicalNode`
- `TrackSegment`
- `SpeedProfile`
- `StationRoute`
- `Cabin`
- `CabinInitialState`
- `Demand`
- `OperatingParameters`
- `Scenario`
- `DiscreteScenario`
- `CabinArcStep`
- `Plan`
- `ReplayResult`

The models package should contain mostly plain data models and small validation helpers. It should not contain replay logic, optimization logic, or heavy discretization logic.

Before creating these files, review exactly which models are needed and what each one should contain. The first models to design in detail should be `Scenario` and `DiscreteScenario`, because together they define the input contract for both replay and the future MILP.

#### `models/scenario.py`

Contains the physical/domain input model.

This model should stay close to real-world input data:

- demand uses clock times, for example `datetime.time`
- track segments use physical lengths in meters
- operating parameters use physical units such as meters per second and meters
- stations and storage/depot locations are part of the same topology

Expected concepts:

- `StationKind`, for example `SERVICE`, `TERMINAL`, and `STORAGE`
- `Station`, with an id, optional name, kind, and references to service routes
- `PhysicalNode`, for physical graph points such as switches, platform entries, platform exits, and depot nodes
- `TrackSegment`, with id, source node, target node, length in meters, speed profile, and resource properties
- `SpeedProfile`, for constant speed or linear speed change over a segment
- `StationRoute`, with id, station id, route kind such as service or skip, and an ordered list of segment ids
- `Cabin`, with a simple integer id
- `CabinInitialState`, with cabin id, station id, and clock time
- `Demand`, with arrival clock time, origin, destination, and count
- `OperatingParameters`, with rope speed, station speed, cabin capacity, cabin length, and minimum clearance
- `Scenario`, which groups the above

The domain scenario should not decide route direction for a demand. A demand only states that passengers want to travel from origin to destination. The plan or optimizer decides how this is served.

#### Physical Infrastructure Model

The project should not model a skippable station as a single station node with a `can_skip` flag. That is too coarse for ropeway infrastructure.

Instead, the physical infrastructure should be represented as a directed segment network:

```text
incoming rope
     |
entry switch
   /        \
skip path   service path
   \        /
 exit switch
     |
outgoing rope
```

The skip path is a real physical path from an entry switch to an exit switch. Cabins on this path typically continue at rope speed and do not interact with passengers.

The service path is a physical path through the station. It may include approach, braking, platform/service, optional waiting, acceleration, and exit segments. Different station technologies can be represented by different segment definitions:

- fixed conveyor systems, where each segment has a fixed speed and therefore fixed travel time
- self-propelled station movement, where cabins must at least roll to the exit but may optionally wait in defined holding areas

This means that stop/skip decisions later become route choices through the infrastructure, not merely Boolean station attributes.

#### Station Service Route Shape

A service route through a station should be modeled as an ordered sequence of physical segments rather than as one station length.

The default shape for a skippable intermediate station should be:

```text
entry_switch
  -> approach_fast
  -> brake
  -> platform
  -> accelerate
  -> depart_fast
  -> exit_switch
```

The skip route is a separate physical route:

```text
entry_switch
  -> skip_bypass
  -> exit_switch
```

This allows the service path and skip path to have different lengths, speeds, capacities, and resource conflicts.

#### Segment Speed Profiles

Track-segment travel time should be derived from physical length and speed. We should avoid storing a separate minimum travel time when it can be computed.

Expected speed-profile types:

- `CONSTANT`, for normal rope travel, platform conveyor motion, skip bypasses, and fast approach/departure sections
- `LINEAR`, for braking and acceleration sections

For a constant-speed segment:

```text
travel_time_seconds = length_m / speed_m_per_s
```

For a linear speed-change segment:

```text
average_speed_m_per_s = (start_speed_m_per_s + end_speed_m_per_s) / 2
travel_time_seconds = length_m / average_speed_m_per_s
```

Braking and acceleration segments should therefore be represented as linear speed profiles between the speeds of adjacent sections. Builder helpers may infer these start/end speeds from neighboring segments later, but the underlying explicit model should support storing the resulting linear profile.

#### Avoiding Redundant Switch Definitions

We should avoid repeatedly specifying the same switch or station geometry in multiple places.

Preferred direction:

- define each physical switch once as a `PhysicalNode`
- define each physical movement once as a `TrackSegment`
- define a station service or skip option as a `StationRoute` that references existing segment ids
- derive graph arcs from these route and segment definitions

For simple examples, we may provide builder helpers that generate the common switch layout automatically. For example, a helper could create:

```text
M_entry_switch
M_service_entry
M_platform
M_service_exit
M_exit_switch
M_skip
```

from one higher-level station specification. The explicit low-level model should still exist underneath, so advanced cases can override the generated layout without changing replay or optimizer code.

#### `models/discrete_scenario.py`

Contains the replay/MILP-ready version of the scenario.

This model should use integer time steps and a one-step movement graph.

- demand uses `time_step`
- service horizon uses `horizon_steps`
- physical track segments are split into discrete position nodes and one-step movement arcs
- every movement arc takes exactly one time step
- waiting is represented by explicit one-step wait arcs at nodes where waiting is allowed
- headway and collision avoidance are represented by conflicts between discrete positions

Replay and MILP code should consume `DiscreteScenario`, not the physical `Scenario` directly.

This keeps numerical assumptions explicit and makes it possible to compare different discretizations later.

Expected concepts:

- `DiscreteNode`, representing a discrete physical position
- `DiscreteArc`, representing either one movement step or one waiting step
- `DiscreteDemand`, with integer arrival time step
- `DiscreteCabinInitialState`, with integer availability time step and initial discrete node
- `DiscreteConflict`, representing two discrete positions that cannot be occupied at the same time
- `DiscreteScenario`, which groups the above

The intended movement rule is:

```text
In each time step, each active cabin either traverses exactly one `DiscreteArc`
or waits on an explicit wait arc.
```

For a physical `TrackSegment`, the discretizer should:

```text
physical_travel_time_seconds = compute from length and speed profile
n_steps = ceil(physical_travel_time_seconds / delta_seconds)
create n_steps one-step movement arcs
```

For constant-speed segments, positions can be spaced approximately uniformly. For linear braking or acceleration segments, positions should be derived from the local speed profile along the segment.

This means slow station movement automatically creates more discrete positions over the same physical distance. Since required cabin spacing is measured in meters, a slow station path may require conflicts across multiple neighboring discrete positions.

### `preprocessing/discretize.py`

Converts the physical `Scenario` into a `DiscreteScenario`.

Expected main function:

```python
discretize_scenario(
    scenario: Scenario,
    delta_seconds: int,
) -> DiscreteScenario
```

This step should handle:

- clock time to time-step conversion
- service horizon conversion
- track-segment length and speed profiles to one-step movement arcs
- station service and skip routes to discrete movement paths
- allowed waiting nodes to one-step wait arcs
- cabin length and clearance to discrete position conflicts
- explicit rounding rules

The discretization should be a separate preprocessing step rather than hidden inside `Scenario`, because the time discretization is a methodological choice that affects both runtime and accuracy.

## Proposed Domain Model Draft

This draft describes the intended contents of `models/scenario.py`. It is intentionally Python-like, but should still be reviewed before implementation.

### Enums

```python
class StationKind(Enum):
    SERVICE = "service"
    TERMINAL = "terminal"
    STORAGE = "storage"
```

```python
class PhysicalNodeKind(Enum):
    ENTRY_SWITCH = "entry_switch"
    EXIT_SWITCH = "exit_switch"
    PLATFORM = "platform"
    HOLD = "hold"
    DEPOT = "depot"
    CONNECTOR = "connector"
```

```python
class TrackSegmentKind(Enum):
    ROPE = "rope"
    STATION = "station"
    SKIP = "skip"
```

```python
class SpeedProfileKind(Enum):
    CONSTANT = "constant"
    LINEAR = "linear"
```

```python
class StationRouteKind(Enum):
    SERVICE = "service"
    SKIP = "skip"
```

### `SpeedProfile`

```python
@dataclass(frozen=True)
class SpeedProfile:
    kind: SpeedProfileKind
    speed_m_per_s: float | None = None
    start_speed_m_per_s: float | None = None
    end_speed_m_per_s: float | None = None
```

Rules:

- `CONSTANT` uses `speed_m_per_s`
- `LINEAR` uses `start_speed_m_per_s` and `end_speed_m_per_s`
- all speeds must be positive
- linear travel time is computed from average speed

### `PhysicalNode`

```python
@dataclass(frozen=True)
class PhysicalNode:
    id: str
    kind: PhysicalNodeKind
    station_id: str | None = None
    allows_waiting: bool = False
```

Waiting is modeled at nodes, not on movement segments. This keeps `TrackSegment` as pure movement and supports station exit holding later.

### `TrackSegment`

```python
@dataclass(frozen=True)
class TrackSegment:
    id: str
    kind: TrackSegmentKind
    from_node_id: str
    to_node_id: str
    length_m: float
    speed_profile: SpeedProfile | None = None
    resource_id: str | None = None
```

Rules:

- `length_m` must be positive
- if `speed_profile` is `None`, defaults are taken from `OperatingParameters` based on `kind`
- `resource_id` groups segments that share a conflict/headway resource
- travel time is not stored here; it is derived during discretization

### `StationRoute`

```python
@dataclass(frozen=True)
class StationRoute:
    id: str
    station_id: str
    kind: StationRouteKind
    segment_ids: tuple[str, ...]
    allows_boarding: bool
    allows_alighting: bool
```

Rules:

- `SERVICE` routes usually allow boarding and alighting
- `SKIP` routes usually allow neither
- segment ids must form a connected directed path
- route geometry is not duplicated; routes only reference `TrackSegment` ids

### `Station`

```python
@dataclass(frozen=True)
class Station:
    id: str
    kind: StationKind = StationKind.SERVICE
    name: str | None = None
    route_ids: tuple[str, ...] = ()
```

Rules:

- `SERVICE` and `TERMINAL` stations may be used as demand origins and destinations
- `TERMINAL` stations model passenger terminal turnarounds and must not define skip routes
- `STORAGE` stations are part of the topology but should not receive passenger demand
- service and skip behavior is defined by referenced `StationRoute`s, not by Boolean station flags

### `Cabin`

```python
@dataclass(frozen=True)
class Cabin:
    id: int
```

Rules:

- cabins are physical vehicles
- cabins are identical in the first version
- global capacity belongs to `OperatingParameters`, not to each cabin

### `CabinInitialState`

```python
@dataclass(frozen=True)
class CabinInitialState:
    cabin_id: int
    node_id: str
    available_from: time
```

Rules:

- initial state references a physical node, not just a station
- storage/depot starts are represented by depot physical nodes
- this avoids a special start type

### `Demand`

```python
@dataclass(frozen=True)
class Demand:
    arrival_time: time
    origin: str
    destination: str
    count: int
```

Rules:

- demand uses clock time in the domain model
- `origin` and `destination` reference `Station.id`
- demand does not encode route direction
- only `SERVICE` and `TERMINAL` stations are valid demand origins and destinations
- `count` must be positive

### `OperatingParameters`

```python
@dataclass(frozen=True)
class OperatingParameters:
    rope_speed_m_per_s: float
    station_speed_m_per_s: float
    cabin_capacity: int
    cabin_length_m: float
    min_clearance_m: float
```

Rules:

- global speeds are defaults used when a segment has no explicit speed profile
- `cabin_length_m` describes the physical cabin length
- `min_clearance_m` describes the required free distance between cabins
- `required_cabin_spacing_m = cabin_length_m + min_clearance_m`
- discrete headway/resource constraints are derived during preprocessing or graph construction

### `Scenario`

```python
@dataclass(frozen=True)
class Scenario:
    id: str
    service_start_time: time
    service_end_time: time
    stations: tuple[Station, ...]
    physical_nodes: tuple[PhysicalNode, ...]
    track_segments: tuple[TrackSegment, ...]
    station_routes: tuple[StationRoute, ...]
    cabins: tuple[Cabin, ...]
    cabin_initial_states: tuple[CabinInitialState, ...]
    demands: tuple[Demand, ...]
    operating: OperatingParameters
```

Validation should eventually check:

- unique ids within each model type
- all station route references exist
- all track segment node references exist
- station routes form connected directed paths
- all cabin initial states reference known cabins and known physical nodes
- every cabin has exactly one initial state in the first version
- demand references known service stations
- demand arrival times lie within the service window
- service end time is after service start time
- all physical quantities are positive where required

## Proposed Discrete Scenario Model Draft

This draft describes the intended contents of `models/discrete_scenario.py`.

The discrete scenario is a graph-like immutable data model, but it is not a NetworkX graph. NetworkX or solver-specific graphs may be derived from it later.

### Enums

```python
class DiscreteArcKind(Enum):
    MOVE = "move"
    WAIT = "wait"
```

```python
class DiscreteConflictReason(Enum):
    HEADWAY = "headway"
    SWITCH = "switch"
    SHARED_RESOURCE = "shared_resource"
```

Each discrete node has implicit capacity one. `DiscreteConflict` adds extra pairwise exclusions between different nodes.

### `DiscreteNode`

```python
@dataclass(frozen=True)
class DiscreteNode:
    id: str
    source_physical_node_id: str | None = None
    source_segment_id: str | None = None
    station_id: str | None = None
    resource_id: str | None = None
    position_m: float | None = None
    allows_waiting: bool = False
    allows_boarding: bool = False
    allows_alighting: bool = False
```

Rules:

- `source_physical_node_id` is used for discrete nodes that correspond to original physical nodes such as entry switches, exit switches, platform nodes, or depot nodes
- `source_segment_id` is used for intermediate discrete positions created from a physical `TrackSegment`
- `resource_id` and `position_m` are used for headway/conflict generation where a meaningful physical resource coordinate exists
- boarding and alighting should only be true at service-capable station positions

### `DiscreteArc`

```python
@dataclass(frozen=True)
class DiscreteArc:
    id: str
    kind: DiscreteArcKind
    from_node_id: str
    to_node_id: str
    source_segment_id: str | None = None
    source_route_id: str | None = None
```

Rules:

- every discrete arc has duration exactly one time step
- `MOVE` arcs connect two different physical/discrete positions
- `WAIT` arcs should normally have the same `from_node_id` and `to_node_id`
- wait arcs are only generated for nodes where waiting is allowed

### `DiscreteDemand`

```python
@dataclass(frozen=True)
class DiscreteDemand:
    time_step: int
    origin: str
    destination: str
    count: int
```

Rules:

- `origin` and `destination` still reference `Station.id`
- demand does not encode route direction
- `time_step` is derived from `Demand.arrival_time`

### `DiscreteCabinInitialState`

```python
@dataclass(frozen=True)
class DiscreteCabinInitialState:
    cabin_id: int
    node_id: str
    available_from_step: int = 0
```

Rules:

- `node_id` references a `DiscreteNode`
- `available_from_step` allows staggered cabin insertion, warm starts, and later rolling-horizon states
- for simple examples all cabins may start at step 0

### `DiscreteConflict`

```python
@dataclass(frozen=True)
class DiscreteConflict:
    node_a_id: str
    node_b_id: str
    reason: DiscreteConflictReason
```

Interpretation:

```text
node_a_id and node_b_id may not be occupied at the same time.
```

Use cases:

- headway conflicts between positions that are closer than `required_cabin_spacing_m`
- switch conflicts between service and skip paths
- shared-resource conflicts in narrow station areas

### `DiscreteScenario`

```python
@dataclass(frozen=True)
class DiscreteScenario:
    id: str
    source_scenario_id: str
    delta_seconds: float
    horizon_steps: int
    nodes: tuple[DiscreteNode, ...]
    arcs: tuple[DiscreteArc, ...]
    conflicts: tuple[DiscreteConflict, ...]
    stations: tuple[Station, ...]
    station_routes: tuple[StationRoute, ...]
    cabins: tuple[Cabin, ...]
    cabin_initial_states: tuple[DiscreteCabinInitialState, ...]
    demands: tuple[DiscreteDemand, ...]
    cabin_capacity: int
    required_cabin_spacing_m: float
```

Validation should eventually check:

- unique discrete node and arc ids
- all arc endpoints reference known discrete nodes
- all conflict nodes reference known discrete nodes
- wait arcs only exist at nodes where waiting is allowed
- all cabin initial states reference known cabins and known discrete nodes
- every cabin has exactly one initial state in the first version
- demand time steps lie within the horizon
- `delta_seconds`, `horizon_steps`, `cabin_capacity`, and `required_cabin_spacing_m` are positive

## Proposed Plan Model Draft

The plan should be arc-based because `DiscreteScenario` uses a one-step movement graph.

Stop/skip should not be stored as a separate `StopAction`. It is derived from the chosen arcs and their `source_route_id`.

For example:

```text
route M_service -> operational stop at M
route M_skip    -> operational skip at M
```

### `CabinArcStep`

```python
@dataclass(frozen=True)
class CabinArcStep:
    cabin_id: int
    time_step: int
    arc_id: str
```

Interpretation:

```text
At `time_step`, cabin `cabin_id` traverses `arc_id`.
```

Because every `DiscreteArc` lasts exactly one time step, this fully describes cabin movement over time.

### `Plan`

```python
@dataclass(frozen=True)
class Plan:
    id: str
    scenario_id: str
    cabin_steps: tuple[CabinArcStep, ...]
```

Validation should eventually check:

- every `cabin_id` references a known cabin
- every `arc_id` references a known discrete arc
- every `time_step` lies within the scenario horizon
- each active cabin uses at most one arc per time step
- consecutive arcs for the same cabin are connected
- each cabin path starts consistently with its `DiscreteCabinInitialState`
- same-node occupancy and `DiscreteConflict`s are not violated

### `baseline.py`

Creates simple non-optimized operating plans.

First baseline:

- `build_all_stop_plan(scenario: DiscreteScenario) -> Plan`

The generated plan should describe where each cabin is over time and where it stops. It should not compute passenger queues or waiting times. That belongs in replay.

### `replay.py`

Executes a plan on a scenario.

Expected main function:

```python
replay(scenario: DiscreteScenario, plan: Plan) -> ReplayResult
```

Responsibilities:

- maintain OD queues
- add new demand at each time step
- board passengers in FCFS order
- enforce cabin capacity
- alight passengers at destination stations
- track cabin load over time
- compute passenger waiting times or enough detail for metrics
- detect invalid plan behavior where possible

### `metrics.py`

Computes summary metrics from `ReplayResult`.

Initial metrics:

- served passengers
- unserved passengers / final backlog
- average waiting time
- maximum waiting time
- total waiting time
- queue length by station and time
- cabin utilization

### `examples.py`

Contains small reproducible scenarios for development and tests.

First scenario:

```text
L - M - R
```

with:

- three stations
- both directions on `L <-> M <-> R`
- a short time horizon
- a few cabins
- simple OD demand such as `L -> R`, `R -> L`, `L -> M`, and `M -> R`

## First Milestone

The first milestone is complete when this works:

```python
scenario = build_three_station_example()
discrete_scenario = discretize_scenario(scenario, delta_seconds=30)
plan = build_all_stop_plan(discrete_scenario)
result = replay(discrete_scenario, plan)
summary = summarize(result)
```

The output should make it clear:

- how many passengers were served
- how long they waited
- whether queues remain at the end
- how full cabins were over time

## Why This Comes Before MILP

The LaTeX proposal describes the methodological core as a time-indexed MILP plus deterministic replay. The replay layer is needed from the beginning because it validates whether a concrete cabin plan actually behaves as expected operationally.

Starting with replay gives us:

- a stable scenario format
- a baseline for later comparison
- a place to debug queue and capacity logic before adding solver complexity
- a target output format for future Gurobi code

## Design Rule for Later Gurobi Work

The MILP should eventually consume `DiscreteScenario` and produce `Plan`.

It should not directly produce final metrics. Metrics should come from replay, so that all-stop and optimized plans are evaluated by the same code path.

# MILP v2 Continuous Event-Activity Network

Status: **not implemented**

## Goal

Replace the large time-expanded movement MILP with a smaller continuous-time
Event-Activity Network (EAN).

The model should keep the full planning horizon and remain exact. It should not
use rolling horizon, periodic patterns, or heuristic decomposition.

The core idea is:

```text
model decisions only at relevant events
```

Instead of:

```text
x[c,t,node] = cabin c is at discrete node node at time step t
```

use:

```text
T[c,i] = time in seconds of cabin c's i-th relevant event
```

Relevant events are switches, merge points, platform boarding/alighting nodes,
wait-capable nodes, terminal turns, and other physical decision points. Track
cells between those points should not become time-indexed MILP positions.

## Motivation

The current time-expanded MILP scales roughly with:

```text
cabins * time_steps * nodes/arcs
```

For `horizon=2400` and 23 cabins this produces tens of millions of variables and
constraints before passenger optimization even starts.

The EAN should scale closer to:

```text
cabins * switch_visits * switch_options
+ headway_checkpoint_conflict_pairs
+ feasible_passenger_rides
```

This should be much smaller if switch visits, switch options, and headway
checkpoints are built tightly.

## Continuous Time

The EAN should use seconds as continuous time:

```text
entry_time[c,k] >= 0
exit_switch_time[c,k] >= entry_time[c,k]
```

Travel durations, headways, release times, and horizon are represented in
seconds, not discrete steps.

This avoids discretization drift and removes the need to create variables for
every half-second position. A discrete export can still be generated later for
frontend replay or comparison with the existing `DiscreteScenario`.

## Switch Visits

The initial v2 MILP should not use a fully generic free event-node choice model.
The real movement decisions happen at switches. Therefore, the primary movement
index should be a bounded sequence of **switch visits**:

```text
k = 0..K
```

For each cabin `c` and switch visit `k`, the model knows which physical switch
is being visited or chooses it from a small switch-transition candidate set. The
decision at that visit is the outgoing switch option:

```text
choose[c,k,o] binary, cabin c chooses switch option o at switch visit k
```

Examples of switch options:

- take station service path
- take skip path
- continue onto one of several future line branches

This keeps the model aligned with the actual decisions:

```text
switch option choice
waiting time if the selected option enters a wait-capable service path
passenger assignment if the selected option serves a station
```

It avoids artificial helper decisions such as:

```text
node[c,i,n]
choose[c,i,a]
```

for every possible event node and activity.

## Switch Option Timing

A switch option expands to deterministic or waiting-capable timing checkpoints.

For the initial implementation, assume binary switch decisions only:

```text
serve[c,k] = 1  cabin c serves the station at switch visit k
skip[c,k] = 1   cabin c takes the skip path at switch visit k
serve[c,k] + skip[c,k] = active[c,k]
```

This is the current special case of the more general future switch-option
model. Later, `serve[c,k]` and `skip[c,k]` can be replaced by `choose[c,k,o]`
over multiple switch options.

For the current service/skip station structure:

```text
entry_time[c,k]         time at the entry switch
platform_entry_time[c,k]  platform entry and alighting time if service is chosen
platform_exit_time[c,k]   platform exit, boarding, and station departure time if service is chosen
exit_switch_time[c,k]     time at the exit/merge switch
```

If `serve[c,k] = 1`, the cabin uses the service path:

```text
entry switch -> platform entry -> platform exit -> exit switch
```

The service timing constraints are:

```text
platform_entry_time >= entry_time + entry_to_platform_entry_seconds
platform_exit_time >= platform_entry_time + min_platform_entry_to_platform_exit_seconds
exit_switch_time >= platform_exit_time + platform_exit_to_exit_switch_seconds
```

Meaning:

- `platform_entry_time` cannot occur before the cabin has physically travelled
  from the entry switch to the platform
- `platform_exit_time` cannot occur before the cabin has moved through the
  platform/service area
- `exit_switch_time` cannot occur before the cabin has travelled from platform
  exit to the exit/merge switch

If no waiting is allowed, these constraints should be tight equalities. If
waiting is allowed, they remain lower bounds and the slack represents waiting or
dwell inside the station service path.

If `skip[c,k] = 1`, the cabin uses the skip path:

```text
entry switch -> skip path -> exit switch
```

The skip timing constraint is:

```text
exit_switch_time = entry_time + skip_entry_to_exit_switch_seconds
```

The platform checkpoint times are irrelevant in the skip case and should not
enable passenger boarding/alighting or platform headway constraints.

Use Gurobi indicator constraints or tight Big-M constraints so that only the
selected case is active:

```text
serve[c,k] = 1 -> service timing constraints
skip[c,k] = 1 -> skip timing constraint
```

All checkpoint time variables must have explicit horizon-derived bounds before
they are used in Big-M constraints:

```text
0 <= entry_time[c,k] <= model_end_seconds
0 <= platform_entry_time[c,k] <= model_end_seconds
0 <= platform_exit_time[c,k] <= model_end_seconds
0 <= exit_switch_time[c,k] <= model_end_seconds
```

This keeps Big-M values tight and prevents irrelevant skip-case platform times
from becoming numerically unconstrained.

The event/activity graph still defines the semantics, durations, and
checkpoints, but the MILP variables should be switch-visit based.

## Waiting

Waiting is represented by slack in the selected switch option's timing
constraints.

For example, in a service option:

```text
platform_exit_time - platform_entry_time - min_platform_entry_to_platform_exit_seconds
```

is the station waiting/dwell slack before departure. The exact interpretation
depends on the station waiting mode.

## Switch Transitions

After a switch option reaches its exit switch, the next switch visit is reached
through the rope/network travel time:

```text
entry_time[c,k+1] = exit_switch_time[c,k] + travel_time(option o to next switch)
```

For future networks with multiple lines or branches, a switch option can also
determine the next switch candidate. Direction should still not be modeled as a
separate field; it should emerge from the directed switch-option graph.

## Initial Switch Sequence

For the initial v2 implementation, plan only with skip/stop switches. The MILP
does not decide which switch is visited next. The switch sequence is built by
the scenario/EAN builder.

For each cabin, define:

```text
EanCabinStart:
  cabin_id
  first_switch_id
  kind  # FIXED | EARLIEST
  time_seconds
```

`first_switch_id` is the next reachable skip/stop entry switch from the cabin's
initial physical position.

Start semantics:

```text
FIXED:
  entry_time[c,0] = time_seconds

EARLIEST:
  entry_time[c,0] >= time_seconds
```

Use `FIXED` when the cabin is already on a deterministic path to the first
switch and cannot choose to wait before reaching it.

Use `EARLIEST` when the cabin can wait before entering the first modeled switch,
for example when it starts in depot/storage or an initial wait-capable position.

If the cabin starts directly at an entry switch and cannot wait before it:

```text
kind = FIXED
time_seconds = current_time
```

After the first switch visit, the builder provides:

```text
switch_id[c,k]
```

for every visit `k`. In the initial skip/stop-only model this sequence is fixed.
Every visited switch has exactly one binary decision:

```text
serve[c,k] = 1  service path
skip[c,k] = 1   skip path
serve[c,k] + skip[c,k] = active[c,k]
```

Future extension:

- if a network has multiple line branches, replace fixed `switch_id[c,k]` with
  switch-state variables and general `choose[c,k,o]` switch options
- do not add this complexity before the skip/stop-only model is implemented and
  validated

Depot note for later:

- depot/storage can be modeled as a special FIFO wait source with unlimited
  capacity
- depot has no passenger service
- depot releases cabins toward a first real skip/stop switch
- once a cabin enters the real system, normal switch/headway constraints apply

## Active Switch Visits

Because waiting is optimized, the builder cannot know exactly how many generated
switch visits will fit before `model_end_seconds`. It should generate an upper
bound and the MILP should activate the prefix that is actually used:

```text
active[c,k] binary, switch visit is used
```

No holes are allowed:

```text
active[c,k+1] <= active[c,k]
```

The first visit must be active:

```text
active[c,0] = 1
```

Timing, serve/skip decisions, headway candidates, and passenger rides are only
meaningful for active visits.

Activation gates:

```text
serve[c,k] + skip[c,k] = active[c,k]
ride[p,c,k,l] <= active[c,k]
ride[p,c,k,l] <= active[c,l]
```

Headway candidates must include `active[c,k]` in their active expression:

```text
PLATFORM_ENTRY active iff serve[c,k] = 1
PLATFORM_EXIT active iff serve[c,k] = 1
EXIT_SWITCH active iff active[c,k] = 1
```

Switch transitions are active only if the next visit is active:

```text
active[c,k+1] = 1
  -> entry_time[c,k+1] = exit_switch_time[c,k] + rope_to_next_switch_seconds
```

Initial movement bound:

```text
active[c,k] = 1 -> exit_switch_time[c,k] <= model_end_seconds
```

Passenger service remains bounded by the passenger horizon:

```text
ride[p,c,k,l] = 1 -> platform_exit_time[c,k] <= horizon_seconds
ride[p,c,k,l] = 1 -> platform_entry_time[c,l] <= horizon_seconds
```

Inactive visits are dummy suffix visits used only because `K` is an upper bound.
They must have no physical, headway, passenger, or capacity effect.

## Resource Usages and Headway Constraints

For the initial v2 MILP, a resource usage should be a headway checkpoint entry,
not an exclusive occupied interval:

```text
resource_id
entry_time_expression
```

The entry time can be one of the switch-option checkpoint times:

```text
entry_time[c,k]
platform_entry_time[c,k]
platform_exit_time[c,k]
exit_switch_time[c,k]
```

or an offset inside a selected switch option, if a later physical model needs
that detail.

Headway is entry-to-entry:

```text
entry_v >= entry_u + resource.headway_seconds
```

Because cabins can overtake via switches or skip/service choices, there is no
global cabin order. Ordering must be local to each resource. For every pair of
possible entries `u` and `v` on the same resource:

```text
u before v OR v before u
```

Introduce:

```text
order[u,v] = 1 if u is before v
```

With activation-aware constraints:

```text
entry_v >= entry_u + headway - M * (1 - order[u,v]) - M * (2 - use_u - use_v)
entry_u >= entry_v + headway - M * order[u,v]       - M * (2 - use_u - use_v)
```

Only build pairs for entries that share the same resource and could overlap
within the horizon. Keep per-resource statistics so we can see which resource
explodes.

## Passenger Model

For v2, passengers can be modeled individually.

Each passenger has:

```text
p = (origin, destination, release_time_seconds)
```

Use ride-assignment variables:

```text
ride[p,c,k,l] binary
```

Meaning:

```text
passenger p boards cabin c at switch visit k
and alights from the same cabin at later switch visit l
```

A ride is feasible only if:

- switch visit `k` is at the passenger origin station
- switch visit `l` is at the passenger destination station
- `l > k`
- both visits belong to the same cabin
- `platform_exit_time[c,k] >= release_time_seconds[p]`

Candidate generation should do as much filtering as possible before the Gurobi
model is built. Do not create a `ride[p,c,k,l]` variable unless:

```text
station_of_switch_visit[c,k] == origin[p]
station_of_switch_visit[c,l] == destination[p]
l > k
```

These are builder filters, not MILP constraints.

Required MILP constraints:

```text
ride[p,c,k,l] <= serve[c,k]
ride[p,c,k,l] <= serve[c,l]
```

These ensure passengers only board and alight when the cabin actually serves
the origin and destination stations.

Release-time constraint:

```text
platform_exit_time[c,k] >= release_time_seconds[p] - M * (1 - ride[p,c,k,l])
```

So a passenger can only be assigned to a cabin departure after they have arrived.

Every passenger is assigned exactly once:

```text
sum feasible ride[p,c,k,l] = 1
```

If unserved demand should be allowed later:

```text
sum feasible ride[p,c,k,l] + unserved[p] = 1
```

Because `K` is an upper bound, ride variables must include horizon guards:

```text
platform_exit_time[c,k] <= horizon_seconds + M * (1 - ride[p,c,k,l])
platform_entry_time[c,l] <= horizon_seconds + M * (1 - ride[p,c,k,l])
```

Passenger rides must board and alight inside the passenger horizon even though
movement may continue until `model_end_seconds`.

## Cabin Capacity

For every cabin and switch-visit interval:

```text
sum_{p,k,l: k <= m < l} ride[p,c,k,l] <= cabin_capacity
```

This directly enforces capacity between consecutive switch visits.

## Waiting-Time Objective

Minimize total passenger waiting time:

```text
minimize sum_p (platform_exit_time_of_assigned_boarding_visit[p] - release_time[p])
```

With `ride[p,c,k,l]`, the boarding time is `platform_exit_time[c,k]`.

The term:

```text
ride[p,c,k,l] * platform_exit_time[c,k]
```

is bilinear and must be linearized.

Introduce:

```text
w[p,c,k,l] = ride[p,c,k,l] * platform_exit_time[c,k]
```

With horizon-derived Big-M:

```text
w <= H * ride
w <= platform_exit_time[c,k]
w >= platform_exit_time[c,k] - H * (1 - ride)
w >= 0
```

Objective:

```text
minimize sum_{p,c,k,l} (w[p,c,k,l] - release_time[p] * ride[p,c,k,l])
```

Report the value in passenger-hours:

```text
objective_seconds / 3600
```

## Expected Modules

Suggested structure:

```text
optimization/ean/
  __init__.py
  models.py
  switch_visit_builder.py
  headway_candidate_builder.py
  headway_pair_builder.py
  passenger_builder.py
  movement_milp.py
  passenger_milp.py
  solution_extraction.py
  validation.py
```

The builders should be inspectable and should return counts/statistics before
the Gurobi model is built.

Module responsibilities:

```text
models.py
  Pure dataclasses/enums only:
  SkipStopTiming, SwitchVisitDefinition, HeadwayCheckpointDefinition,
  EanCabinStart, StationEanConfig, Passenger, RideCandidate, EanConfig,
  HeadwayCandidate, HeadwayPair, result metadata.

switch_visit_builder.py
  Builds fixed skip/stop switch visit sequences per cabin from cabin starts,
  timings, horizon_seconds, and tail_seconds. Computes the upper-bound K and
  emits SwitchVisitDefinition records.

headway_candidate_builder.py
  Builds HeadwayCandidate records from switch visits, station configs, and
  checkpoint definitions. Handles mode-specific checkpoint generation.

headway_pair_builder.py
  Builds filtered candidate pairs per physical checkpoint and reports pair
  statistics.

passenger_builder.py
  Expands demand to Passenger records and builds RideCandidate records.

movement_milp.py
  Builds and solves the movement-only continuous EAN MILP:
  active/serve/skip variables, timing constraints, transitions, and headways.

passenger_milp.py
  Extends movement_milp with ride variables, capacity constraints, release-time
  constraints, and waiting-time objective.

solution_extraction.py
  Converts Gurobi solutions into inspectable movement/passenger plans.

validation.py
  Validates EAN inputs and extracted solutions independently of Gurobi.
```

Do not mix builder logic, Gurobi variable creation, and solution extraction in
one file. The builder outputs should be serializable and inspectable before a
Gurobi model is created.

## Data Model Draft

The first implementation should introduce explicit EAN data models before
building Gurobi variables. Initial planned dataclasses:

```text
SkipStopTiming
SwitchVisitDefinition
HeadwayCheckpointDefinition
EanCabinStart
StationEanConfig
Passenger
RideCandidate
EanConfig
```

`SkipStopTiming`, `StationEanConfig`, `EanConfig`, and
`HeadwayCheckpointDefinition` are defined in detail for now. The remaining
dataclasses should be defined after the switch timing and headway semantics are
final.

### SkipStopTiming

`SkipStopTiming` describes the physical timing of one skip/stop switch visit.
For the initial model, every switch is a skip/stop switch with one binary
decision for active visits:

```text
serve[c,k] = 1  service path
skip[c,k] = 1   skip path
serve[c,k] + skip[c,k] = active[c,k]
```

Fields:

```text
switch_id
station_id
entry_to_platform_entry_seconds
min_platform_entry_to_platform_exit_seconds
platform_exit_to_exit_switch_seconds
skip_entry_to_exit_switch_seconds
rope_to_next_switch_seconds
```

Only `min_platform_entry_to_platform_exit_seconds` is a minimum duration where
waiting/dwell slack can be introduced. The other timing fields are deterministic
travel times.

If `serve[c,k] = 1`:

```text
platform_entry_time = entry_time + entry_to_platform_entry_seconds
platform_exit_time >= platform_entry_time + min_platform_entry_to_platform_exit_seconds
exit_switch_time = platform_exit_time + platform_exit_to_exit_switch_seconds
```

If the selected waiting mode is `NO_WAITING`, the middle inequality becomes a
tight equality:

```text
platform_exit_time = platform_entry_time + min_platform_entry_to_platform_exit_seconds
```

If `skip[c,k] = 1`:

```text
exit_switch_time = entry_time + skip_entry_to_exit_switch_seconds
```

After the exit switch:

```text
entry_time[c,k+1] = exit_switch_time[c,k] + rope_to_next_switch_seconds
```

### StationEanConfig

Waiting mode should be configured per station, not globally. Different stations
can have different physical waiting infrastructure.

Planned fields:

```text
station_id
waiting_mode  # NO_WAITING | END_OF_PLATFORM_WAIT | STATION_FIFO_BUFFER
fifo_capacity | None
```

`fifo_capacity` is only relevant for:

```text
waiting_mode = STATION_FIFO_BUFFER
```

Validation:

```text
if waiting_mode == STATION_FIFO_BUFFER:
  fifo_capacity must be set
else:
  fifo_capacity should be None
```

### EanConfig

Global EAN solver configuration should stay small:

```text
horizon_seconds
tail_seconds
cabin_capacity
station_configs
```

Semantics:

```text
horizon_seconds:
  passenger service and objective cutoff

tail_seconds:
  movement/headway continuation after the passenger horizon

model_end_seconds = horizon_seconds + tail_seconds
```

`model_end_seconds` is derived from `horizon_seconds` and `tail_seconds`. It
must not be passed as an independent config value.

Passenger rides must be fully completed inside `horizon_seconds`:

```text
boarding_time <= horizon_seconds
alighting_time <= horizon_seconds
```

Cabin movement and headway constraints may continue until `model_end_seconds`:

```text
active switch visits must satisfy exit_switch_time <= model_end_seconds
```

This avoids hard horizon artifacts where cabins disappear immediately at the
passenger cutoff, while keeping the passenger objective scoped to the requested
planning horizon.

Do not put `max_switch_visits` into `EanConfig` initially. The builder/solver
should compute the required number of switch visits per cabin from:

- horizon and tail
- cabin starts
- fixed switch sequence
- minimum switch-to-switch travel times

### HeadwayCheckpointDefinition

`HeadwayCheckpointDefinition` describes one physical checkpoint where entry
times must be separated by a minimum time headway.

Planned fields:

```text
id
kind
switch_id
station_id
headway_seconds
applies_to_serve
applies_to_skip
waiting_modes
```

Kinds:

```text
PLATFORM_ENTRY
PLATFORM_EXIT
EXIT_SWITCH
```

`waiting_modes` is the set of station waiting modes for which the checkpoint is
generated.

Examples:

```text
PLATFORM_ENTRY:
  applies_to_serve = true
  applies_to_skip = false
  waiting_modes = {NO_WAITING, END_OF_PLATFORM_WAIT, STATION_FIFO_BUFFER}
  headway_seconds = station_headway_seconds

PLATFORM_EXIT:
  applies_to_serve = true
  applies_to_skip = false
  waiting_modes = {END_OF_PLATFORM_WAIT, STATION_FIFO_BUFFER}
  headway_seconds = station_headway_seconds

EXIT_SWITCH:
  applies_to_serve = true
  applies_to_skip = true
  waiting_modes = {NO_WAITING, END_OF_PLATFORM_WAIT, STATION_FIFO_BUFFER}
  headway_seconds = merge_or_rope_headway_seconds
```

Candidate activation:

```text
PLATFORM_ENTRY active iff serve[c,k] = 1
PLATFORM_EXIT active iff serve[c,k] = 1
EXIT_SWITCH active iff active[c,k] = 1
```

`EXIT_SWITCH` is active for both stop and skip because every switch visit reaches
the exit/merge switch.

### SwitchVisitDefinition

`SwitchVisitDefinition` is produced by the EAN builder. It defines the fixed
skip/stop switch sequence for the initial model.

Planned fields:

```text
cabin_id
visit_index
switch_id
```

Do not duplicate `station_id` here. It is derived from:

```text
SkipStopTiming[switch_id].station_id
```

MILP time variables are indexed by:

```text
(cabin_id, visit_index)
```

Validation:

```text
visit_index starts at 0 for each cabin
visit indices are contiguous for each cabin
switch_id exists in SkipStopTiming
```

The builder should generate a safe upper bound of visits for `model_end_seconds`.
The MILP activates the prefix of visits that is actually used. `max_switch_visits`
should not be a user-facing config field initially.

### EanCabinStart

`EanCabinStart` defines the initial timing constraint for a cabin's first
modeled switch visit.

Planned fields:

```text
cabin_id
first_switch_id
kind  # FIXED | EARLIEST
time_seconds
```

Semantics:

```text
FIXED:
  entry_time[c,0] = time_seconds

EARLIEST:
  entry_time[c,0] >= time_seconds
```

Use `FIXED` when the cabin is already on a deterministic path to the first
switch and cannot choose to wait before reaching it.

Use `EARLIEST` when the cabin can wait before entering the first modeled switch,
for example when it starts in depot/storage or an initial wait-capable position.

Validation:

```text
cabin_id is unique
first_switch_id exists in SkipStopTiming
time_seconds >= 0
kind is FIXED or EARLIEST
SwitchVisitDefinition(cabin_id, 0).switch_id == first_switch_id
```

### Passenger

`Passenger` represents one individual passenger in the optimization model.

Planned fields:

```text
id
origin_station_id
destination_station_id
release_time_seconds
```

Validation:

```text
origin_station_id exists
destination_station_id exists
origin_station_id != destination_station_id
release_time_seconds >= 0
```

Demand groups from the physical scenario can be expanded into individual
`Passenger` records before building the EAN passenger model.

### RideCandidate

`RideCandidate` is produced by the passenger ride builder. It defines one
possible assignment of a passenger to a cabin and two switch visits.

Planned fields:

```text
id
passenger_id
cabin_id
board_visit_index
alight_visit_index
```

Semantics:

```text
passenger boards cabin_id at board_visit_index
passenger alights from the same cabin at alight_visit_index
```

The corresponding MILP variable is:

```text
ride[passenger_id, cabin_id, board_visit_index, alight_visit_index]
```

`id` is a stable serialized builder identifier for inspection, exports, and
headway/passenger diagnostics. It is not a separate MILP index dimension.

Builder filters:

```text
board_visit_index < alight_visit_index
station_of_switch_visit[cabin_id, board_visit_index] == passenger.origin_station_id
station_of_switch_visit[cabin_id, alight_visit_index] == passenger.destination_station_id
```

Validation:

```text
passenger_id exists
cabin_id exists
board_visit_index and alight_visit_index exist for the cabin
board_visit_index < alight_visit_index
```

The builder should not require `stop=1` when generating candidates, because
`stop` is a MILP decision. Instead, the MILP enforces:

```text
ride <= serve[cabin_id, board_visit_index]
ride <= serve[cabin_id, alight_visit_index]
```

Passenger times for a selected ride:

```text
boarding_time = platform_exit_time[cabin_id, board_visit_index]
alighting_time = platform_entry_time[cabin_id, alight_visit_index]
```

## Headway Candidate and Pair Builder

Before building Gurobi constraints, create explicit headway candidates from
`HeadwayCheckpointDefinition` and `SwitchVisitDefinition`.

Planned generated model:

```text
HeadwayCandidate:
  id
  checkpoint_id
  cabin_id
  visit_index
  time_reference
  activation_reference
```

Examples:

```text
PLATFORM_ENTRY:
  time_reference = PLATFORM_ENTRY_TIME
  activation_reference = SERVE

PLATFORM_EXIT:
  time_reference = PLATFORM_EXIT_TIME
  activation_reference = SERVE

EXIT_SWITCH:
  time_reference = EXIT_SWITCH_TIME
  activation_reference = ACTIVE
```

For every pair of candidates `u` and `v` on the same physical checkpoint,
introduce one order binary:

```text
order[u,v] = 1 if u is before v
```

Headway constraints:

```text
time_v >= time_u + headway
          - M * (1 - order[u,v])
          - M * (2 - active_u - active_v)

time_u >= time_v + headway
          - M * order[u,v]
          - M * (2 - active_u - active_v)
```

If both candidates are active, exactly one temporal order must satisfy the
headway. If either candidate is inactive, both constraints are relaxed.

Pair generation filters:

```text
u.checkpoint_id == v.checkpoint_id
u.id < v.id
not same cabin and same visit
skip pair if earliest/latest bounds prove they cannot interact
```

The builder should report per-checkpoint statistics:

```text
candidate_count
pair_count_before_filtering
pair_count_after_filtering
```

This is important because headway pairs are the main remaining source of model
growth in the continuous EAN.

## Movement MILP Constraint Summary

The movement-only v2 MILP should be implementable from the builder outputs
without passenger variables.

### Variables

For every generated cabin switch visit `(c,k)`:

```text
active[c,k] binary
serve[c,k] binary
skip[c,k] binary
entry_time[c,k] continuous
platform_entry_time[c,k] continuous
platform_exit_time[c,k] continuous
exit_switch_time[c,k] continuous
```

For every generated headway pair `(u,v)`:

```text
order[u,v] binary
```

### Active Visit Constraints

```text
active[c,0] = 1
active[c,k+1] <= active[c,k]
serve[c,k] + skip[c,k] = active[c,k]
```

Inactive visits are dummy suffix visits. They must not create timing,
transition, headway, passenger, or capacity effects.

### Start Constraints

For `EanCabinStart.kind == FIXED`:

```text
entry_time[c,0] = EanCabinStart.time_seconds
```

For `EanCabinStart.kind == EARLIEST`:

```text
entry_time[c,0] >= EanCabinStart.time_seconds
```

### Time Bounds

All time variables must be bounded:

```text
0 <= entry_time[c,k] <= model_end_seconds
0 <= platform_entry_time[c,k] <= model_end_seconds
0 <= platform_exit_time[c,k] <= model_end_seconds
0 <= exit_switch_time[c,k] <= model_end_seconds
```

For active visits:

```text
active[c,k] = 1 -> exit_switch_time[c,k] <= model_end_seconds
```

### Service Timing

If `serve[c,k] = 1`:

```text
platform_entry_time[c,k]
  = entry_time[c,k] + entry_to_platform_entry_seconds

platform_exit_time[c,k]
  >= platform_entry_time[c,k] + min_platform_entry_to_platform_exit_seconds

exit_switch_time[c,k]
  = platform_exit_time[c,k] + platform_exit_to_exit_switch_seconds
```

For stations with `NO_WAITING`, the middle inequality is a tight equality.

### Skip Timing

If `skip[c,k] = 1`:

```text
exit_switch_time[c,k]
  = entry_time[c,k] + skip_entry_to_exit_switch_seconds
```

Platform times are irrelevant in the skip case and must not activate passenger
or platform-headway constraints.

### Switch Transition

For consecutive active visits:

```text
active[c,k+1] = 1
  -> entry_time[c,k+1]
     = exit_switch_time[c,k] + rope_to_next_switch_seconds
```

The `rope_to_next_switch_seconds` value comes from the `SkipStopTiming` of the
current switch visit.

### Headway Constraints

For each generated headway pair `(u,v)`:

```text
time_v >= time_u + headway
          - M * (1 - order[u,v])
          - M * (2 - active_u - active_v)

time_u >= time_v + headway
          - M * order[u,v]
          - M * (2 - active_u - active_v)
```

Where:

```text
active_u = serve[c,k] for platform checkpoints
active_u = active[c,k] for exit-switch checkpoints
```

The objective for movement-only feasibility is:

```text
minimize 0
```

## Implementation Stages

The implementation should proceed definition-first. Do not start with Gurobi
variables before the EAN concepts and conversion rules are stable.

### Step 1: Core Model Definitions

Define the core EAN concepts and their exact semantics:

- `EventNode`
- `Activity`
- `Resource`
- `ResourceUsage`
- `SwitchVisit`
- `SwitchOption`
- `Passenger`
- `RideCandidate`

This step should answer:

- what is an event node?
- what is an activity?
- what counts as a resource?
- how do resource usages encode headway-relevant occupancy?
- what does one cabin switch visit represent?
- how do passengers relate to switch visits?

No Gurobi implementation in this step.

Initial event-node decision for the current model:

```text
EventNodeKind:
- ENTRY_SWITCH
- PLATFORM
- WAIT
- EXIT_SWITCH
```

There should be no separate terminal-turn node in the initial EAN. Terminal
behavior should be represented by normal activities unless a terminal later has
its own physical conflict, wait, or timing requirement.

There should be no separate boarding and alighting nodes initially. Instead,
station passenger handling is split across two service-path event nodes:

```text
PLATFORM allows_alighting = true
WAIT allows_boarding = true
```

Passenger actions use the switch visit's service checkpoint times:

```text
platform_entry_time[c,k] = alighting checkpoint time if service is selected
platform_exit_time[c,k] = boarding/departure checkpoint time if service is selected
```

For a `PLATFORM` event:

```text
alighting happens at platform_entry_time[c,k]
```

For a `WAIT` event:

```text
boarding happens at platform_exit_time[c,k]
waiting/dwell is represented by service timing slack before platform_exit_time[c,k]
```

This keeps boarding after the cabin has moved through the platform/service area
and completed any waiting.

For non-wait event nodes, including `PLATFORM` initially:

```text
no additional dwell is introduced at that checkpoint
```

For `WAIT` nodes:

```text
platform_exit_time[c,k] may be later than the minimum service departure time
```

Initial station graph semantics:

```text
station with skip:
  ENTRY_SWITCH -> PLATFORM -> WAIT -> EXIT_SWITCH
  ENTRY_SWITCH -> EXIT_SWITCH

station without skip:
  ENTRY_SWITCH -> PLATFORM -> WAIT -> EXIT_SWITCH
```

Passengers can only alight at `PLATFORM` event nodes and can only board at
`WAIT` event nodes. A cabin that uses the skip activity cannot board or alight
at that station.

Initial activity decision for the current model:

```text
ActivityKind:
- ROPE
- SERVICE_ENTRY
- SERVICE_PLATFORM
- SERVICE_EXIT
- SKIP
```

Semantics:

```text
ROPE:
  EXIT_SWITCH of one station -> ENTRY_SWITCH of the next station

SERVICE_ENTRY:
  ENTRY_SWITCH -> PLATFORM

SERVICE_PLATFORM:
  PLATFORM -> WAIT

SERVICE_EXIT:
  WAIT -> EXIT_SWITCH

SKIP:
  ENTRY_SWITCH -> EXIT_SWITCH
```

`SERVICE_ENTRY` includes the physical path after the entry switch before
alighting:

```text
entry switch
-> approach fast
-> brake/decelerate
-> platform arrival
```

Alighting happens only after this activity, at the platform checkpoint time:

```text
platform_entry_time[c,k]
```

`SERVICE_PLATFORM` represents the required movement through the platform/service
area after alighting and before the boarding/wait point:

```text
platform/service movement
-> wait/boarding point
```

`SERVICE_EXIT` includes the physical path after waiting and boarding before the
exit switch:

```text
wait/boarding point departure
-> accelerate
-> depart fast
-> exit switch
```

Boarding happens before this activity, at the station departure checkpoint time:

```text
platform_exit_time[c,k]
```

Brake, accelerate, approach, and depart sections should not become additional
event nodes initially. They are represented by:

- activity duration
- resource usage offsets inside `SERVICE_ENTRY`, `SERVICE_PLATFORM`, and
  `SERVICE_EXIT`

If any of these internal sections needs collision/headway protection, it should
be represented as a `ResourceUsage`, not as a separate event node.

## Station Waiting Modes

The EAN should support different station waiting semantics. They should be
modeled explicitly instead of hard-coding one physical assumption.

Passenger service is instantaneous in all modes. Passengers do not create
boarding or alighting service time.

For optimization and waiting-time accounting, use:

```text
alighting_time = earliest station service/platform time
boarding_time = station departure time after any waiting
```

This means passenger waiting ends when the assigned cabin departs the station
with the passenger, not when the passenger could physically step into a slow or
waiting cabin.

### 1. No Waiting

Cabins move through the station with deterministic minimum timing:

```text
ENTRY_SWITCH -> PLATFORM -> EXIT_SWITCH
```

or, when using the split service representation:

```text
ENTRY_SWITCH -> PLATFORM -> WAIT/BOARDING_POINT -> EXIT_SWITCH
```

with zero dwell:

```text
platform_exit_time = platform_entry_time + min_platform_entry_to_platform_exit_seconds
```

Passenger times:

```text
alighting_time = platform_entry_time
boarding_time = platform_exit_time
```

Effects:

- smallest model
- useful as a baseline
- may become infeasible if headway conflicts require active delay

### 2. Waiting at the End of the Platform

Cabins can wait only at a defined wait/boarding point near the end of the
service path:

```text
ENTRY_SWITCH -> PLATFORM -> WAIT -> EXIT_SWITCH
```

Semantics:

```text
alighting happens at platform_entry_time[c,k]
boarding happens at platform_exit_time[c,k]
waiting happens as platform_exit_time[c,k] minus the minimum departure time
```

Passenger times:

```text
alighting_time = platform_entry_time
boarding_time = platform_exit_time
```

Effects:

- compact and easy to model
- physically plausible when a station has a defined waiting/boarding position
- does not allow waiting at arbitrary positions inside the station

This is a good initial implementation mode.

### 3. Waiting at Arbitrary Positions in the Station

Cabins may wait anywhere along the service path. A direct continuous
space-time formulation would be much harder because the optimizer would need to
choose both time and physical stopping position.

The preferred exact simplification is a **station FIFO buffer** under these
assumptions:

- the station service path is one-dimensional and directed
- cabins cannot overtake within the same service path
- overtaking can still happen via skip/service choices outside the service path
- exact waiting position is irrelevant as long as all timing, headway, and
  station capacity constraints are satisfiable
- the service path has known minimum travel times between relevant checkpoints

For each cabin service visit, model only key times:

```text
entry_time
platform_entry_time
platform_exit_time
exit_switch_time
```

Minimum travel constraints:

```text
platform_entry_time >= entry_time + entry_to_platform_entry_seconds
platform_exit_time >= platform_entry_time + min_platform_entry_to_platform_exit_seconds
exit_switch_time >= platform_exit_time + platform_exit_to_exit_switch_seconds
```

For the local FIFO order of cabins on the same service path:

```text
platform_entry_next >= platform_entry_prev + platform_entry_headway
platform_exit_next >= platform_exit_prev + platform_exit_headway
exit_switch_next >= exit_switch_prev + exit_switch_headway
```

If the station can hold at most `Q` cabins with required spacing, add a buffer
capacity constraint:

```text
entry_of_(k+Q) >= exit_switch_of_k
```

Passenger times:

```text
alighting_time = platform_entry_time
boarding_time = platform_exit_time
```

This permits arbitrary waiting inside the station without selecting exact wait
positions. The extra dwell appears as:

```text
platform_exit_time - platform_entry_time - minimum_platform_to_platform_exit_time
```

This mode is exact only under the FIFO/no-overtaking-inside-service-path
assumption. It is still compatible with overtaking through skip paths, because
the FIFO order is local to the station service path, not global to all cabins.

Implementation note:

- v2 can start with mode 2 (`END_OF_PLATFORM_WAIT`)
- mode 1 is a special case with zero wait
- mode 3 should be planned as `STATION_FIFO_BUFFER`
- mode 3 likely needs a dedicated station service-path sequencing model rather
  than simple pairwise resource ordering on every internal section

Initial resource decision for the current model:

```text
ResourceKind:
- PLATFORM_ENTRY
- PLATFORM_EXIT
- EXIT_SWITCH
```

For the initial EAN, a `Resource` should be understood primarily as a
**headway checkpoint**, not as an exclusive occupied segment.

Resources are not exclusive by default. Do not add a generic non-overlap
constraint such as:

```text
entry_next >= exit_previous
```

Instead, the initial headway rule is entry-to-entry:

```text
entry_next >= entry_previous + resource.headway_seconds
```

Use as few headway checkpoints as possible. Headway is needed where spacing can
become critical:

- at the platform arrival point for service paths
- at the station departure point if waiting can compress departures
- at the exit/merge switch where service and skip paths rejoin

Known checkpoint kinds:

```text
PLATFORM_ENTRY:
  entry_time = platform_entry_time[c,k]

PLATFORM_EXIT:
  entry_time = platform_exit_time[c,k]

EXIT_SWITCH:
  entry_time = exit_switch_time[c,k]
```

Only `PLATFORM_ENTRY` and `EXIT_SWITCH` are always generated in the initial
model. `PLATFORM_EXIT` is generated only for waiting modes
where station waiting can compress platform departures.

Mode-specific checkpoints:

```text
NO_WAITING:
  PLATFORM_ENTRY at platform_entry_time[c,k]
  EXIT_SWITCH at exit_switch_time[c,k]

END_OF_PLATFORM_WAIT:
  PLATFORM_ENTRY at platform_entry_time[c,k]
  PLATFORM_EXIT at platform_exit_time[c,k]
  EXIT_SWITCH at exit_switch_time[c,k]

STATION_FIFO_BUFFER:
  PLATFORM_ENTRY at platform_entry_time[c,k]
  PLATFORM_EXIT at platform_exit_time[c,k]
  EXIT_SWITCH at exit_switch_time[c,k]
  plus station FIFO/capacity constraints
```

`PLATFORM_EXIT` is needed when waiting can compress departures.
Example: two cabins may enter the platform with valid station headway, but if
the first cabin waits much longer than the second, their departure times can
become too close. A departure checkpoint prevents this.

For `NO_WAITING`, `PLATFORM_EXIT` is redundant and should be omitted
initially, because platform exit time is deterministically derived from platform
entry time. The station entry headway therefore implies the same ordering and
spacing at platform exit.

`entry_time[c,k]` at the station entry switch is not a headway checkpoint in the
initial model. The entry switch splits one incoming stream into service/skip
paths. Since this does not merge flows and the outgoing paths do not create more
cabins than the incoming rope stream, the existing incoming spacing is
sufficient for the initial physics.

Wait-related headways are handled by the selected station waiting mode. In
particular, `END_OF_PLATFORM_WAIT` and `STATION_FIFO_BUFFER` should include
`PLATFORM_EXIT` with station-speed headway.

`ResourceUsage` defines when a cabin enters a headway checkpoint:

```text
resource_id
entry_time_expression
active_expression
```

The entry time can be:

```text
entry_time[c,k]
platform_entry_time[c,k]
platform_exit_time[c,k]
exit_switch_time[c,k]
checkpoint_time[c,k] + offset_seconds inside a switch option
```

Examples:

```text
PLATFORM_ENTRY:
  entry_time = platform_entry_time[c,k]
  active = serve[c,k]

PLATFORM_EXIT:
  entry_time = platform_exit_time[c,k]
  active = serve[c,k]
  only generated for waiting modes where station waiting can compress departures

EXIT_SWITCH:
  entry_time = exit_switch_time[c,k]
  active = active[c,k]
```

Headway candidates are therefore mode-dependent:

```text
NO_WAITING:
  PLATFORM_ENTRY active iff serve[c,k] = 1
  EXIT_SWITCH active iff active[c,k] = 1

END_OF_PLATFORM_WAIT:
  PLATFORM_ENTRY active iff serve[c,k] = 1
  PLATFORM_EXIT active iff serve[c,k] = 1
  EXIT_SWITCH active iff active[c,k] = 1

STATION_FIFO_BUFFER:
  PLATFORM_ENTRY active iff serve[c,k] = 1
  PLATFORM_EXIT active iff serve[c,k] = 1
  EXIT_SWITCH active iff active[c,k] = 1
  plus station FIFO/capacity constraints
```

For two candidates `u` and `v` on the same physical checkpoint, build a
pairwise ordering constraint only if both can be active. Platform checkpoint
pairs are conditional on both visits selecting service:

```text
active_u = serve[c,k]
active_v = serve[d,l]
```

Exit-switch pairs are conditional only on visit activity because every active
serve or skip path reaches the exit/merge switch:

```text
active_u = active[c,k]
active_v = active[d,l]
```

Internal service, skip, rope, brake, and acceleration sections should not get
headway resources unless there is a specific physical reason. On deterministic
same-direction sections with no merge, no split, no overtaking, and no variable
speed that can compress spacing, a downstream checkpoint is sufficient.

### Step 2: Physical Scenario to EAN Graph

Define how the existing physical scenario is converted into an EAN graph:

- physical nodes that become EAN event nodes
- track, station, service, skip, and terminal paths that become activities
- switch, lane, rope, station, and merge conflict areas that become resources
- deterministic durations in seconds

This step should make clear which physical points are real decisions and which
intermediate geometry is represented only as duration/resource usage.

### Step 3: Activity Durations

Define duration calculation for every activity type:

- rope travel
- skip path
- approach fast
- brake
- platform/service movement
- accelerate
- depart fast
- terminal turn

Decide per station path whether brake/accelerate sections are separate
activities or offsets within a larger service activity.

### Step 4: Resources and Headway Semantics

Define headway checkpoints precisely.

For each checkpoint resource, specify:

```text
resource_id
headway_seconds
is_optional
```

For each activity or event that enters a checkpoint, specify:

```text
resource_id
entry_time_expression
```

This is the most important correctness step. It must cover only physically
necessary headway points:

- platform arrival spacing
- exit/merge switch spacing
- optional wait departure spacing, depending on waiting mode
- station FIFO checkpoints for `STATION_FIFO_BUFFER`

No global cabin order may be assumed.

### Step 5: Switch-Visit Bound

Define how to compute `K`, the maximum number of switch visits per cabin.

The bound must be conservative enough to preserve feasibility, but tight enough
to keep the model small. The builder should report:

- `K`
- switch count
- switch option count
- possible choices count
- headway checkpoint usage count
- candidate conflict pair count

### Step 6: Movement-Only EAN MILP

Implement the first Gurobi model without passengers:

```text
minimize 0
```

It should include:

- fixed cabin starts
- switch visit sequence
- switch option choice
- timing
- waiting
- resource/headway conflicts

### Step 7: Movement Validation and Export

Validate and export EAN movement solutions:

- selected switch options form a valid chain
- switch option endpoints match the next switch visit
- switch checkpoint times respect durations
- non-wait nodes have zero dwell
- headway constraints hold in continuous time

Optionally export a derived discrete/replay plan for the frontend.

### Step 8: Passenger Ride Candidates

Add individual passenger candidate generation:

```text
ride[p,c,k,l]
```

Generate a candidate only if:

- switch visit `k` can serve the passenger origin
- switch visit `l` can serve the passenger destination
- `l > k`
- both visits belong to the same cabin
- the release time can theoretically be respected

### Step 9: Passenger Assignment and Capacity

Add passenger feasibility constraints:

- every passenger is assigned exactly once, or explicitly unserved
- cabin capacity holds on every switch-visit interval
- passengers board and alight only at valid service visits

Start again with:

```text
minimize 0
```

### Step 10: Waiting-Time Objective

Add the passenger waiting-time objective:

```text
minimize total waiting seconds
```

Use standard Big-M linearization for:

```text
ride[p,c,k,l] * platform_exit_time[c,k]
```

Report objective metadata in passenger-hours.

### Stage 1: EAN Data Model

Create pure Python models for:

- switch visits
- skip/stop switch timing definitions
- switch options
- resource usages
- resource conflict pairs
- passenger ride candidates

No Gurobi dependency yet.

### Stage 2: Movement Feasibility

Build continuous-time EAN movement feasibility:

- fixed cabin starts
- switch visit sequence
- stop/skip choices
- switch checkpoint timing
- waiting
- resource/headway conflicts
- no passengers

Objective:

```text
minimize 0
```

### Stage 3: Individual Passenger Assignment

Add:

- individual passengers from demand expansion
- feasible ride candidates
- capacity between switch-visit intervals
- all passengers served or explicit `unserved[p]`

### Stage 4: Waiting-Time Objective

Add linearized waiting objective:

```text
minimize total passenger waiting seconds
```

Export passenger-hours in metadata.

## Validation Requirements

The EAN solution must be validated independently:

- every active switch visit has exactly one serve/skip decision
- the fixed switch visit sequence is respected
- switch checkpoint times respect service/skip durations
- non-wait nodes have zero dwell time
- headway/resource constraints hold in continuous time
- passengers board only after release time
- passengers board and alight at valid station nodes
- cabin capacity holds on every switch-visit interval
- every served passenger has exactly one ride

## Open Risks

### Headway Pair Explosion

The exact headway model is pairwise by resource usage. The pair count can still
be large if switch-visit bounds are too loose or resources are defined too
broadly.

Mitigation:

- tight switch-visit bounds
- earliest/latest time filtering
- resource-specific pair statistics
- split broad resources into precise conflict resources

### Switch-Visit Upper Bound

`K` must be large enough to cover all feasible plans but small enough to avoid
creating useless choices.

The first implementation should compute a conservative bound from the horizon
and the shortest possible switch-to-switch cycle, then report it clearly.

### Passenger Candidate Explosion

Individual passengers create many possible `ride[p,c,k,l]` variables.

Mitigation:

- only generate physically valid origin/destination switch-visit pairs
- filter by release time and earliest/latest switch-visit bounds
- allow grouping identical passengers later if needed, without changing the EAN
  movement model

## Non-Goals

- no rolling horizon
- no periodic pattern assumption
- no fixed global cabin order
- no time-expanded `x[c,t,node]` movement grid
- no direction field separate from the event-activity graph
- no heuristic passenger boarding in the optimizer

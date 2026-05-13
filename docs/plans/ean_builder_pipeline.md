# EAN Builder Pipeline

Status: **not implemented**

## Goal

Define the builder layer for the continuous-time EAN model before any Gurobi
model is created.

The builders convert scenario/EAN input data into small, explicit, inspectable
records:

```text
physical scenario / demand / starts
-> EAN timings and configs
-> switch visits
-> headway checkpoints
-> headway candidates
-> headway pairs
-> passengers
-> ride candidates
```

Builder output must be serializable and testable without `gurobipy`.

## Non-Goals

- no Gurobi variables
- no MILP constraints
- no objective
- no solution extraction
- no replay export
- no automatic scenario design decisions hidden inside the solver

## Files

Target package:

```text
src/ropeway_skip_stop_optimization/optimization/ean/
  models.py
  builders/
    __init__.py
    switch_visit_builder.py
    ring_switch_visit_builder.py
    headway_checkpoint_builder.py
    headway_candidate_builder.py
    headway_pair_builder.py
    passenger_builder.py
  validation.py
```

`models.py` stays pure dataclasses/enums. Builder result and metadata
dataclasses may live there too, as long as they remain Gurobi-independent.

## Builder Principles

Builders should:

- validate their inputs early
- return explicit records, not hidden closures or solver expressions
- keep stable ids for debugging and frontend/export inspection
- report counts and per-resource statistics
- avoid duplicating derivable data unless it is intentionally cached metadata
- do as much safe pruning as possible before the MILP exists

Builders should not:

- assume a global cabin order
- assume periodicity
- use a rolling horizon
- decide `serve` vs. `skip`
- require a passenger to be served when generating candidates

## Stage 1: Switch Visit Builder

Generic interface file:

```text
builders/switch_visit_builder.py
```

Use a small object-oriented builder interface because more switch-visit
strategies are likely:

```text
SwitchVisitBuilder          abstract base class
RingSwitchVisitBuilder      v0 implementation for fixed directed ring lines
```

The builder objects should be immutable configuration objects. They should not
store mutable build state. Calling `build(...)` returns a complete
`SwitchVisitBuildResult`.

Planned interface:

```python
class SwitchVisitBuilder(ABC):
    @abstractmethod
    def build(
        self,
        config: EanConfig,
        cabin_starts: tuple[EanCabinStart, ...],
        timings: tuple[SkipStopTiming, ...],
    ) -> SwitchVisitBuildResult:
        """Build switch visits without creating solver variables."""
```

Ring-specific implementation file:

```text
builders/ring_switch_visit_builder.py
```

Planned v0 implementation:

```python
@dataclass(frozen=True)
class RingSwitchVisitBuilder(SwitchVisitBuilder):
    switch_cycle: tuple[str, ...]
    safety_visit_margin: int = 1

    def build(
        self,
        config: EanConfig,
        cabin_starts: tuple[EanCabinStart, ...],
        timings: tuple[SkipStopTiming, ...],
    ) -> SwitchVisitBuildResult:
        ...
```

Scope for v0:

```text
fixed directed ring line only
```

The first builder is intentionally limited to ring lines with a fixed switch
order. Each switch has exactly one next switch in the ring. The MILP only
decides whether an active visit serves or skips the station.

It does **not** support yet:

- branch choices
- multiple outgoing switch transitions
- arbitrary directed switch graphs
- choosing the next switch inside the MILP

Inputs:

```text
EanConfig
tuple[EanCabinStart, ...]
tuple[SkipStopTiming, ...]
switch_cycle
```

`switch_cycle` is the fixed directed ring order:

```text
(switch_0, switch_1, ..., switch_n)
```

The transition after `switch_i` goes to:

```text
switch_cycle[(i + 1) mod len(switch_cycle)]
```

The initial model uses this fixed skip/stop switch sequence. The MILP decides
only whether each active visit serves or skips the station.

Output records:

```text
SwitchVisitDefinition:
  cabin_id
  visit_index
  switch_id
```

`station_id` is not stored on `SwitchVisitDefinition`; it is derived from:

```text
SkipStopTiming[switch_id].station_id
```

Builder output should stay minimal and avoid storing derivable data.

Add only these generic builder models:

```text
SwitchTransition:
  from_switch_id
  to_switch_id
  min_seconds
  max_seconds

SwitchVisitBuildResult:
  visits
  transitions
```

These values are intentionally **not** stored as required metadata because they
are derivable:

- `cabin_count`
- `total_visit_count`
- `visit_count_by_cabin`
- `model_end_seconds`
- `switch_cycle`
- `cycle_min_seconds`
- `full_min_time_rotations_by_cabin`
- `partial_min_time_visits_by_cabin`
- `min_switch_to_switch_seconds`
- `safety_visit_margin`

If we need these for logging/export later, compute them with helper functions or
add a separate optional diagnostics object. Do not inflate the core builder
result with redundant state.

Core rule:

```text
model_end_seconds = horizon_seconds
```

Tail generation is deferred for v0. Current example exports set
`tail_seconds = 0.0`, so `model_end_seconds == horizon_seconds` and the horizon
is treated as the physical model boundary. This accepts horizon-edge artifacts
until we explicitly decide to model post-horizon physical/headway continuation.

The builder computes a conservative upper bound of visits per cabin from the
minimum-time ring traversal. It should be large enough to cover movement inside
`model_end_seconds`, but tight enough to avoid useless visits.

First compute the minimum and maximum time from every switch to the next switch
in the ring:

```text
edge_min_seconds[switch_i] =
  min(service_min_time_i, skip_time_i)
  + rope_to_next_switch_seconds_i

edge_max_seconds[switch_i] =
  max(service_max_time_i, skip_time_i)
  + rope_to_next_switch_seconds_i
```

where:

```text
service_min_time_i =
  entry_to_platform_entry_seconds
  + min_platform_entry_to_platform_exit_seconds
  + platform_exit_to_exit_switch_seconds

skip_time_i =
  skip_entry_to_exit_switch_seconds
```

For station waiting modes that allow unbounded waiting, `service_max_time_i` is
infinite. Use Python `math.inf` internally for this because it preserves normal
numeric comparisons and makes max-time propagation explicit.

For JSON/export later, serialize infinite max times as `None` or another
explicit sentinel, not JSON `Infinity`, because JSON `Infinity` is not portable.

Then compute:

```text
cycle_min_seconds = sum(edge_min_seconds[s] for s in switch_cycle)
remaining_seconds = model_end_seconds - start.time_seconds
full_rotations = floor(remaining_seconds / cycle_min_seconds)
partial_remaining = remaining_seconds - full_rotations * cycle_min_seconds
```

The visit count is:

```text
full_rotations * len(switch_cycle)
+ visits in the next partial rotation whose minimum elapsed time is <= partial_remaining
+ safety_visit_margin
```

The builder can use a small fixed `safety_visit_margin`, for example `1`, until
we have tighter proofs.

The first visit at `start.time_seconds` counts if:

```text
start.time_seconds <= model_end_seconds
```

The planned builder function should document the v0 limitation explicitly:

```python
"""Build switch visits for a fixed directed ring of skip/stop switches.

This v0 builder assumes a single immutable switch cycle. Each switch has exactly
one next switch in switch_cycle, and the MILP only decides whether an active
visit serves or skips the station. It does not model branch choices, alternate
lines, or arbitrary directed switch graphs.

The visit bound is computed from minimum switch-to-next-switch travel times,
full minimum-time ring rotations, and a final partial rotation up to
config.model_end_seconds.
"""
```

Planned helper functions:

```text
calculate_min_max_switch_to_next_seconds(timing, station_config)
build_ring_switch_transitions(timings, station_configs, switch_cycle)
count_visits_by_cabin(visits)
transition_by_from_switch_id(transitions)
```

`SwitchTransition` and `SwitchVisitBuildResult` are generic and can be reused by
future non-ring builders. `RingSwitchVisitBuilder` is intentionally
ring-specific.

Ring-specific helper functions should live in
`builders/ring_switch_visit_builder.py` next to `RingSwitchVisitBuilder`.
Generic helpers can be moved later if a second builder needs them.

Validation:

- every cabin start is valid
- cabin ids are unique
- every `first_switch_id` exists in `SkipStopTiming`
- every `switch_cycle` id exists in `SkipStopTiming`
- every `first_switch_id` is in `switch_cycle`
- `switch_cycle` ids are unique
- visit indices start at `0` and are contiguous per cabin
- `SwitchVisitDefinition(cabin_id, 0).switch_id == EanCabinStart.first_switch_id`

## Stage 2: Headway Checkpoint Builder

File:

```text
builders/headway_checkpoint_builder.py
```

Use the same object-oriented builder pattern as switch visits:

```text
HeadwayCheckpointBuilder          abstract base class
SkipStopHeadwayCheckpointBuilder  v0 implementation for skip/stop stations
```

The builder output is a tuple of `HeadwayCheckpointDefinition` records. No
separate result model is needed initially because no additional non-derivable
artifact is produced.

Planned interface:

```python
class HeadwayCheckpointBuilder(ABC):
    @abstractmethod
    def build(
        self,
        timings: tuple[SkipStopTiming, ...],
        station_configs: tuple[StationEanConfig, ...],
    ) -> tuple[HeadwayCheckpointDefinition, ...]:
        """Build physical headway checkpoint definitions."""
```

Planned v0 implementation:

```python
@dataclass(frozen=True)
class SkipStopHeadwayCheckpointBuilder(HeadwayCheckpointBuilder):
    station_headway_seconds_by_station_id: dict[str, float]
    exit_switch_headway_seconds_by_switch_id: dict[str, float]

    def build(
        self,
        timings: tuple[SkipStopTiming, ...],
        station_configs: tuple[StationEanConfig, ...],
    ) -> tuple[HeadwayCheckpointDefinition, ...]:
        ...
```

This builder creates physical checkpoint definitions only. It does **not**
create cabin-specific headway candidates and does **not** create pairwise
conflict/order constraints. Those are handled by later builders.

Inputs:

```text
tuple[SkipStopTiming, ...]
tuple[StationEanConfig, ...]
station_headway_seconds_by_station_id
exit_switch_headway_seconds_by_switch_id
```

Output records:

```text
HeadwayCheckpointDefinition:
  id
  kind
  switch_id
  station_id
  headway_seconds
  applies_to_serve
  applies_to_skip
  waiting_modes
```

Initial checkpoint rules:

```text
PLATFORM_ENTRY:
  generated for every skip/stop station
  applies_to_serve = true
  applies_to_skip = false

PLATFORM_EXIT:
  generated only when waiting_mode is END_OF_PLATFORM_WAIT or STATION_FIFO_BUFFER
  applies_to_serve = true
  applies_to_skip = false

EXIT_SWITCH:
  generated for every skip/stop station
  applies_to_serve = true
  applies_to_skip = true
```

No `ENTRY_SWITCH` checkpoint initially.

For the concrete configured scenario, `waiting_modes` should contain only the
station's configured mode:

```text
waiting_modes = (station_config.waiting_mode,)
```

The field still stays tuple-valued because future builders may emit reusable
checkpoint definitions covering multiple modes.

Checkpoint ids:

```text
platform_entry::{switch_id}
platform_exit::{switch_id}
exit_switch::{switch_id}
```

Validation:

- every station config has matching timings if it participates in skip/stop
- headway seconds are positive
- checkpoint ids are unique
- `PLATFORM_EXIT` is not generated for `NO_WAITING`
- every timing's station has a station config
- every timing's station has a station headway value
- every timing's switch has an exit-switch headway value

## Stage 3: Headway Candidate Builder

File:

```text
builders/headway_candidate_builder.py
```

Use the same builder pattern:

```text
HeadwayCandidateBuilder              abstract base class
SwitchVisitHeadwayCandidateBuilder   v0 implementation combining switch visits and checkpoints
```

No new model is needed. The existing `HeadwayCandidate` dataclass is sufficient.

Planned interface:

```python
class HeadwayCandidateBuilder(ABC):
    @abstractmethod
    def build(
        self,
        visits: tuple[SwitchVisitDefinition, ...],
        checkpoints: tuple[HeadwayCheckpointDefinition, ...],
    ) -> tuple[HeadwayCandidate, ...]:
        """Build cabin-visit-specific headway candidates."""
```

Planned v0 implementation:

```python
@dataclass(frozen=True)
class SwitchVisitHeadwayCandidateBuilder(HeadwayCandidateBuilder):
    def build(
        self,
        visits: tuple[SwitchVisitDefinition, ...],
        checkpoints: tuple[HeadwayCheckpointDefinition, ...],
    ) -> tuple[HeadwayCandidate, ...]:
        ...
```

Inputs:

```text
tuple[SwitchVisitDefinition, ...]
tuple[HeadwayCheckpointDefinition, ...]
tuple[StationEanConfig, ...]
```

Output records:

```text
HeadwayCandidate:
  id
  checkpoint_id
  cabin_id
  visit_index
  time_reference
  activation_reference
```

Mapping:

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

The candidate builder does not create algebraic expressions. It only creates
references that the MILP builder later maps to variables.

Build rule:

```text
create a candidate iff visit.switch_id == checkpoint.switch_id
```

Candidate id:

```text
candidate::{checkpoint_id}::cabin_{cabin_id}::visit_{visit_index}
```

Mapping helpers should live in the same file:

```text
time_reference_for_checkpoint_kind(kind)
activation_reference_for_checkpoint_kind(kind)
```

Validation:

- every candidate references an existing checkpoint
- every candidate references an existing switch visit
- candidate ids are unique
- checkpoint `waiting_modes` match the station config
- visit keys `(cabin_id, visit_index)` are unique
- checkpoint ids are unique

## Stage 4: Headway Pair Builder

File:

```text
builders/headway_pair_builder.py
```

Use an object-oriented strategy interface because pair generation is the main
remaining size driver and will need multiple algorithms:

```text
HeadwayPairBuilder          abstract base class
AllPairsHeadwayPairBuilder  v0 implementation, all unordered pairs per checkpoint
```

Planned interface:

```python
class HeadwayPairBuilder(ABC):
    @abstractmethod
    def build(
        self,
        candidates: tuple[HeadwayCandidate, ...],
        checkpoints: tuple[HeadwayCheckpointDefinition, ...],
    ) -> tuple[HeadwayPair, ...]:
        """Build candidate conflict pairs for headway ordering."""
```

Planned v0 implementation:

```python
@dataclass(frozen=True)
class AllPairsHeadwayPairBuilder(HeadwayPairBuilder):
    def build(
        self,
        candidates: tuple[HeadwayCandidate, ...],
        checkpoints: tuple[HeadwayCheckpointDefinition, ...],
    ) -> tuple[HeadwayPair, ...]:
        ...
```

Inputs:

```text
tuple[HeadwayCandidate, ...]
tuple[HeadwayCheckpointDefinition, ...]
optional earliest/latest bounds
```

Output records:

```text
HeadwayPair:
  id
  checkpoint_id
  first_candidate_id
  second_candidate_id
  headway_seconds
```

Pair rules:

```text
same checkpoint_id
candidate ids differ
only one unordered pair per candidate pair
raise on duplicate same checkpoint/cabin/visit candidates
```

Pair id:

```text
pair::{checkpoint_id}::{first_candidate_id}::{second_candidate_id}
```

The candidate ids are sorted lexicographically inside each checkpoint group so
the pair ids are stable.

Future pruning:

```text
if latest_u + headway <= earliest_v:
  fixed order, no order binary needed

if latest_v + headway <= earliest_u:
  fixed order, no order binary needed

if intervals cannot interact:
  omit pair
```

Initial implementation builds all possible same-checkpoint pairs. The pruning
can be added once earliest/latest bounds exist.

Do not add a result/metadata model initially. Pair counts are derivable from
the returned `HeadwayPair` records and can be computed by helper functions later
if needed.

## Stage 5: Passenger Builder

File:

```text
passenger_builder.py
```

Inputs:

```text
demands or explicit passenger records
tuple[SwitchVisitDefinition, ...]
tuple[SkipStopTiming, ...]
```

Output records:

```text
Passenger:
  id
  origin_station_id
  destination_station_id
  release_time_seconds

RideCandidate:
  id
  passenger_id
  cabin_id
  board_visit_index
  alight_visit_index
```

Ride candidate filters:

```text
board_visit_index < alight_visit_index
station_of_switch_visit[cabin_id, board_visit_index] == passenger.origin_station_id
station_of_switch_visit[cabin_id, alight_visit_index] == passenger.destination_station_id
same cabin_id for board and alight
```

Do not filter by `serve` because `serve` is a MILP decision. The MILP later adds:

```text
ride <= serve[cabin_id, board_visit_index]
ride <= serve[cabin_id, alight_visit_index]
```

Optional future filters:

- release time feasibility from earliest possible board time
- horizon feasibility from earliest possible alight time
- OD-specific route reachability
- grouping identical passengers if individual passengers explode

Metadata:

```text
PassengerBuildMetadata:
  passenger_count
  ride_candidate_count
  ride_candidate_count_by_passenger
  max_candidates_per_passenger
```

## Stage 6: Validation Layer

File:

```text
validation.py
```

Validation should be independent of Gurobi.

Initial checks:

- ids are unique per record type
- all references resolve
- switch visits are contiguous per cabin
- start switch equals first generated visit
- checkpoint switch ids exist
- headway candidates reference compatible visits/checkpoints
- headway pairs reference same-checkpoint candidates
- ride candidates reference valid passenger and switch visits
- ride candidates have increasing visit indices

Validation should return inspectable issues later. For the first implementation,
raising `ValueError` is acceptable and consistent with current project style.

## Implementation Order

1. Add builder result/metadata dataclasses to `models.py`.
2. Implement `switch_visit_builder.py` and tests.
3. Implement `headway_checkpoint_builder.py` and tests.
4. Implement `headway_candidate_builder.py` and tests.
5. Implement `headway_pair_builder.py` and tests.
6. Implement `passenger_builder.py` and tests.
7. Add one integration test that builds the full EAN builder pipeline for the
   current three-station example, but still does not call Gurobi.

## Open Decisions

- exact switch sequence input format for the first implementation
- whether station/exit headway seconds come directly from physical scenario
  operating parameters or from an EAN-specific config
- whether `safety_visit_margin = 1` is enough for switch-visit bounds
- whether passenger ids should be expanded deterministically from demand index
  and passenger offset

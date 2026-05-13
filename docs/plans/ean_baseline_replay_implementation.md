# EAN Baseline Replay Implementation Plan

Status: **partially implemented**

Implemented so far:

- example-specific three-station EAN config and ring switch order
- reusable EAN plan models
- reusable EAN build artifact model
- physical timing derivation
- deterministic physical node to EAN switch start derivation
- ring EAN artifact builder pipeline
- deterministic earliest all-stop EAN movement plan builder
- EAN movement plan validation against `EanBuildArtifact`
- physical event projection from EAN movement plan
- explicit `NotImplementedError` for FIFO-buffer waits in projection until
  station position traces exist
- generic EAN export artifact set
- manifest wiring for EAN build artifact, EAN result, and EAN replay

Not yet implemented:

- station FIFO wait position traces for `time -> position` replay
- frontend wiring for EAN artifacts
- Gurobi/SAT feasibility builders for finding a plan

## Goal

Implement the first EAN end-to-end pipeline without optimization:

```text
Physical Scenario
  -> example-specific EAN config
  -> generic EAN build artifact
  -> deterministic all-stop EAN movement plan
  -> physical event projection
```

The result should be reusable for later Gurobi solvers. The solver should
eventually output the same `EanMovementPlan` model as the deterministic baseline.

## Core Separation

Keep these responsibilities separate:

- Physical `Scenario`: what exists in the ropeway system.
- Example EAN config: how a specific example should be interpreted for EAN.
- EAN artifact: derived optimization/replay representation.
- EAN baseline: deterministic policy that produces an EAN plan.
- EAN projection: maps EAN plan events back to physical references.

Do not store EAN-specific starts or switch visits in `Scenario`.

## Waiting Configuration

Waiting is configured **per station**, not globally.

Existing model direction is correct:

```python
StationEanConfig(
    station_id="M",
    waiting_mode=StationWaitingMode.NO_WAITING,
    fifo_capacity=None,
)
```

For the first baseline:

```text
L: NO_WAITING
M: NO_WAITING
R: NO_WAITING
```

Meaning:

```text
platform_exit_time =
    platform_entry_time
    + min_platform_entry_to_platform_exit_seconds

wait_seconds = 0
```

Later station-specific modes:

- `NO_WAITING`
- `END_OF_PLATFORM_WAIT`
- `STATION_FIFO_BUFFER`

These modes should affect timing and headway candidate generation, but the first
baseline only supports `NO_WAITING`.

## What Is General

General implementation belongs under:

```text
src/ropeway_skip_stop_optimization/optimization/ean/
```

### `plan.py`

Add reusable EAN movement plan models.

```text
EanRouteDecision
  STOP
  SKIP

EanCabinVisit
  cabin_id
  visit_index
  switch_id
  station_id
  decision
  switch_time_seconds
  platform_entry_time_seconds
  platform_exit_time_seconds
  exit_switch_time_seconds
  next_switch_time_seconds
  wait_seconds

EanCabinTrajectory
  cabin_id
  visits

EanMovementPlan
  scenario_id
  horizon_seconds
  model_end_seconds
  trajectories
```

Notes:

- `decision` is fixed to `STOP` in the v0 baseline, but the field is general.
- `wait_seconds` is `0.0` in v0, but the field prepares the model for later
  station waiting.
- Platform times are `None` for future skip visits.
- v0 intentionally uses `tail_seconds = 0.0`, so `model_end_seconds` equals
  `horizon_seconds`. The horizon is currently the physical model boundary.
- Automatic tail generation is deferred. It should only be reintroduced once we
  explicitly decide to model post-horizon physical/headway effects.

OOP: dataclasses are enough. No plan class hierarchy needed.

### `artifact.py`

Add a generic bundle for derived EAN data:

```text
EanBuildArtifact
  scenario_id
  config
  switch_cycle
  timings
  cabin_starts
  switch_visits
  switch_transitions
  headway_checkpoints
  headway_candidates
  headway_pairs
```

The artifact is the input to baselines and future solvers.

OOP: dataclass only.

### `projection.py`

Add generic physical event projection:

```text
EanPhysicalEventKind
  ENTER_SWITCH
  ENTER_PLATFORM
  ENTER_WAIT
  EXIT_WAIT
  EXIT_PLATFORM
  EXIT_SWITCH
  REACH_NEXT_SWITCH

EanPhysicalEvent
  time_seconds
  cabin_id
  visit_index
  event_kind
  switch_id
  station_id
  physical_node_id
  source_segment_ids

EanPhysicalReplay
  scenario_id
  horizon_seconds
  model_end_seconds
  events
```

Add function:

```python
project_ean_movement_plan_to_physical_replay(
    scenario: Scenario,
    artifact: EanBuildArtifact,
    plan: EanMovementPlan,
) -> EanPhysicalReplay
```

OOP: use a function first. A class is not needed until projection gets multiple
strategies.

Projection v0 supports `NO_WAITING` and `END_OF_PLATFORM_WAIT`. It must raise
`NotImplementedError` when a visit has `wait_seconds > 0` at a station with
`STATION_FIFO_BUFFER`, because a FIFO wait cannot be mapped to one physical node.
It needs a separate station trace model that maps each cabin's station position
as a function of time.

Future FIFO trace model:

```text
StationFifoPositionTraceBuilder
  input:
    visits for one station/service direction
    platform entry/exit times
    station path length
    station speed profile
    required cabin spacing
  output:
    piecewise cabin traces:
      move intervals: t0, t1, s0, s1
      wait intervals: t0, t1, s
```

FIFO projection semantics:

- local station coordinate `s` runs along the service station path
- cabins enter in platform-entry-time order
- no overtaking
- moving cabins advance at the station speed/profile unless blocked by the
  required spacing to the cabin in front
- waiting positions are derived by this traffic simulation, not by assigning all
  waits to `platform_exit`
- a plan is not FIFO-projectable if a cabin cannot reach `platform_exit` by its
  `platform_exit_time_seconds`
- replay can later render these traces as `time -> position` in the station
  instead of only point events

### `builders/artifact_builder.py`

Add a generic artifact builder interface plus a ring implementation:

```python
class EanBuildArtifactBuilder(ABC):
    def build(self, scenario: Scenario, config: EanConfig) -> EanBuildArtifact:
        ...

class RingEanBuildArtifactBuilder(EanBuildArtifactBuilder):
    switch_cycle: tuple[str, ...]
    ...
```

Responsibilities:

- validate scenario and config
- build `SkipStopTiming`
- derive `EanCabinStart` from `Scenario.cabin_initial_states`
- build ring switch visits
- build headway checkpoints
- build headway candidates
- build headway pairs

OOP: class is useful because it composes multiple builder dependencies.

The base interface should not assume a ring forever. The first implementation
does assume a fixed directed ring and should say so in its class name.

### `builders/fixed_start_builder.py`

Add a generic start mapper:

```python
class EanCabinStartBuilder(ABC):
    def build(
        self,
        scenario: Scenario,
        config: EanConfig,
        timings: tuple[SkipStopTiming, ...],
        switch_cycle: tuple[str, ...],
    ) -> tuple[EanCabinStart, ...]:
        ...

class PhysicalCabinStartToEanStartBuilder(EanCabinStartBuilder):
    ...
```

It should derive EAN starts from physical starts:

```text
Scenario.cabin_initial_states
  -> next reachable EAN switch
  -> travel time to that switch
  -> EanCabinStart
```

For v0, only support unambiguous deterministic starts. If a start cannot be
mapped, fail loudly with a clear error.

The builder needs `timings` and `switch_cycle` because "next EAN switch" is not
defined by `Scenario` alone. It is defined by the EAN interpretation of the
scenario.

OOP: abstract base class is useful because later we may add depot starts,
synthetic starts, or optimized start builders.

### `builders/timing_builder.py`

Add timing derivation from physical scenario data:

```python
class SkipStopTimingBuilder(ABC):
    def build(self, scenario: Scenario, switch_cycle: tuple[str, ...]) -> tuple[SkipStopTiming, ...]:
        ...

class PhysicalSkipStopTimingBuilder(SkipStopTimingBuilder):
    ...
```

Responsibilities:

- derive service timing from station route segment ids
- derive skip timing from skip route segment ids
- set `skip_allowed=False` when no physical skip route exists, e.g. terminals
- derive `rope_to_next_switch_seconds` from the rope segment between exit switch
  and next entry switch
- reuse a shared physical segment travel-time calculation for constant and
  linear speed profiles

Do not manually enter `SkipStopTiming` seconds for examples.

OOP: useful because timing derivation may later differ for ring lines, branch
graphs, and richer physical station models.

### `baselines/movement_plan_builder.py`

Add abstract baseline interface:

```python
class EanMovementPlanBuilder(ABC):
    def build(self, artifact: EanBuildArtifact) -> EanMovementPlan:
        ...
```

OOP: useful because later we will have all-stop, skip-pattern, warm-start, and
solver-output builders.

### `baselines/all_stop.py`

Add deterministic all-stop baseline:

```python
class AllStopEanMovementPlanBuilder(EanMovementPlanBuilder):
    def build(self, artifact: EanBuildArtifact) -> EanMovementPlan:
        ...
```

Assumptions:

- all station configs use `NO_WAITING`
- all visits choose `STOP`
- `wait_seconds = 0.0`
- switch visits are already generated

Timing propagation:

```text
platform_entry = switch_time + entry_to_platform_entry_seconds
platform_exit = platform_entry + min_platform_entry_to_platform_exit_seconds
exit_switch = platform_exit + platform_exit_to_exit_switch_seconds
next_switch = exit_switch + rope_to_next_switch_seconds
```

No headway solving in v0. Headways can be validated later.

## What Is Example-Specific

Example-specific implementation belongs near the example:

```text
src/ropeway_skip_stop_optimization/examples/three_station_ean.py
```

Add helper functions:

```python
build_three_station_ean_config() -> EanConfig
build_three_station_ean_ring_switch_order() -> tuple[str, ...]
```

For the first example:

```text
waiting mode:
  L = NO_WAITING
  M = NO_WAITING
  R = NO_WAITING

ring switch order:
  M_entry_lr
  R_entry_lr
  M_entry_rl
  L_entry_rl
```

or whichever exact switch sequence the existing physical graph implies. This
must be verified from the scenario, not guessed in tests.

Do not hardcode this example's ring order inside general EAN builders.

Keep this separate from `examples/three_station.py` so the physical example
builder stays focused on physical scenario data. `three_station_ean.py` is the
example-specific EAN interpretation.

## Physical Starts

Physical starts remain in `Scenario`:

```python
CabinInitialState(
    cabin_id=0,
    node_id="L_platform_exit",
    available_from=time(8, 0),
)
```

EAN starts are derived:

```python
EanCabinStart(
    cabin_id=0,
    first_switch_id="M_entry_lr",
    kind=EanCabinStartKind.FIXED,
    time_seconds=<available_from_delta + travel_time_to_switch>,
)
```

For the three-station example:

```text
L_platform_exit -> L_exit_lr -> M_entry_lr
R_platform_exit -> R_exit_rl -> M_entry_rl
```

If a start is already on an EAN switch, travel time is zero.

## Timing Builder

General timing calculation should derive from physical segments:

```text
entry_to_platform_entry_seconds
min_platform_entry_to_platform_exit_seconds
platform_exit_to_exit_switch_seconds
skip_entry_to_exit_switch_seconds
rope_to_next_switch_seconds
skip_allowed
```

Do not enter these numbers manually for the example. They should come from
segment lengths and speed profiles.

If no physical skip route exists for a switch, `skip_allowed` is `False` and
transition builders must ignore `skip_entry_to_exit_switch_seconds` as a
decision option. The seconds value can still be populated with service travel
time to keep the timing record numeric.

If the existing EAN builders already calculate part of this, reuse that logic.
If not, add the timing builder described above:

```text
builders/timing_builder.py
```

OOP: a class is reasonable if it needs scenario indexes and config. Otherwise a
pure function is acceptable.

Headway seconds should also be derived where possible:

```text
station headway seconds ~= required_cabin_spacing_m / station_speed_m_per_s
exit switch headway seconds ~= required_cabin_spacing_m / rope_speed_m_per_s
```

If a station has a custom speed profile, derive from that profile instead of
blindly using global operating speeds. For the first example, the global
operating speeds are sufficient.

## Validation

Validation checks a concrete optimizer/baseline output. It does not search for a
feasible plan. Gurobi/SAT belongs in a separate movement-plan builder that
produces an `EanMovementPlan`; the validator then checks that concrete output.

Add:

```text
src/ropeway_skip_stop_optimization/optimization/ean/validation.py
```

Public API:

```python
def validate_ean_movement_plan_against_artifact(
    artifact: EanBuildArtifact,
    plan: EanMovementPlan,
    tolerance_seconds: float = 1e-6,
) -> ValidationReport:
    ...
```

Checks:

- artifact and plan dataclasses validate structurally
- `plan.scenario_id`, `horizon_seconds`, and `model_end_seconds` match the artifact
- plan trajectories cover exactly the artifact cabin starts
- plan visits match artifact switch visit definitions by `(cabin_id, visit_index)`
- every plan visit `station_id` matches the `SkipStopTiming.station_id` for its
  switch
- first visit respects `EanCabinStart`:
  - `FIXED`: `switch_time_seconds == start.time_seconds`
  - `EARLIEST`: `switch_time_seconds >= start.time_seconds`
- `SKIP` visits are only allowed when `SkipStopTiming.skip_allowed` is true
- `wait_seconds > 0` is only allowed for station configs whose waiting mode is
  not `NO_WAITING`
- headway checkpoints only apply when the station config waiting mode is in
  `checkpoint.waiting_modes`
- candidate activation must respect both activation reference and checkpoint
  path applicability:
  - `SERVE`: active only for `STOP` and `checkpoint.applies_to_serve`
  - `SKIP`: active only for `SKIP` and `checkpoint.applies_to_skip`
  - `ACTIVE`: active for `STOP` when `checkpoint.applies_to_serve`, and active
    for `SKIP` when `checkpoint.applies_to_skip`
- timing equations match `SkipStopTiming`
  - STOP:
    - `platform_entry = switch + entry_to_platform_entry`
    - `platform_exit = platform_entry + min_platform_entry_to_platform_exit + wait`
    - `exit_switch = platform_exit + platform_exit_to_exit_switch`
    - `next_switch = exit_switch + rope_to_next_switch`
  - SKIP:
    - platform times are `None`
    - `wait_seconds == 0`
    - `exit_switch = switch + skip_entry_to_exit_switch`
    - `next_switch = exit_switch + rope_to_next_switch`
- per-cabin visits are chained:
  - `next_visit.switch_time_seconds == previous_visit.next_switch_time_seconds`
- event times and safety visits:
  - all emitted visits are structurally and timing-equation validated
  - switch visits after `model_end_seconds` may exist because the artifact can
    include safety visits for downstream chaining
  - headway pairs are evaluated only when both candidate event times are within
    `model_end_seconds`
  - no event time may be negative
  - replay/projection should later filter emitted events by horizon/model-end
    depending on the artifact being exported
  - for the current v0 baseline, `model_end_seconds == horizon_seconds`; this is
    deliberate and accepts horizon-edge artifacts instead of adding tail logic
- active headway pairs satisfy:
  - `abs(t1 - t2) >= pair.headway_seconds`
  - pairs are ignored if their checkpoint is inactive for the station waiting
    mode

Issue codes:

```text
EAN_PLAN_ID_MISMATCH
EAN_PLAN_HORIZON_MISMATCH
EAN_TRAJECTORY_CABIN_MISMATCH
EAN_VISIT_MISMATCH
EAN_VISIT_STATION_MISMATCH
EAN_START_TIME_VIOLATION
EAN_SKIP_NOT_ALLOWED
EAN_WAIT_NOT_ALLOWED
EAN_CHECKPOINT_MODE_MISMATCH
EAN_TIMING_MISMATCH
EAN_TRAJECTORY_CHAIN_MISMATCH
EAN_TIME_WINDOW_VIOLATION
EAN_HEADWAY_VIOLATION
```

Use `ValidationReport`/`ValidationIssue` from the existing validation package so
callers can inspect all issues instead of failing at the first error.

Tests:

```text
tests/test_optimization_ean_movement_plan_validation.py
```

Minimum assertions:

- Three-station artifact + `EarliestAllStopEanMovementPlanBuilder` validates
  shape and timing without timing mismatch issues.
- Mutating a platform entry time produces `EAN_TIMING_MISMATCH`.
- Mutating a terminal visit to `SKIP` produces `EAN_SKIP_NOT_ALLOWED`.
- Mutating a `NO_WAITING` visit to positive `wait_seconds` produces
  `EAN_WAIT_NOT_ALLOWED`.
- Mutating a visit station id away from its timing station id produces
  `EAN_VISIT_STATION_MISMATCH`.
- Mutating checkpoint waiting modes so they exclude the configured station mode
  produces `EAN_CHECKPOINT_MODE_MISMATCH`.
- Moving a first switch time before an `EARLIEST` start produces
  `EAN_START_TIME_VIOLATION`.
- Mutating a relevant event time to a negative value produces
  `EAN_TIME_WINDOW_VIOLATION`.
- A synthetic too-close pair produces `EAN_HEADWAY_VIOLATION`.

## Export

Do not hardcode `three_station_v0` inside the export pipeline.

Generic EAN export support works by teaching examples to advertise whether they
can build an EAN artifact. The export system depends on that capability, not on
a specific example id.

### Example Capability

Protocol near the example abstractions:

```python
class EanScenarioExample(Protocol):
    def build_ean_config(self, scenario: Scenario) -> EanConfig:
        ...

    def build_ean_artifact_builder(
        self,
        scenario: Scenario,
        config: EanConfig,
    ) -> EanBuildArtifactBuilder:
        ...
```

`ThreeStationExample` implements this protocol by delegating to:

```text
build_three_station_ean_config(scenario)
RingEanBuildArtifactBuilder(
  switch_cycle=build_three_station_ean_ring_switch_order(scenario)
)
```

Keep the physical scenario builder focused on physical data. The example-level
EAN methods are the bridge from the physical example to its EAN interpretation.

### Export Context

EAN caches on `ExportContext`:

```text
ean_artifact()
ean_all_stop_plan()
ean_physical_replay()
```

These methods:

- validate that `context.example` implements `EanScenarioExample`
- build the scenario once through `context.scenario()`
- build the EAN config and artifact through the example capability
- build the deterministic all-stop EAN movement plan
- validate the plan against the artifact before projecting it
- project the plan back to physical replay events

If an example does not support EAN, fail with a clear `ValueError`.

### Artifact Set

Artifact set:

```text
ean_all_stop_baseline
```

Files:

```text
ean_build_artifact.json
ean_all_stop_movement_plan.json
ean_physical_replay.json
```

Kinds:

```text
ean_input
ean_result
ean_replay
```

`ArtifactKind` has `EAN_INPUT`, `EAN_RESULT`, and `EAN_REPLAY`.
The manifest should expose all three so the frontend can later choose an EAN
view/replay independently from the deprecated discrete-time replay.

## Tests

Implemented Python pipeline tests:

```text
tests/test_optimization_ean_fixed_start_builder.py
tests/test_optimization_ean_artifact_builder.py
tests/test_optimization_ean_earliest_all_stop_baseline.py
tests/test_optimization_ean_projection.py
tests/test_optimization_ean_movement_plan_validation.py
```

Minimum assertions:

- example EAN config has station configs for `L`, `M`, `R`
- all first example station configs use `NO_WAITING`
- fixed starts are derived from physical starts, not manually provided
- `L_platform_exit` starts map to `M_entry_lr`
- `R_platform_exit` starts map to `M_entry_rl`
- all-stop baseline creates visits for all cabins
- all visits have `STOP`
- all visits have `wait_seconds == 0.0`
- per-cabin event times are monotonic
- projection emits sorted events

Implemented export tests:

```text
tests/test_export_scenarios.py
```

Minimum assertions:

- `ean_all_stop_baseline` writes all three EAN JSON artifacts
- manifest contains `ean_input`, `ean_result`, and `ean_replay`
- build artifact has `scenario_id == "three_station_v0"`
- build artifact has four skip/stop timings for the three-station ring
- middle-station switches allow skip
- terminal switches do not allow skip
- EAN movement plan visits are all `STOP`
- EAN physical replay contains events and references physical node ids

## Implementation Order

Completed:

1. Add EAN config helpers in `examples/three_station_ean.py`.
2. Add `plan.py`.
3. Add `artifact.py`.
4. Add `builders/timing_builder.py`.
5. Add `builders/fixed_start_builder.py`.
6. Add `builders/artifact_builder.py`.
7. Add `baselines/movement_plan_builder.py`.
8. Add earliest all-stop baseline.
9. Add `validation.py`.
10. Add `projection.py`.
11. Add EAN unit tests.

Completed export step:

1. Add the `EanScenarioExample` protocol.
2. Make `ThreeStationExample` implement it without hardcoding anything in
   `exports`.
3. Add EAN caches to `ExportContext`.
4. Add EAN artifact builders.
5. Add `ean_all_stop_baseline` to the artifact set registry.
6. Add export tests.

Remaining:

1. Wire the exported EAN artifacts into the frontend.
2. Implement station FIFO position traces.
3. Add solver-backed EAN movement-plan builders.

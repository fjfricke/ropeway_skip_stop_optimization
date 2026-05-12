# EAN Baseline Replay Implementation Plan

Status: **planned**

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
```

Do not enter these numbers manually for the example. They should come from
segment lengths and speed profiles.

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

Add later, but design for:

```python
validate_ean_movement_plan(artifact, plan)
```

Checks:

- station configs exist for all stations in timings
- every visit references a known timing
- all v0 station configs are `NO_WAITING`
- all v0 visits have `decision == STOP`
- all v0 visits have `wait_seconds == 0`
- timing equations match `SkipStopTiming`
- event times are monotonic per cabin
- projected events are sorted

## Export Later

Do not implement export first.

After the Python pipeline works, add an artifact set:

```text
ean_all_stop_baseline
```

Files:

```text
ean_build_artifact.json
ean_all_stop_movement_plan.json
ean_physical_replay.json
```

This should use the manifest-driven export system.

## Tests

Add tests in this order:

```text
tests/test_optimization_ean_fixed_start_builder.py
tests/test_optimization_ean_artifact_builder.py
tests/test_optimization_ean_all_stop_baseline.py
tests/test_optimization_ean_projection.py
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

## Implementation Order

1. Add EAN config helpers in `examples/three_station_ean.py`.
2. Add `plan.py`.
3. Add `artifact.py`.
4. Add `builders/timing_builder.py`.
5. Add `builders/fixed_start_builder.py`.
6. Add `builders/artifact_builder.py`.
7. Add `baselines/movement_plan_builder.py`.
8. Add `baselines/all_stop.py`.
9. Add `projection.py`.
10. Add tests.
11. Only then add exports/frontend support.

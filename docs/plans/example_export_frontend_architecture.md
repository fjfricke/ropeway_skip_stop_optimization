# Example, Export, and Frontend Artifact Architecture

Status: **implemented**

## Goal

Examples, generated artifacts, and frontend loading should be separated cleanly.

The physical scenario should stay the source of truth. Exported files should be
derived artifacts with explicit metadata, and the frontend should discover those
artifacts from a manifest instead of hardcoding filenames.

## Current Problem

The current implementation mixes four responsibilities:

- `examples.py` builds the built-in physical scenario.
- `export_scenarios.py` knows concrete examples, concrete artifact types,
  concrete filenames, solver flags, and frontend output paths.
- `frontend/public/scenarios/` contains generated files with naming conventions
  encoded in Python and TypeScript.
- `frontend/src/App.tsx` hardcodes the `three_station_v0` artifact filenames.

This works for one demo, but it will not scale cleanly to:

- multiple examples
- multiple demand scenarios
- multiple movement plans
- discrete-time and EAN optimization side by side
- physical replay and legacy discrete-time replay side by side
- frontend selection between scenarios and solver outputs

## Principles

- `Scenario` remains canonical.
- Example builders create domain objects, not files.
- Export builders create files, not domain definitions.
- The frontend reads a manifest, not Python filename conventions.
- Generated artifacts should be grouped by example id.
- Discrete-time artifacts remain supported for old replay and frontend graph
  views.
- EAN artifacts should be added later without changing the frontend loading
  architecture again.
- Avoid compatibility reexports. Imports should point to the final package
  locations directly.

## Target Package Structure

```text
src/ropeway_skip_stop_optimization/
  examples/
    __init__.py
    base.py
    discrete.py
    ean.py
    registry.py
    three_station.py
    three_station_ean.py

  exports/
    __init__.py
    artifacts.py
    cli.py
    json_codec.py
    manifest.py
    runner.py
```

The current top-level `examples.py` and `export_scenarios.py` are replaced by
these packages. No compatibility layer is planned.

## Example Layer

The example layer owns reproducible input scenarios.

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass

from ropeway_skip_stop_optimization.models import Scenario


@dataclass(frozen=True)
class ScenarioExampleMetadata:
    id: str
    label: str
    description: str
    tags: tuple[str, ...] = ()


class ScenarioExample(ABC):
    metadata: ScenarioExampleMetadata

    @abstractmethod
    def build_scenario(self) -> Scenario:
        ...
```

The three-station example becomes:

```text
examples/three_station.py
  ThreeStationExample
  build_three_station_near_capacity_demands
  helper functions for physical topology construction

examples/three_station_ean.py
  example-specific EAN config and ring switch interpretation
```

The registry maps stable ids to example objects:

```python
EXAMPLES: dict[str, ScenarioExample] = {
    "three_station_v0": ThreeStationExample(),
}
```

Optional example capabilities keep generated artifact types explicit:

```text
examples/discrete.py
  DiscreteScenarioExample
    build_discretization_config(scenario)

examples/ean.py
  EanScenarioExample
    build_ean_config(scenario)
    build_ean_artifact_builder(scenario, config)
```

An artifact set that needs a discrete scenario should require
`DiscreteScenarioExample`. An artifact set that needs EAN should require
`EanScenarioExample`. This avoids assuming every physical example can be mapped
to every optimization/replay representation.

## Export Artifact Layer

An artifact is one generated output file or one manifest entry.

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any


class ArtifactKind(StrEnum):
    SCENARIO = "scenario"
    DISCRETE_SCENARIO = "discrete_scenario"
    MOVEMENT_PLAN = "movement_plan"
    PASSENGER_REPLAY = "passenger_replay"
    REPLAY_METRICS = "replay_metrics"
    MILP_RESULT = "milp_result"
    EAN_INPUT = "ean_input"
    EAN_RESULT = "ean_result"
    EAN_REPLAY = "ean_replay"


@dataclass(frozen=True)
class ExportArtifact:
    id: str
    kind: ArtifactKind
    relative_path: Path
    payload: Any
    label: str | None = None
```

Builders should be small classes with one responsibility:

```python
class ArtifactBuilder(ABC):
    id: str
    kind: ArtifactKind

    @abstractmethod
    def build(self, context: ExportContext) -> ExportArtifact:
        ...
```

Examples:

- `PhysicalScenarioArtifactBuilder`
- `DiscreteScenarioArtifactBuilder`
- `GreedyAllStopMovementPlanArtifactBuilder`
- `GreedyAllStopPassengerReplayArtifactBuilder`
- `ReplayMetricsArtifactBuilder`
- `MilpV0MovementPlanArtifactBuilder`
- `MilpV1PassengerWaitingPlanArtifactBuilder`
- `EanBuildArtifactArtifactBuilder`
- `EanAllStopMovementPlanArtifactBuilder`
- `EanPhysicalReplayArtifactBuilder`

## Export Context

`ExportContext` should cache expensive intermediate objects so artifact builders
do not rebuild the same scenario, discrete scenario, movement plan, or replay.

```python
@dataclass
class ExportContext:
    example: ScenarioExample
    progress: ProgressReporter

    _scenario: Scenario | None = None
    _discrete_scenario: DiscreteScenario | None = None
    _greedy_plan: MovementPlan | None = None
    _greedy_passenger_replay: PassengerReplayResult | None = None
    _ean_artifact: EanBuildArtifact | None = None
    _ean_all_stop_plan: EanMovementPlan | None = None
    _ean_physical_replay: EanPhysicalReplay | None = None

    def scenario(self) -> Scenario:
        ...

    def discrete_scenario(self) -> DiscreteScenario:
        ...

    def greedy_all_stop_plan(self) -> MovementPlan:
        ...

    def greedy_passenger_replay(self) -> PassengerReplayResult:
        ...

    def ean_artifact(self) -> EanBuildArtifact:
        ...

    def ean_all_stop_plan(self) -> EanMovementPlan:
        ...

    def ean_physical_replay(self) -> EanPhysicalReplay:
        ...
```

MILP builders use builder-local parameters for solver-specific outputs. EAN and
discrete exports use example capabilities to get their example-specific config.

## Artifact Sets

The frontend usually needs a coherent group of files, not a single file.

```python
@dataclass(frozen=True)
class ArtifactSet:
    id: str
    label: str
    builders: tuple[ArtifactBuilder, ...]
    is_default: bool = False
```

Suggested initial sets:

- `physical_only`
- `discrete_debug`
- `greedy_all_stop`
- `milp_v0_feasibility`
- `milp_v1_passenger_feasibility`
- `milp_v1_waiting_time`
- `ean_all_stop_baseline`

The default frontend set for `three_station_v0` should be `greedy_all_stop`
until an optimized solution is stable enough to become the default.

## Output Layout

Default output should move from a flat `frontend/public/scenarios/` directory to
a generated, manifest-driven tree:

```text
frontend/public/generated/examples/
  manifest.json
  three_station_v0/
    scenario.json
    discrete_dt_0p5.json
    greedy_all_stop_movement_plan.json
    greedy_all_stop_passenger_replay.json
    greedy_all_stop_replay_metrics.json
    milp_v1_waiting_time_c23_h240.json
```

The generated directory should be ignored by git by default. If we want a small
demo bundle checked in, we should make that an explicit decision and keep only
the selected files tracked.

## Manifest Contract

The frontend should load only one stable manifest first:

```text
/generated/examples/manifest.json
```

Suggested manifest shape:

```json
{
  "schema_version": 1,
  "generated_at": "2026-05-12T00:00:00+02:00",
  "examples": [
    {
      "id": "three_station_v0",
      "label": "Three station ring",
      "description": "Three-station bidirectional ring with middle skip.",
      "default_artifact_set": "greedy_all_stop",
      "artifact_sets": [
        {
          "id": "greedy_all_stop",
          "label": "Greedy all-stop replay",
          "artifacts": {
            "scenario": "three_station_v0/scenario.json",
            "discrete_scenario": "three_station_v0/discrete_dt_0p5.json",
            "movement_plan": "three_station_v0/greedy_all_stop_movement_plan.json",
            "passenger_replay": "three_station_v0/greedy_all_stop_passenger_replay.json",
            "replay_metrics": "three_station_v0/greedy_all_stop_replay_metrics.json"
          }
        }
      ]
    }
  ]
}
```

The manifest should contain frontend-facing metadata only. Large payloads stay in
separate artifact files.

## Frontend Loading

`frontend/src/App.tsx` should stop hardcoding:

```text
/scenarios/three_station_v0.json
/scenarios/three_station_v0__dt_0p5.json
...
```

Instead it should:

1. Load `/generated/examples/manifest.json`.
2. Select the default example.
3. Select the default artifact set.
4. Load the artifact URLs listed in the manifest.
5. Render views based on which artifacts are present.

This makes the frontend tolerant of partial artifact sets:

- scenario only: physical view
- scenario + discrete scenario: physical and graph/debug views
- plus movement plan: replay view
- plus passenger replay and metrics: passenger and metrics views
- later EAN input/result: EAN debug and physical projection views

## CLI

The replacement CLI should live in:

```text
exports/cli.py
```

Example commands:

```bash
uv run python -m ropeway_skip_stop_optimization.exports.cli \
  --example three_station_v0 \
  --artifact-set greedy_all_stop \
  --output-root frontend/public/generated/examples \
  --clean
```

```bash
uv run python -m ropeway_skip_stop_optimization.exports.cli \
  --example three_station_v0 \
  --artifact-set milp_v1_waiting_time \
  --milp-horizon 240 \
  --milp-cabin-count 23 \
  --milp-variable-strategy sparse_reachability \
  --progress
```

CLI responsibilities:

- resolve example id
- resolve artifact set id
- create output root
- optionally clean only the selected example output directory
- run artifact builders
- write artifact JSON files
- write/update `manifest.json`
- print written paths

The CLI should not contain the business logic for building each artifact. It
should orchestrate builders.

## JSON Codec

Dataclass, enum, and time serialization should move out of the CLI/export
runner:

```text
exports/json_codec.py
  to_jsonable(value: Any) -> Any
  write_json(path: Path, payload: Any) -> None
```

This keeps future EAN artifact serialization consistent with existing scenario,
plan, replay, and metric serialization.

## Migration Plan

1. Create `examples/` package and move the three-station scenario builder there.
2. Update tests to import `ThreeStationExample` or registry helpers directly.
3. Create `exports/json_codec.py` and move generic JSON serialization there.
4. Create artifact builder interfaces and implement physical scenario and
   discrete scenario builders first.
5. Add `manifest.py` and generate a manifest for the two initial artifacts.
6. Update frontend to load manifest and scenario/discrete artifacts from it.
7. Move greedy movement plan, passenger replay, and metrics exports into
   artifact builders.
8. Add MILP artifact builders after the simple builders are stable.
9. Remove old `examples.py` and `export_scenarios.py` once all imports and tests
   use the new structure. Done.

## Open Decisions

- Should any generated demo artifacts stay tracked in git, or should all
  generated frontend artifacts be ignored?
- Should the frontend default to the first manifest example or a configured
  default example id?
- Should solver-heavy artifact sets be excluded from normal export unless
  explicitly requested?
- Should the manifest include validation summaries for each artifact set?
- Should artifact file names include parameter values such as `c23_h240`, or
  should parameters live only in artifact metadata while filenames stay stable?

## Recommended First Implementation Slice

Start with the smallest useful slice:

- `examples/base.py`
- `examples/registry.py`
- `examples/three_station.py`
- `exports/json_codec.py`
- `exports/artifacts.py` with physical and discrete builders
- `exports/manifest.py`
- `exports/cli.py`
- frontend manifest loading for physical and discrete scenario only

After that works, move the greedy replay artifacts into the same pipeline.

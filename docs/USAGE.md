# Define, optimize and view a ropeway system

> AI-generated documentation.

Run commands from the repository root after [installation](../README.md#install).
Use new example IDs and output directories; keep the submitted instances unchanged.

## Explore an existing example

List registered systems:

```sh
uv run python -c "from ropeway_skip_stop_optimization.examples.registry import EXAMPLES; print('\n'.join(sorted(EXAMPLES)))"
```

Export geometry only, or an all-stop timetable with the event-based builder:

```sh
uv run ropeway-skip-stop-optimization --example five_station_circle_cw_half_skip_no_wait_v0 --artifact-set physical_only
uv run ropeway-skip-stop-optimization --example five_station_circle_cw_half_skip_no_wait_v0 --artifact-set ean_all_stop_baseline
```

Both write to `frontend/public/generated/examples/`. Start the frontend as
shown in the main README, open `/`, and select the example and artifact set.
Neither command optimizes passenger assignment. Other artifact sets can invoke
solvers; inspect `uv run ropeway-skip-stop-optimization --help` before choosing one.

## Create a new system

The physical data model is [models/scenario.py](../src/ropeway_skip_stop_optimization/models/scenario.py):
stations, track segments, station routes, cabins, demand and operating parameters.
Examples implement `build_scenario()`; event-based solvers additionally use
`build_ean_config()` and `build_ean_artifact_builder()`.

For a ring, reuse [circular_skip_stop.py](../src/ropeway_skip_stop_optimization/examples/circular_skip_stop.py).
Create `src/ropeway_skip_stop_optimization/examples/my_ring.py`:

```python
from dataclasses import replace
from ropeway_skip_stop_optimization.examples.base import ScenarioExampleMetadata
from ropeway_skip_stop_optimization.examples.circular_skip_stop import (
    FiveStationCircleCwFullSkipNoWaitExample,
)


class MyRingExample(FiveStationCircleCwFullSkipNoWaitExample):
    metadata = ScenarioExampleMetadata(
        id="my_ring_v1", label="My ring", description="Five-station test system"
    )
    spec = replace(
        FiveStationCircleCwFullSkipNoWaitExample.spec,
        scenario_id=metadata.id,
        label=metadata.label,
        description=metadata.description,
        rope_segment_length_m=300.0,
        cabin_capacity=10,
        demand_count_per_od_pair=20,
    )
```

Import `MyRingExample` in [examples/registry.py](../src/ropeway_skip_stop_optimization/examples/registry.py)
and add `MyRingExample.metadata.id: MyRingExample()` to its `EXAMPLES` dictionary.
Then use `--example my_ring_v1` in the export and optimization commands.

| Change | Where |
|---|---|
| Station sequence, segment lengths, speeds, cabin size and capacity | `CircularSkipStopSpec` in your example |
| OD demand and release times | `Scenario.demands`; override `build_scenario()` with `dataclasses.replace` and `Demand` records |
| Service window | `service_start_time` / `service_end_time` in the ring spec |
| Waiting and event-model horizon | Your example's `build_ean_config()`; runners may override these settings |
| Headway assumptions | `Scenario.headway_design`, defined in [models/headway.py](../src/ropeway_skip_stop_optimization/models/headway.py) |
| Initial layout for baseline export | `build_ean_artifact_builder()` and its start builder |
| Optimization fleet | Runner `--cabins` or `--fixed-k`, rather than the example's display fleet |

The ring helper initially releases equal demand for every OD pair at service
start. Its defaults are illustrative, not the calibrated thesis geometry.
`scenario.validate()` checks data consistency; it does not prove that a timetable
is feasible. Start by exporting the physical system and its baseline.

For a different topology, implement the physical nodes/routes and matching
circulation definition, following the existing examples. An arbitrary physical
graph is not automatically supported by every solver. Keep the geometry,
circulation sequence and headway configuration consistent.

## Optimize with fixed cabin starts: labelled arc-flow

Gurobi selects STOP/SKIP movements and integer passenger flows. This example
uses two cabins, the balanced-reference start policy and no waiting:

```sh
uv run python benchmarks/run_ddd_fixed_k_arc_flow.py \
  --example five_station_circle_cw_half_skip_no_wait_v0 \
  --cabins 2 --start-policy balanced_reference --mode skip_stop \
  --formulation labeled --objective journey_time \
  --waiting-headway-multiplier 0 --time-limit 30 --threads 1 \
  --campaign-id my_arc_run --output-dir results/my_arc
```

Requires a Gurobi license. Read `results/my_arc/my_arc_run/result.json` for
status, objective, bound and any validated incumbent. The generic runner's
journey-cost objective includes an unserved penalty; it does not impose the
thesis study's full-service requirement. Use the [study runners](experiments/README.md)
for that comparison. Initialization/seed stages have separate budget options.

`--mode all_stop` restricts movements to stops. Positive waiting caps and
`--waiting-step-seconds` add discrete waiting choices and can enlarge the time
network substantially. Keep the first instance small. `--frontend-live` publishes
progress under `/optimization/my_arc_run`; it is not the example-export command.

## Optimize initial positions: CP-SAT

OIP means optimized initial placement. Unlike fixed-start arc-flow, the generic
EAN formulation can choose initial positions, STOP/SKIP and passenger assignment:

```sh
uv run python benchmarks/run_oip.py \
  --example five_station_circle_cw_half_skip_no_wait_v0 \
  --backend cp_sat --fixed-k 2 --formulation ean --objective served \
  --maximum-wait-seconds 0 --time-limit 30 --workers 1 \
  --output results/my_oip
```

Add `--build-only` to inspect model size without search. A completed run writes
`manifest.json`, `result.json` and available certificates/snapshots to its output
directory. A timeout may produce no incumbent; it is not an infeasibility proof.
The generic output above is not automatically included in the submitted viewer.

- `--operation all_stop` fixes all visits to STOP.
- `--maximum-wait-seconds 10` permits bounded waiting in the EAN formulation.
- `--ticks-per-second` controls the time grid (default: 1,000, i.e. milliseconds).
- `--k-max` instead of `--fixed-k` permits an optional fleet in supported generic
  configurations; this is initial placement, not repeated reservoir dispatch.
- `--formulation nowait_templates` uses repeating stopping types and requires
  exact K, zero waiting and `--type-catalog`. Catalogues are topology-specific;
  the BD/CE catalogue expects station IDs S1–S4. The [service campaign](experiments/README.md)
  uses predefined pattern counts, not unrestricted pattern search.

Both runners expose further options through `--help`. New systems and generic
runs are separate from the frozen thesis campaigns and their result selection.

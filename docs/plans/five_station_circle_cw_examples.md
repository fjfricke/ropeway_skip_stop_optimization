# Five Station Circle cw Examples

Status: planned

## Goal

Add a new clockwise circular five-station example family without changing the
existing three-station and five-station line examples.

The new family should be passenger-facing as:

```text
Five station circle cw
```

The technical base id should be:

```text
five_station_circle_cw
```

The circle is clockwise-only in v0. Internally, the EAN can still use the
existing ring terminology because the current EAN builder models a fixed
directed switch cycle.

## Variants

Implement one full-cabin baseline variant and half-cabin comparison variants.

| Example id | Label | Skip routes | Waiting | Cabin starts |
|---|---|---:|---:|---|
| `five_station_circle_cw_full_no_skip_no_wait_v0` | `Five station circle cw full cabins no_skip+no_wait` | no | no | all max start cabins |
| `five_station_circle_cw_half_no_skip_no_wait_v0` | `Five station circle cw half cabins no_skip+no_wait` | no | no | every second max start cabin |
| `five_station_circle_cw_half_skip_no_wait_v0` | `Five station circle cw half cabins skip+no_wait` | yes | no | every second max start cabin |
| `five_station_circle_cw_half_skip_wait_v0` | `Five station circle cw half cabins skip+wait` | yes | yes | every second max start cabin |

Use one family:

```text
family_id: five_station_circle
family_label: Five station circle
```

Use these variant ids:

```text
full_no_skip_no_wait
half_no_skip_no_wait
half_skip_no_wait
half_skip_wait
```

Use tags consistently:

```text
circle
cw
ean-demo
scaling-demo
full-cabins or half-cabins
```

Add `skip-stop` only for skip-enabled variants. Add `no-skip`, `no-waiting`, or
`waiting` as appropriate.

## Physical Scenario

Use five service stations:

```text
A, B, C, D, E
```

All stations are `StationKind.SERVICE`. There are no terminal stations and no
turnaround routes.

Use one clockwise physical direction with node ids of this form:

```text
A_entry_cw
A_service_approach_cw
A_platform_entry_cw
A_platform_exit_cw
A_service_accelerate_cw
A_exit_cw
```

Each station has one service route:

```text
A_service_cw:
  A_entry_cw
  -> A_service_approach_cw
  -> A_platform_entry_cw
  -> A_platform_exit_cw
  -> A_service_accelerate_cw
  -> A_exit_cw
```

Skip-enabled variants add one skip route per station:

```text
A_skip_cw:
  A_entry_cw -> A_exit_cw
```

The rope segments close the circle:

```text
A_exit_cw -> B_entry_cw
B_exit_cw -> C_entry_cw
C_exit_cw -> D_entry_cw
D_exit_cw -> E_entry_cw
E_exit_cw -> A_entry_cw
```

Use the same default physical parameters as the current five-station examples:

```text
service window: 08:00-08:20
rope speed: 5.0 m/s
platform speed: 0.5 m/s
rope segment length: 150.0 m
platform length: 10.0 m
bypass length: 20.0 m
cabin capacity: 8
cabin length: 3.0 m
minimum clearance: 0.5 m
```

## Demand

Use all ordered OD pairs between the five stations:

```text
5 * 4 = 20 demand groups
```

Use a demand size that is just reachable by the full no-skip/no-wait all-stop
baseline over the 1200s service horizon. With five stations, uniform all-OD
demand loads each directed rope section with `10 * count_per_od_pair`
passengers. The all-stop baseline provides 160 complete traversals on its
bottleneck section, so the bottleneck capacity is `160 * 8 = 1280` passenger
section seats and the uniform OD count is `1280 / 10 = 128`.

The half-cabin variants use every second start cabin. For the half
no-skip/no-wait all-stop baseline, the bottleneck section has 80 complete
traversals, so the bottleneck capacity is `80 * 8 = 640` passenger section
seats. With the same `10 * count_per_od_pair` section load, the uniform OD
count is `640 / 10 = 64`.

```text
arrival_time: 08:00
full count per OD pair: 128
half count per OD pair: 64
```

Passengers travel clockwise. For example, `D -> B` travels through:

```text
D -> E -> A -> B
```

## EAN Setup

Use a fixed clockwise switch cycle:

```text
(
  "A_entry_cw",
  "B_entry_cw",
  "C_entry_cw",
  "D_entry_cw",
  "E_entry_cw",
)
```

The examples use:

```text
RingEanBuildArtifactBuilder
ContinuousAllStopMaxCabinStartBuilder
```

Wrap the start builder with `KeepEverySecondCabinStartBuilder` for half-cabin
variants.

Waiting mode:

```text
full_no_skip_no_wait: NO_WAITING at all stations
half_no_skip_no_wait: NO_WAITING at all stations
half_skip_no_wait:    NO_WAITING at all stations
half_skip_wait:       END_OF_PLATFORM_WAIT at all stations
```

## Implementation Steps

1. Add a new module:

   ```text
   src/ropeway_skip_stop_optimization/examples/circular_skip_stop.py
   ```

2. Define a reusable `CircularSkipStopSpec` with:

   ```text
   scenario_id
   station_ids
   label
   description
   include_skip_routes
   service_station_waiting_mode
   physical parameter defaults
   ```

3. Implement reusable builders:

   ```text
   build_circular_skip_stop_scenario(spec)
   build_circular_skip_stop_ean_config(scenario, waiting_mode, tail_seconds=0.0)
   build_circular_skip_stop_ean_ring_switch_order(scenario)
   ```

4. Implement the example class:

   ```text
   FiveStationCircleCwFullNoSkipNoWaitExample
   ```

5. Add convenience functions for tests and exports:

   ```text
   build_five_station_circle_cw_full_no_skip_no_wait_scenario()
   build_five_station_circle_cw_full_no_skip_no_wait_ean_config()
   build_five_station_circle_cw_ean_ring_switch_order()
   ```

6. Register the example in:

   ```text
   src/ropeway_skip_stop_optimization/examples/registry.py
   ```

7. Extend frontend layout selection in:

   ```text
   frontend/src/scenarioLayout.ts
   ```

   Add a circle-specific layout for scenario ids starting with:

   ```text
   five_station_circle_cw
   ```

   The physical view should place the five stations around a closed circle and
   make the `E -> A` rope segment visually explicit.

8. Extend the schematic station view in:

   ```text
   frontend/src/components/LineViewLayer.tsx
   ```

   For `five_station_circle_cw*`, render station points on a closed circle
   instead of an open horizontal line.

9. Extend export helpers that depend on `lineViewPoints` and `lineArcId` so the
   closing `E -> A` arc is available in line/schematic exports.

10. Regenerate artifacts after implementation with the export CLI.

## Test Plan

Add:

```text
tests/test_examples_five_station_circle.py
```

Test the following:

- the scenarios validate
- the examples are registered
- each scenario has five service stations and zero terminal stations
- each scenario has 20 OD demand groups
- no-skip/no-wait variants have no skip routes
- skip/no-wait variant has five skip routes
- the EAN config sets all station waiting modes to `NO_WAITING`
- switch cycle equals `A, B, C, D, E`
- switch cycle is physically closed through the rope segment `E_exit_cw_to_A_entry_cw`
- the EAN artifact builds
- the full example uses all max start cabins
- half examples use every second max start cabin

Run:

```bash
uv run pytest tests/test_examples_five_station_circle.py
uv run pytest tests/test_examples_five_station.py tests/test_export_scenarios.py
```

## Export Commands

After implementation, generate artifacts from the repository root.

No-skip no-wait:

```bash
uv run python -m ropeway_skip_stop_optimization.exports.cli \
  --example five_station_circle_cw_full_no_skip_no_wait_v0 \
  --artifact-set ean_all_stop_baseline \
  --output-root frontend/public/generated/examples \
  --progress
```

Half no-skip no-wait:

```bash
uv run python -m ropeway_skip_stop_optimization.exports.cli \
  --example five_station_circle_cw_half_no_skip_no_wait_v0 \
  --artifact-set physical_only \
  --output-root frontend/public/generated/examples \
  --progress
```

Half skip no-wait:

```bash
uv run python -m ropeway_skip_stop_optimization.exports.cli \
  --example five_station_circle_cw_half_skip_no_wait_v0 \
  --artifact-set physical_only \
  --output-root frontend/public/generated/examples \
  --progress
```

Half skip wait:

```bash
uv run python -m ropeway_skip_stop_optimization.exports.cli \
  --example five_station_circle_cw_half_skip_wait_v0 \
  --artifact-set physical_only \
  --output-root frontend/public/generated/examples \
  --progress
```

## Assumptions

- `full cabins` means all starts generated by `ContinuousAllStopMaxCabinStartBuilder`.
- `half cabins` means every second start from the same max-start sequence.
- The circle is clockwise-only in this first version.
- Existing line examples and their labels remain unchanged.
- The EAN builder names containing `ring` remain unchanged because they describe
  the internal fixed switch cycle.
- Generated JSON files should be produced through the export CLI, not edited by
  hand.

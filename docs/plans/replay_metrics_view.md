# Replay Metrics View

Status: **implemented v1**

## Goal

Add a compact graph view for passenger replay metrics. The view should show when demand enters the system, how many passengers are waiting, how many are onboard/in transit, when passengers alight, and how total waiting time accumulates over the replay horizon.

This should be calculated in the Python replay layer and exported as static JSON. The frontend should only visualize the exported time series.

## Scope

v1 covers metrics for a completed `PassengerReplayResult` over a fixed `DiscreteScenario` and `MovementPlan`.

Included:

- incoming demand per time step
- boarded passengers per time step
- alighting passengers per time step
- current waiting passengers per time step
- current onboard passengers per time step
- cumulative total waiting time over time
- static JSON export for the three-station all-stop passenger replay
- frontend metrics view with SVG charts

Not included:

- new passenger behavior models
- walking/access times
- platform assignment models
- optimization decisions
- live backend
- per-passenger animation changes

For this project phase, demand is assumed to be immediately available for boarding at the relevant station queue once it arrives.

## Backend Design

Add a new module:

```text
src/ropeway_skip_stop_optimization/replay/metrics.py
```

Add models either in `models/replay.py` or in a dedicated model module if it grows. For v1, keeping them with replay models is acceptable.

Suggested dataclasses:

```python
@dataclass(frozen=True)
class ReplayMetricsStep:
    time_step: int
    arrivals_count: int
    boarding_count: int
    alighting_count: int
    waiting_count: int
    onboard_count: int
    cumulative_waiting_passenger_hours: float
    waiting_by_station: tuple[PassengerStationMetric, ...]
    onboard_by_od: tuple[PassengerOdMetric, ...]


@dataclass(frozen=True)
class ReplayMetrics:
    discrete_scenario_id: str
    movement_plan_horizon_steps: int
    delta_seconds: float
    steps: tuple[ReplayMetricsStep, ...]
```

Supporting aggregate rows:

```python
@dataclass(frozen=True)
class PassengerStationMetric:
    station_id: str
    count: int


@dataclass(frozen=True)
class PassengerOdMetric:
    origin: str
    destination: str
    count: int
```

`waiting_by_station` and `onboard_by_od` should be exported in v1 even if the first chart only plots totals. They are valuable for tooltips and debugging bottlenecks.

## Metric Semantics

For each `time_step`:

`arrivals_count`

- sum of all `DiscreteDemand.count` where `demand.time_step == time_step`
- represents passengers newly entering station queues at that step

`boarding_count`

- sum of `BoardingEvent.count` in `ReplayStepState.boarding_events`
- useful for checking throughput but not required as a primary chart series

`alighting_count`

- sum of `AlightingEvent.count` in `ReplayStepState.alighting_events`
- shown as bars on the chart

`waiting_count`

- sum of `PassengerQueueState.waiting_count` in `ReplayStepState.queue_states`
- current passengers waiting in station queues after that step's replay processing

`onboard_count`

- sum of `CabinLoadState.load_count` in `ReplayStepState.cabin_loads`
- current passengers in transit after that step's replay processing

`cumulative_waiting_passenger_hours`

- running integral of queue length over time
- update rule per step: `cumulative += waiting_count * delta_seconds / 3600`
- includes passengers who are still waiting at the end of the horizon
- displayed in the frontend as passenger-hours

Important: this is intentionally different from the current replay summary field `total_waiting_steps`, which only counts completed waiting time at boarding. The graph view needs operational waiting already accumulated by all currently waiting passengers, including passengers who might never board.

`waiting_by_station`

- aggregate `ReplayStepState.queue_states` by `station_id`
- used in the tooltip and later for station-level queue charts

`onboard_by_od`

- aggregate all `CabinLoadState.onboard_groups` by `(origin, destination)`
- used in the tooltip and later for OD-level in-transit charts

## Export Contract

Add export artifact builder in `exports/artifacts.py`:

```python
def export_three_station_greedy_all_stop_replay_metrics(output_dir: Path) -> Path:
    ...
```

Output filename:

```text
three_station_v0__dt_0p5__greedy_all_stop_replay_metrics.json
```

JSON shape:

```json
{
  "discrete_scenario_id": "three_station_v0__dt_0p5",
  "movement_plan_horizon_steps": 2400,
  "delta_seconds": 0.5,
  "steps": [
    {
      "time_step": 0,
      "arrivals_count": 3480,
      "boarding_count": 0,
      "alighting_count": 0,
      "waiting_count": 3480,
      "onboard_count": 0,
      "cumulative_waiting_passenger_hours": 0.48333333333333334,
      "waiting_by_station": [
        { "station_id": "L", "count": 1160 },
        { "station_id": "M", "count": 1160 },
        { "station_id": "R", "count": 1160 }
      ],
      "onboard_by_od": []
    }
  ]
}
```

The export command should write this file together with the existing scenario, discrete scenario, movement plan, and passenger replay JSON.

## Frontend Design

Add a new top-level view next to:

- `Scenario View`
- `Graph View`
- `Replay View`

Suggested name:

```text
Metrics View
```

Data loading:

- `App.tsx` loads the new metrics JSON from `frontend/public/scenarios`.
- If the metrics file fails to load, show a compact warning panel and keep the other views working.

Components:

```text
MetricsView
ReplayMetricsChart
MetricsTooltip
MetricsSummaryPanel
```

v1 chart:

- x-axis: replay time / time step
- bars:
  - arrivals
  - alightings
- tooltip-only or optional thin bars:
  - boardings
- lines:
  - waiting_count
  - onboard_count
  - cumulative waiting time

Because `cumulative_waiting_passenger_hours` can be much larger than passenger counts, either:

- use a separate right-side axis for cumulative passenger-hours, or
- normalize it visually and show exact values in the tooltip.

Recommendation for v1:

- left axis: passenger counts
- right axis: cumulative passenger-hours
- all steps remain in JSON
- frontend may downsample or aggregate only for SVG rendering density

Tooltip should show:

- time step
- clock time
- arrivals
- boardings
- alightings
- waiting
- waiting by station
- onboard
- onboard by OD
- cumulative waiting passenger-hours

## Visual Style

The view should feel like a technical operations chart, not a marketing dashboard.

Use:

- dense but readable SVG
- muted grid lines
- clear legend
- restrained colors
- hover crosshair
- stable chart dimensions

Avoid:

- decorative cards inside cards
- oversized hero-style typography
- generic analytics gradients
- viewport-scaled fonts

## Tests

Backend tests:

- metrics length equals `horizon_steps + 1`
- step `0` arrivals equals total demand for the current near-capacity example
- cumulative waiting passenger-hours is monotonic
- final `cumulative_waiting_passenger_hours` includes current queue waiting over the full horizon, not only boarded passengers
- final `waiting_count` equals replay summary `unserved_passengers`
- final `onboard_count` equals replay summary `onboard_passengers`
- `waiting_by_station` sums to `waiting_count`
- `onboard_by_od` sums to `onboard_count`
- exported JSON contains required top-level keys and at least one nonzero arrival/alighting step

Frontend checks:

- metrics JSON loads
- Metrics View renders without runtime errors
- chart shows arrivals at step `0`
- chart shows nonzero waiting after step `0`
- chart shows alighting bars later in the horizon
- tooltip or hover state shows exact values
- build passes with `npm run build`

Visual QA:

- desktop viewport: labels/legend readable, no overlap
- narrow viewport: chart remains usable through horizontal scroll or stacked layout

## Implementation Order

1. Add replay metrics dataclasses and calculation function.
2. Add backend tests for aggregate metrics.
3. Add export function and export tests.
4. Regenerate static JSON exports.
5. Add frontend types for metrics JSON.
6. Add `Metrics View` tab and load the metrics file.
7. Implement v1 SVG chart with bars and lines.
8. Run Python tests, frontend build, and browser smoke test.

## Open Questions

- Should `boarding_count` be visible in v1 or only in tooltip?
- What downsampling strategy should the frontend use once scenarios become larger than the current 2,401-step example?
- Should later views add station-level queue series beyond the tooltip breakdown?

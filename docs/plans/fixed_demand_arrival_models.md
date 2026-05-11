# Fixed Demand Arrival Models

Status: v0 implemented for fixed arrival accumulation. Boarding and alighting are still not implemented.

## Goal

Model passenger demand in the simplest useful way:

- passengers arrive as fixed OD batches at a fixed clock time
- no stochastic arrivals
- no arrival rates or time windows
- no individual passenger objects yet
- no boarding, alighting, queue clearing, or waiting-time optimization yet

This is enough to visualize demand in the physical scenario and later feed a replay evaluator.

## Current State

The physical scenario already has fake demand events in `build_three_station_scenario()`:

```text
08:01  L -> R  6 passengers
08:02  L -> M  4 passengers
08:03  M -> R  5 passengers
08:04  R -> L  6 passengers
08:05  R -> M  3 passengers
08:06  M -> L  4 passengers
08:08  L -> R  5 passengers
08:09  R -> L  5 passengers
```

The current domain model is already the right v0 shape:

```python
@dataclass(frozen=True)
class Demand:
    arrival_time: time
    origin: str
    destination: str
    count: int
```

The current discrete model is also already the right v0 shape:

```python
@dataclass(frozen=True)
class DiscreteDemand:
    time_step: int
    origin: str
    destination: str
    count: int
```

## Model Boundary

Keep the model layers separate:

```text
Scenario Demand
  clock-time OD demand input

Discrete Demand
  same OD demand converted to integer time steps

Replay Demand State
  derived state: queues, served counts, waiting time, backlog
```

`Scenario` and `DiscreteScenario` should store demand input only. They should not store replay results.

## Domain Model: `Demand`

Use `Demand` for fixed arrivals.

Rules:

- `arrival_time` is a `datetime.time`
- `origin` and `destination` reference `Station.id`
- `origin != destination`
- `count > 0`
- `arrival_time` lies inside the service window
- only passenger stations may be origins or destinations
- demand does not encode route direction
- demand does not decide whether a cabin goes service or skip

No new model is needed for rates yet. Avoid names like `DemandFlow` until we actually model flow over an interval.

### Demand Identity

For now, `Demand` does not need an explicit `id`.

If the frontend or replay logs need stable event identity, derive it from scenario order:

```text
demand::0
demand::1
demand::2
```

Only add `Demand.id` if we need to edit, select, or compare demand events as first-class objects.

## Discrete Model: `DiscreteDemand`

`DiscreteDemand` is an arrival event in discrete time.

Conversion:

```text
time_step = (arrival_time - service_start_time) / delta_seconds
```

For v0, demand times should be exactly representable by `delta_seconds`. If not, raise instead of silently rounding. This is different from segment-duration rounding, where conservative `ceil` is acceptable.

Rules:

- `0 <= time_step <= horizon_steps`
- `origin` and `destination` still reference `Station.id`
- `count > 0`
- no route direction
- no assigned cabin
- no boarding decision

## Replay Input Models

The first replay evaluator should consume:

```text
DiscreteScenario.demands
MovementPlan.trajectories
DiscreteScenario.cabin_capacity
```

It should not mutate either `DiscreteScenario` or `MovementPlan`.

## Replay Output Models

When we start evaluating demand in replay, add separate replay models. These are outputs, not scenario inputs.

### `PassengerQueueState`

Suggested shape:

```python
@dataclass(frozen=True)
class PassengerQueueState:
    time_step: int
    station_id: str
    destination: str
    waiting_count: int
```

Meaning:

- aggregated queue count at a station for one destination
- no individual passenger identities
- can be emitted for every time step or only when the count changes

### `DemandArrivalEvent`

This may be derived from `DiscreteDemand` for replay logs:

```python
@dataclass(frozen=True)
class DemandArrivalEvent:
    demand_index: int
    time_step: int
    origin: str
    destination: str
    count: int
```

This is useful for frontend timelines, but it does not need to replace `DiscreteDemand`.

### Later, Not Now

Do not implement these in the first demand step:

- individual `Passenger`
- passenger route choice
- priority classes
- stochastic demand generation
- missed-boarding logic
- exact waiting-time metrics per passenger
- optimizer assignment of demand to cabins

## First Replay Semantics

For the first version, replay demand can be purely cumulative:

1. At each time step, add all `DiscreteDemand` events whose `time_step` equals the current step.
2. Aggregate queues by `(origin, destination)`.
3. Display the queue state in the frontend.
4. Do not board passengers yet.
5. Do not reduce queues yet.

Example:

```text
step 120: +6 L -> R
step 240: +4 L -> M
step 360: +5 M -> R
```

With `delta_seconds = 0.5`, one minute equals 120 steps.

## Frontend Contract

The existing scenario JSON already contains physical demand:

```json
{
  "arrival_time": "08:01",
  "origin": "L",
  "destination": "R",
  "count": 6
}
```

The discrete scenario JSON already contains discrete demand:

```json
{
  "time_step": 120,
  "origin": "L",
  "destination": "R",
  "count": 6
}
```

For the first replay demand overlay, the frontend can compute cumulative queues directly from `DiscreteDemand` and the current replay step:

```text
waiting(origin, destination, step)
  = sum(count for demand where demand.time_step <= step)
```

This is deliberately naive because boarding is not modeled yet.

## Frontend Presentation

Use one shared demand summary component for both static scenario demand and replay demand queues.

Implemented component:

```text
frontend/src/components/DemandSummaryPanel.tsx
```

Display rules:

- title stays `Demand`
- header shows total passenger count as `{total} pax`
- each OD pair is shown as one row
- row layout is:

```text
origin -> destination                 count
first_time-last_time
```

- the static Scenario View uses all physical `Scenario.demands`
- the Replay View uses cumulative queues derived from `DiscreteScenario.demands` up to the current step
- Replay View may show a small highlighted arrival row above the summary rows when demand arrives exactly at the current step

Example in Replay View at step `120`:

```text
+6 L -> R                             08:01

L -> R                                6
08:01
```

This keeps the visual language identical between the normal Demand panel and the time-dependent Replay demand panel.

## Validation

Domain validation should continue to check:

- demand origin exists
- demand destination exists
- origin and destination are passenger stations, not storage
- origin and destination differ
- count is positive
- arrival time lies inside service window

Discrete validation should continue to check:

- demand step lies inside horizon
- origin and destination exist
- origin and destination differ
- count is positive

Future replay validation should check:

- every demand destination is reachable by at least one service route in the movement plan
- boarding is only allowed where `allows_boarding=True`
- alighting is only allowed where `allows_alighting=True`
- cabin load never exceeds capacity

## Implementation Order

1. Keep current `Demand` and `DiscreteDemand` models unchanged. Done.
2. Add a small replay demand accumulator that derives queue counts from `DiscreteScenario.demands`. Done.
3. Show cumulative queue counts in Replay View for the current time step. Done.
4. Add tests for demand accumulation at steps `0`, `120`, `240`, and after the last fake demand. Done.
5. Reuse the existing demand summary design for Replay demand queues. Done.
6. Only after that, decide how boarding and alighting should consume queues. Not yet implemented.

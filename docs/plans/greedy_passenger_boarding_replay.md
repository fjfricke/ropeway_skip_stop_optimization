# Greedy Passenger Boarding Replay

Status: v0 implemented for `GREEDY_FIFO_NEXT_COMPATIBLE_CABIN`. Other boarding policies are not implemented yet.

## Goal

Add the first passenger-serving replay model:

- passengers arrive from fixed `DiscreteDemand` events
- passengers wait in station waiting pools with destination metadata
- cabins follow an existing `MovementPlan`
- passengers board according to a configurable boarding policy
- the first example policy boards greedily into the next available cabin that can serve their destination
- each cabin boards passengers until it is full, then remaining passengers wait for the next suitable cabin
- passengers alight when the cabin reaches their destination
- no optimizer decisions yet

This is an evaluator over a fixed movement plan. It must not change cabin paths.

## Core Semantics

At each time step:

1. Add all demand arrivals at this step to station waiting pools.
2. For every cabin at its current node:
   - if the node allows alighting, unload passengers whose destination is this station
   - if the node allows boarding, ask the active boarding policy which waiting passengers from this station should board this cabin
3. Record events and snapshot state.

Ordering inside one time step:

```text
demand arrivals
alighting
boarding
snapshot
```

Reasoning:

- demand arriving at a step should be allowed to board a cabin that is available at that same step
- alighting before boarding frees capacity
- snapshot after boarding is what the frontend should display for that step

## Meaning Of "Right Direction"

Do not encode direction directly in `Demand`.

A cabin is in the right direction for a passenger if:

```text
from the cabin's current movement-plan position,
following that cabin's future trajectory,
the cabin reaches an alighting-capable node at the passenger destination
before it reaches an alighting-capable node at the passenger origin again
```

This makes the rule future proof:

- works for `L -> M -> R -> M -> L`
- works for ring lines where the intuitive left/right direction is not enough
- works when skip paths bypass a station
- works when optimized paths differ by cabin
- works when a cabin waits at a platform

For the current all-stop baseline, this will naturally board `L -> R` passengers into cabins moving from `L` toward `M/R`, not cabins that just returned toward the opposite side.

## Existing Inputs

Use current models unchanged:

```python
DiscreteScenario.demands
DiscreteScenario.nodes
DiscreteScenario.cabin_capacity
MovementPlan.trajectories
```

Required node flags already exist:

```python
DiscreteNode.station_id
DiscreteNode.allows_boarding
DiscreteNode.allows_alighting
```

No changes to `Demand` or `DiscreteDemand` are needed.

## New Replay Models

Add these to `models/replay.py`.

### `PassengerBatch`

Use aggregate batches, not individual passengers.

```python
@dataclass(frozen=True)
class PassengerBatch:
    batch_id: str
    demand_index: int
    origin: str
    destination: str
    arrival_step: int
    count: int
```

Rules:

- one initial batch per `DiscreteDemand`
- batch ids can be derived as `demand::{index}`
- batches may be split during boarding
- `count` is always positive

Why batches instead of passengers:

- keeps replay compact
- still supports exact waiting-time metrics for fixed-arrival batches
- supports partial boarding by splitting counts
- can be refined to individual passengers later without changing high-level replay semantics

### `QueueItem`

Mutable implementation can use this internally, but exported snapshots should stay immutable.

```python
@dataclass(frozen=True)
class QueueItem:
    batch_id: str
    demand_index: int
    origin: str
    destination: str
    arrival_step: int
    remaining_count: int
```

Internal waiting pools are keyed by station:

```text
station_id
```

Each station waiting pool contains `QueueItem`s with destination and arrival metadata.

The general replay model must not require FIFO. It only stores enough information for policies to make ordering decisions:

- `arrival_step`
- `demand_index`
- `origin`
- `destination`
- `remaining_count`

Public queue snapshots can still be aggregated by `(station_id, destination)`.

### `OnboardPassengerGroup`

Represents passengers currently inside one cabin.

```python
@dataclass(frozen=True)
class OnboardPassengerGroup:
    batch_id: str
    demand_index: int
    origin: str
    destination: str
    arrival_step: int
    boarded_step: int
    count: int
```

Rules:

- `count > 0`
- all passengers in a group share the same origin, destination, arrival step, and boarding step
- cabin load is the sum of onboard group counts

### `CabinLoadState`

Snapshot of a cabin's passenger load at a step.

```python
@dataclass(frozen=True)
class CabinLoadState:
    time_step: int
    cabin_id: int
    node_id: str
    onboard_groups: tuple[OnboardPassengerGroup, ...]
```

Derived properties can be helper functions:

```python
load_count(state) -> int
free_capacity(state, cabin_capacity) -> int
```

Do not store `free_capacity` unless frontend export needs it.

### `PassengerQueueState`

The existing `PassengerQueueState` is still useful, but it should become the public aggregate snapshot:

```python
@dataclass(frozen=True)
class PassengerQueueState:
    time_step: int
    station_id: str
    destination: str
    waiting_count: int
```

Internally, we need queue items to preserve arrival metadata for policy decisions and waiting-time metrics. Public snapshots can remain aggregated.

### `BoardingEvent`

```python
@dataclass(frozen=True)
class BoardingEvent:
    time_step: int
    cabin_id: int
    station_id: str
    destination: str
    batch_id: str
    count: int
    waiting_steps: int
```

Rules:

- emitted when passengers board
- `waiting_steps = time_step - arrival_step`
- may be emitted multiple times for one demand batch if it is split across cabins

### `AlightingEvent`

```python
@dataclass(frozen=True)
class AlightingEvent:
    time_step: int
    cabin_id: int
    station_id: str
    batch_id: str
    count: int
    onboard_steps: int
```

Rules:

- emitted when passengers leave a cabin at their destination
- `onboard_steps = time_step - boarded_step`

### `ReplayStepState`

Optional but useful for frontend exports and tests:

```python
@dataclass(frozen=True)
class ReplayStepState:
    time_step: int
    queue_states: tuple[PassengerQueueState, ...]
    cabin_loads: tuple[CabinLoadState, ...]
    boarding_events: tuple[BoardingEvent, ...]
    alighting_events: tuple[AlightingEvent, ...]
```

For large horizons, we may not want to export every step forever. v0 can emit every step because the current scenario is small.

### `ReplayResult`

```python
@dataclass(frozen=True)
class ReplayResult:
    discrete_scenario_id: str
    movement_plan_horizon_steps: int
    steps: tuple[ReplayStepState, ...]
    boarding_events: tuple[BoardingEvent, ...]
    alighting_events: tuple[AlightingEvent, ...]
    final_queue_states: tuple[PassengerQueueState, ...]
    final_cabin_loads: tuple[CabinLoadState, ...]
```

Keep events both per step and flat if useful. If duplication becomes annoying, store flat events and derive per-step views in frontend/export.

## Boarding Policy

Add a small policy object or enum. Do not hard-code FIFO or any other ordering into replay internals.

```python
class BoardingPolicyKind(Enum):
    GREEDY_FIFO_NEXT_COMPATIBLE_CABIN = "greedy_fifo_next_compatible_cabin"
```

Potential config:

```python
@dataclass(frozen=True)
class ReplayConfig:
    boarding_policy: BoardingPolicyKind = BoardingPolicyKind.GREEDY_FIFO_NEXT_COMPATIBLE_CABIN
    allow_same_step_demand_boarding: bool = True
    alight_before_board: bool = True
```

This keeps room for later:

- no boarding
- reservation-based boarding
- priority boarding
- optimizer-provided assignment
- stochastic passenger behavior
- non-FIFO heuristics

## Example Policy: Greedy FIFO Next Compatible Cabin

This is only the first example/baseline policy. It is not part of the general model.

At a time step, process cabins in deterministic order:

```text
movement_plan.trajectories order, then cabin_id as a tie breaker if needed
```

For each cabin at a boarding-capable station, this policy does:

1. Compute free capacity.
2. Sort the station's waiting items by `arrival_step`, then `demand_index`.
3. Scan those waiting items from oldest to newest.
4. For each queue item:
   - check whether this cabin can alight at that item's destination in its future trajectory before returning to the origin
   - if not reachable, leave the item in the waiting pool
   - if reachable, board as many passengers as possible from that item
   - if the item is partially boarded, keep the remainder in the waiting pool
5. Stop when the cabin is full or no compatible waiting passengers remain.

This matches “next available cabin”:

- time order decides which cabin gets passengers first
- FIFO order is only this policy's passenger-selection rule
- capacity stops boarding when full
- incompatible destinations are skipped without removing them from the waiting pool

Important: A cabin should not board passengers for a destination it will only reach after passing the same origin again. That would be the wrong direction for the current cycle.

Future policies can use the same waiting pool but choose differently:

- prioritize a destination
- maximize cabin fill
- avoid splitting groups
- balance OD waiting times
- use optimizer-provided assignments
- reserve seats for downstream stations

## Direction / Reachability Helper

Add a helper, probably in `replay/routing.py` or `replay/passengers.py`:

```python
def can_cabin_serve_destination_from_step(
    discrete_scenario: DiscreteScenario,
    trajectory: CabinTrajectory,
    time_step: int,
    origin_station_id: str,
    destination_station_id: str,
) -> bool:
    ...
```

Algorithm:

1. Starting after or at `time_step`, scan the cabin trajectory forward.
2. Look at nodes with `allows_alighting=True`.
3. If station is `destination_station_id`, return `True`.
4. If station is `origin_station_id` and this is not the current boarding node, return `False`.
5. Stop after at most one path cycle or at horizon end.

For cyclic plans, we may need trajectory wrapping. In v0, the exported `MovementPlan` already covers the horizon, so scanning until horizon is enough for the fixed replay. Later, add path-cycle metadata if we need infinite periodic replay.

## Replay Function Shape

Add a new function:

```python
def replay_passenger_boarding(
    discrete_scenario: DiscreteScenario,
    movement_plan: MovementPlan,
    config: ReplayConfig | None = None,
) -> ReplayResult:
    ...
```

Expected behavior:

- validate movement plan first
- initialize empty station waiting pools and empty cabin loads
- iterate `time_step` from `0` to `movement_plan.horizon_steps`
- add arrivals
- process alighting
- process boarding
- emit step state

Do not put this into `baselines/`; it is not a plan producer. It belongs under `replay/`.

## Metrics

Initial metrics can be derived from `ReplayResult`:

```python
served_passengers = sum(event.count for event in alighting_events)
boarded_passengers = sum(event.count for event in boarding_events)
unserved_passengers = sum(state.waiting_count for state in final_queue_states)
total_waiting_steps = sum(event.count * event.waiting_steps for event in boarding_events)
average_waiting_seconds = total_waiting_steps * delta_seconds / boarded_passengers
max_waiting_steps = max(event.waiting_steps for event in boarding_events)
```

For passengers still waiting at the end, define separately:

```text
backlog_waiting_steps_at_horizon
```

Do not mix served-passenger average waiting time with final backlog unless a metric name explicitly says so.

## Frontend Export Contract

The replay JSON should later include passenger replay output separately from `MovementPlan`.

Suggested file:

```text
three_station_v0__dt_0p5__greedy_all_stop_passenger_replay.json
```

Suggested shape:

```json
{
  "discrete_scenario_id": "three_station_v0__dt_0p5",
  "movement_plan_id": "greedy_all_stop",
  "boarding_policy": "greedy_fifo_next_compatible_cabin",
  "steps": [
    {
      "time_step": 120,
      "queue_states": [],
      "cabin_loads": [],
      "boarding_events": [],
      "alighting_events": []
    }
  ],
  "summary": {
    "boarded_passengers": 0,
    "served_passengers": 0,
    "unserved_passengers": 0
  }
}
```

The frontend should keep `MovementPlan` and passenger replay as separate inputs:

```text
MovementPlan = where cabins are
PassengerReplay = what passengers did
```

This lets us compare different passenger policies on the same cabin movement plan.

## Validation

Replay validation should check:

- movement plan validates against the discrete scenario
- every demand destination is reachable by at least one compatible cabin during the replay horizon, or report unreachable backlog
- boarding happens only at nodes with `allows_boarding=True`
- alighting happens only at nodes with `allows_alighting=True`
- no cabin load exceeds `DiscreteScenario.cabin_capacity`
- no passenger alights at a station other than their destination
- all boarded counts originate from prior or same-step demand
- final accounting balances:

```text
arrived = waiting_at_end + onboard_at_end + served
```

## First Test Cases

Backend tests:

1. At step `120`, `L -> R` demand arrives and boards the next compatible cabin if free capacity exists.
2. A cabin with no future alighting at `R` before returning to `L` must not board `L -> R` passengers.
3. Capacity is enforced:
   - if 11 passengers wait and capacity is 8, first compatible cabin boards 8, next compatible cabin boards 3.
4. Alighting frees capacity before boarding at the same station and step.
5. Accounting balances at horizon end.
6. Skip paths do not count as destination service because skip nodes do not allow alighting.

Frontend tests / QA:

1. Replay panel shows waiting queues decreasing after boarding.
2. Cabin inspector shows current load and onboard destinations.
3. Timeline step with boarding shows a boarding event.
4. Timeline step with alighting shows an alighting event.

## Implementation Order

1. Add replay dataclasses for passenger batches, cabin loads, boarding/alighting events, and replay result. Done.
2. Add reachability helper for “right direction”. Done.
3. Implement greedy boarding replay. Done for `GREEDY_FIFO_NEXT_COMPATIBLE_CABIN`.
4. Add backend tests for demand arrival, boarding, capacity split, alighting, and accounting. Done.
5. Export passenger replay JSON for `three_station_v0`. Done.
6. Extend frontend types. Done.
7. Show passenger replay in Replay View. Done:
   - queue counts after boarding
   - cabin load in cabin inspector
   - recent boarding/alighting events
8. Add non-FIFO policies. Not yet implemented.
9. Add frontend controls to switch passenger policies. Not yet implemented.

# Simple Cabin Circulation Baseline Plan

Status: **partially implemented**

Implemented now:

- generic movement/replay models:
  - `DiscretePath`
  - `CabinPosition`
  - `CabinTrajectory`
  - `MovementPlan`
- reusable `validate_movement_plan(...)`
- greedy all-stop circulation baseline
- tests for all-stop cycle construction, skip exclusion, greedy placement, and movement-plan validation

Not implemented yet:

- frontend replay animation
- plan JSON export
- passenger boarding/alighting
- optimizer-generated plans

## Purpose

Build the first simple cabin circulation scenario on top of the existing discrete graph.

This is not an optimizer yet.

The goal is to produce a deterministic baseline plan where cabins:

- never use skip sections
- are greedily placed on the all-stop loop without touching headway conflicts
- keep driving around the loop forever

This gives us a minimal replayable cabin movement model before adding MILP, passenger assignment, skip decisions, or waiting optimization.

## Scope

In scope:

- fixed all-stop route through the current physical scenario
- greedy initial cabin placement on the discrete all-stop cycle
- deterministic movement by one move arc per time step
- validation against existing discrete headway constraints
- output a simple `Plan` or replay trace

Out of scope:

- skip routes
- passenger demand satisfaction
- boarding/alighting
- optimizer decisions
- dynamic dispatch from storage
- waiting optimization
- station dwell time decisions

## All-Stop Cycle

Cabins should follow exactly this segment cycle:

```text
L_exit_lr_to_M_entry_lr
M_service_lr
M_exit_lr_to_R_entry_lr
R_service_turnaround
R_exit_rl_to_M_entry_rl
M_service_rl
M_exit_rl_to_L_entry_rl
L_service_turnaround
```

Expanded into physical segments:

```text
L_exit_lr_to_M_entry_lr
M_lr_approach_fast
M_lr_brake
M_lr_platform
M_lr_accelerate
M_lr_depart_fast
M_exit_lr_to_R_entry_lr
R_turnaround_decelerate
R_turnaround_platform
R_turnaround_accelerate
R_exit_rl_to_M_entry_rl
M_rl_approach_fast
M_rl_brake
M_rl_platform
M_rl_accelerate
M_rl_depart_fast
M_exit_rl_to_L_entry_rl
L_turnaround_decelerate
L_turnaround_platform
L_turnaround_accelerate
```

Skip segments are deliberately excluded:

```text
M_lr_skip_bypass
M_rl_skip_bypass
```

## Discrete Cycle Construction

Use `DiscreteScenario.arcs` to build an ordered list of move arcs for the all-stop cycle.

For each physical segment in cycle order:

- find all `DiscreteArc(kind=MOVE)` with `source_segment_id == segment_id`
- sort by their step suffix
- append to cycle arc list

The resulting cycle should be closed:

```text
last_arc.to_node_id == first_arc.from_node_id
```

The ordered cycle nodes can be derived as:

```text
cycle_nodes = [first_arc.from_node_id] + [arc.to_node_id for arc in cycle_arcs]
```

The final duplicate closing node can be omitted for modular indexing.

## Greedy Cabin Placement

Input:

- `DiscreteScenario`
- ordered all-stop cycle nodes
- number of cabins, initially from `Scenario.cabins`

Greedy placement idea:

1. Start with an empty placement list.
2. Iterate candidate positions along the cycle in order.
3. Place a cabin at the first candidate node that does not conflict with already placed cabins.
4. Continue until all cabins are placed or no feasible position remains.

Conflict test:

```text
candidate is feasible if:
  for every placed_node:
    (candidate, placed_node) is not a headway constraint pair
```

Use existing `DiscreteConstraint(kind=HEADWAY)` pairs.

Important:

- physical node backed positions count too
- endpoint headway constraints count too
- skip nodes are not considered because the all-stop cycle excludes skip arcs

## Movement Rule

After placement, every cabin advances one cycle index per time step:

```text
position_index[t + 1] = (position_index[t] + 1) % len(cycle_nodes)
```

For this first baseline:

- no waiting
- no branching
- no skip
- no route choice
- all cabins move synchronously

This is intentionally simple.

If greedy placement respects all pairwise conflicts at time `t = 0`, synchronous movement around one fixed cycle should preserve relative spacing along the same cycle. We should still validate every generated time step because cross-segment constraints and duplicated physical nodes can reveal modeling mistakes.

## Replay Horizon

Use the discrete scenario horizon:

```text
horizon_steps = discrete_scenario.horizon_steps
```

For early testing, it may be useful to support a shorter override such as:

```text
max_steps = 240
```

This lets us replay two minutes at `delta_seconds = 0.5`.

## Reusable Output Models

The baseline should not introduce a long-lived `CabinCirculationPlan` model that only fits this simple case.

Instead, add generic movement/replay models that can also be produced later by:

- greedy baselines
- handcrafted replay examples
- MILP solutions
- heuristic or repair algorithms

### DiscretePath

A `DiscretePath` is an ordered path through the discrete graph.

For this baseline, the all-stop cycle is one `DiscretePath`.

Later, paths can represent:

- service alternatives
- skip alternatives
- depot dispatch paths
- repositioning paths
- optimizer-selected route fragments

Suggested model:

```python
@dataclass(frozen=True)
class DiscretePath:
    id: str
    arc_ids: tuple[str, ...]
    node_ids: tuple[str, ...]
    source_segment_ids: tuple[str, ...] = ()
    source_route_ids: tuple[str, ...] = ()
```

Validation should check:

- every arc exists
- every node exists
- arc sequence is connected
- `node_ids` matches the arc chain

### CabinPosition

A `CabinPosition` records where a cabin is at one discrete time step.

Suggested model:

```python
@dataclass(frozen=True)
class CabinPosition:
    time_step: int
    node_id: str
    incoming_arc_id: str | None = None
```

`incoming_arc_id` is optional because at `time_step = 0` there is no incoming movement.

For replay, `node_id` is the main state.

For validation/debugging, `incoming_arc_id` explains how the cabin got there.

### CabinTrajectory

A `CabinTrajectory` is the full planned movement of one cabin.

Suggested model:

```python
@dataclass(frozen=True)
class CabinTrajectory:
    cabin_id: int
    positions: tuple[CabinPosition, ...]
```

Validation should check:

- every time step appears exactly once for the chosen horizon
- time steps are contiguous
- transitions between consecutive positions follow a valid move or wait arc

### MovementPlan

A `MovementPlan` is the generic output object.

The greedy all-stop circulation baseline should return this type.

Later, a MILP solution should also be converted into this same type.

Suggested model:

```python
@dataclass(frozen=True)
class MovementPlan:
    discrete_scenario_id: str
    horizon_steps: int
    trajectories: tuple[CabinTrajectory, ...]
    paths: tuple[DiscretePath, ...] = ()
```

The plan should stay method-neutral.

Do not encode `greedy`, `all_stop`, or `optimizer` as required core fields.

Those belong to builder metadata or filenames, not the reusable model.

## Plan Validation

Add validation as separate logic:

```python
validate_movement_plan(plan: MovementPlan, scenario: DiscreteScenario) -> None
```

This should be reusable for every future plan producer.

Validate:

- `plan.discrete_scenario_id == scenario.id`
- every cabin exists if cabins are mapped, or every cabin id is unique if cabins are generated externally
- every `node_id` exists in the `DiscreteScenario`
- every `incoming_arc_id` exists when present
- every transition follows a valid move or wait arc
- no two cabins occupy the same node at the same time
- no two cabins occupy headway-conflicting nodes at the same time
- optional: no cabin uses a forbidden path/segment set

The simple baseline can call this validator after generating the plan.

This is the important reusable boundary:

```text
producer -> MovementPlan -> validator/replay/frontend
```

The producer can be greedy now and MILP later.

## Baseline Builder

The simple circulation code should be a producer of `MovementPlan`.

Suggested function:

```python
build_greedy_all_stop_circulation_plan(
    discrete_scenario: DiscreteScenario,
    cabin_ids: tuple[int, ...],
    horizon_steps: int,
) -> MovementPlan
```

Responsibilities:

- construct the all-stop `DiscretePath`
- greedily place cabins on that path
- generate synchronous one-step movement around the cycle
- return a `MovementPlan`
- validate the generated plan

The all-stop cycle and greedy placement stay in this builder.

They should not leak into the generic model names.

## Earlier Output Model Alternative

Reuse or extend `models/plan.py`.

Minimum useful output:

```python
@dataclass(frozen=True)
class CabinStep:
    cabin_id: int
    time_step: int
    node_id: str

@dataclass(frozen=True)
class CabinCirculationPlan:
    discrete_scenario_id: str
    cycle_node_ids: tuple[str, ...]
    steps: tuple[CabinStep, ...]
```

Alternatively, if existing `Plan` already has enough structure, build this as a helper that returns a `Plan`.

The preferred direction is now the generic `DiscretePath` + `CabinTrajectory` + `MovementPlan` structure above.

## Validation

Validate:

- every `node_id` exists in the `DiscreteScenario`
- every transition follows the next all-stop cycle move arc
- no cabin uses skip segment nodes
- no two cabins occupy the same node at the same time
- no two cabins occupy headway-conflicting nodes at the same time
- no cabin disappears before the horizon

The baseline should fail loudly if greedy placement cannot place all requested cabins.

## Tests

Add tests for:

- all-stop cycle is constructed and closed
- skip segments are absent from the cycle
- greedy placement places all example cabins
- initial placement has no headway conflicts
- generated movement remains valid for at least one full cycle
- generated movement validates for a short horizon, e.g. 240 steps

## Implementation Steps

1. Add a preprocessing or baseline module, e.g.

```text
src/ropeway_skip_stop_optimization/baselines/simple_circulation.py
```

2. Implement all-stop cycle arc extraction.
3. Implement greedy placement.
4. Implement deterministic synchronous movement.
5. Add validation helpers or integrate with existing `Plan.validate`.
6. Add tests.
7. Later export the generated plan for frontend replay.

## Known Limitations

- This baseline does not optimize capacity or service quality.
- It assumes all cabins keep moving every step.
- It does not model dwell time or passenger exchange.
- It ignores skips completely.
- It may underuse station waiting capacity.
- It is useful as a replay and validation baseline, not as an operational strategy.

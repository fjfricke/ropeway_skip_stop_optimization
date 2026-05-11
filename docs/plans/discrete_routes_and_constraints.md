# Discrete Routes And Constraint Semantics Plan

## Purpose

Improve `DiscreteScenario` so that it is useful for baseline plans and later MILP construction.

Two things are currently missing:

1. Explicit discrete route objects.
2. Rich constraint metadata.

Right now, route membership is only stored indirectly through `DiscreteArc.source_route_id`, and spacing constraints are represented as `DiscreteConflict(reason=HEADWAY)`.

That is enough for first graph construction, but too weak for:

- all-stop baseline generation
- route/skip decisions
- relaxed optimizer variants
- selectively disabling constraint groups
- debugging infeasible MILP models

## Goals

Add:

- explicit `DiscreteRoute`
- typed `DiscreteConstraint` or richer `DiscreteConflict`
- constraint `kind`, `scope`, and `strength`
- enough source metadata to filter constraints by origin

Do not add:

- Gurobi model code
- passenger replay
- cabin path plans
- exact switch constraints yet

## Discrete Routes

Add to `models/discrete_scenario.py`:

```python
@dataclass(frozen=True)
class DiscreteRoute:
    id: str
    source_route_id: str
    arc_ids: tuple[str, ...]
```

For v0:

- create one `DiscreteRoute` for each physical `StationRoute`
- route id can equal source route id for now
- route arc sequence is built by concatenating discrete movement arcs for each physical segment in route order
- no routes for main rope segments yet

Example:

```text
M_service_lr:
  M_lr_approach_fast      10 arcs
  M_lr_brake               8 arcs
  M_lr_platform           20 arcs
  M_lr_accelerate          8 arcs
  M_lr_depart_fast        10 arcs
  total                   56 arcs
```

`M_skip_lr`:

```text
M_lr_skip_bypass          28 arcs
```

Terminal turnaround:

```text
L_service_turnaround      8 + 20 + 8 = 36 arcs
R_service_turnaround      8 + 20 + 8 = 36 arcs
```

### Validation

`DiscreteRoute.validate()` should check:

- `arc_ids` is non-empty
- referenced arcs exist
- arc sequence is connected:

```text
arc[i].to_node_id == arc[i+1].from_node_id
```

`DiscreteScenario.validate()` should check:

- route ids are unique
- every `DiscreteRoute.source_route_id` references a physical station route
- all route arc ids exist
- each route arc sequence is connected

## Constraint Semantics

Current model:

```python
class DiscreteConflictReason(Enum):
    HEADWAY = "headway"
    SWITCH = "switch"
    SHARED_RESOURCE = "shared_resource"
```

This is too coarse.

Replace or extend it with:

```python
class DiscreteConstraintKind(Enum):
    NODE_OCCUPANCY = "node_occupancy"
    HEADWAY = "headway"
    SWITCH_OCCUPANCY = "switch_occupancy"
    SHARED_RESOURCE = "shared_resource"
    ROUTE_CONTINUITY = "route_continuity"


class DiscreteConstraintScope(Enum):
    SAME_NODE = "same_node"
    SAME_SEGMENT = "same_segment"
    CROSS_SEGMENT = "cross_segment"
    SWITCH = "switch"
    ROUTE = "route"


class DiscreteConstraintStrength(Enum):
    HARD = "hard"
    RELAXABLE = "relaxable"
```

### Naming Choice

Prefer renaming `DiscreteConflict` to `DiscreteConstraint` if the edit is still small enough.

Reason:

- not every future optimizer constraint is a pairwise conflict
- route continuity and assignment constraints are not naturally "conflicts"
- "constraint" matches later MILP terminology

However, if renaming causes too much churn, keep `DiscreteConflict` for pairwise occupancy conflicts and add richer fields first.

Recommended v0 compromise:

```python
@dataclass(frozen=True)
class DiscreteConstraint:
    id: str
    kind: DiscreteConstraintKind
    scope: DiscreteConstraintScope
    strength: DiscreteConstraintStrength
    node_ids: tuple[str, ...] = ()
    arc_ids: tuple[str, ...] = ()
    resource_id: str | None = None
    source_segment_ids: tuple[str, ...] = ()
    source_route_ids: tuple[str, ...] = ()
```

Then `DiscreteScenario` uses:

```python
constraints: tuple[DiscreteConstraint, ...]
```

instead of:

```python
conflicts: tuple[DiscreteConflict, ...]
```

This is a clean model, but it requires updating tests and existing code.

## Constraint Mapping In Discretizer

Same-segment headway:

```python
DiscreteConstraint(
    id="constraint::headway::same_segment::<node_a>::<node_b>",
    kind=DiscreteConstraintKind.HEADWAY,
    scope=DiscreteConstraintScope.SAME_SEGMENT,
    strength=DiscreteConstraintStrength.HARD,
    node_ids=(node_a_id, node_b_id),
    resource_id=segment.resource_id,
    source_segment_ids=(segment.id,),
)
```

Cross-segment headway:

```python
DiscreteConstraint(
    id="constraint::headway::cross_segment::<node_a>::<node_b>",
    kind=DiscreteConstraintKind.HEADWAY,
    scope=DiscreteConstraintScope.CROSS_SEGMENT,
    strength=DiscreteConstraintStrength.HARD,
    node_ids=(node_a_id, node_b_id),
    resource_id=None,
    source_segment_ids=(segment_a.id, segment_b.id),
)
```

For v0, all generated constraints are `HARD`.

Later relaxed optimizers can filter:

```python
without_cross_segment_headway = tuple(
    constraint
    for constraint in scenario.constraints
    if not (
        constraint.kind is DiscreteConstraintKind.HEADWAY
        and constraint.scope is DiscreteConstraintScope.CROSS_SEGMENT
    )
)
```

## Why Scope Matters

`HEADWAY` alone is insufficient.

Examples:

- same segment headway is relatively reliable
- cross segment headway is conservative near branches and merges
- switch occupancy will be a different physical rule
- shared resource constraints may represent station capacity or conveyor occupancy

A relaxed optimizer may keep same-segment headway but remove cross-segment headway to debug feasibility or speed.

Therefore at minimum we need:

```text
kind = HEADWAY
scope = SAME_SEGMENT | CROSS_SEGMENT
```

## Test Plan

Update `tests/test_discretize.py`.

Routes:

- every physical `StationRoute` has a matching `DiscreteRoute`
- `M_service_lr` has 56 arcs
- `M_skip_lr` has 28 arcs
- `L_service_turnaround` has 36 arcs
- every `DiscreteRoute` arc sequence is connected

Constraints:

- same-segment headway constraints exist with:

```text
kind = HEADWAY
scope = SAME_SEGMENT
```

- cross-segment headway constraints exist with:

```text
kind = HEADWAY
scope = CROSS_SEGMENT
```

- the known pair:

```text
seg::L_turnaround_accelerate::7
seg::L_exit_lr_to_M_entry_lr::1
```

is a cross-segment headway constraint.

- the known same-segment pair:

```text
seg::L_turnaround_platform::1
seg::L_turnaround_platform::2
```

is a same-segment headway constraint.

- constraint ids are unique
- no constraint contains duplicate node ids
- `DiscreteScenario.validate()` passes

## Migration Steps

1. Add new enums and `DiscreteConstraint`.
2. Add `DiscreteRoute`.
3. Update `DiscreteScenario` field:

```python
routes: tuple[DiscreteRoute, ...]
constraints: tuple[DiscreteConstraint, ...]
```

4. Keep compatibility aliases only if needed during migration.
5. Update discretizer to emit `routes` and `constraints`.
6. Update tests from `.conflicts` to `.constraints`.
7. Remove or deprecate old `DiscreteConflict` after tests pass.

## Known Open Questions

- Should node occupancy be emitted as explicit constraints now or left implicit for later MILP?
- Should route continuity be a model constraint or only part of route validation?
- Should cross-segment headway near branches be `HARD` or eventually `RELAXABLE`?

For v0:

- emit only headway constraints
- keep all headway constraints `HARD`
- do not emit route continuity constraints as optimizer constraints yet
- validate route continuity structurally in `DiscreteRoute.validate()`

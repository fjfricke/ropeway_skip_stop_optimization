# Cross-Segment Headway v0 Plan

## Purpose

Extend the discretizer conflict generation so that required cabin spacing is enforced across segment boundaries, not only inside a single physical segment.

The current v0 conflict logic catches positions that are too close on the same `TrackSegment`. That is not enough because many important distances cross boundaries:

- terminal turnaround segment chains
- station approach, brake, platform, accelerate, depart chains
- rope-to-station and station-to-rope transitions
- service/skip merge points
- the circulating loop closure back into `L`

## Scope

Add cross-segment `HEADWAY` conflicts to `discretize_scenario()`.

Still not included:

- exact switch occupancy constraints
- merge ordering constraints
- route-choice-specific blocking logic
- continuous physical validation
- cabin initial placement checks

This remains a graph-level spacing approximation.

## Core Idea

For two discrete position nodes on connected directed segments:

```text
segment A: ... pos_a -> A.to_node
segment B: B.from_node -> pos_b ...
```

if:

```text
A.to_node == B.from_node
```

then the forward distance from `pos_a` to `pos_b` is:

```text
distance = (A.length_m - pos_a) + pos_b
```

If:

```text
distance < required_cabin_spacing_m
```

create:

```python
DiscreteConflict(
    node_a_id=pos_a_node.id,
    node_b_id=pos_b_node.id,
    reason=DiscreteConflictReason.HEADWAY,
)
```

## Multiple Short Segments

Some station segments are only 3m or 5m. Since required spacing is 3.5m, it is possible that a cabin near the end of one segment conflicts with positions beyond the immediately next segment.

Therefore v0 should traverse successors until the accumulated distance is at least `required_cabin_spacing_m`.

Example:

```text
A end -> B length 3m -> C beginning
```

A position near the end may conflict with positions in both B and C.

## Segment Successors

Build directed successor relationships from physical topology:

```python
successors[A.id] = [
    B.id
    for B in scenario.track_segments
    if A.to_node_id == B.from_node_id
]
```

This naturally handles branches:

- at `M_entry_lr`, successors include service approach and skip bypass
- at `M_entry_rl`, successors include service approach and skip bypass

It also handles merges:

- service path and skip path may both lead to the same exit switch

For v0, generating conflicts along all physical successors is acceptable. It may be conservative at branch/merge points, but it prevents obviously unsafe close positions.

## Node Distance Model

Need a small internal structure during discretization:

```python
SegmentPositionNode:
    node_id: str
    segment_id: str
    position_m: float
```

Only interior segment-position nodes currently have `source_segment_id` and `position_m`.

Physical endpoint nodes `pn::*` currently have no segment-local position. For v0 cross-segment headway, this is acceptable because endpoint nodes are instantaneous graph junctions, not cabin holding positions unless they have wait arcs.

If a physical endpoint allows waiting, we should eventually include it in conflicts. For v0, include waiting physical nodes at boundary position:

- as `position_m = 0` for outgoing segments
- as `position_m = segment.length_m` for incoming segments

This matters for terminal platform exits with wait arcs.

## Conflict Deduplication

Conflicts should be unordered pairs.

Use canonical pair keys:

```python
key = tuple(sorted((node_a_id, node_b_id)))
```

Do not emit:

- self-conflicts
- duplicate conflicts

The existing same-segment conflict generation should also use this dedup mechanism once cross-segment conflicts are added.

## Traversal Algorithm

For each source segment `A` and each position node on `A`:

1. Compute distance remaining to segment end:

```text
remaining = A.length_m - pos_a
```

2. Traverse successor segments depth-first:

```text
walk(next_segment, accumulated_distance=remaining)
```

3. For each position node on the successor segment:

```text
distance = accumulated_distance + pos_b
```

4. If distance is below required spacing, add conflict.

5. Continue walking into the next successor segment only while:

```text
accumulated_distance + next_segment.length_m < required_cabin_spacing_m
```

6. Avoid infinite loops by tracking visited segment ids in the current walk path.

Because required spacing is short and segments are positive length, traversal should remain small.

## Boundary Waiting Nodes

For physical nodes with `allows_waiting=True`, include conflicts against nearby segment positions:

Incoming side:

```text
distance = segment.length_m - pos_on_incoming_segment
```

Outgoing side:

```text
distance = pos_on_outgoing_segment
```

If either distance is below required spacing, create a `HEADWAY` conflict with the waiting physical node.

This prevents a cabin from waiting at a platform exit while another cabin is too close on the adjacent station or rope segment.

## Tests

Add tests to `tests/test_discretize.py`:

- conflict exists across `L_turnaround_accelerate -> L_exit_lr_to_M_entry_lr`
- conflict exists across `L_turnaround_decelerate -> L_turnaround_platform`
- conflict exists from waiting node `pn::L_platform_exit` to nearby positions on `L_turnaround_accelerate`
- no duplicate conflict pairs
- no self-conflicts
- `DiscreteScenario.validate()` still passes
- total conflicts increases compared with same-segment-only baseline

Use specific node ids when possible, for example:

```text
seg::L_turnaround_accelerate::7
seg::L_exit_lr_to_M_entry_lr::1
```

For `delta_seconds=0.5`:

- `L_turnaround_accelerate` length 3m, 8 steps, position 7 is at 2.625m
- remaining distance to `L_exit_lr` is 0.375m
- first rope position is at 2.5m
- total forward distance is 2.875m < 3.5m
- therefore a conflict is expected

## Known Limitations

- Branch/merge handling is conservative because conflicts are generated across all physical successors.
- Endpoint nodes without waiting are not treated as occupied positions.
- Exact switch occupancy is still not modeled.
- Cross-segment distance is path-local, not global geometry.
- Multiple alternative paths can create conservative conflicts near shared switches.

These limitations are acceptable for v0 because the goal is to avoid clearly unsafe close spacing across segment boundaries before building optimization logic.

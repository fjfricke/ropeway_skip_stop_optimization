# Frontend Discrete Overlay Plan

## Purpose

Extend the frontend so the physical scenario viewer can inspect the generated `DiscreteScenario`.

The goal is not to show the entire discrete graph by default. The current example already has:

```text
478 discrete nodes
482 arcs
1764 constraints
```

Rendering all nodes and all constraints as visible lines at once would be unreadable.

Instead, the frontend should provide a **discrete overlay drilldown** on top of the physical network.

## UX Principle

The physical network remains the primary map.

Discrete data is shown as an overlay based on the current physical selection:

- selected physical segment
- selected physical node
- selected station route
- selected constraint neighborhood

This keeps the visualization grounded in the real infrastructure while allowing detailed debugging.

## Data Export

Python should export a static discrete JSON next to the physical JSON:

```text
frontend/public/scenarios/three_station_v0.json
frontend/public/scenarios/three_station_v0_discrete_dt_0p5.json
```

The discrete JSON should include:

```json
{
  "id": "three_station_v0__dt_0p5",
  "source_scenario_id": "three_station_v0",
  "delta_seconds": 0.5,
  "horizon_steps": 2400,
  "nodes": [],
  "arcs": [],
  "routes": [],
  "constraints": [],
  "demands": [],
  "cabin_capacity": 8,
  "required_cabin_spacing_m": 3.5
}
```

Important fields for frontend filtering:

Discrete node:

```json
{
  "id": "seg::L_turnaround_accelerate::7",
  "source_physical_node_id": null,
  "source_segment_id": "L_turnaround_accelerate",
  "station_id": "L",
  "resource_id": "L_service_turnaround",
  "position_m": 2.625,
  "allows_waiting": false,
  "allows_boarding": false,
  "allows_alighting": false
}
```

Physical node-backed discrete node:

```json
{
  "id": "pn::L_platform_exit",
  "source_physical_node_id": "L_platform_exit",
  "source_segment_id": null,
  "station_id": "L",
  "allows_waiting": true
}
```

Constraint:

```json
{
  "id": "constraint::headway::cross_segment::...",
  "kind": "headway",
  "scope": "cross_segment",
  "strength": "hard",
  "node_ids": ["seg::...", "seg::..."],
  "arc_ids": [],
  "resource_id": null,
  "source_segment_ids": ["L_turnaround_accelerate", "L_exit_lr_to_M_entry_lr"],
  "source_route_ids": ["L_service_turnaround"]
}
```

## Frontend Types

Add to `frontend/src/types.ts`:

- `DiscreteScenario`
- `DiscreteNode`
- `DiscreteArc`
- `DiscreteRoute`
- `DiscreteConstraint`
- `DiscreteConstraintKind`
- `DiscreteConstraintScope`
- `DiscreteConstraintStrength`

Keep them separate from physical types.

## Loading

`App` or `ScenarioViewer` should load:

- physical scenario JSON
- discrete scenario JSON

If the discrete JSON fails to load, the physical viewer should still work and show a small unavailable state for the overlay.

## Interaction Model

### Default State

Only physical scenario is visible.

Discrete overlay is off or empty until a meaningful selection exists.

### Physical Segment Click

When the user clicks a physical segment:

1. Select the physical segment.
2. Show the selected segment's discrete positions.
3. Show movement arcs along that segment.
4. If `Constraint Neighborhood` mode is active, show all constraints touching those discrete positions.
5. Show surrounding nodes and segments touched by those constraints.

This answers:

> "If I click a path in physical view, can I see its discrete representation?"

Yes: selected segment plus surrounding affected discrete nodes.

### Physical Route Click

When the user selects a station route:

1. Show all arcs in the matching `DiscreteRoute`.
2. Show all discrete nodes touched by those arcs.
3. Optionally show constraints touching those route nodes.

Useful examples:

- `M_service_lr` shows 56 arcs
- `M_skip_lr` shows 28 arcs
- `L_service_turnaround` shows 36 arcs

### Physical Node Click

When the user clicks a physical node:

1. Show the discrete node `pn::<physical_node_id>`.
2. Show wait arc if present.
3. Show constraints involving that discrete node.
4. Show neighboring affected nodes.

This is especially useful for waiting nodes:

- `pn::L_platform_exit`
- `pn::R_platform_exit`

## Overlay Modes

Add a control group in the same visual language as the existing toolbar.

Physical layer toggles remain:

```text
[Service] [Skip] [Demand] [Parameters]
```

Add a second discrete toolbar group:

```text
[Discrete] [Selected] [Neighborhood] [Move Arcs] [Wait Arcs] [Same Headway] [Cross Headway]
```

If horizontal space gets tight, split into two rows:

```text
Physical:
[Service] [Skip] [Demand] [Parameters]

Discrete:
[Discrete] [Selected] [Neighborhood] [Move Arcs] [Wait Arcs] [Same Headway] [Cross Headway]
```

Use icon + text buttons matching the existing style.

Recommended icons from `lucide-react`:

- `Discrete`: `Network`
- `Selected`: `MousePointer2` or `Focus`
- `Neighborhood`: `Radar` or `ScanSearch`
- `Move Arcs`: `MoveRight`
- `Wait Arcs`: `TimerPause`
- `Same Headway`: `Rows3`
- `Cross Headway`: `GitMerge` or `Shuffle`

### Master Toggle

`Discrete` is the master switch.

When off:

- no discrete nodes
- no discrete arcs
- no constraints
- inspector still shows physical information only

When on:

- selected physical entities can show discrete overlays
- overlay content is controlled by mode and layer toggles

### Overlay Mode Buttons

Use a mutually exclusive segmented pair:

```text
[Selected] [Neighborhood]
```

Recommended v1 default:

```text
Neighborhood
```

Because the user explicitly wants to see all cross-segment constraints around the selected path.

### Discrete Off

No discrete data rendered.

### Selected

Only render discrete nodes/arcs directly belonging to the selected physical entity.

For selected segment:

```ts
visibleNodeIds = nodes where source_segment_id === selectedSegmentId
visibleArcIds = arcs where source_segment_id === selectedSegmentId
```

### Constraint Neighborhood

For selected segment:

```ts
selectedNodeIds =
  nodes where source_segment_id === selectedSegmentId

relatedConstraints =
  constraints where constraint.node_ids intersects selectedNodeIds

visibleNodeIds =
  selectedNodeIds
  + all node_ids from relatedConstraints

visibleConstraintIds =
  relatedConstraints

visibleSegmentIds =
  selectedSegmentId
  + all source_segment_ids from relatedConstraints
  + source_segment_id of visible nodes
```

This shows:

- selected segment discrete nodes
- cross-segment constraint endpoints
- same-segment constraints
- surrounding segments affected by constraints

## Discrete Arc And Constraint Toggles

These toggles control which discrete objects are visible after the overlay mode has chosen the object set.

### Move Arcs

Shows `DiscreteArc(kind=move)`.

For selected segment:

```ts
visibleMoveArcs = arcs where source_segment_id === selectedSegmentId
```

For neighborhood mode:

```ts
visibleMoveArcs =
  selected segment move arcs
  + move arcs touching visible node ids
```

Default: on.

### Wait Arcs

Shows `DiscreteArc(kind=wait)`.

Only wait arcs whose node is part of the visible discrete node set should be rendered.

Default: on.

### Same Headway

Shows constraints:

```ts
kind === "headway" && scope === "same_segment"
```

Default: on.

### Cross Headway

Shows constraints:

```ts
kind === "headway" && scope === "cross_segment"
```

Default: on.

This is important for inspecting boundary spacing across:

- station segment chains
- terminal turnarounds
- rope/station transitions
- service/skip merge neighborhoods

### Toggle Interaction Rules

- If `Discrete` is off, all discrete layer toggles are visually disabled.
- If `Move Arcs` is off, discrete nodes can still be shown.
- If both `Same Headway` and `Cross Headway` are off, constraints are hidden but surrounding nodes from the selected segment should remain visible.
- In `Selected` mode, constraint toggles have no effect unless we decide to show selected-segment same constraints there. v1 should keep constraints only in `Neighborhood` mode.

## Default Toolbar State

Initial page load:

```ts
discreteOverlay = false
overlayMode = "neighborhood"
showMoveArcs = true
showWaitArcs = true
showSameHeadway = true
showCrossHeadway = true
```

After user selects a physical segment and turns on `Discrete`, the overlay should immediately show the constraint neighborhood.

## Constraint Filters

Add toggles:

- Same-segment headway
- Cross-segment headway

For now, only `HEADWAY` exists.

Later:

- switch occupancy
- shared resource
- node occupancy

Default:

- same-segment on
- cross-segment on

## Rendering

Use the existing SVG renderer and physical layout.

Discrete coordinates are derived from physical coordinates:

### Physical Node-Backed Discrete Nodes

```ts
pn::<physical_node_id> -> layout.nodes[physical_node_id]
```

### Segment Position Nodes

```ts
seg::<segment_id>::i
```

Use:

- `source_segment_id`
- `position_m`
- physical segment `length_m`
- existing `segmentPath()` geometry

For straight segments:

```text
t = position_m / length_m
point = lerp(from, to, t)
```

For curved segments:

Use the same quadratic curve as the physical segment:

```text
point = quadraticBezier(from, control, to, t)
```

This keeps discrete nodes aligned with the drawn physical segment.

## Visual Encoding

Discrete nodes:

- small circular dots
- selected segment nodes: dark blue
- surrounding constraint nodes: amber
- waiting physical nodes: square or ring marker

Move arcs:

- thin blue strokes
- only visible for selected segment/route

Constraints:

- same-segment: thin muted violet or gray lines
- cross-segment: orange lines
- line opacity low by default
- stronger on hover/selected constraint

Surrounding physical segments:

- subtle halo or outline
- do not fully recolor them

## Inspector

Extend inspector to understand:

- selected physical segment with discrete summary
- selected discrete node
- selected discrete constraint
- selected discrete route

For a selected physical segment, show:

```text
Physical segment
length: ...
speed profile: ...
discrete steps: ...
visible discrete nodes: ...
constraints:
  same-segment: ...
  cross-segment: ...
neighbor segments:
  ...
```

For a selected constraint:

```text
Constraint
kind: headway
scope: cross_segment
strength: hard
nodes: ...
segments: ...
routes: ...
```

## Implementation Order

1. Export discrete JSON from Python.
2. Add frontend discrete types.
3. Load discrete JSON in `App`/`ScenarioViewer`.
4. Add overlay mode and constraint filter state.
5. Add coordinate helpers for discrete nodes.
6. Render selected-segment discrete nodes and move arcs.
7. Render constraint neighborhood for selected segment.
8. Extend inspector summaries.
9. Add route-selection overlay later if needed.

## Tests / QA

Python:

- discrete export creates JSON
- JSON contains `routes` and `constraints`
- `three_station_v0_discrete_dt_0p5.json` has:

```text
478 nodes
482 arcs
6 routes
1764 constraints
```

Frontend:

- physical viewer still loads without discrete overlay
- clicking `L_turnaround_accelerate` shows discrete nodes on that segment
- same click shows cross-segment endpoint on `L_exit_lr_to_M_entry_lr`
- cross-segment filter hides/shows cross-segment constraints
- same-segment filter hides/shows same-segment constraints
- inspector reports counts for selected segment

Visual QA:

- overlay remains readable at default zoom
- panning/zooming keeps discrete node marker sizes stable
- constraint lines do not dominate the physical network
- selected segment neighborhood is understandable without showing all 1764 constraints

## Known Limitations

- Full all-constraints line rendering is intentionally not the default.
- Constraint Neighborhood is one-hop from selected segment nodes, not a full transitive closure.
- Route overlay can be added after segment-neighborhood overlay works.
- Dense station platform segments may still need opacity tuning.

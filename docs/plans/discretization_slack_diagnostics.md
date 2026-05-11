# Discretization Slack Diagnostics Plan

Status: **not yet implemented**

## Purpose

The current frontend graph view shows rounding slack per physical `TrackSegment`.

This is useful for inspecting where `ceil(physical_travel_seconds / delta_seconds)` adds artificial travel time, but it is not enough for later optimization work.

Next, slack diagnostics should move from a segment-only view to route- and switch-aware diagnostics.

## Current State

Implemented now:

- discrete nodes represent time-step boundaries
- every move arc consumes exactly one `delta_seconds` step
- segment duration is rounded with `ceil`
- linear brake/accelerate positions are computed from integrated speed over time
- frontend `Graph View` shows segment-level slack

Not implemented yet:

- route-level slack
- skip-vs-service drift at matching entry/exit switches
- backend-exported discretization report
- cycle-level drift analysis for the ring line

## Route-Level Slack

For every relevant route, compute:

- physical travel seconds
- discrete travel seconds
- slack seconds
- duration steps
- source segment ids

Important routes:

- `M_service_lr`
- `M_skip_lr`
- `M_service_rl`
- `M_skip_rl`
- `L_service_turnaround`
- `R_service_turnaround`
- full all-stop cycle:
  - `L -> M service -> R -> M service -> L`
- skip variants:
  - `L -> M skip -> R`
  - `R -> M skip -> L`

The goal is to see whether `ceil` creates unfair route-duration distortion.

## Switch And Merge Drift

At matching service/skip alternatives, compare the total discrete duration between the same entry and exit switches.

Examples:

```text
M_entry_lr -> M_exit_lr
  service: M_lr_approach_fast + M_lr_brake + M_lr_platform + M_lr_accelerate + M_lr_depart_fast
  skip:    M_lr_skip_bypass
```

```text
M_entry_rl -> M_exit_rl
  service: M_rl_approach_fast + M_rl_brake + M_rl_platform + M_rl_accelerate + M_rl_depart_fast
  skip:    M_rl_skip_bypass
```

For each alternative pair, compute:

- physical service duration
- physical skip duration
- discrete service duration
- discrete skip duration
- physical duration difference
- discrete duration difference
- drift error:

```text
drift_error_seconds =
  (discrete_service_seconds - discrete_skip_seconds)
  - (physical_service_seconds - physical_skip_seconds)
```

This is important because cabins from service and skip paths merge again at the exit switch.

## Cycle Drift

For circulating systems, repeated `ceil` rounding can accumulate.

The diagnostics should compute:

- physical cycle duration
- discrete cycle duration
- total cycle slack
- slack per lap
- approximate drift after `n` laps

This is especially relevant because cabins run in a ring line and long-term offsets may appear even if local constraints are feasible.

## Backend Report

Slack diagnostics should eventually be computed in Python and exported with the discrete scenario.

Possible structure:

```python
@dataclass(frozen=True)
class SegmentDiscretizationReport:
    segment_id: str
    physical_seconds: float
    discrete_seconds: float
    slack_seconds: float
    duration_steps: int

@dataclass(frozen=True)
class RouteDiscretizationReport:
    route_id: str
    physical_seconds: float
    discrete_seconds: float
    slack_seconds: float
    duration_steps: int
    segment_ids: tuple[str, ...]

@dataclass(frozen=True)
class AlternativePathDriftReport:
    from_node_id: str
    to_node_id: str
    left_route_id: str
    right_route_id: str
    physical_difference_seconds: float
    discrete_difference_seconds: float
    drift_error_seconds: float
```

The frontend should then render this report instead of recomputing all values from raw segments and arcs.

## Frontend View

Extend `Graph View` with tabs or segmented controls:

- `Segments`
- `Routes`
- `Switch Drift`
- `Cycle`

Keep the current segment slack table as the `Segments` tab.

Add route-level rows for route slack.

Add switch-drift rows grouped by entry/exit switch pair.

## Not Yet Implemented

This document is a planning note only.

No route-level slack, switch drift, cycle drift, or backend report exists yet.

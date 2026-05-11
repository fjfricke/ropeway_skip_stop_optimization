# Discretization Notes

## Purpose

This document collects known discretization issues for the ropeway model.

The first implementation should use a simpler approximation so that the replay baseline and data model can be built. The points below should remain visible because they affect physical validity, cyclic cabin movement, skip/service comparisons, and later MILP quality.

## Physical Versus Discrete Model

The physical scenario uses:

- clock times
- segment lengths in meters
- speed profiles in meters per second
- cabin length in meters
- required clearance in meters
- station geometry and switch paths

The discrete model uses:

- integer time steps
- discrete physical position nodes
- one-step movement arcs
- explicit one-step waiting arcs where waiting is allowed
- conflict constraints between occupied discrete positions

This conversion is an approximation. It must be explicit and measurable.

## Required Cabin Spacing

The relevant spacing parameter should not be only a headway distance.

It should be modeled as:

```text
required_cabin_spacing_m = cabin_length_m + min_clearance_m
```

This separates vehicle geometry from the operational safety margin.

## Time Discretization

For a physical movement:

```text
physical_travel_time_seconds = length_m / effective_speed_m_per_s
```

The simple conservative approximation is:

```text
travel_time_steps = ceil(physical_travel_time_seconds / delta_seconds)
```

This prevents cabins from moving faster than the physical model permits.

However, this also creates rounding slack:

```text
rounding_slack_seconds =
    travel_time_steps * delta_seconds - physical_travel_time_seconds
```

This slack is not physically free. It represents implicit waiting or delay.

## Waiting And Rounding Slack

Rounding slack can only be physically interpreted if it can occur at a place where waiting is allowed.

Examples of valid waiting locations:

- depot or storage nodes
- platform/holding nodes
- station exit holding zones
- other explicitly modeled hold nodes

Rounding a movement up and silently treating the extra time as slower movement is an approximation. For long-term cyclic operation, this can create artificial drift unless the slack can be absorbed at waiting nodes.

## One-Step Movement Graph

The intended discrete movement representation is:

```text
one arc = one time step
```

In each `delta_seconds` step, an active cabin either:

- traverses exactly one movement arc, or
- traverses one wait arc at a node where waiting is allowed

Physical `TrackSegment`s are therefore not represented as long arcs with multi-step travel time. They are split into a sequence of discrete positions and one-step movement arcs.

For a physical segment:

```text
physical_travel_time_seconds = computed from length and speed profile
n_steps = ceil(physical_travel_time_seconds / delta_seconds)
```

The discretizer then creates `n_steps` movement arcs.

For constant-speed segments, discrete positions can be placed approximately uniformly along the segment.

For linear braking or acceleration segments, discrete positions should follow the local speed profile, because equal time steps do not correspond to equal distances.

## Spatial Discretization And Conflicts

A naive block-capacity rule is not sufficient:

```text
one cabin per block
```

If block lengths are shorter than `required_cabin_spacing_m`, two cabins in adjacent blocks might still be too close.

If block lengths are longer than `required_cabin_spacing_m`, the model may become overly conservative and reduce capacity artificially.

Therefore, the better approach is:

- split physical segments into one-step discrete position arcs
- compute conflict relationships between discrete positions
- forbid simultaneous occupation of conflicting positions

In that approach, position capacity alone is not the headway model. Position conflicts encode safe simultaneous occupancy.

## Segment Splitting

For simple initial approximation, segments may be discretized into one-step arcs without cycle calibration.

For constant-speed segments, block travel time is computed directly from length and speed.

For linear braking or acceleration segments, local block speeds should be derived from the linear speed profile at the block start and end positions.

Slow station movement naturally produces shorter physical movement per time step. For example:

```text
delta_seconds = 5
rope_speed = 5 m/s      -> 25 m per step
station_speed = 1 m/s   -> 5 m per step
```

If required cabin spacing is 25 m, this means a station path may require conflicts across roughly five neighboring discrete positions.

## Cyclic Cabin Movement

Ropeway cabins circulate. This makes local rounding errors more important than in a one-shot path problem.

If every segment travel time is rounded up independently, a full loop becomes longer in the discrete model than in the physical system. Over many cycles, this can create artificial schedule drift.

This is acceptable for a first conservative prototype, but should be measured.

The discrete model should report, at least later:

- physical route duration
- discrete route duration
- absolute timing error
- error per cycle
- accumulated rounding slack

## Cycle-Calibrated Discretization

A better later approach is cycle-calibrated discretization.

Instead of rounding every segment independently, choose integer segment or block durations so that the total cycle duration and cumulative arrival times from an anchor point are approximated as well as possible.

Example objective:

```text
minimize cumulative timing error from an anchor node
```

Possible anchor:

- a main station platform
- a depot exit
- a specific switch node on the loop

This can reduce long-term drift in cyclic operation.

Tradeoff:

- conservative rounding is physically safer but may create drift
- cycle-calibrated rounding is more accurate globally but can make individual arcs slightly faster than their physical minimum unless validated later

## Merge-Point Consistency

Skip-stop infrastructure creates alternative paths that merge again.

Example:

```text
entry_switch
   /        \
service     skip
   \        /
 exit_switch
```

At such merge points, discretization should preserve relative route durations as well as possible.

Important quantity:

```text
physical_duration(service_route) - physical_duration(skip_route)
```

should be approximated by:

```text
discrete_duration(service_route) - discrete_duration(skip_route)
```

If this difference is distorted, the optimizer may overvalue or undervalue skipping.

Later discretization should therefore measure route-duration distortion for alternative paths sharing the same entry and exit switches.

## Possible Future Architecture

The project may eventually use a layered approach:

```text
Discrete MILP
  chooses cabin paths, service/skip routes, and rough timing

Continuous or EAN-style validator
  checks exact physical feasibility, headways, switch conflicts, and timing

Replay
  evaluates passenger queues, boarding, alighting, and waiting times
```

If the validator finds a physical infeasibility, it may be possible to add logical cuts back to the discrete MILP. This resembles logic-based Benders decomposition.

This is not part of the first implementation, but it is a useful extension path.

## Initial Approximation Choice

For the first implementation, use a simpler method:

- use a fixed `delta_seconds`, likely 0.5 seconds for the first small experiments
- compute movement durations from length and speed
- split physical movements into one-step arcs using `ceil(physical_time / delta_seconds)`
- allow waiting only through explicit wait arcs at allowed nodes
- keep station and skip geometry physically specified
- do not yet implement cycle-calibrated rounding
- implement only the simplest useful conflict logic first
- record enough information to inspect discretization error later

This keeps the first replay baseline tractable while making the approximation explicit.

For a tiny debug scenario with:

```text
cabin_length_m = 3.0
min_clearance_m = 0.5
rope_speed_m_per_s = 5.0
```

the strict maximum step size from spacing and rope speed is:

```text
(3.0 + 0.5) / 5.0 = 0.7s
```

Use `0.5s` instead of `0.7s` because it is below the strict maximum and aligns cleanly with minute-based clock times.

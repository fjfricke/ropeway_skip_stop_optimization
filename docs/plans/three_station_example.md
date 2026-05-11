# Three-Station Example Scenario Plan

## Purpose

Define the first small physical `Scenario` before implementing the discretizer or replay.

This example should test whether the domain models can express:

- circulating ropeway movement with terminal turnarounds
- bidirectional movement on the `L-M` and `M-R` spans
- one skippable intermediate station
- separate service and skip paths
- entry and exit switches
- station approach, braking, platform, acceleration, and departure segments
- depot or storage starts
- OD demand with clock times

The goal is not realism yet. The goal is a small, explicit scenario that exposes model mistakes early.

## Topology

The first scenario is a directed circulating line with three passenger stations:

```text
L -> M -> R -> M -> L
```

The middle station `M` is skippable.

At the terminal stations, cabins do not disappear or reverse by magic. They pass through explicit station turnaround routes:

```text
L_entry_rl -> L_platform_entry -> L_platform_exit -> L_exit_lr
R_entry_lr -> R_platform_entry -> R_platform_exit -> R_exit_rl
```

At `M`, each direction has an entry switch and an exit switch. A cabin can either:

- take the service route through the station platform
- take the skip route through a bypass path

Conceptually, for direction `L -> R`:

```text
L
  -> M_entry_lr
       /                  \
      / service route      \ skip route
     v                      v
   approach_fast          skip_bypass
     -> brake              |
     -> platform           |
     -> accelerate         |
     -> depart_fast        |
       \                  /
        v                v
        M_exit_lr
          -> R
```

Direction `R -> L` should be represented with its own directed physical nodes and segments:

```text
R
  -> M_entry_rl
       /                  \
      / service route      \ skip route
     v                      v
   approach_fast          skip_bypass
     -> brake              |
     -> platform           |
     -> accelerate         |
     -> depart_fast        |
       \                  /
        v                v
        M_exit_rl
          -> L
```

This keeps the first example explicit. Later builders can generate symmetric reverse-direction infrastructure automatically.

## Stations

Passenger stations:

- `L`, kind `TERMINAL`
- `M`, kind `SERVICE`
- `R`, kind `TERMINAL`

Optional storage/depot station:

- `D`

The depot is not a demand origin or destination. It may be represented as a `STORAGE` station and one or more `DEPOT` physical nodes.

## Physical Nodes

Suggested physical nodes for the first explicit version:

```text
D_depot

L_entry_rl
L_platform_entry
L_platform_exit
L_exit_lr

R_entry_lr
R_platform_entry
R_platform_exit
R_exit_rl

M_entry_lr
M_service_approach_lr
M_platform_entry_lr
M_platform_exit_lr
M_service_accelerate_lr
M_exit_lr

M_entry_rl
M_service_approach_rl
M_platform_entry_rl
M_platform_exit_rl
M_service_accelerate_rl
M_exit_rl
```

Kinds:

- `D_depot`: `DEPOT`, waiting allowed
- terminal `*_entry_*` nodes: `ENTRY_SWITCH`
- terminal `*_exit_*` nodes: `EXIT_SWITCH`
- terminal `*_platform_entry`, `*_platform_exit`: `PLATFORM`, service-capable
- `M_entry_lr`, `M_entry_rl`: `ENTRY_SWITCH`
- `M_exit_lr`, `M_exit_rl`: `EXIT_SWITCH`
- `M_platform_entry_*`, `M_platform_exit_*`: `PLATFORM`
- intermediate station path nodes: `CONNECTOR` unless they are explicit holding points

If exit waiting is needed later, add:

```text
M_exit_hold_lr
M_exit_hold_rl
```

as `HOLD` nodes with `allows_waiting=True`.

## Track Segments

Use directed `TrackSegment`s.

### Main Rope Segments

Forward direction:

```text
L_exit_lr_to_M_entry_lr
M_exit_lr_to_R_entry_lr
```

Reverse direction:

```text
R_exit_rl_to_M_entry_rl
M_exit_rl_to_L_entry_rl
```

Together with the terminal turnaround routes, these segments form one directed cycle:

```text
L_exit_lr
  -> M_entry_lr
  -> M service/skip lr
  -> M_exit_lr
  -> R_entry_lr
  -> R_service_turnaround
  -> R_exit_rl
  -> M_entry_rl
  -> M service/skip rl
  -> M_exit_rl
  -> L_entry_rl
  -> L_service_turnaround
  -> L_exit_lr
```

### M Service Route: L -> R

```text
M_lr_approach_fast:
  M_entry_lr -> M_service_approach_lr

M_lr_brake:
  M_service_approach_lr -> M_service_brake_lr

M_lr_platform:
  M_service_brake_lr -> M_platform_exit_lr

M_lr_accelerate:
  M_platform_exit_lr -> M_service_accelerate_lr

M_lr_depart_fast:
  M_service_accelerate_lr -> M_exit_lr
```

The model currently has only nodes and segments, not explicit platform intervals. If we want clearer platform boundaries, split this into:

```text
M_lr_platform_entry:
  M_service_brake_lr -> M_platform_entry_lr

M_lr_platform:
  M_platform_entry_lr -> M_platform_exit_lr
```

Preferred first version: use explicit `M_platform_entry_lr` and `M_platform_exit_lr`.

### M Skip Route: L -> R

```text
M_lr_skip_bypass:
  M_entry_lr -> M_exit_lr
```

### M Service Route: R -> L

Mirror the same structure:

```text
M_rl_approach_fast
M_rl_brake
M_rl_platform_entry
M_rl_platform
M_rl_accelerate
M_rl_depart_fast
```

### M Skip Route: R -> L

```text
M_rl_skip_bypass:
  M_entry_rl -> M_exit_rl
```

## Speed Profiles

Suggested default physical assumptions:

```text
rope_speed = 5.0 m/s
station_fast_speed = 1.0 m/s
platform_speed = 0.5 m/s
```

Segment profiles:

- main rope: constant `rope_speed`
- skip bypass: constant `rope_speed`
- approach_fast: constant `station_fast_speed`
- brake: linear `station_fast_speed -> platform_speed`
- platform: constant `platform_speed`
- accelerate: linear `platform_speed -> station_fast_speed`
- depart_fast: constant `station_fast_speed`

## Example Lengths

Initial placeholder lengths should be chosen so that travel times are integer multiples of the default `delta_seconds`.

Use:

```text
delta_seconds = 0.5
```

Rationale:

```text
cabin_length_m = 3.0
min_clearance_m = 0.5
required_cabin_spacing_m = 3.5
rope_speed_m_per_s = 5.0
strict maximum delta = required_cabin_spacing_m / rope_speed_m_per_s = 0.7s
```

`0.5s` is below this strict maximum, aligns cleanly with minute-based clock times, and gives simple step lengths:

```text
rope movement per step = 2.5 m
station fast movement per step = 0.5 m
platform movement per step = 0.25 m
```

Recommended v0 lengths:

```text
L_exit_lr_to_M_entry_lr:      150 m   -> 30s -> 60 steps
M_exit_lr_to_R_entry_lr:      150 m   -> 30s -> 60 steps
R_exit_rl_to_M_entry_rl:      150 m   -> 30s -> 60 steps
M_exit_rl_to_L_entry_rl:      150 m   -> 30s -> 60 steps

approach_fast:          5 m   ->  5s -> 10 steps
brake:                  3 m   ->  4s ->  8 steps
platform:               5 m   -> 10s -> 20 steps
accelerate:             3 m   ->  4s ->  8 steps
depart_fast:            5 m   ->  5s -> 10 steps

skip_bypass:           70 m   -> 14s -> 28 steps
```

For brake and accelerate, the calculation uses the average speed of the linear profile:

```text
avg_speed = (1.0 + 0.5) / 2 = 0.75 m/s
3 m / 0.75 m/s = 4s = 8 steps
```

These are placeholders for model testing. They should be easy to change.

## Station Routes

For `M`, define four routes:

```text
M_service_lr
M_skip_lr
M_service_rl
M_skip_rl
```

`M_service_*`:

- kind: `SERVICE`
- allows boarding: yes
- allows alighting: yes
- segments: approach, brake, platform entry/platform, accelerate, depart

`M_skip_*`:

- kind: `SKIP`
- allows boarding: no
- allows alighting: no
- segments: skip bypass

For terminal stations `L` and `R`, define explicit terminal turnaround service routes:

```text
L_service_turnaround: L_entry_rl -> L_platform_entry -> L_platform_exit -> L_exit_lr
R_service_turnaround: R_entry_lr -> R_platform_entry -> R_platform_exit -> R_exit_rl
```

Each terminal service route should include:

```text
entry -> decelerate -> platform -> accelerate -> exit
```

This keeps terminal stations structurally explicit without creating false station paths that are not connected to the circulating loop.

## Cabins

Start with a small number of cabins:

```text
0, 1, 2, 3
```

Initial states:

- simplest: all cabins start at a depot node with staggered `available_from` times
- alternative: place cabins at different physical nodes at `service_start_time`

For the first baseline, staggered depot availability is easier to reason about.

## Operating Parameters

Example values:

```text
rope_speed_m_per_s = 5.0
station_speed_m_per_s = 0.5
cabin_capacity = 8
cabin_length_m = 3.0
min_clearance_m = 0.5
required_cabin_spacing_m = 3.5
```

## Demand

Use a short service window first:

```text
08:00 to 08:20
```

Example OD demand:

```text
08:01  L -> R  6 passengers
08:02  L -> M  4 passengers
08:03  M -> R  5 passengers
08:04  R -> L  6 passengers
08:05  R -> M  3 passengers
08:06  M -> L  4 passengers
```

Demand should not encode route direction. It only states origin, destination, arrival time, and passenger count.

## Open Design Notes

- The first explicit version may feel verbose. That is acceptable because it tests the low-level model.
- After the first explicit scenario works, build helper functions to generate common skippable-station geometry.
- Terminal service modeling may need a small design pass once the all-stop baseline generator is implemented.
- Full circular operation is part of the first scenario. `L` and `R` are terminal turnaround stations, not dead ends.

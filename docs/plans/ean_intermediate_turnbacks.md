# EAN Intermediate Turnback Plan

Status: **future semantic and experimental work**

## Goal

Allow selected intermediate stations to contain a crossover that lets a cabin
reverse direction instead of continuing to the next terminal. Evaluate
short-turn operation as a separate extension of skip, waiting, and fleet
activation.

The intended physical layout is:

```text
entry in direction A
-> service platform
-> optional wait position
-> normal exit in direction A

or

entry in direction A
-> service platform
-> optional wait position
-> crossover
-> entry in direction B
```

This is a topology and operating-policy extension, not a solver-preserving
optimization. The existing no-turnback route must remain available so that
enabling a crossover weakly enlarges the feasible set.

## Operational Motivation

Skip reduces station time but does not change the section of line served by a
cabin. An intermediate turnback can concentrate service on a highly demanded
subnetwork, rebalance asymmetric directional demand, and avoid sending every
cabin through weakly demanded outer sections.

Potential questions include:

- how much passenger time is saved by short-turn operation;
- whether the same demand can be served with fewer cabins;
- whether a larger fleet can be used effectively on a congested inner section;
- which station is the most useful turnback location;
- how often a crossover is used under symmetric and asymmetric demand;
- whether the benefit justifies the infrastructure and operational complexity.

For a minimization objective, when every no-turnback movement remains feasible:

```text
optimal_with_turnback <= optimal_without_turnback
```

The comparison must still enforce equal served demand or lexicographically
maximize service before passenger time.

## Current Model Limitation

The physical scenario already supports directed nodes, connected track
segments, resources, and station routes. A crossover can therefore be drawn in
the physical graph.

The current EAN builder cannot use that branch:

- `RingSwitchVisitBuilder` assumes one immutable directed switch cycle;
- every switch has exactly one next switch;
- `PhysicalSkipStopTimingBuilder` expects exactly one service route and at most
  one skip route from an entry switch;
- service and skip routes must lead to the same exit switch;
- passenger ride candidates are generated from a fixed cabin visit sequence.

Adding one connector segment alone is therefore insufficient. A turnback
changes the next switch, downstream visit sequence, possible passenger paths,
and resource conflicts.

## Physical Representation

For a station `M`, add direction-specific branch and merge nodes:

```text
M_platform_exit_lr
-> M_wait_lr
-> M_exit_lr

M_wait_lr
-> M_crossover_lr_to_rl
-> M_entry_rl
```

Add the reverse crossover only when the infrastructure is physically
bidirectional:

```text
M_wait_rl
-> M_crossover_rl_to_lr
-> M_entry_lr
```

The crossover requires explicit resources for every physical conflict it
creates:

- exclusive crossover occupancy;
- conflict between opposite crossover movements;
- merge conflict at the opposite entry;
- conflicts with crossed main-line tracks where applicable;
- finite holding or queue capacity before the crossover;
- minimum clearance after leaving the wait position.

If both directions share one physical crossover, model one shared unary
resource rather than two independent directed resources.

## Keep Passenger and Movement Semantics Separate

Do not encode turnback solely as another `StationRouteKind`. Passenger service
and movement effect are orthogonal:

```text
passenger behavior:
  service
  skip

movement effect:
  continue
  turnback
  depot entry
  depot exit
```

A turnback can still serve a station, and a future depot route can also contain
service or non-service movement. Use a route-option abstraction that records
both properties instead of creating combined enum values such as
`SERVICE_TURNBACK`.

One possible future representation is:

```text
EanRouteOption
  id
  from_switch_id
  to_switch_id
  station_id
  passenger_behavior
  movement_effect
  timing
  occupied_resources
```

The exact data shape should follow the physical route builder, but downstream
code must be able to select among multiple destinations from one switch.

## Passenger Policy at a Turnback

Treat these as explicit, mutually exclusive semantic policies.

### Mandatory Alighting

All passengers must leave before the cabin enters the crossover. The crossover
is passenger-free. A new visit at the opposite station entrance may permit
boarding for the reverse direction.

This is the simplest and safest first implementation because every passenger
journey remains inside one precomputed directional movement pattern.

### Reachability-Based Through Riding

Passengers may remain onboard only if their destination is reachable after the
selected turnback without violating the passenger-path rules.

This is operationally more flexible but couples passenger assignment directly
to the cabin's route choice.

### Unrestricted Through Riding

Do not implement unrestricted onboard turnback unless repeated station visits,
dominated loops, destination reachability, and passenger information semantics
have been defined. It can generate unnecessary cycles and unintuitive journeys.

Use mandatory alighting for the first prototype. Evaluate reachability-based
through riding only after the graph-based passenger evaluator exists.

## Phase 0: Fixed Short-Turn Patterns

Before replacing the ring EAN, define a small library of deterministic cabin
circulation patterns:

```text
full line cycle
left-side short-turn cycle at station M
right-side short-turn cycle at station M
```

Each pattern has a fixed switch sequence. A benchmark run either assigns
cabins to patterns externally or lets each cabin choose one pattern once at the
start. Stop, skip, and waiting decisions remain optimized within the selected
pattern.

This phase should:

- reuse the current fixed-sequence visit and passenger builders where possible;
- use explicit crossover timing and resources;
- begin with mandatory alighting at every turnback;
- keep the number of patterns small and manually auditable;
- compare full-cycle-only against mixed full and short-turn operation.

Pattern choice at the start may use one binary per cabin and pattern:

```text
sum(pattern[cabin, p] for p) = active[cabin]
```

Do not permit arbitrary pattern switching during operation in this phase.

## Phase 1: Movement-Only Switch Graph

Proceed only if fixed-pattern experiments show relevant operational benefit or
if arbitrary short-turn timing is required for the research question.

Replace the fixed switch-cycle assumption with a directed switch graph. For
cabin \(c\), event layer \(k\), switch \(s\), and route option \(r\), define:

```text
visit[c, k, s] in {0, 1}
route[c, k, r] in {0, 1}
```

Route selection:

```text
sum(route[c, k, r] for r leaving s) = visit[c, k, s]
```

State propagation:

```text
visit[c, k + 1, target]
  = sum(route[c, k, r] for r ending at target)
```

Route timing is conditional on selection:

```text
next_switch_time
  = current_departure_time + route_travel_time
  when route[c, k, r] = 1
```

The event-layer bound must be derived conservatively from minimum route times.
Prune unreachable `(layer, switch)` states before creating variables.

The first graph prototype contains movement, stop/skip, waiting, and physical
headways but no integrated passenger assignment. Validate its movement with
the physical replay and use the fixed-movement passenger evaluator afterward.

## Phase 2: Turnback Resource Model

Add route-specific resource occupancies rather than treating the crossover as
only another travel duration.

For each selected crossover traversal, derive:

```text
crossover entry time
crossover exit time
opposite-side merge time
```

Enforce:

- no overlap on a shared crossover;
- opposite-direction exclusion;
- merge headway against normal arrivals;
- clearance before a following cabin leaves the wait area;
- capacity and FIFO semantics of the pre-crossover waiting area;
- every physical crossing conflict represented by the layout.

Do not reuse a platform or exit-switch checkpoint unless it describes the same
physical conflict interval. Add dedicated checkpoint or interval semantics
where needed.

## Phase 3: Passenger Integration

Use the fixed-movement passenger evaluator first:

```text
optimize movement with turnbacks
-> freeze movement and timings
-> evaluate passenger service exactly
```

For integrated optimization, replace fixed ride-candidate sequences with
route-activated passenger-flow arcs or pattern-specific candidates.

Under mandatory alighting:

- no ride arc crosses a selected turnback;
- passengers may alight at the turnback station;
- a later reverse-direction visit creates new boarding opportunities.

Under reachability-based through riding:

- onboard-flow arcs continue through the crossover only when the downstream
  route remains selected;
- destination reachability must be enforced;
- dominated repeated loops must be removed;
- cabin capacity remains shared across the direction change.

Classical fixed-sequence ride-candidate generation is not sufficient for fully
dynamic route choices.

## Phase 4: Infrastructure Siting

Initially, crossover locations are fixed scenario inputs. Only after operating
benefits are established should the optimizer decide where infrastructure is
built.

For candidate station \(s\):

```text
build_turnback[s] in {0, 1}
use_turnback[c, k, s] <= build_turnback[s]
```

Possible design models:

```text
sum(build_turnback[s]) <= infrastructure_budget
```

or:

```text
passenger objective + construction_cost[s] * build_turnback[s]
```

Prefer a Pareto comparison across zero, one, and multiple permitted crossover
locations rather than relying on an arbitrary construction-cost coefficient.

## Experiment Matrix

Compare:

```text
operation:
  no turnback
  fixed short-turn patterns
  dynamic turnback

demand:
  symmetric
  directional imbalance
  inner-section concentration
  outer-section concentration

fleet:
  equal available fleet
  equal dispatched fleet
  minimum fleet for a service target

waiting:
  no waiting
  configured waiting
```

Record:

- served and unserved demand;
- waiting and journey time;
- OD-level service and fairness;
- crossover traversals by station and direction;
- cabins assigned to each circulation pattern;
- available, dispatched, and peak active fleet;
- main-line, wait-area, merge, and crossover utilization;
- model size, runtime, incumbent, bound, and gap.

The most important cases are asymmetric demand and concentrated inner-section
demand. Symmetric demand alone may understate the value of short-turning.

## Correctness Tests

Before performance benchmarking:

- disabling every crossover reproduces the existing ring result;
- one cabin follows each deterministic short-turn pattern exactly;
- turnback occurs only after the configured service and wait point;
- mandatory alighting prevents passenger flow across the crossover;
- opposite crossover traversals cannot overlap on a shared resource;
- normal arrivals and crossover merges satisfy the same physical entry
  clearance;
- no route choice creates a disconnected or duplicate cabin state;
- horizon-boundary turnbacks retain enough context for physical clearance;
- replay traverses every selected physical segment in the correct direction;
- tiny graph instances agree with exhaustive route enumeration.

## Interaction with Other Plans

### Fleet Activation and Depots

Turnbacks and optional depot dispatch both change movement topology and active
fleet semantics. Implement and validate them independently first. When
combined, depot dispatch chooses which cabins enter service while turnback
decisions choose their operational circulation.

Do not infer the value of a crossover from one all-stop-derived fixed cabin
placement. Use equal fleet assumptions from
`ean_fleet_activation_and_depots.md`.

### Decomposition

The fixed-movement passenger evaluator is especially valuable because a
turnback graph makes integrated passenger candidates more complicated. Add
turnback route decisions to a future movement master only after the
fixed-movement evaluation is exact.

### Full-Day Operation

Dynamic turnbacks affect the terminal state and wrap-around headways. Do not
combine the first turnback prototype with return-to-depot, cyclic-day, Benders,
delayed headways, or a new CP backend.

## Stage Gates

1. Add physical crossover fixtures and deterministic pattern validation.
2. Run fixed-pattern passenger experiments with mandatory alighting.
3. Stop if short-turn patterns do not improve passenger service, fleet
   efficiency, or a relevant asymmetric-demand case.
4. Build the movement-only switch graph only after a positive result or a
   clear need for dynamic route choice.
5. Add graph-based passenger integration only after fixed-movement evaluation
   is exact and route resources are fully validated.
6. Consider infrastructure siting only after operational turnback value is
   established at fixed locations.

## Thesis Integration

Describe intermediate turnbacks as an optional network and operating-policy
extension, separate from skip-stop decisions. The abstract model should use a
directed movement graph with route choices, while the implementation section
may explain that the first experiment restricts cabins to a finite pattern
library.

The evaluation should separate:

- the value of operating a configured crossover;
- the value of dynamically choosing when to turn;
- the value of choosing the crossover location;
- interactions with fleet size and asymmetric demand.

Do not present fixed-pattern results as evidence that the fully dynamic graph
has been optimized.

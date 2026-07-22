# EAN Optimized Initial Placement Design Record

## Status

Implemented as the `OPTIMIZED_INITIAL_PLACEMENT` v0 fleet mode.

The implementation uses a fixed future ring visit list with a selectable
initial offset. A compact station or rope boundary shell connects directly to
the first active visit; inactive earlier slots do not represent pre-service
movement. Source dispatch and sink recovery were removed; recovery remains
separate future work.

This plan replaces explicit source deployment during `[0, W)` with an
optimized, physically feasible network state at passenger-service start `W`.
Recovery after `T` remains a separate open design problem.

This is the design record that motivated the implemented v0 formulation. The
normative summary is `current_architecture.md`; remaining recovery and
capacity work is tracked in `docs/plans`.

## Motivation

The passenger optimization does not necessarily need to know how cabins were
dispatched from a source depot. It needs the best physically feasible state of
the active fleet when passenger service begins.

Explicitly modeling a complete warm-up currently creates:

- dispatch variables and source merge constraints;
- complete pre-service cabin trajectories;
- Stop/Skip and waiting decisions for every warm-up visit;
- headway candidates and all-pairs constraints before passenger service;
- artificial dependence on a selected source boundary;
- a warm-up horizon whose reachability guarantee becomes difficult once Skip
  and cross-boundary waiting are allowed.

Instead, the model should directly optimize the initial network state at `W`.

## Proposed Semantics

Replace:

```text
Source Reservoir
    -> dispatch during [0, W)
    -> explicit warm-up movement
    -> state at W
```

with:

```text
Ideal Initial Reservoir
    -> optimized physically feasible state at W
    -> passenger service during [W, T]
```

The source reservoir is ignored before passenger service:

- no dispatch times;
- no source headway before `W`;
- no warm-up visits;
- no deployment makespan;
- no requirement that the selected state be reachable from one physical source
  within a finite warm-up period.

Inactive cabins remain outside the network. Every active cabin is placed
directly into a feasible physical state at `W`.

This is not an operational source-deployment model. The fleet mode should
eventually be renamed accordingly, for example:

```text
OPTIMIZED_INITIAL_PLACEMENT
IDEAL_INITIAL_RESERVOIR
BOUNDARY_STATE_FLEET
```

## Time Normalization

`W` no longer represents modeled deployment duration. It is only the
passenger-release boundary.

The optimization can either retain absolute times:

```text
Passenger Service [W, T]
```

or normalize the service model:

```text
Passenger Service [0, D]
D = T - W
```

Exports can restore the calendar offset afterward.

## Why an Instantaneous Snapshot Is Insufficient

A set of positions that satisfies all constraints exactly at `W` may have no
feasible continuation immediately after `W`.

Example:

- one cabin is on a slower service branch;
- a following cabin is on a faster skip branch;
- both positions are collision-free at `W`;
- both cabins are scheduled to reach the shared exit switch almost
  simultaneously after `W`.

The state is instantaneously valid but violates the future merge headway.

The required contract is therefore:

> Select a physically feasible state at `W` that has a feasible continuation
> into the passenger-service EAN.

## Initial Boundary State

Introduce an explicit boundary state for every potential cabin:

```text
cabin_active
physical component occupied at W
selected route branch
progress on the current movement
previous physical event
next scheduled physical event
ongoing resource occupancy
elapsed and remaining waiting
passenger load = 0
```

Possible physical states include:

- on a rope segment;
- on a service approach or exit segment;
- on a platform segment;
- waiting at an allowed station location;
- on a skip branch;
- exactly at an entry or exit switch.

## Initial Boundary Shell

Do not represent the initial state as an isolated position. Build a small
trajectory fragment around `W`:

```text
last relevant event before W
current physical state at W
first relevant event after W
```

This `InitialBoundaryShell` must contain enough information to prove:

- physical separation at `W`;
- valid occupancy of rope and station resources;
- valid route choice before `W`;
- correct continuation of Skip or service movement across `W`;
- correct continuation of waits across `W`;
- headways between events before and after `W`;
- a seamless transition into the regular passenger-service visits.

The shell replaces a complete warm-up trajectory.

## Visit Continuation Strategy

The initial-placement implementation will use one fixed directed ring visit
list per cabin with a selectable initial offset. Slots before the selected
offset are inactive; they do not represent pre-service movement. The boundary
shell connects directly to the first active visit, after which the existing
Stop/Skip and waiting decisions continue unchanged.

Alternatives considered:

- Dynamic visits select their switch inside the MILP. This supports arbitrary
  graph branches, but makes timings, headways, passenger candidates, and visit
  transitions conditional and substantially enlarges the formulation.
- State-specific paths duplicate a complete future trajectory for every
  possible initial state. This is simpler locally but multiplies the service
  EAN by the number of possible starts.

The fixed ring list is preferred for the current single directed ring because
it has the same initial-placement expressiveness with a smaller, stronger
model. If the physical network later permits a visit to continue to different
next switches, this decision must be revisited and the visit layer changed to
dynamic graph visits or explicit path alternatives.

## Cabins on Rope Segments

The current EAN does not directly represent a cabin initially located inside a
rope segment.

Represent such a state through virtual boundary events:

```text
exit_time[c] <= W <= next_entry_time[c]

next_entry_time[c]
    = exit_time[c] + rope_travel_time
```

The continuous rope progress is:

```text
progress[c]
    = (W - exit_time[c]) / rope_travel_time
```

This permits every position along the rope without discretizing the segment.

For cabins on the same constant-speed rope, the virtual exit times and their
normal exit-switch headways imply the required spatial separation at `W`.
This implication must be proved and validated for every supported speed
profile.

## Cabins Inside Stations

Represent an initial station state with a local visit whose physical activity
overlaps `W`:

```text
entry_time <= W <= exit_time
```

The cabin may be:

- traversing the service route;
- traversing the skip route;
- moving along the platform;
- waiting at an allowed waiting position.

The service or skip decision may have occurred before `W`, while the exit
event and its headway occur after `W`.

## Waiting Across `W`

Waiting must be allowed to cross the passenger-service boundary:

```text
wait_start <= W <= wait_end
```

Track:

```text
elapsed_wait = W - wait_start
remaining_wait = wait_end - W
```

For finite station waiting limits:

```text
elapsed_wait + remaining_wait <= max_wait
```

If waiting is unbounded, determine which parts of the elapsed history are
actually relevant to future feasibility.

A cabin that entered the station before `W` may still board passengers if its
modeled boarding event occurs during `[W, T]`.

## Passenger-Service Coupling

Passenger eligibility depends on event times, not on when the containing visit
started:

```text
boarding_time in [W, T]
alighting_time in [W, T]
```

Therefore:

- a visit beginning before `W` may serve passengers after `W`;
- a Skip decision before `W` may create an exit event after `W`;
- a wait beginning before `W` may continue into service;
- passenger candidate generation must include overlapping boundary visits.

After the first regular post-boundary event, the existing passenger-service EAN
should take over.

## Boundary Headways

The initial placement must cover three headway relationships:

```text
pre-W event  <-> pre-W event
pre-W event  <-> post-W event
post-W event <-> post-W event
```

The first group should only be generated for events needed to certify the
initially occupied resources.

The second group is essential. For example, a virtual source event at
`W - 0.3` must be able to constrain a regular event at `W + 0.2`.

The third group remains part of the normal passenger-service model.

Do not assume a globally fixed cabin order without proving that overtaking is
impossible. Service and skip branches may merge in a different order at an
exit switch.

## Fleet Variables

The initial placement layer should use variables conceptually similar to:

```text
cabin_active[c]
initial_component[c, resource]
initial_route[c, service_or_skip]
previous_event_time[c]
next_event_time[c]
initial_wait_elapsed[c]
initial_wait_remaining[c]
```

The exact representation should follow the existing EAN timing and headway
builders rather than introduce unrelated physical semantics.

The fleet constraint remains:

```text
sum(cabin_active[c]) <= K
```

The passenger optimization jointly chooses:

- how many cabins are active;
- where they are at `W`;
- their current route and movement state;
- their first service events;
- subsequent Stop/Skip and waiting behavior.

## Removed Warm-Up Variables

The optimized initial-placement mode should not create:

- `dispatch_time`;
- Source dispatch headway orders;
- warm-up deployment makespan;
- complete visits lying strictly before `W`;
- warm-up passenger-independent route variables beyond the boundary shell;
- warm-up headway pairs unrelated to a resource occupied at `W`.

## Objective

The initial objective order should be:

```text
1. unserved demand
2. waiting or journey time
3. active cabins
4. optional initial-state regularization
5. recovery objective, once defined
```

Potential initial-state regularization must not silently reintroduce a
deployment policy. If used, it should only break symmetry or prefer simpler
equivalent states.

## Proposed Architecture

```text
EanInitialPlacementModelBuilder
    active fleet
    physical boundary state at W
    InitialBoundaryShell
    rope and station occupancy
    cross-boundary headways

EanPassengerMovementModelBuilder
    overlapping boundary visits
    regular visits after W
    Stop/Skip and waiting
    passenger assignment

EanRecoveryModelBuilder
    to be designed separately
```

All three layers should reuse one shared physical timing, route, occupancy, and
headway interpretation.

## Implementation Phases

### Phase 1: Boundary-state specification

- enumerate every physical state supported at `W`;
- define previous and next events for each state;
- define which resources are occupied;
- define waiting history and residual state;
- define passenger eligibility for overlapping visits.

### Phase 2: Rope boundary states

- support arbitrary continuous rope positions;
- derive positions from virtual event times;
- prove equivalence between exit headways and rope separation;
- connect the next entry event to the normal service EAN.

### Phase 3: Station boundary states

- support service, skip, platform, and waiting states;
- reuse existing station timing builders;
- model cross-boundary resource occupancy;
- connect boundary visits to passenger candidates.

### Phase 4: Boundary headways

- generate only headways required by the boundary shell;
- include pre-/post-boundary conflicts;
- validate merge ordering across service and skip branches;
- compare pair counts with the explicit warm-up model.

### Phase 5: Fleet integration

- optimize active fleet count and initial placement jointly;
- preserve cabin-ID symmetry breaking;
- remove source dispatch variables and objectives;
- retain automatic or explicit `K`.

### Phase 6: Export and replay

- export the optimized physical state at `W`;
- create replay context for cabins already inside resources;
- avoid synthetic pre-service station visits;
- preserve absolute-time offsets if the solver uses normalized time.

## Tests

Add tests for:

- an initial cabin at every supported rope position;
- multiple cabins on one rope with exact minimum separation;
- a service route crossing `W`;
- a skip route crossing `W`;
- waiting beginning before and ending after `W`;
- a boundary visit boarding passengers after `W`;
- pre-/post-boundary exit-switch conflicts;
- service/skip merge order changes;
- empty, partial, and full active fleets;
- equivalence to explicit warm-up states where both models overlap;
- lower variable and headway-pair counts than the explicit warm-up model;
- unchanged Fixed-Start behavior.

## Open Questions

- Is an arbitrary optimized state acceptable even if no physical source could
  have produced it in finite time?
- Which speed profiles permit rope spacing to be certified only through
  virtual exit times?
- Is elapsed unbounded waiting relevant, or is remaining waiting sufficient?
- Which physical states must be excluded because they have no valid
  continuation?
- Should `W` remain in solver time or exist only as an export offset?
- Should the current reservoir mode be replaced or retained as a separate
  operational deployment option?
- How should automatic `K` relate to the existence of a feasible optimized
  initial placement?
- What terminal state and recovery guarantee will be required at `T`?

## Acceptance Criteria

The future implementation is complete when:

- no explicit warm-up trajectory is required;
- active cabins may start anywhere physically supported at `W`;
- rope, service, skip, platform, and waiting boundary states are represented;
- all selected states have a feasible continuation;
- headways crossing `W` are enforced;
- passengers can use visits overlapping `W`;
- source dispatch variables and warm-up headway pairs are absent;
- exports and replay represent the true boundary state;
- model size is measurably lower than the explicit warm-up formulation;
- Fixed-Start models remain structurally unchanged;
- recovery remains explicitly separated until its real bound is established.

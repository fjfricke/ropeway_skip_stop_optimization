# EAN Initial Placement Model Reference

## Status

Implemented v0 modeling contract. The production formulation represents the
physical fleet state with station and rope boundary selectors connected to a
fixed future ring visit list at a selectable initial offset. It does not
materialize a pre-service ring cycle.

It replaces explicit source deployment before passenger service. Recovery
after passenger service is intentionally outside the scope of this document.

This document records the detailed model contract. Future extensions and open
research questions are tracked separately in `docs/plans`.

## 1. Model Contract

The model chooses the best physically feasible state of at most `K` empty
cabins at passenger-service start.

The selected state must:

- satisfy all physical spacing and resource-occupancy constraints at the
  boundary;
- contain all residual timing and occupancy information that still affects
  events after the boundary;
- connect exactly to the regular passenger-service EAN;
- permit service/skip routes and waiting that cross the boundary;
- contain no passengers before passenger service begins.

The model does not prove that a real source depot could have produced the
selected state.

## 2. Time Convention

Normalize passenger-service start to:

```text
W = 0
```

Passenger service is optimized on:

```text
[0, D]
```

where:

```text
D = T - W
```

Exports and replay may add the original absolute `W` offset afterward.

Boundary-state variables may use negative event times when an activity began
before passenger service.

## 3. Sets

```text
C  potential cabins, ordered by cabin ID
S  EAN entry switches on the directed ring
R  physical rope segments between EAN stations
Q  supported initial-state templates
P  physical headway checkpoints
```

Supported initial-state templates in v0:

```text
ROPE
SERVICE_ROUTE
SKIP_ROUTE
PLATFORM_WAIT
ENTRY_SWITCH
EXIT_SWITCH
```

Exact switch states should use one deterministic ownership convention to avoid
two templates representing the same state.

Recommended convention:

```text
an event exactly at 0 belongs to the post-boundary activity
```

## 4. Fleet Activation

Variables:

```text
active[c] in {0,1}
state_selected[c,q] in {0,1}
```

Every active cabin selects exactly one initial state:

```text
sum(state_selected[c,q] for q in Q[c]) = active[c]
```

Fleet limit:

```text
sum(active[c] for c in C) <= K
```

Cabin-ID activation symmetry:

```text
active[c+1] <= active[c]
```

Inactive cabins:

- occupy no physical resource;
- create no boundary event;
- create no regular visit;
- consume no passenger capacity;
- create no headway candidate.

## 5. Initial Passenger State

All active cabins start empty:

```text
initial_load[c] = 0
```

Demand release times satisfy:

```text
release_time[g] >= 0
```

No passenger may board before time `0`.

## 6. Rope Initial State

For a cabin on the rope after station switch `s`, define:

```text
rope_selected[c,s] in {0,1}
previous_exit_time[c,s]
next_entry_time[c,s]
```

Timing:

```text
next_entry_time[c,s]
    = previous_exit_time[c,s] + rope_travel_time[s]
```

Conditional overlap with the boundary:

```text
previous_exit_time[c,s] <= 0
next_entry_time[c,s] >= 0
```

These inequalities are activated only when `rope_selected[c,s] = 1`.

With the post-boundary ownership convention, a strict interior rope state is:

```text
previous_exit_time[c,s] <= -epsilon
next_entry_time[c,s] >= epsilon
```

Endpoint states use the corresponding switch template.

### Rope position

For constant speed:

```text
elapsed = -previous_exit_time[c,s]
progress = elapsed / rope_travel_time[s]
position = progress * rope_length[s]
```

The optimization does not require an explicit position variable if rope
spacing can be proved from the virtual exit times.

For non-constant speed profiles, either:

- prove that the existing temporal exit headway implies the required spatial
  separation throughout the segment; or
- add a profile-aware position and spacing formulation.

Do not silently assume this equivalence.

## 7. Rope Ordering and Headways

### Local initial ordering

At time `0`, cabins are empty and have no cabin-specific properties. Their IDs
may therefore be assigned as a symmetry convention.

For two cabins `a < b` selected on the same directed rope, define the lower ID
as the cabin farther ahead in the travel direction. It must have left the
previous exit switch earlier:

```text
previous_exit_time[a,s] + rope_headway[s]
    <= previous_exit_time[b,s]
```

Conditionally:

```text
previous_exit_time[a,s] + rope_headway[s]
    <= previous_exit_time[b,s]
       + M * (2 - rope_selected[a,s] - rope_selected[b,s])
```

Because the order is fixed by the local Cabin-ID symmetry convention, the
reverse inequality is not needed.

Therefore, for initial cabins on one rope, do not create both:

```text
a before b
b before a
```

### Limits of fixed ordering

This fixed ordering is valid only for initial packing on a single non-branching
resource.

It must not be applied globally to all later checkpoints because:

- service and skip routes are parallel branches;
- a following cabin may use the faster skip branch;
- cabins may reach the common exit switch in a different order;
- waiting may change the order at a merge.

At such merges, the order remains a decision.

## 8. Service-Route Initial State

For a service route at switch `s`, define:

```text
service_selected[c,s] in {0,1}
entry_time[c,s]
platform_entry_time[c,s]
wait_entry_time[c,s]
platform_exit_time[c,s]
exit_switch_time[c,s]
wait_time[c,s] >= 0
```

Timing:

```text
platform_entry_time
    = entry_time + entry_to_platform_entry

wait_entry_time
    = platform_entry_time + minimum_platform_travel

platform_exit_time
    = wait_entry_time + wait_time

exit_switch_time
    = platform_exit_time + platform_exit_to_exit_switch
```

Boundary overlap:

```text
entry_time <= 0 <= exit_switch_time
```

Waiting:

```text
wait_time = 0
```

for `NO_WAITING`, and:

```text
0 <= wait_time <= max_wait
```

for finite `END_OF_PLATFORM_WAIT`.

If no explicit maximum exists, derive a finite model bound without changing
the feasible post-boundary behavior.

## 9. Location Within a Service Route

The event times determine the physical substate at time `0`:

```text
entry_time <= 0 < platform_entry_time
    -> service approach

platform_entry_time <= 0 < wait_entry_time
    -> platform traversal

wait_entry_time <= 0 < platform_exit_time
    -> waiting at platform exit

platform_exit_time <= 0 < exit_switch_time
    -> service exit movement
```

Explicit region binaries are only required when:

- exports need the exact physical substate;
- different resources apply to different route sections;
- additional segment-level capacities must be enforced.

The current `SkipStopTiming` contains aggregated durations. Exact physical
position and replay will require a segment-level timing interpretation derived
from the physical service route.

## 10. Waiting Across the Boundary

For a wait overlapping time `0`:

```text
wait_entry_time <= 0 <= platform_exit_time
```

Derived values:

```text
elapsed_wait = -wait_entry_time
remaining_wait = platform_exit_time
```

For a finite wait limit:

```text
elapsed_wait + remaining_wait <= max_wait
```

If only future feasibility matters and waiting is unbounded, determine whether
elapsed waiting can be normalized without loss of generality.

The cabin may board passengers after time `0` if its boarding event occurs at:

```text
platform_exit_time >= 0
```

## 11. Skip-Route Initial State

Variables:

```text
skip_selected[c,s] in {0,1}
entry_time[c,s]
exit_switch_time[c,s]
```

Timing:

```text
exit_switch_time
    = entry_time + skip_entry_to_exit_switch
```

Boundary overlap:

```text
entry_time <= 0 <= exit_switch_time
```

The exit event after time `0` participates in the normal exit-switch merge
headways.

## 12. Initial Resource Occupancy

Every selected state must identify the physical resources occupied at time
`0`.

At minimum:

```text
rope segment
service approach
platform movement
platform-exit waiting position
service exit
skip branch
entry or exit switch
```

For resources already represented by EAN headway semantics, reuse the same
checkpoint interpretation.

If the physical model contains capacities not represented by the EAN, either:

- extend the shared EAN resource model globally; or
- explicitly state that the initial state is EAN-feasible rather than fully
  physically feasible.

Do not add boundary-only physical rules that disagree with the service model.

## 13. Boundary Headway Candidates

Boundary states create the same logical checkpoint events as regular visits:

```text
platform entry
platform exit / wait occupancy
exit switch
```

Candidates can occur before or after time `0`.

Generate conflicts for:

```text
boundary candidate <-> boundary candidate
boundary candidate <-> regular service candidate
regular candidate  <-> regular candidate
```

Pairs whose time bounds prove sufficient separation should not be generated.

Example pruning:

```text
latest_time[a] + headway <= earliest_time[b]
```

implies fixed order and requires no binary order variable.

## 14. Ordering Rules by Case

### Case A: Initial cabins on the same single-lane rope

Order may be fixed by Cabin ID.

Required:

```text
one directed headway inequality
```

Not required:

```text
two-way disjunction
```

### Case B: A pre-boundary event and a post-boundary event

Their temporal order is already known:

```text
pre-boundary event <= 0 <= post-boundary event
```

Required:

```text
pre_event + headway <= post_event
```

No order binary is required.

### Case C: Service/Skip merge at an exit switch

The order is not known because different branches and waits may reorder
cabins.

Required:

```text
a_exit + headway <= b_exit
OR
b_exit + headway <= a_exit
```

Both inequalities and one order binary are required unless bounds fix the
order.

### Case D: Future events at a shared checkpoint

The order is generally not known and must use the existing disjunction.

Do not impose Cabin-ID order globally.

### Case E: Platform-exit waiting occupancy

Use interval occupancy semantics:

```text
leader.platform_exit + headway
    <= follower.wait_entry
```

or the reverse ordering.

If one interval is known to span time `0` and the other starts after `0`, the
order may already be fixed.

## 15. Boundary Carry-Over

Initial placement must pass all still-relevant state into passenger service.

### Rope state

```text
first_regular_visit.switch_time
    = boundary_rope.next_entry_time
```

### Service or skip state

The boundary visit is itself the first regular cabin visit. Its entry may be
negative, while its boarding, exit, and next-switch events may be positive.

### Ongoing wait

The boundary visit's platform-exit event remains a regular service event.

### Headway cooldown

If a checkpoint was used shortly before time `0`, its event remains a boundary
candidate until all possible post-boundary conflicts are excluded.

No additional continuation-feasibility subproblem is needed. The regular
passenger-service constraints establish the feasible continuation.

## 16. Passenger Constraints

Passenger eligibility depends on event times:

```text
board_time >= release_time >= 0
alight_time <= D
```

Do not require:

```text
visit.entry_time >= 0
```

A boundary service visit may:

- begin before `0`;
- wait across `0`;
- board passengers after `0`;
- continue as an ordinary passenger-carrying visit.

## 17. Time Bounds

Boundary event variables need finite negative lower bounds.

Derive them from the selected state:

```text
rope lower bound
    = -rope_travel_time

skip lower bound
    = -skip_travel_time

service lower bound
    = -(service_travel_time + maximum_relevant_wait)
```

Do not use one unnecessarily large global negative Big-M.

Every conditional timing and headway row should use state-specific bounds.

## 18. Symmetry

Safe symmetry breaking:

- active Cabin IDs form a prefix;
- Cabin IDs determine local order on one initial single-lane resource;
- equivalent state templates use a deterministic ordering;
- unused state variables are fixed to zero where possible.

Unsafe symmetry breaking:

- fixed Cabin-ID order at every future exit switch;
- fixed order across service and skip branches;
- fixed global order when overtaking through station branches is possible.

## 19. Required Model Builders

Proposed ownership:

```text
EanInitialPlacementStateBuilder
    physical state templates and bounds

EanInitialPlacementModelBuilder
    fleet activation
    state selection
    initial occupancy
    local ordering

EanBoundaryHeadwayCandidateBuilder
    boundary checkpoint events
    cross-boundary conflict candidates

EanBoundaryMovementLinkBuilder
    connection to first regular visits

EanPassengerMovementModelBuilder
    existing post-boundary movement and passenger service
```

All builders must reuse the existing physical timing and headway builders.

## 20. Variables Not Required

The optimized initial-placement mode does not need:

- source switch configuration;
- dispatch times;
- source dispatch headway orders;
- deployment makespan;
- complete warm-up visits;
- pre-boundary passenger variables;
- a separate continuation-feasibility model.

## 21. Validation

The extracted solution should validate:

- every active cabin has exactly one boundary state;
- every inactive cabin has no state or events;
- rope progress lies within its segment;
- initial rope spacing is sufficient;
- station resource occupancy is valid;
- waits obey station rules;
- boundary checkpoint headways hold;
- cross-boundary headways hold;
- every boundary state connects to exactly one regular trajectory;
- all cabins start empty;
- no passenger event occurs before service start.

## 22. Tests

Required focused tests:

- one cabin at arbitrary rope progress;
- two cabins at exactly the rope spacing limit;
- reversed Cabin-ID rope placement is removed only by symmetry;
- no reverse rope-order inequality is generated;
- service approach crossing the boundary;
- platform traversal crossing the boundary;
- waiting crossing the boundary;
- skip route crossing the boundary;
- boundary wait versus future platform-exit conflict;
- boundary exit versus future exit-switch conflict;
- service/skip merge requiring a two-way order disjunction;
- bounds fixing a merge order without a binary;
- boundary visit boarding after time `0`;
- partial and full active fleets;
- unchanged Fixed-Start artifacts and models.

## 23. Open Decisions

- Can every supported rope speed profile use temporal exit separation as a
  proof of spatial separation?
- Which segment-level station resources are missing from the current EAN?
- How should unbounded elapsed waiting be normalized?
- Is overtaking through every service/skip station physically intended?
- Should the first implementation use pairwise local rope constraints or an
  ordered-slot formulation?
- How is automatic `K` related to the existence of an initial placement?
- Which state representation is needed by replay and visualization?

## 24. Acceptance Criteria

The initial-placement model is acceptable when:

- all supported physical locations at service start can be represented;
- no explicit warm-up trajectory is built;
- local rope ordering uses one directed inequality after symmetry breaking;
- variable merge orders retain the complete two-way disjunction;
- boundary resource occupancy and headway memory are preserved;
- boundary visits connect directly to passenger service;
- overlapping visits may board passengers after service start;
- model bounds remain finite and resource-specific;
- extracted states pass independent physical and EAN validation;
- model size is lower than the explicit warm-up formulation;
- Fixed-Start behavior remains structurally unchanged.

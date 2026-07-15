# EAN Fleet Activation and Depot Plan

Status: **future semantic and experimental work**

## Goal

Remove the current dependence on an exogenously selected all-stop cabin count
and start placement. Allow skip and all-stop policies to use the same available
fleet while deciding how many cabins to dispatch.

Use ideal phase-boundary reservoirs for setup and teardown, while modeling
every depot that remains usable during passenger service as a physical
resource. The boundary abstraction isolates line and station capacity from
overnight storage throughput; the operational depot captures dynamic fleet
changes during the measured service period.

This is a model-semantic extension, not a solver-preserving optimization.
Implement it after the current structural reformulations are stable and before
the final skip-benefit experiment campaign. The existing fixed-start model
remains the exact reference for regression tests and controlled fixed-fleet
experiments.

## Current Limitation

`ContinuousAllStopMaxCabinStartBuilder` derives a cabin count from the all-stop
cycle duration and the largest all-stop headway, then distributes those cabins
over equal phases of that all-stop cycle. Several examples retain only every
second generated start.

This construction is deterministic and useful for reproducible examples, but
it does not answer any of the following:

- how many cabins should be available;
- how many cabins should actually enter service;
- whether skip operation can safely and usefully operate more cabins;
- whether the chosen initial phases are favorable to skip;
- how many cabins are required to reach a target service level.

An all-stop-derived fleet can therefore bias a skip experiment. Conversely,
forcing a larger fleet onto the line can make all-stop infeasible even though a
real operator would leave surplus cabins in a depot.

## Quantities to Keep Separate

Do not use one ambiguous "cabin count". Report:

```text
available fleet:
  cabins physically available to the optimization

dispatched fleet:
  available cabins that enter service during the modeled period

peak active fleet:
  maximum cabins simultaneously on the line

owned fleet:
  long-term fleet size, relevant only once fleet cost and multi-day inventory
  are modeled
```

Without a cabin cost or service target, an economically optimal fleet size is
undefined. Additional optional cabins cannot worsen the optimum because they
may remain unused.

## Selected Boundary and Depot Architecture

Use three distinct concepts.

### Entry Reservoir

The complete available fleet starts in an ideal source reservoir. It may
dispatch cabins only during the passenger-free warm-up. The source has
unbounded internal capacity and no processing time, but every merge onto the
line must satisfy the physical line, switch, and following-cabin headways.

### Exit Reservoir

During the passenger-free recovery phase, cabins may leave the line into an
ideal sink reservoir. Once a cabin has cleared the physical divergence
checkpoint, it consumes no further resource. The sink adds no storage or
processing headway beyond the physical line exit.

### Operational Physical Depot

If cabins may enter or leave storage during passenger service, use a physical
depot. The first implementation has one depot with:

- explicit entry and exit routes;
- line-side merge and divergence conflicts;
- finite entry and exit processing times;
- a minimum internal dwell time;
- local inventory conservation;
- unlimited internal storage capacity.

The entry and exit reservoirs are disabled during passenger service. New
service-period cabins must come from inventory already placed in the physical
depot by the end of warm-up. Cabins returned to that depot may be redispatched
only through its physical exit.

The simplest layout co-locates the ideal phase-boundary interfaces and the
physical depot inventory. At service start, unused source inventory becomes
initial operational-depot inventory. At service end, inventory already parked
in the physical depot is already clear of the line; cabins still on the line
use the recovery sink.

## Operating Phases

Use one complete model horizon:

```text
[0, W):
  passenger-free warm-up
  entry reservoir enabled
  exit reservoir disabled

[W, W + T]:
  measured passenger service
  boundary reservoirs disabled
  operational physical depot enabled

(W + T, D]:
  passenger-free recovery
  entry reservoir disabled
  exit reservoir enabled

D = W + T + R
```

All passengers must have alighted by \(W+T\). Every cabin must be either in the
physical depot or removed through the exit reservoir by \(D\). For a single
co-located storage facility, both states represent the same end-of-day stored
fleet.

Use one common passenger-free movement policy in warm-up and recovery for
all-stop and skip experiments. It may use deadhead bypasses when the research
question is passenger-service policy rather than non-revenue operation.

## Experiment Questions

Treat the following as separate experiments.

### Fixed Available Fleet

For each fleet cap \(K\), compare all-stop and skip under identical demand,
horizon, waiting, service, and resource conditions:

```text
sum(active[cabin]) <= K
```

This produces the performance curves:

```text
objective_all_stop(K)
objective_skip(K)
```

The primary comparison uses the same \(K\), not independently selected fleets.

### Minimum Fleet for a Service Target

For a required service level \(q\), solve:

```text
minimize dispatched cabins
subject to served demand >= q
```

Repeat for multiple demand-coverage and passenger-time targets. This measures
whether skip provides the same service with fewer cabins.

### Physical Capacity Frontier

Force or maximize the number of dispatched or simultaneously active cabins
without using passenger quality as the only criterion. An all-stop case may be
infeasible for a count that remains feasible with skip. Report that result as a
policy-dependent physical capacity frontier, not as a passenger-objective
comparison.

Prevent artificial last-minute dispatches from counting as usable capacity.
Each counted cabin must enter by a defined reference time and either remain
active through a defined operating interval or complete a minimum certified
service movement.

### Fleet-Cost Tradeoff

Only when a defensible cabin cost is available, evaluate:

```text
passenger objective + cabin_cost * dispatched cabins
```

Prefer a Pareto curve over selecting one arbitrary cost coefficient.

## Phase 0: Controlled Fixed-Start Fleet Sweep

Before changing the model, run fixed-start comparisons for cabin counts whose
initial states are valid for both all-stop and skip. This provides a limited
sensitivity analysis and regression baseline.

Do not use the current all-stop maximum as a claimed skip maximum. Do not
interpret infeasibility caused by an artificially forced fixed placement as a
general physical infeasibility result.

## Phase 1: Ideal Boundary Reservoirs

Introduce a finite set of potential cabins initially outside the service line.
Each potential cabin receives an activation variable:

```text
active[cabin] in {0, 1}
sum(active[cabin]) <= available_fleet_count
```

An active cabin chooses a warm-up dispatch time through the configured entry
reservoir. An inactive cabin remains stored and creates no active visit chain
or line resource consumption.

The first implementation should support one source, one sink, and one
deterministic ring connection. It must include:

- optional cabin activation;
- warm-up dispatch time bounds;
- activation of all generated visits and route decisions by the cabin
  activation;
- merge headways between dispatched cabins and cabins already on the line;
- line-to-sink divergence clearance during recovery;
- a finite available-fleet cap;
- extraction and validation of inactive and dispatched cabins;
- consistent passenger-candidate generation for active cabins only.

`EanCabinStartKind.EARLIEST` alone is not sufficient. It permits delaying a
first event but does not by itself provide explicit fleet activation, depot
inventory, or complete removal of an inactive cabin's visit chain.

Keep the line empty at model time zero. Warm-up is part of the explicit
movement model, so every service-start line state is reached from the source
rather than asserted as an arbitrary initial placement.

## Multi-Round Boundary Reachability

Do not require every cabin to enter or leave within one circulation. The
boundary model must generate enough passenger-free visits for repeated passes
of the source or sink checkpoint.

For a one-directional strongly connected ring, a useful constructive argument
is:

1. Take a feasible periodic target schedule with interchangeable cabins.
2. Follow that schedule with only a subset of its cabin trajectories present.
3. At each period, inject one missing cabin when its target trajectory crosses
   the source checkpoint.
4. Because the complete target schedule is feasible, the subset plus that
   trajectory satisfies every upper-capacity and separation constraint.
5. Repeat until all target trajectories are present.

Removal is the reverse construction: remove one trajectory at its sink passage
per period. Removing a cabin cannot create a new upper-capacity or separation
conflict.

The one-cabin-per-period rule is a conservative existence construction, not a
required dispatch policy. Several cabins may enter or leave within one period
when their target phases and all interface conflicts permit it. The slower
construction is useful because it proves that sufficiently long setup and
teardown windows can reproduce the target line state without relying on that
higher interface throughput.

This proves reachability only under explicit assumptions:

- the target movement is periodic or repeatable during setup and teardown;
- cabins are interchangeable;
- the source and sink lie on every required circulation component;
- passenger-free constraints are monotone under removing cabin trajectories;
- the boundary merge or divergence imposes no stricter requirement than the
  corresponding target trajectory;
- no maintenance, minimum-service, or local-inventory condition distinguishes
  cabin identities.

For multiple disconnected circulation components, provide a boundary interface
for each component or a physical route connecting them.

The argument does not establish unconditional equivalence between an ideal
reservoir and every physical depot. An ideal reservoir can reproduce every
physical-depot dispatch schedule because it has fewer restrictions. The reverse
direction additionally requires that the physical depot can admit or release
at least one cabin per sufficiently long circulation without a stricter throat
or blocking conflict.

Under these assumptions, the useful equivalence is only:

```text
same reachable periodic line state with sufficiently long setup or teardown
```

It is not equality of setup duration, dispatch schedule, operating cost, depot
throughput, or robustness. A physical depot with a narrow throat may need much
longer than the ideal reservoir even when both can eventually produce the same
line state. If the physical interface cannot reproduce a required target phase,
the reservoir remains a relaxation rather than an equivalent representation.

Treat ideal boundary reservoirs as the selected experiment abstraction:

```text
capacity of line and stations with non-limiting setup and teardown storage
```

Do not present their warm-up or recovery duration as a prediction of physical
depot processing time.

## Warm-Up and Recovery Horizon Selection

Treat \(W\) and \(R\) as maximum setup and teardown windows, not as durations
that every solution must consume. Record and, after the passenger and fleet
objectives, minimize the actual deployment and recovery makespans.

The one-trajectory-per-period construction gives conservative topology-specific
bounds for a repeatable ring schedule:

```text
W_max
  = available_fleet_count * setup_period
  + source_clearance

R_max
  = available_fleet_count * recovery_period
  + sink_clearance
```

The setup and recovery periods are canonical passenger-free circulation times,
not unrestricted waiting upper bounds. Use the same \(W_{\max}\) and
\(R_{\max}\), derived from the largest fleet in the experiment matrix, for
all-stop and skip comparisons.

Generate enough source and sink opportunities for every allowed round. A
one-round suffix is not sufficient merely because every cabin passes the
boundary location once: the chosen target phase or physical merge may require
later opportunities.

Before reducing either bound:

- construct an explicit feasible setup and teardown schedule;
- verify every cabin and resource transition;
- rerun with larger windows and check passenger objective, active fleet, and
  service pattern stability;
- record whether the source, sink, or final-clearance deadline is binding.

If the conservative multi-round domains make the integrated MILP too weak,
first solve or construct setup and teardown schedules separately and use them
as fixed boundary plans or MIP starts. Do not silently shorten the windows and
thereby exclude reachable service states.

## Explicit Non-Priority: Arbitrary On-Line Start Placement

Do not first optimize arbitrary initial positions of interchangeable cabins on
the ring. Such a model must certify the pre-horizon movement that produced the
chosen state, enforce headways across time zero, select movement phases, and
break substantial cabin symmetry. Without those conditions, an optimized
placement may be mathematically convenient but physically unreachable.

If steady-state initial placement later becomes necessary, formulate it as the
identity-free cyclic-day model with wrap-around headways rather than as a
standalone free-position heuristic.

## Formulation Outline

For each potential cabin \(c\), use:

```text
y_c:
  cabin is dispatched

d_c:
  dispatch or first merge time

a_c,v:
  operational visit v is active
```

At minimum:

```text
a_c,v <= y_c

y_c = 0
  => no active route, timing, headway, capacity, or passenger decisions

y_c = 1
  => a valid dispatch and complete certified movement prefix
```

Prefer one cabin-level activation to repeated independent visit activation.
Visit activation must still follow the selected finite-horizon semantics.

Add symmetry breaking for interchangeable potential cabins:

```text
y_c >= y_(c+1)

d_c <= d_(c+1) when both cabins are active
```

Cabin identifiers must not create artificial differences in objective or
feasibility.

## Configuration

Represent fleet semantics separately from formulation optimizations:

```text
EanFleetConfig
  mode:
    fixed_starts
    boundary_reservoirs

  available_fleet_count
  warmup_seconds
  recovery_seconds
  boundary_source
  boundary_sink
  operational_depot:
    none
    single_infinite_storage
```

The fleet mode changes the feasible set and therefore must not be included in
`EanOptimizationConfig`. Benchmark metadata must record the complete fleet
configuration.

Stop/skip policy, waiting policy, horizon semantics, and solver settings remain
independent experiment dimensions. An all-stop comparison uses the same
optional-dispatch fleet model with skip decisions disabled.

## Phase 2: Fair Fleet Experiment Matrix

After exact small-instance validation, evaluate:

```text
policy:
  all_stop
  skip

available fleet:
  increasing K values

waiting:
  no_waiting
  configured waiting

objective:
  served demand first
  passenger time second
  dispatched fleet third when appropriate
```

Record:

- available, dispatched, and peak active cabins;
- served and unserved demand;
- waiting and journey time;
- OD-level and fairness metrics;
- dispatch times and depot utilization;
- model size, runtime, incumbent, bound, and gap.

Use the same lexicographic service rule as the general skip-benefit campaign.
Do not report a passenger-time improvement that is caused by serving fewer
passengers.

## Phase 3: Operational Physical Depot

After the boundary-reservoir model is validated, add one physical depot that
may be used during passenger service:

- depot nodes and directed entry and exit paths;
- dispatch and return headways;
- inventory by cabin type;
- line-entry and line-exit conflicts;
- minimum depot dwell time;
- optional withdrawal and redispatch;
- unlimited internal storage capacity in the first implementation.

Here, unlimited capacity \(\kappa_d = \infty\) applies only to the number of
cabins stored inside the depot. It does not remove finite entry and exit
processing times, minimum dwell, merge and divergence headways, switch
conflicts, or line-side blocking. Operational throughput therefore remains
physical even in the infinite-storage case.

The physical `DEPOT` node kind may be reused, but the EAN needs explicit depot
events and resource constraints. A deterministic path from a depot to a switch
is only a mapping convenience, not a complete depot model.

Initially permit at most one line-service interval per cabin:

```text
source or depot -> line -> depot or sink
```

Then evaluate repeated service intervals:

```text
depot -> line -> depot -> line -> depot
```

Repeated dispatch requires a minimum depot dwell, bounded dispatch count, and
reporting of active cabin-hours and depot movements. Otherwise the optimizer
may use storage for cost-free reordering or excessive entry/exit cycles.

For a depot \(d\), conserve local inventory:

```text
inventory[d, after event]
  = inventory[d, before event]
  + returns[d]
  - dispatches[d]
```

When multiple operational depots are added later, keep inventories local.
Cabins may not disappear into one depot and reappear at another without an
explicit offline transfer and travel time.

## Phase 4: Terminal and Full-Day Extensions

The finite passenger-service horizon is not enough to establish a repeatable
all-day operation. Add one of the following terminal contracts.

### Closed Reservoir-to-Reservoir Day

All cabins originate in the entry reservoir, all passengers alight by the end
of passenger service, and every cabin is stored in the co-located operational
depot or exit reservoir at model end. This is the selected first full-day
contract.

### Identity-Free Cyclic Day

Require the physical terminal state after day length \(D\) to equal the initial
state modulo interchangeable cabin identities:

```text
state(c, D) = state(pi(c), 0)
```

On a no-overtaking ring, prefer a type-preserving cyclic order shift over
general assignment binaries when the topology proves it sufficient. Add
wrap-around headways between the final and initial events.

### Hybrid Line and Depot Cycle

Allow some cabins to remain on the line while others are exchanged through
depots:

```text
line state at D = line state at 0, modulo interchangeable identities
depot inventory by type at D = depot inventory by type at 0
```

This must preserve mixed stop, skip, and waiting operation. Do not constrain
the terminal state through a fixed all-stop or no-wait policy.

### Multi-Day or Rolling Operation

Use a multi-day supercycle only when fleet inventories or operating states
genuinely differ between days. Use rolling horizon for operational replanning,
not as a proof of indefinite extendability.

## Correctness Tests

Before performance benchmarking:

- on a tiny source-entry fixture, fix every activation and dispatch event and
  reproduce the equivalent deterministic-start result;
- fix selected activations to zero and verify that no visit, headway,
  passenger, or capacity decision remains active for those cabins;
- enumerate tiny dispatch cases and compare the optimum;
- validate source merge and sink divergence headways;
- validate construction and removal over multiple warm-up/recovery rounds;
- validate the assumptions of the periodic target-state reachability argument
  on tiny rings;
- validate physical-depot merge, divergence, dwell, and inventory constraints;
- verify all-stop and skip with the same available fleet;
- test empty dispatch, partial dispatch, and full dispatch;
- test horizon-boundary dispatch and complete post-horizon clearance;
- validate extracted plans against the physical scenario.

## Stage Gates

1. Keep the fixed-start model as default until optional dispatch matches exact
   tiny cases and produces valid extracted plans.
2. Use ideal reservoirs only in warm-up and recovery; service-period fleet
   changes require the physical operational depot.
3. Do not combine the first dispatch prototype with Benders, delayed headways,
   or a new CP backend.
4. Add only one infinite-storage physical depot first. Add finite storage,
   multiple depots, and offline transfers separately.
5. Apply decomposition only after the active-fleet semantics are stable; cabin
   activation then belongs in the movement master.
6. Run the final skip-benefit campaign only after reporting fleet assumptions
   explicitly and comparing at equal available fleet or equal service target.

## Thesis Integration

Update the abstract mathematical model to distinguish available, dispatched,
and active cabins. Describe optional dispatch as a semantic extension rather
than a performance optimization.

The implementation chapter should state that fixed all-stop-derived starts are
the current baseline and explain phase-boundary reservoirs, the reachability
assumptions, activation, dispatch, symmetry breaking, and operational-depot
resources. The evaluation chapter should report fleet-cap and service-target
curves rather than one assumed "optimal" cabin count.

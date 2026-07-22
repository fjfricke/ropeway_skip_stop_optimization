# EAN Terminal Recovery Feasibility

Status: **future research and implementation plan**

## Decision

Keep the implemented finite-horizon contract unchanged:

```text
passenger cutoff:          T
configured tail:           delta_tail
certification horizon:     H = T + delta_tail
```

Passengers must complete their rides by `T`. Movement, route clearance, and
relevant resource conflicts are certified through `H`, but the model does not
require a depot return or an empty network at `H`.

An ideal sink recovery is a separate future terminal mode. It must not change
the meaning of `tail_seconds` or silently replace the current certification
horizon.

## Goal

Determine whether every feasible physical state at `T` can be continued until
all active cabins leave the directed ring through one ideal sink. Recovery is
only a feasibility condition:

- no passenger service occurs after `T`;
- waiting remains available where the physical model permits it;
- all movement, occupancy, and headway constraints remain valid until return;
- every active cabin leaves at its first modeled sink passage after `T`;
- the ideal sink adds no processing time, storage limit, or outgoing headway;
- no recovery-time objective is required.

The sink must lie on the fixed directed ring and must be traversed by every
active trajectory. From any ring position, the next sink occurrence is
topologically at most one complete ring away. Waiting can delay that occurrence
in time, but it cannot require another topological cycle.

## Non-Goals

This work does not initially:

- model a physical depot, siding, or sink capacity;
- minimize a recovery makespan;
- derive an operational formula `H = T + R`;
- forbid waiting after `T`;
- derive an automatic fleet upper bound;
- change optimized initial placement or fixed-start semantics;
- support branches that can avoid the selected sink.

## 1. Define the Terminal State at `T`

The terminal state passed from passenger service to recovery must contain all
information needed to continue the physical schedule. A cabin position alone
is insufficient. Define a boundary state `sigma_T` containing at least:

- active cabins;
- the selected station or rope state of each cabin at `T`;
- any route or rope traversal already in progress;
- residual minimum travel or service time;
- elapsed and remaining permitted waiting state;
- occupied station, rope, and switch resources;
- the last relevant checkpoint occurrence before `T`;
- local precedence decisions whose separation interval crosses `T`;
- passenger emptiness at `T`.

The state definition must be shared by monolithic recovery, decomposition, plan
extraction, and replay. It should reuse the initial-placement boundary-state
vocabulary where the physical meanings coincide.

## 2. Investigate a Universal Continuation Lemma

First attempt to prove the strongest useful statement:

> For every feasible passenger-service state `sigma_T` on a directed ring,
> there exists a conflict-free continuation that removes every active cabin at
> the next sink passage while preserving all physical constraints.

The theorem domain must explicitly state:

- one directed ring without overtaking;
- one sink entry contained in every trajectory;
- homogeneous or otherwise order-compatible cabins;
- the exact waiting permissions and finite storage capacities;
- station service or skip choices after `T`;
- merge, platform, switch, and rope headway semantics;
- whether any maximum waiting time remains active after `T`.

Candidate constructive proof:

1. Preserve the cyclic order already present at `T`.
2. Select a passenger-free continuation for the leading cabin.
3. Delay each following cabin only where permitted until all predecessor
   headways and occupancies are satisfied.
4. Remove a cabin immediately when it reaches the sink.
5. Observe that removal deletes future resource use and therefore cannot create
   a new conflict.
6. Continue until the ring is empty.

The proof must address station buffers and merges explicitly. A feasible
instantaneous state does not by itself prove that the required waiting is
available or that a deadlock cannot occur.

### Outcome A: lemma proved

If the lemma holds for the implemented physical assumptions, no recovery MILP
is required for passenger optimization. Generate the recovery trajectory
constructively after solving and validate it with the normal physical replay.
The proof and replay become the terminal feasibility certificate.

### Outcome B: lemma refuted or too restrictive

Retain explicit recovery feasibility as a separate subproblem. Record minimal
counterexamples because they determine which terminal-state features and cuts
are necessary.

## 3. Reference Monolithic Recovery Model

Before implementing decomposition, define a small exact reference model:

- append a recovery suffix containing at most one repeated ring;
- allow normal Stop/Skip and waiting decisions after `T`;
- disable all passenger variables in the suffix;
- continue route chaining, occupancy, and headway constraints across `T`;
- remove each cabin at its next sink entry;
- deactivate every later route and resource occurrence.

If the constructed suffix contains exactly one reachable sink occurrence for
each boundary state, return-selection binaries are unnecessary. If a common
endogenous visit list contains several sink candidates around `T`, use binary
`q[c,k]` and require:

```text
sum(q[c,k] for k in sink_candidates[c]) = cabin_active[c]
q[c,k] = 1  =>  sink_entry_time[c,k] >= T
```

The selected sink visit has an arrival event but no following station route.
The preceding active route still chains into this event.

The suffix length is topological, not temporal. Permitted waiting may make the
duration much longer than the no-wait travel time while the trajectory still
uses no more than the path from its state at `T` to the next sink.

## 4. Technical Time Domain

Sink recovery has no predefined operational end `H`. A finite MILP time domain
is still required. Derive a technical completeness bound `B_tech` that is large
enough for every feasible one-ring recovery schedule in the theorem domain.

Investigate bounds based on:

- the number of remaining temporal events;
- maximum primitive travel, service, waiting, and headway lags;
- an acyclic precedence graph after fixing local orders;
- finite station-storage capacities.

The thesis and API must distinguish this numerical bound from an operational
recovery guarantee. If no finite complete bound exists under unbounded waiting,
either derive a constructive schedule with a finite bound or state the
additional bounded-wait assumption required by the solver.

## 5. Logic-Based Decomposition

If universal constructive recovery cannot be proved, evaluate:

```text
master:
  fleet initialization
  passenger service through T
  terminal state sigma_T

subproblem:
  passenger-free continuation from sigma_T
  at most one topological ring suffix
  removal of every active cabin at the sink
```

Workflow:

1. Solve the passenger-service master.
2. Fix `sigma_T` in the recovery feasibility subproblem.
3. Accept the solution when the subproblem is feasible.
4. If it is infeasible, derive a logic-based feasibility cut.
5. Resolve the master until a recoverable terminal state is found or
   infeasibility is proved.

Start with the monolithic reference model to validate the decomposition on
small instances. A no-good cut excluding the complete terminal binary state is
correct but likely weak. Prefer cuts over a minimal conflicting combination of:

- terminal resource occupations;
- cabin cyclic order;
- station-route choices crossing `T`;
- precedence decisions crossing `T`;
- bounded-wait or storage conditions.

Classical LP Benders is not assumed to apply because the recovery subproblem
contains integer route and ordering decisions. Treat this as logic-based
Benders or branch-and-check unless a stronger subproblem structure is proved.

## 6. Fleet-Mode Integration

Recovery is orthogonal to fleet initialization and should eventually be
selected by a separate terminal configuration:

```text
fleet mode:
  fixed starts
  optimized initial placement

terminal mode:
  certification horizon
  ideal sink recovery
```

Both fleet modes must use the same recovery builder, terminal-state contract,
and validator. The default terminal mode remains the certification horizon.

## 7. Evidence and Tests

Before production use:

- enumerate small feasible states at `T` and search for recovery
  counterexamples;
- include station, rope, skip, service, and waiting boundary states;
- test headways and occupancies crossing `T`;
- test empty, partial, and full active fleets;
- verify that every active cabin encounters the sink within one topological
  suffix;
- verify that waiting changes times but not the number of required ring visits;
- compare constructive, decomposed, and monolithic feasibility decisions;
- compare extracted recovery trajectories with physical replay;
- verify unchanged plans and model structure for the default certification
  horizon.

## Acceptance Criteria

This future task is complete when:

- the terminal state `sigma_T` is formally defined;
- the universal continuation lemma is proved under explicit assumptions or
  replaced by documented counterexamples;
- one-ring topological sufficiency is proved for the selected sink topology;
- the technical time bound is justified without presenting it as operational
  recovery duration;
- the monolithic reference model is validated;
- any decomposition cuts are correct and terminate on the reference instances;
- both fleet modes use the same optional recovery semantics;
- the existing `H = T + delta_tail` behavior remains the unchanged default.

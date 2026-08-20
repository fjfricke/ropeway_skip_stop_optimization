# DDD Reservoir Fleet Planning

Status: **Single-interface solver core and exact finite bounded Waiting are
implemented; topology campaign and full experiment runner remain planned**

## Purpose and related plans

Replace arbitrary optimized initial placement in the final fleet-sizing
experiments with an explicit passenger-free setup process. Cabins start in an
ideal entry reservoir, may be dispatched during warm-up, and then remain on the
physical network through the measured service horizon and its safety tail.

This plan specializes the boundary and fleet semantics from
[`ean_fleet_activation_and_depots.md`](ean_fleet_activation_and_depots.md) for
the trajectory-column and time-expanded DDD solver described in
[`ddd_trajectory_column_generation.md`](ddd_trajectory_column_generation.md).
The general EAN plan remains authoritative for physical depots, multi-round
reachability, and full-day terminal contracts. This document defines the
first implementation and its bound contract.

The research objective is not to optimize where interchangeable cabins happen
to be at time zero. It is to determine, for a physical network and demand
profile, how service quality changes with the available and actually operated
fleet, with and without Skip-Stop and later with bounded Waiting.

## Selected operating contract

Use three consecutive phases:

```text
[-W, 0):       passenger-free warm-up; entry reservoir enabled
[0, H]:        measured passenger release and service; reservoir disabled
(H, H + T]:    completion and resource-clearance tail; reservoir disabled
```

- The physical line is empty at `-W`.
- All available cabins initially occupy the ideal entry reservoir.
- The interface contract is explicit. In `IDEAL_NON_LIMITING` mode dispatch
  itself consumes no additional physical resource; the first movement route
  still consumes every normal entry, rope, switch, and mechanism resource.
  In `PHYSICAL_RESOURCE` mode dispatch additionally creates the declared
  resource occurrences at the declared offsets and separations.
- No Passenger is released or served during warm-up.
- Passenger release and service occur in `[0, H]`; every accepted passenger
  must alight by `H` under the existing canonical Passenger semantics.
- A dispatched cabin stays on the line through model end. It is never removed,
  returned to storage, or redispatched.
- The tail continues every active trajectory only to clear physical resource
  occurrences after Passenger service has ended.
- A cabin that is never dispatched remains in the reservoir, has no visits,
  carries no passengers, and consumes no physical resource.

The ideal reservoir is an experiment abstraction for non-limiting initial
storage. It is not a claim about the throughput or geometry of a realizable
depot. Dispatch after service begins and every form of on-line removal remain
out of scope.

Implementation checkpoint (2026-08-18): the repository contains the typed
reservoir domain, stored and continuous dispatch columns, all-stop warm-up,
optional/exact dispatch cardinality, prefix and dispatch-time symmetry,
resource and inventory validation, checkpoint schema v5, continuous compact
proof pricing, restricted continuous dispatch-window primal pricing, and an
optional absolute time-expanded dispatch-anchor sweep. Both restricted
oracles are primal-only; all certified continuous-domain lower bounds still
come exclusively from complete continuous pricing. The fixed-$K$
campaign, topology-specific boundary registry, and polished frontend replay
remain later phases. Bounded end-of-platform Waiting is now represented by
complete integer wait choices in compact continuous-dispatch proof pricing;
the absolute anchor sweep is deliberately disabled in this mode.

Reservoir attachment is explicit scenario data, never inferred from list
order. `DddReservoirBoundaryConfig` names the entry state, boundary mode,
optional dispatch-resource usages, required first-route resources, and
permitted route behavior. The first Five-Station ring fixture
uses one configured entry switch. The later line fixture attaches at its
declared terminal interface; each independent double-ring direction receives
its own declared interface unless a physical connector is modeled.

## Fleet quantities and the meaning of fixed K

Never expose one ambiguous cabin count. Report:

```text
K_available:
  cabins available in the reservoir for this solve

K_dispatched:
  available cabins that enter the physical network at least once

K_peak_active:
  maximum cabins simultaneously outside storage

K_owned:
  long-term fleet; introduced only with defensible ownership economics
```

Because Version 1 permits dispatch only during warm-up and no removal, every
dispatched cabin remains on the line throughout measured service. Therefore

$$
K_{\mathrm{peak\ active}}=K_{\mathrm{dispatched}}
$$

in Version 1. Both fields remain explicit because they diverge once a physical
service-period depot is introduced.

The primary experiment fixes `K_available` outside the optimization. Cabins
may remain unused, hence

$$
K_{\mathrm{dispatched}}\le K_{\mathrm{available}}.
$$

For a minimization Passenger objective and identical boundary conditions,
optional dispatch implies the monotonicity

$$
J^\star(K+1)\le J^\star(K),
$$

because the extra cabin can remain stored. Consequently Passenger quality
alone does not define an economically ideal owned fleet. The evaluation must
provide at least one of:

1. the Pareto frontier `(fleet, Passenger objective)`;
2. minimum fleet for a declared service target;
3. a sensitivity over explicit cabin costs.

A separate `EXACT_DISPATCHED` experiment mode forces

$$
K_{\mathrm{dispatched}}=K
$$

and is used only for physical capacity frontiers and controlled solver tests.
It must not be confused with the primary available-fleet comparison.

## Column and master formulation

### Reservoir and active trajectory columns

For every available canonical cabin ID `c`, define a trajectory domain

$$
P_c=P_c^{\mathrm{stored}}\cup P_c^{\mathrm{dispatch}}.
$$

`P_c_stored` contains one canonical zero-cost dummy column. A dispatched
column contains:

- reservoir interface and dispatch time;
- first physical movement state and route option;
- complete warm-up, service, and terminal-tail path;
- Stop/Skip decisions and finite bounded Waiting decisions;
- all regular and boundary resource occurrences;
- Passenger ride quantities during the measured service phase;
- terminal-tail coverage provenance.

The master retains one selection equation per available cabin:

$$
\sum_{p\in P_c}\lambda_{cp}=1.
$$

Let `stored(p)` identify the dummy column. Then

$$
d_c
=1-\sum_{p\in P_c:\,stored(p)}\lambda_{cp},
\qquad
K_{\mathrm{dispatched}}=\sum_c d_c.
$$

All Passenger, conflict, and resource rows have coefficient zero for the
stored column. The existing cabin-prefix symmetry is applied to dispatch:

$$
d_{c+1}\le d_c.
$$

Dispatched cabins are secondarily ordered by interface, dispatch time, and
first physical phase. This only canonicalizes interchangeable labels at the
reservoir boundary; it imposes no later order and does not prohibit
overtaking.

### Demand and the empty-service solution

Optional dispatch makes the all-stored plan physically feasible. It must not
be accidentally attractive because Passenger service was omitted. Retain the
canonical unserved-demand penalty and report served demand explicitly. For
service-target experiments, add the declared coverage or Passenger-quality
constraint directly. A result with `K_dispatched = 0` is valid only when the
declared demand objective or target genuinely permits it.

### Fleet objectives

Keep the primary Passenger objective unchanged for each fixed
`K_available`. Fleet selection is evaluated outside the solve. Optional
secondary objectives may minimize, in lexicographic order:

1. Passenger objective;
2. `K_dispatched`;
3. active cabin-seconds;
4. warm-up deployment makespan.

Apply a secondary fleet objective only after the primary Passenger objective
is proved optimal or after fixing it within an explicitly reported tolerance.
Do not allow the secondary objective to change the reported primary optimum or
its bound. If the primary gap remains open, report `K_dispatched` for the best
incumbent, not as a proved minimum among Passenger-optimal schedules.

Keep ownership and operation economics separate. An ownership sensitivity uses

$$
F^\star_{\mathrm{owned}}(K)
=J^\star(K)+c^{\mathrm{owned}}K_{\mathrm{available}},
$$

whereas an operating sensitivity may charge

$$
c^{\mathrm{dispatch}}K_{\mathrm{dispatched}}
+c^{\mathrm{time}}T_{\mathrm{active}}.
$$

Evaluate ownership cost outside the fixed-`K_available` runs. Add operating
cost only as a declared secondary or alternative objective; do not silently
mix the two meanings of fleet cost.

## Time-expanded reservoir start domain

### Multi-source path graph

Extend the successful fixed-start `TIME_EXPANDED_PATH` pricing formulation
with a reservoir super-source. A dispatch arc selects a legal combination

$$
(\text{interface},\ \text{phase},\ t^{\mathrm{dispatch}})
$$

and enters the existing absolute time-expanded movement graph. The stored arc
connects the source directly to a nonphysical stored terminal. Physical
movement then uses the existing exactly reachable Stop/Skip time states.

Version 1 supports:

- one ideal entry interface;
- one deterministic ring circulation pattern;
- No-Wait service;
- exact fixed `K_available` with optional dispatch;
- Journey-Time and Waiting-Time Passenger objectives;
- Headway architectures A, B, and C;
- Pair-only trajectory conflicts and complete final validation.

The reservoir route carries an explicit behavior and resource signature. In
particular, architecture B must know whether the dispatched cabin behaves as a
service or bypass leader at its first merge. No virtual pre-boundary behavior
may be inferred from a cabin ID or omitted from validation.

### Dispatch-time domain and certification

A finite dispatch-anchor set

$$
\Theta'\subset[-W,0)
$$

defines an exact finite-grid model but not the complete continuous reservoir
domain. Distinguish two oracles:

```text
time-expanded anchor oracle:
  fast primal columns and valid upper bounds

restricted continuous-window oracle:
  fast primal columns near a feasible dispatch train; no global bound

complete proof oracle:
  complete declared start domain and reduced-cost lower bounds
```

Initial anchors are derived from:

- source and service-boundary endpoints;
- canonical headway slots;
- Passenger release times minus reachable boarding offsets;
- passenger cutoff minus reachable alighting offsets;
- dispatch times from neighboring-K warm starts;
- conflict shifts `t +/- required_headway`.

The implemented complete Compact oracle covers every continuous dispatch time
and the stored alternative. It is shared between equivalent cabins to avoid
solving the same proof problem $K$ times. Its incumbent may therefore give all
cabins the same dispatch time; that is harmless for the reduced-cost proof but
usually poor primal diversification.

The second oracle has a deliberately separate role. It solves a small number
of cabin-specific continuous dispatch windows around a canonical dispatch
train. The windows are visited from the centre outwards and then rotated over
CG rounds. These solves may add a valid new master column even when its current
reduced cost is nonnegative, because several individually mediocre columns can
form a substantially better conflict-free integer schedule. They never enter
the pricing correction and never certify a lower bound. The absolute
time-expanded anchor oracle remains an opt-in alternative with the same
primal-only contract.

Thus one round has the logical split

$$
\underbrace{z_R+\sum_c\min\{0,\underline r_c\}}
_{\text{certified lower bound from complete proof pricing}}
\qquad\text{and}\qquad
\underbrace{\mathcal P_R\cup\mathcal P^{\mathrm{primal}}}
_{\text{larger restricted master for upper bounds}}.
$$

The stored column remains explicit in every restricted master; complete
pricing takes the minimum over stored and dispatched alternatives.

The intended scalable proof path is adaptive DDD over dispatch-time cells. A
cell `[l, u]` supplies an optimistic lower-bound representation; a concrete
anchor inside it supplies a feasible trajectory. Split a cell when its
optimistic path is selected, a conflict crosses its interior, or its Passenger
event cost is not exact. A finite anchor pool alone must never be exported as a
continuous-domain lower bound.

## Headways, conflicts, and validation

In physical-boundary mode every dispatched trajectory contains the configured
source occurrence in addition to normal route occurrences. In ideal mode it
does not. Both modes apply the same effective headway policy and dominance
certificates to every resource that is actually declared.

Keep initially:

- exact within-trajectory movement and Passenger capacity;
- eager rope and non-merge resource semantics already proven compact;
- shared order variables where existing rules permit them;
- Pair-only cross-trajectory conflicts with complete separation;
- physical validation of every accepted incumbent.

Generate delayed conflict rows for:

- dispatch against a cabin already passing the source merge;
- two close dispatches;
- regular downstream merge conflicts;
- resource conflicts in the terminal tail.

The stored column is compatible with every physical trajectory. A result is a
valid upper bound only after rebuilding the canonical movement core from the
EAN artifact, reconstructing the movement and fleet plans, and passing
physical policy, boundary, Passenger, headway, and reservoir inventory
validation. Because the physical network is empty before the explicit
dispatch event, there is no omitted pre-boundary cabin whose headway must be
guessed.

## Warm-up and terminal-tail horizons

Treat warm-up `W` and terminal tail `T` as experiment parameters with explicit
provenance. One circulation is a useful first warm-up gate but not a general
reachability proof. The final experiment must:

1. generate enough source opportunities for multiple dispatch rounds;
2. construct or solve a valid setup schedule;
3. compare at least `W` and `2W` and verify stability of Passenger objective,
   dispatched fleet, and policy;
4. derive `T` from the latest Passenger completion and maximum physical
   resource-clearance requirement, then verify it against a larger tail;
5. report whether source throughput, Passenger completion, or final resource
   clearance binds;
6. use the same windows for All-Stop and Skip-Stop at the same maximum
   available fleet.

Every dispatched cabin continues its physical trajectory through common model
end `D = H + T`; there is no exit decision. Every accepted Passenger must have
alighted by `H`, and every resource occurrence included before `D` must be
validated through its clearance time. The resulting certificate is explicitly
finite-horizon. It does not prove that the terminal line state can repeat
indefinitely.

If long setup makes the integrated model weak, compute the setup plan
separately and use it as a fixed boundary plan or warm start. Do not silently
shorten the warm-up and call a resulting source-boundary failure generally
unreachable.

## Bounded Waiting extension

The implemented first Waiting domain uses station-specific explicit maxima and
a finite control step $\Delta$ (one second in the reference experiments):

$$
w_v=m_v\Delta,\qquad m_v\in\{0,\ldots,W_v/\Delta\}.
$$

Only Stop visits at `END_OF_PLATFORM_WAIT` stations can wait. A positive wait
is legal only if the visit's minimum platform exit is at or after time zero;
therefore Waiting cannot improve or alter the passenger-free deployment before
the service boundary. Route propagation and resource occurrences use the
exact formulas in `ddd_trajectory_column_generation.md`.

The reservoir proof oracle retains a continuous dispatch time and jointly
optimizes the complete finite wait domain in its compact MILP. Consequently
its objective bound is valid for this declared bounded-Waiting domain. The
separate compact dispatch-window oracle remains primal-only. Resource-window
cuts and absolute time-expanded dispatch anchors are rejected until their
coefficients/domain account for continuous dispatch and wait-dependent
resource endpoints. The No-Wait optimum remains only an upper bound for a
minimization problem in which Waiting is optional.

## Fixed-K experiment runner

The detailed runner, certificate-analysis, live-event, and frontend design is
specified in
[`ddd_fleet_sweep_live_dashboard.md`](ddd_fleet_sweep_live_dashboard.md).
This section retains the fleet experiment's mathematical reporting contract.

Add a runner that takes one topology, demand profile, operating policy, and a
set of available fleets. Each `K_available` is a separate resumable solve.
Neighboring runs warm-start each other:

- `K -> K+1`: retain all columns and add one stored column;
- `K -> K-1`: drop one unused cabin first, otherwise drop the least useful
  canonical trajectory and repair;
- reuse conflict rows only when their trajectory fingerprints remain valid;
- never transfer a numerical bound without re-solving the corresponding
  fixed-K master and proof pricing.

For each K report:

```text
K_available
K_dispatched
K_peak_active
Passenger LB / UB / relative gap
served demand and canonical Passenger metrics
time to first validated incumbent
root and final model sizes
pricing and separation time
dispatch, merge, and terminal-tail conflict counts
warm-up deployment makespan and terminal-tail length
validation certificate
```

For a service target `J_target`:

- `UB_K <= J_target` certifies that K is sufficient;
- `LB_K > J_target` certifies that K is insufficient.

For available-fleet ownership cost `c`, K is globally certified when

$$
UB_K+cK < LB_{K'}+cK'
\qquad\forall K'\ne K.
$$

Thus the experiment can identify a fleet even when not every individual
fixed-K gap is zero.

## Implementation phases

### Phase 0: Semantics and fixed dispatch equivalence — complete

- Add typed reservoir boundary configuration and `DddReservoirStartDomain`.
- Add stored and fixed-dispatch reference trajectories.
- Fix a tiny dispatch schedule and reproduce the existing fixed-start result.
- Implement complete reservoir, movement, Passenger, and inventory validation.
- Do not add Waiting or continuous dispatch optimization.

### Phase 1: No-Wait multi-source primal pricing — complete

- Add reservoir source/stored/dispatch arcs to `TIME_EXPANDED_PATH`.
- Add optional dispatch and prefix symmetry to the trajectory master.
- Generate dispatch anchors and multiple diverse valid columns.
- Export a bound only for the explicitly declared finite anchor domain.
- Do not present the current OIP proof result as a reservoir-domain bound.
- Export fleet and boundary metrics.

### Phase 2: Continuous dispatch proof — complete for one interface

- Implement the single-interface continuous Compact proof reference.
- Compare it against exhaustive Tiny reservoir enumeration.
- Add adaptive dispatch-time DDD cells if Compact proof pricing becomes the
  bottleneck.
- Export a continuous-domain lower bound only after all cells or start
  subdomains have valid objective bounds.

### Phase 3: Topology extension, fixed-K campaign, and frontend export — next

- First run the complete bound gate on the supported single ring.
- Add a deterministic-line reservoir interface and validate terminal entry,
  turnback, and terminal-tail semantics before running the artificial line.
- Add one reservoir domain per independent double-ring direction and validate
  any physically shared resources before solving both patterns together.
- Only after those topology gates, run the artificial line and double-ring
  demand families over a declared K matrix.
- Compare All-Stop and Skip-Stop at identical `K_available`.
- Export stored cabins, dispatch events, service trajectories, fleet metrics,
  and bound intervals to the frontend.
- Produce fleet/service Pareto curves and service-target certificates.

### Phase 4: Finite bounded Waiting — solver core complete

- Add physically valid finite Wait choices to compact proof pricing.
- Preserve No-Wait columns as warm starts and feasible fallbacks.
- Establish separate finite-domain and continuous-Waiting bound statements;
  continuous unrestricted Waiting remains out of scope.
- Compare objective gain against solve time and certificate degradation.

### Phase 5: Longer horizons

- Use rolling horizon for full-day operation only after the finite-horizon
  boundary model is validated.
- Preserve the dispatch-only contract in every window; physical depots and
  on-line removal remain in the separate general EAN depot plan.

## Correctness tests

- `K_available = 0` and all-stored solutions;
- partial and full dispatch with exact fleet counts;
- stored cabins have no visits, passengers, conflicts, or resource usage;
- fixed dispatch reproduces the matching fixed-start optimum and plan;
- prefix symmetry on/off gives the same optimum;
- source merge Headways for A, B, and C;
- architecture-B first-leader behavior;
- dispatch before, exactly on, and after boundary endpoints;
- multiple warm-up dispatch rounds;
- invalid late dispatch, premature path termination, and incomplete Passenger
  or resource clearance are rejected;
- Tiny exhaustive comparison of trajectory columns, Passenger objective, and
  bounds;
- monotonicity of available-fleet Passenger optima;
- exact-dispatched capacity cases;
- neighboring-K warm starts never change validation or bounds;
- Pair-only separation finds every concrete boundary and regular conflict;
- frontend replay reproduces dispatch, inactive cabins, and physical spacing;
- Waiting tests separately cover zero, sparse finite, and refined domains.

## Performance gates

Use Five-Station architecture B, `K_available = 19`, and No-Wait as the first
computational gate. Begin with one circulation of warm-up, but automatically
increase it until a fully validated constructive all-stop dispatch schedule
exists. Use that same validated window for Skip-Stop, fixed-start, and Compact
OIP comparisons at 5, 30, 300, and 600 seconds. A source-boundary failure under
an unvalidated short warm-up is not solver-performance evidence.

Record:

- time to first validated incumbent;
- certified LB, UB, and gap trajectory;
- model build, pricing, separation, and validation time;
- columns and conflicts by source, regular merge, and terminal tail;
- dispatched and peak-active cabins.

Run the continuous-gap gate only after Phase 2 provides complete reservoir
proof pricing. Proceed to higher K only if the first case produces a validated
incumbent within 30 seconds and a nontrivial complete-domain bound. Treat a
single-digit gap within ten minutes as the desired experiment target, not as a
correctness requirement. Treat Waiting results as experiment evidence only if
the No-Wait reservoir model is at least competitive with Compact OIP in both
incumbent quality and certified gap.

## Thesis and experiment reporting

Document the ideal reservoir as a boundary abstraction, not a realizable
depot. State warm-up, terminal tail, dispatch availability, Waiting domain,
and fleet definition for every result.

The evaluation reports:

- equal-available-fleet All-Stop versus Skip-Stop curves;
- dispatched and peak-active fleet alongside available fleet;
- minimum fleet intervals for service targets;
- optional cabin-cost sensitivity rather than one arbitrary fleet-cost claim;
- sensitivity to warm-up/tail length and Waiting domain;
- separate numerical and continuous-domain certificate statements.

Do not call `K_available` the ideal operated fleet when surplus cabins remain
stored. Do not call `K_dispatched` the ideal owned fleet without an ownership
cost or service-level criterion.

## Explicit non-goals of the first version

- arbitrary on-line OIP;
- service-period reservoir dispatch and every form of cabin removal;
- multiple physical depots or finite depot storage;
- dynamic turnbacks and multiple circulation patterns;
- continuous unrestricted Waiting;
- integrated choice of owned fleet and Passenger objective in one large MILP;
- global integer optimality beyond the declared root-column-generation and
  fixed-domain certificate.

# Dynamic Discretization Discovery for Cabin and Passenger Planning

Status: **proposed research and implementation plan**

Research snapshot: **2026-08-05**

## Decision Summary

Develop an optional exact solver path based on **Dynamic Discretization
Discovery (DDD)**. It represents cabin circulation and passenger movement on
a partially time-expanded network whose time partitions are refined only
where the current solution cannot be realized in continuous time.

The target loop is:

```text
physical movement network + fixed K + demand + finite horizon
    -> optimistic partial time-space MILP
    -> valid lower bound
    -> exact cabin-flow decomposition and continuous-time lift
    -> complete movement, resource, and passenger validation
    -> feasible upper bound or structured refinement evidence
    -> add time boundaries, timed arcs, and resource rows
    -> warm-started re-solve
```

For the minimization problem, every reported iteration must preserve

$$
LB_q \leq z^\star \leq UB_q,
$$

where $z^\star$ is the optimum of the continuous-time cabin-and-passenger
problem. A partial-master incumbent is never itself an upper bound. Only a
fully lifted and independently validated movement and passenger plan may
update $UB$.

The first proof slice is deliberately movement-only and deterministic:

- fixed $K$;
- fixed initial placement;
- deterministic current line and ring circulations;
- one fixed service alternative per movement decision;
- no additional cabin waiting;
- finite-horizon source/sink semantics;
- complete resource and headway validation.

With these conditions combined, event times are predetermined. This slice
is therefore a complete correctness oracle for horizon, projection, path
decomposition, and validation semantics, not a meaningful optimization or
performance benchmark. The first nontrivial DDD optimization gate is fixed
$K$, fixed starts, Stop/Skip alternatives, and no additional waiting.

Stop/Skip alternatives are the next movement stage. Additional cabin waiting,
platform occupancy, passenger feasibility, passenger journey time, optimized
initial placement, and day-scale operation follow as separate gated stages.
This order is required because each extension needs its own relaxation,
lifting, refinement, and termination argument.

DDD is introduced in parallel to the current EAN and does not initially
replace it. The continuous EAN remains the exact reference formulation on
small cases, the complete physical validator remains authoritative, and the
existing delayed-merge work remains the lower-risk near-term improvement.

## Why This Solver Path Is Different

### Full time expansion

A complete time-expanded formulation on a uniform quantum $\Delta$ has
size approximately

$$
O\!\left(\lvert A\rvert\frac{H}{\Delta}\right)
$$

for cabin movement before passenger commodities are added. It has a strong
network structure and static resource-packing constraints, but a fine quantum
and a long horizon make it prohibitively large. It also approximates
continuous waiting unless every relevant time is aligned with $\Delta$.

### Current continuous-time EAN

The current EAN represents only physical visits and keeps event times
continuous. Its base size is independent of a global time quantum, but an
unknown conflict order introduces a binary disjunction

$$
t_j \geq t_i+h-M(1-z_{ij}),
$$

$$
t_i \geq t_j+h-Mz_{ij}.
$$

Near dense merges or under broad OIP time bounds, the potential pair universe
can dominate model construction and search. Delayed merge generation reduces
the initial universe but retains continuous Big-$M$ scheduling semantics.

### Proposed DDD model

DDD keeps a time-indexed network structure without constructing all time
copies. A partial model assigns an event to a coarse time cell or sparse time
copy, uses optimistic travel and passenger costs, and includes only resource
conflicts that are already unavoidable at the current resolution. A separate
lift decides whether the selected support can be realized with exact event
times.

The expected benefit is therefore not merely fewer variables. It is the
combination of:

- anonymous integral cabin flow instead of cabin-label copies;
- static packing or clique rows instead of most Big-$M$ order decisions;
- linear passenger flow on timed service opportunities;
- nonuniform time resolution by physical state or arc;
- a dual bound from the optimistic master;
- a primal bound from exact reconstruction;
- systematic refinement only around relevant travel, resource, waiting, and
  passenger boundaries.

## Relationship to Existing Plans

This plan is complementary to, not a replacement for:

- [`ean_fixed_k_delayed_merge_headways.md`](ean_fixed_k_delayed_merge_headways.md):
  exact continuous-time EAN with merge-only delayed disjunctions;
- [`rotation_passenger_flow_hybrid.md`](rotation_passenger_flow_hybrid.md):
  restricted occurrence-pool matheuristic without a global bound unless exact
  pricing is later introduced;
- [`zero_wait_passenger_master_timing_cuts.md`](zero_wait_passenger_master_timing_cuts.md):
  simpler structural passenger master with an exact timing subproblem but no
  inherent global lower bound;
- [`discrete_time_backlog.md`](discrete_time_backlog.md): the existing full
  uniform-grid prototype, retained as a small-instance reference;
- [`ean_network_builder_migration.md`](ean_network_builder_migration.md): the
  canonical physical movement network that DDD must consume rather than
  introducing another manually maintained topology.

The DDD prototype may reuse the current EAN's route semantics, resource
provenance, movement-plan types, passenger semantics, validators, and export
layer. It must not reuse an EAN artifact as if eager cabin-pair materialization
were part of the DDD network.

## Literature Basis

The algorithmic pattern is established but problem-specific:

- Boland, Hewitt, Marshall, and Savelsbergh introduced iterative refinement of
  partially time-expanded networks for exact continuous-time service network
  design ([Operations Research, 2017](https://doi.org/10.1287/opre.2017.1624)).
- Marshall, Boland, Savelsbergh, and Hewitt developed interval-based DDD and
  report partial models often far below the size of the complete expansion
  ([Transportation Science, 2021](https://doi.org/10.1287/trsc.2020.0994)).
- Shu, Xu, and Baldacci show that holding costs require a new relaxation and
  exact algorithm rather than a mechanical reuse of the original construction
  ([Transportation Science, 2024](https://doi.org/10.1287/trsc.2022.0104)).
  This is directly relevant to passenger waiting and journey time.
- van Lieshout and van der Schaft apply DDD to continuous trip shifting in
  multidepot vehicle scheduling and solve real-life instances with close to
  4,000 trips
  ([INFORMS Journal on Computing, 2025](https://doi.org/10.1287/ijoc.2024.0698)).
- Croella, Luteberget, Mannino, and Ventura adapt interval DDD to train
  rescheduling with shared track resources. Their comparison also warns that
  Big-$M$ may remain competitive for linear continuous objectives
  ([preprint](https://luteberget.github.io/preprints/maxsatddd-2023-06-14.pdf)).
- Van Dyk and Koenemann identify hard node-storage constraints as a special
  difficulty for DDD relaxations
  ([preprint](https://arxiv.org/abs/2303.01419)). Platform occupancy and cabin
  waiting make this limitation directly relevant here.

The intended contribution is not to present DDD itself as new. It is to
derive and test a valid DDD relaxation for cyclic ropeway cabin circulation
with Stop/Skip merges, headways, optional station holding, cabin capacity,
and passenger service.

## Mathematical Target Problem

Let $P$ denote the full continuous-time planning problem. It contains:

- a finite physical movement network $G=(V,A)$;
- fixed cabin count $K$;
- route alternatives $A_v$ at each decision state;
- continuous event times $t_e$;
- optional waiting $w_e$;
- resource usages with entry, clearing, and headway semantics;
- aggregate passenger demand with release times;
- cabin capacity $Q$;
- a finite horizon $[0,H]$;
- the configured passenger objective and deterministic tie breakers.

The exactness target assumes:

1. all movement and minimum dwell durations are strictly positive where they
   advance a circulation;
2. route and Stop/Skip option sets are finite;
3. additional cabin waiting is bounded and legal only at explicit holding
   states;
4. the number of visits within $[0,H]$ is finite;
5. demand has finitely many release-time or piecewise-linear breakpoints;
6. costs are linear or piecewise linear over the represented breakpoints;
7. horizon-start and horizon-tail semantics are explicit;
8. resource capacity and headway rules have complete deterministic
   validation semantics.

If arbitrary continuous demand functions, unbounded waiting, continuously
variable speeds, or nonlinear objectives are introduced, the initial target
changes from finite exact convergence to certified $\varepsilon$-optimality.

## Bound and Result Contract

For iteration $q$, let $M_q$ be the current partial master and $L_q$ the
exact lifting problem for its selected support.

### Lower bound

The master must be a relaxation:

$$
\mathcal F(P) \xrightarrow{\pi_q} \mathcal F(M_q),
$$

with

$$
c_{M_q}(\pi_q(x)) \leq c_P(x)
\qquad \forall x\in\mathcal F(P).
$$

Therefore,

$$
LB_q := \operatorname{BestBound}(M_q) \leq z^\star.
$$

The Gurobi best bound is valid even when $M_q$ reaches its time limit before
proving its own optimum. Refinement should be nested whenever possible so
that recorded lower bounds are monotone. Independently of nesting, the
reported global lower bound is

$$
LB^{\mathrm{global}}_q=\max_{i\leq q} LB_i.
$$

### Upper bound

A partial-master solution may update $UB$ only after:

1. integral cabin flow has been decomposed into exactly $K$ continuous
   cabin paths;
2. an exact timing problem has assigned all event and waiting times;
3. complete movement and resource validation has passed;
4. exact passenger routing on the realized service has passed;
5. the real objective has been recomputed independently.

Then

$$
UB_q=\min\{UB_{q-1},c_P(x_q^{\mathrm{feas}})\}.
$$

Before the first feasible lift, $UB=+\infty$.

### Statuses

```text
OPTIMAL
  a fully validated incumbent exists and the certified gap is within the
  exact solver tolerance

FEASIBLE_WITH_GAP
  a fully validated incumbent exists, with finite valid LB and UB

RELAXATION_INFEASIBLE
  the partial relaxation is proven infeasible; therefore the full problem is
  infeasible under the same boundary assumptions

UNKNOWN_NO_INCUMBENT
  a valid lower bound may exist, but no fully validated lift was found

UNKNOWN_WITH_INCUMBENT
  a fully validated plan exists, but the configured proof budget expired

INVALID_INTERNAL
  a result that was treated as lifted or certified failed independent
  validation or a bound invariant was violated
```

`OPTIMAL` must never be inferred from “no new violation found” alone. The
master bound and feasible-plan objective must close the configured gap.

## Partial Time Representation

### Canonical discretization

For each movement state or state-arc pair, maintain a deterministic ordered
partition of the horizon:

$$
\mathcal D_v=\{I_{v,1},\ldots,I_{v,m_v}\},
\qquad
I_{v,p}=[\ell_{v,p},u_{v,p}).
$$

Different states may use different partitions. Later experiments may use
arc-dependent partitions when high-degree states otherwise inherit too many
irrelevant time boundaries.

Initial boundaries include only values needed for a valid initial
relaxation:

- $0$ and $H$;
- exact fixed-start events;
- demand release and objective breakpoints once passengers are enabled;
- earliest/latest reachability bounds;
- boundary-reservoir and tail cutoffs;
- mandatory resource availability changes.

No uniform global $\Delta$ is introduced.

### Partial timed nodes and arcs

A partial node represents an event occurring somewhere in a cell:

$$
(v,I), \qquad t_v\in I.
$$

A partial movement arc exists when at least one continuous realization of its
source cell, target cell, route option, travel duration, and permitted waiting
is possible. This existential compatibility deliberately relaxes consistency
between successive arcs. The exact lift restores one common event time at
every selected visit.

Every partial arc stores:

```text
arc_id
source_state_id / source_interval_id
target_state_id / target_interval_id
route_option_id
minimum_duration / maximum_duration
activation semantics
possible resource-usage envelope
mandatory resource-usage core
lower-bound passenger cost
provenance
```

The master uses integer cabin-flow variables

$$
y_a\in\mathbb Z_{\geq0}.
$$

Flow conservation holds at partial state-time nodes. Fixed starts inject
exactly one unit at each supplied initial state, and the sink receives exactly
$K$ units according to explicit finite-horizon tail semantics.

The partial network must be acyclic in its horizon/layer dimension. Coarse
time cells may not create zero-time circulation loops. Repeated physical
states therefore carry enough visit, circulation, or monotone horizon-layer
provenance to prevent an artificial cycle inside one time cell.

## Resource and Headway Relaxation

### Resource usage envelopes

For a selected partial usage $p$, define the set of all possible exact
occupancy intervals

$$
\mathcal I_p
=
\{[s_p(t),e_p(t)) : t \text{ is consistent with the partial arc}\}.
$$

The possible envelope is the union of those intervals. The mandatory core is
their intersection:

$$
I_p^{\mathrm{mandatory}}
=
\bigcap_{I\in\mathcal I_p} I.
$$

Only conflicts that hold for every possible realization may constrain the
optimistic master. For a platform entry interval
$t^{\mathrm{entry}}\in[\ell_e,u_e]$ and exit interval
$t^{\mathrm{exit}}\in[\ell_x,u_x]$, a simple mandatory occupancy core is

$$
[u_e,\ell_x)
$$

when $u_e<\ell_x$; otherwise the core is empty.

This relaxation may be weak, but it is safe. Using the full envelope as if it
were mandatory could cut off a realizable continuous schedule and invalidate
the lower bound.

### Master packing rows

At current resolution, build interval-conflict graphs over mandatory resource
cores. For a capacity-one maximal clique $C$, add

$$
\sum_{p\in C}y_p\leq1.
$$

Known non-overtaking corridor orders may also provide exact adjacent
constraints. Unknown or potentially avoidable conflicts remain relaxed and
are handled by the lift and refinement.

### Exact resource lift

After cabin-flow decomposition, solve a continuous timing MILP containing:

- exact travel and minimum dwell equations;
- cell-membership bounds selected by the master;
- legal waiting bounds for enabled stages;
- all exact resource entry/clearing semantics;
- topology-proven precedence;
- order binaries only for conflicts whose order is still unresolved;
- horizon and tail semantics.

The lift is a feasibility problem first. Secondary objectives minimize total
additional waiting, latest completion time, and a deterministic tie-breaker.
It is not permitted to change the selected physical route support unless the
current experiment explicitly enables a repair heuristic. A repaired route is
a new master candidate, not a lift of the old master solution.

## Refinement Evidence

Every failed or optimistic lift returns structured evidence. Required
refinement reasons are:

```text
TRAVEL_TIME_UNDERESTIMATE
EVENT_CELL_INCONSISTENCY
RESOURCE_HEADWAY_CONFLICT
PLATFORM_OCCUPANCY_CONFLICT
WAITING_BOUND_CONFLICT
HORIZON_OR_TAIL_CONFLICT
PASSENGER_RELEASE_CONFLICT
PASSENGER_CAPACITY_CUT
PASSENGER_COST_UNDERESTIMATE
FLOW_DECOMPOSITION_CONFLICT
```

Examples:

- a departure at $t$ with duration $\tau$ adds the exact propagated
  boundary $t+\tau$ at the target state;
- a resource conflict between exact entries $t_i,t_j$ adds relevant
  clearing boundaries $t_i+h$ and/or $t_j+h$, then rebuilds the local
  packing graph;
- inconsistent arrival and departure choices inside one coarse cell split the
  cell at the exact lifted bound that caused the contradiction;
- a required wait until $t^{\mathrm{free}}$ adds that exact station boundary
  and a legal hold transition;
- an underestimated passenger arrival adds the realized arrival boundary and
  corrects affected ride and waiting costs.

Refinement must satisfy two rules:

1. the old optimistic support cannot recur with exactly the same uncorrected
   artifact;
2. the projection of every real feasible solution remains feasible in the
   refined master.

Batch all independent refinement evidence from one lift, deduplicate
boundaries deterministically, and limit only the batch size, never the
completeness of final validation.

## Cabin Waiting and Platform Occupancy

Additional waiting is introduced only after no-wait movement DDD is correct.
For a service visit,

$$
t^{\mathrm{exit}}
=
t^{\mathrm{entry}}
+\tau^{\min}_{\mathrm{service}}
+w,
\qquad
0\leq w\leq\bar w.
$$

Skip alternatives fix $w=0$ unless the physical network explicitly defines
a separate legal skip-holding state.

In the partial master, a hold arc connects compatible station time cells and
uses an optimistic lower-bound waiting cost. In the lift, $w$ remains
continuous. A required value such as $7.65$ seconds creates an exact
boundary; it does not force a global half-second grid.

Platform occupancy covers the complete interval from physical entry until
physical clearing, including additional waiting. The partial master uses only
mandatory occupancy cores. The lift and final validator use the full exact
occupancy interval.

Because hard storage is a known DDD difficulty, this stage has a proof gate:

- prove that the mandatory-core construction is a relaxation;
- prove that hold-arc compatibility cannot remove a real schedule;
- prove that every detected storage conflict produces progress;
- compare against exhaustive fine-grid and continuous EAN references on
  small cases.

If this proof is not established, waiting-enabled DDD remains heuristic and
must not expose a lower-bound certificate.

## Passenger Feasibility

Passengers are added first as a feasibility flow with zero journey-time cost.
The partial passenger network contains:

- exact demand-release nodes;
- station waiting arcs between consecutive represented event boundaries;
- boarding and alighting arcs only for Stop service;
- through-service arcs across skipped stations;
- ride arcs enabled by selected cabin movement;
- horizon sink or unserved-demand semantics matching the current model.

When project semantics permit, aggregate passenger commodities by destination
rather than by OD-time row. For destination $d$, let

$$
f^d_g\geq0
$$

be passenger flow on passenger arc $g$. Flow conservation includes demand
injection at the exact release boundary. On a cabin ride arc,

$$
\sum_d f^d_g\leq Qy_{a(g)}.
$$

The aggregation is exact only if passengers with the same destination become
interchangeable after injection and no origin-specific service constraint or
objective term is lost. Otherwise retain the required commodity distinction.

For every partial cabin solution, the exact passenger-feasibility lift runs on
the realized cabin timetable. If it is infeasible, derive a semantic
space-time capacity cut when possible. For a passenger cut $S$, a typical
form is

$$
Q\sum_{a\in\delta^+(S)}y_a\geq D(S).
$$

The cut must be defined over physical service opportunities so that later
time-column additions receive correct coefficients. A no-good cut over the
current timed arc IDs is a fallback for search, not automatically a global
feasibility cut.

## Passenger Journey-Time Objective

Once passenger feasibility is exact, add waiting and ride costs. For a fixed
realized service, the passenger subproblem is a linear min-cost flow.

The partial master uses optimistic costs:

$$
c_g^{LB}
=
\min\{c_g(t):t \text{ is realizable inside the current cells}\}.
$$

Demand release times are exact partition boundaries and may never be rounded
earlier. An exact passenger lift recomputes boarding, alighting, transfers,
waiting, arrival, and the configured journey-time objective on the realized
cabin timetable.

If a partial arc assigns a passenger an objective of $100$ but the exact
lift yields $110.4$, the exact event boundaries and corrected local costs
are refinement evidence. The partial cost may remain optimistic elsewhere;
the global lower bound remains valid as long as it never overestimates any
real solution's projection.

Holding-cost correctness is a separate theorem and acceptance gate. Do not
infer it from the movement-only proof.

## Optional Passenger Decomposition

The first exact passenger stage keeps passenger flow in the partial master so
that the lower-bound direction is explicit. If passenger variables dominate,
introduce a later decomposition:

```text
partial cabin DDD master
    -> exact or partial timed service
    -> passenger min-cost-flow LP
    -> feasibility min-cut or dual optimality information
    -> semantic master cut and/or new timed service columns
```

Classical Benders cuts are valid only when the passenger dual remains feasible
for every later generated passenger column. A cut derived from a restricted
passenger graph can become invalid when new paths are introduced. Therefore,
the decomposition must either:

- perform complete passenger pricing before accepting a dual cut;
- express the cut over a full semantic space-time cut whose coefficients for
  future service arcs are defined;
- or classify the result as logic-based search guidance rather than a global
  lower-bound cut.

Do not add Benders merely to reduce the visible master size. Add it only after
profiling shows that passenger flow, rather than cabin integrality or DDD
refinement, is the measured bottleneck.

## Solver Architecture

### Canonical types

Introduce solver-independent immutable objects:

```text
DddTimeBoundary
DddTimeCell
DddStatePartition
DddTimedMovementArc
DddResourceEnvelope
DddPartialNetwork
DddMasterResult
DddCabinFlowDecomposition
DddLiftResult
DddRefinementEvidence
DddIterationMetrics
DddOptimalityCertificate
```

All IDs must be deterministic from physical provenance, time-boundary value,
route option, and resource usage. Floating-point boundary values require one
canonical normalization policy shared by IDs, equality, sorting, export, and
solver tolerances.

### Components

```text
EanMovementNetwork
    -> DddInitialPartitionBuilder
    -> DddPartialNetworkBuilder
    -> DddCabinPassengerMaster
    -> DddFlowDecomposer
    -> DddContinuousTimingLift
    -> DddPassengerLift
    -> DddCompleteValidator
    -> DddRefinementPlanner
    -> DddSolveCoordinator
```

The coordinator owns the total solve budget, warm starts, iteration metrics,
best global LB, best validated UB, checkpointing, and final certificate. The
builders do not mutate canonical physical-network objects.

### Public configuration

Add a separate solver family rather than another EAN headway mode:

```text
CabinPassengerSolverFamily.CONTINUOUS_EAN
CabinPassengerSolverFamily.DDD_PARTIAL_TIME_NETWORK
```

Initial DDD options:

```text
initial_partition_policy
partition_scope = STATE | ARC
max_refinement_rounds
max_new_boundaries_per_round
total_time_limit_seconds
master_time_fraction
lift_time_fraction
exact_gap_tolerance
time_normalization_tolerance
enable_stop_skip
enable_cabin_waiting
enable_passengers
enable_passenger_objective
enable_passenger_decomposition
```

Unsupported combinations fail before model construction with a precise
message. In particular, OIP, dynamic routing, unbounded waiting, and passenger
decomposition remain disabled until their acceptance gates are complete.

## Iterative Solve Algorithm

```text
input: physical network, fixed starts, K, demand, horizon, total budget

build deterministic initial partitions D_0
LB_best <- -infinity
UB_best <- +infinity
incumbent_best <- none

for q = 0, 1, ...:
    build/update partial network M_q from D_q
    solve M_q within remaining master budget
    LB_best <- max(LB_best, valid solver best bound)

    if M_q is proven infeasible:
        return RELAXATION_INFEASIBLE with certificate

    for selected master incumbents in deterministic priority order:
        decompose anonymous cabin flow
        solve exact continuous timing lift

        if movement lift is feasible:
            validate all movement and resource semantics
            solve exact passenger lift when enabled

            if complete plan is feasible:
                evaluate real objective
                UB_best <- min(UB_best, real objective)
                retain validated incumbent

        collect all lift, validation, and cost-refinement evidence

    if validated incumbent exists and certified gap <= tolerance:
        return OPTIMAL

    if no safe refinement exists:
        return INVALID_INTERNAL or blocked research status

    add a deterministic batch of safe boundaries, arcs, and rows
    install compatible partial warm starts

    if total budget expires:
        return UNKNOWN_WITH_INCUMBENT or UNKNOWN_NO_INCUMBENT
```

The coordinator should try more than one master incumbent only when Gurobi's
solution pool provides meaningfully different supports at low additional
cost. This is an optional primal acceleration and does not alter the bound.

## Progress and Metrics

Visible progress per iteration must report:

```text
round
elapsed / remaining budget
time cells / boundaries by state and arc
partial nodes / cabin arcs / passenger arcs
integer / continuous variables
rows / nonzeros
master incumbent / master best bound / master gap
global LB / validated UB / certified gap
flow decomposition status and time
timing-lift status and time
passenger-lift status and time
validation time
refinement counts by reason
new boundaries / arcs / cliques
peak RSS when available
```

Checkpoint after each completed refinement round. A checkpoint must contain
the physical-network fingerprint, normalized partitions, active timed arcs,
generated rows, valid bounds, validated incumbent, solver configuration, and
code/version provenance. Resume must reject incompatible physical or demand
inputs.

## Implementation Phases

### Phase 0: Mathematical specification and census

Deliver:

- a precise continuous full-problem specification independent of EAN code;
- finite-horizon and tail semantics;
- an upper bound on visits from positive minimum circulation durations;
- the movement-only projection $\pi_q$;
- proofs for master relaxation, lift validity, and refinement progress;
- a census tool estimating full-grid and partial-network sizes;
- a reference complete expansion for tiny instances only.

The reviewable proof draft lives as the standalone LaTeX note
`idp_report/notes/ddd_phase0/main.tex`. The read-only census entry point is
`benchmarks/run_ddd_phase0_census.py`; it builds sparse artifacts and reports
the exact complete pair universe without materializing all pairs.

Implemented Phase-0 reference infrastructure:

- solver-independent domain types in `optimization/ddd/models.py`;
- strict sparse-EAN adapter in `optimization/ddd/artifact_adapter.py`;
- exhaustive trajectory generation, resource sweep, symmetry-reduced
  combination, and complete reference validation in
  `optimization/ddd/reference.py`;
- conversion back to the existing `EanMovementPlan` and therefore reuse of
  complete validation, replay, and export semantics;
- benchmark entry point `benchmarks/run_ddd_phase0_reference.py`;
- synthetic boundary/conflict tests and a tiny continuous-EAN cross-check.
- a physical two-cabin Three-Station Stop/Skip fixture with four exact route
  supports, three feasible supports, and one independently reproduced
  exit-switch violation.
- a closed solver-independent delayed-conflict loop whose optimistic support
  master selects that invalid support, whose exact lift returns structured
  `RESOURCE_HEADWAY_CONFLICT` evidence, and whose prefix cut excludes exactly
  the proven conflict before a validated second-round solution is accepted.
- a genuine time-partition fixture whose initial partial path splices two
  incompatible witnesses in one coarse event cell, whose cell lift derives
  the exact split boundary, and whose rebuilt master raises the certified
  lower bound from zero to one;
- a separate cell-free support recovery that validates an objective-one
  incumbent in the first round, so primal discovery does not wait for bound
  refinement; the second round closes `LB = UB = 1`, in agreement with the
  exhaustive exact oracle.

The network-derived Phase-0 gate is now implemented. A layered partial graph
is built from the network-backed DDD movement problem, and a Gurobi integer
flow master chooses anonymous cabin flow without enumerating complete paths.
Its integral solution is decomposed deterministically and passed to the same
cell lift and cell-free recovery contracts. The per-path cell lift intentionally
ignores shared resources and therefore cannot certify feasibility by itself;
all lifted paths are checked together against the complete horizon and resource
model before an upper bound is accepted. On the physical Three-Station
fixture, the initial graph has three reachable nodes and six arcs; one split
at `R_entry_lr` raises the certified lower bound from zero to one and closes
`LB = UB = 1` in round two. The recovered trajectory passes complete sparse
EAN validation.

The combined movement-only loop is now implemented. Exact-prefix conflict rows
trigger delayed partial disaggregation: only cabins and visit depths referenced
by active cuts receive binary prefix-flow variables, linked below the anonymous
arc multiplicities. Early termination is represented explicitly, so a cabin is
not forced to reach the deepest visit of another support. Decomposition consumes
the solved prefix arcs before assigning residual anonymous flow, preventing a
different post-solve cabin matching from bypassing or falsely repeating a cut.
The physical
two-cabin Three-Station fixture combines two time splits and two conflict rows,
then closes `LB = UB = 4` with six prefix variables. This proves integration;
multi-cabin scaling remains open.

Gate:

- no production solver code until the movement-only lower-bound theorem and
  result contract are reviewable;
- no use of naive predecessor-time rounding for resource occupancy without a
  proof that it remains a relaxation.

### Phase 1: Deterministic movement, fixed starts, no waiting

Support one deterministic circulation pattern and fixed service semantics.
Implement sparse partitions, anonymous cabin flow, exact decomposition,
continuous timing lift, and complete validation.

This stage deliberately contains no scheduling choice. Implement it only as
the smallest executable reference kernel and exhaustive oracle. Do not use its
runtime or zero objective as evidence that DDD improves optimization.

Gate:

- exact agreement with exhaustive small reference cases;
- monotone valid LB and validated UB;
- finite convergence on one- and three-station toy cases;
- deterministic output and resume.

### Phase 2: Stop/Skip alternatives and merge resources

Add alternative route arcs and exact resource usages. Build mandatory-core
packing rows and refine from exact merge/headway conflicts.

This is the first nontrivial performance gate: route choices alter event times
and merge order while the no-wait exact-time universe remains finite.

Gate:

- same feasible/infeasible classification as eager EAN on small cases;
- every DDD-feasible plan passes the current complete validator;
- no pairwise cabin-label order universe in the master;
- comparison against delayed-merge EAN at identical fixed $K$.

### Phase 3: Continuous cabin waiting and platform occupancy

Add bounded holding arcs, exact continuous waiting in the lift, full platform
occupancy intervals, and storage-aware refinements.

Gate:

- formal relaxation proof for hard station occupancy;
- exact small-case agreement with continuous EAN;
- point-headway, platform-wait occupancy, Stop/Skip activation, horizon, and
  duplicate-boundary unit tests;
- no lower-bound certificate if the storage proof remains incomplete.

### Phase 4: Passenger feasibility

Add destination-aggregated passenger flow, exact release boundaries, stop-only
boarding/alighting, through-passenger continuity, and cabin capacity.

Gate:

- exact passenger feasibility agreement with fixed-movement passenger solves;
- all passenger demand conserved;
- capacity min-cut tests;
- commodity aggregation equivalence on cases without origin-specific rules.

### Phase 5: Passenger journey-time objective

Add optimistic partial costs, exact passenger lift, objective refinements, and
global LB/UB reporting.

Gate:

- holding-cost lower-bound proof;
- exact objective agreement on enumerated tiny cases;
- no partial solution reported as a passenger-feasible incumbent;
- reproducible certified gaps under early termination.

### Phase 6: Scaling and optional decomposition

Profile 5- and 15-station instances. Add passenger decomposition only if
passenger flow dominates memory or solve time. Evaluate state- versus
arc-dependent partitions, multi-incumbent refinement, batched clique
generation, and semantic Benders/min-cut rows.

Gate:

- every acceleration preserves the certificate contract;
- heuristic cuts are explicitly separated from bound-valid cuts;
- ablations show which mechanism improves time to first feasible plan, LB,
  UB, and final gap.

### Phase 7: Optimized initial placement

Add OIP only after the fixed-start method is stable. Initial supply becomes a
decision over compatible state-time cells with exact physical packing and
symmetry handling.

Gate:

- fixed-start remains an exact special case;
- initial placement lifts to exact nonoverlapping physical starts;
- no cabin-label factorial symmetry is introduced merely for export IDs.

### Phase 8: Long horizon and rolling operation

Test multi-hour and day-scale operation. A monolithic day solve is optional;
rolling horizon is the expected production mode. Boundary state includes:

- cabin positions and in-progress movement;
- onboard passengers;
- station queues by destination;
- active resource reservations;
- a terminal-value estimate for deferred demand and cabin distribution.

The detailed window must preserve its own valid LB/UB. A sequence of locally
optimal windows is not a global day-optimality certificate. Report the day as
a validated feasible operational plan plus explicitly defined aggregate or
window bounds.

## Tests

### Unit tests

- deterministic time normalization and IDs;
- partition insertion, splitting, ordering, and deduplication;
- existential partial-arc compatibility;
- monotone horizon/layer acyclicity;
- mandatory resource-core computation;
- maximal interval cliques;
- fixed-$K$ source and sink flow;
- integer-flow decomposition into exactly $K$ paths;
- exact travel propagation;
- refinement-reason selection and deterministic batching;
- passenger release boundaries;
- passenger waiting and ride costs;
- capacity-cut coefficients for existing and future timed arcs;
- checkpoint compatibility and resume.

### Bound-invariant tests

For exhaustively enumerable toy problems:

$$
LB_q\leq z^\star\leq UB_q
$$

must hold after every round. Add intentional adversarial cases for:

- rounded arrivals before demand release;
- platform waiting that crosses several coarse cells;
- a resource conflict absent from mandatory cores;
- Stop/Skip reconvergence with reversed order;
- a partial passenger connection that cannot be lifted;
- master infeasibility;
- time limit before the first incumbent;
- time limit after a feasible incumbent;
- repeated identical refinement evidence.

### Cross-formulation tests

Compare DDD, continuous eager EAN, delayed-merge EAN, and full fine expansion
where tractable:

- same movement feasibility;
- same optimal tiny passenger objective;
- same horizon and tail interpretation;
- same Stop/Skip and waiting semantics;
- complete final movement and passenger validation;
- consistent infeasibility on proven cases.

## Experimental Program

Run controlled matrices rather than one large showcase:

### Topologies

- one-station ring;
- three-station ring;
- five-station circle;
- five-station line where supported;
- generated 15-station ring and line after small equivalence passes.

### Factors

- fixed starts versus later OIP;
- no-skip versus Stop/Skip;
- no additional waiting versus bounded waiting;
- movement-only versus passenger feasibility versus journey time;
- low, medium, and near-capacity $K$;
- 20, 60, and 180 minute horizons;
- later rolling day windows.

### Baselines

- current eager/shared-eager continuous EAN;
- merge-delayed continuous EAN;
- complete uniform-grid model on small cases;
- zero-wait passenger master plus timing repair;
- rotation-occurrence heuristic where available.

### Primary measurements

- build time and peak RSS;
- root relaxation and solver best bound;
- time to first validated feasible plan;
- global LB, UB, and gap over time;
- DDD rounds and boundaries added;
- partial size as a fraction of full estimated expansion;
- lift success rate;
- refinement reasons;
- passenger objective and unserved demand;
- final physical validation;
- result sensitivity to initial partition policy.

Do not compare only final wall-clock time. The purpose is to determine whether
DDD improves model construction, primal discovery, dual progress, or all
three.

## Acceptance and Stop Criteria

Continue beyond movement-only only if:

- bound invariants hold on every enumerated toy case;
- DDD uses materially fewer timed nodes/arcs than the full expansion;
- refinement converges without repeatedly rediscovering the same artifact;
- at least one nontrivial fixed-$K$ case is faster or provides a stronger
  certificate than the continuous EAN baseline.

Pause or reject the approach if:

- platform storage cannot be relaxed without destroying useful bounds;
- most rounds add nearly the full fine time grid;
- the timing lift repeatedly becomes as hard as the original EAN;
- passenger holding-cost refinement destroys lower-bound progress;
- anonymous-flow decomposition needs cabin-indexed structure of comparable
  size to the current model;
- the complete validator finds any accepted plan invalid.

Failure at a later stage does not invalidate earlier results. Movement-only
DDD may remain useful as a capacity-feasibility method even if integrated
passenger DDD is not competitive.

## Thesis Integration

The thesis should present the method only to the degree achieved:

1. motivate the conflict between strong time-indexed formulations and their
   full-grid size;
2. distinguish continuous Big-$M$ EAN, full time expansion, partial time
   expansion, and restricted occurrence pools;
3. define the optimistic partial master and exact lift;
4. prove the implemented lower-bound, upper-bound, and refinement properties;
5. state explicitly which extensions remain heuristic or unproved;
6. report LB/UB trajectories, partial/full size ratios, and validation;
7. compare against the existing EAN and simpler passenger-guided heuristics;
8. discuss hard platform storage and passenger holding costs as the central
   extensions beyond standard service-network DDD.

Preferred terminology:

> Dynamic Discretization Discovery on a partial time-space cabin network with
> delayed resource-conflict separation and exact passenger recourse.

Do not call the method ordinary column generation unless reduced-cost pricing
is actually implemented. New time nodes and arcs are columns in a broad row-
and-column sense, but the defining mechanism is feasibility- and
bound-driven discretization refinement.

## Immediate Next Work

Completed Phase-0 foundations are the movement contract, proof note, model-size
census, exhaustive oracle, delayed resource-conflict loop, safe time-cell
split, cell lift, independent full validation, cell-free primal recovery, and
the first complete
`LB/lift/refine/UB` certificate.

Completed additionally: visit-layer partial graph construction from the
canonical network, anonymous integer flow, deterministic path decomposition,
the two-round physical Three-Station bound certificate, and the four-round
combined time/conflict certificate with delayed partial disaggregation.

Next:

1. measure how prefix-variable growth behaves on larger fixed-start cases;
2. add mandatory-core resource rows before delayed separation;
3. compare graph, row, and solve growth against enumerated support and eager
   EAN references;
4. only after that gate, introduce bounded station waiting.

This sequence is intentionally conservative. The main value of the approach
is the certificate

$$
LB\leq z^\star\leq UB,
$$

so no performance shortcut may silently weaken that contract.

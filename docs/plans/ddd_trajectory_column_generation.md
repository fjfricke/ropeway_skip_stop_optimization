# DDD-Guided Whole-Horizon Trajectory Column Generation

Status: **proposed implementation and research plan**

## Decision Summary

Add a separate fixed-$K$ optimizer that selects complete, cabin-specific,
whole-horizon trajectories together with passenger flow. Integrate it with the
current DDD bound engine, CP-SAT movement oracle, exact Passenger Assignment,
and complete movement validator through a small hybrid coordinator.

The new optimizer is not another refinement rule inside the current anonymous
DDD master. Its modeled unit is different:

- the anonymous DDD master chooses aggregate movement-arc multiplicities;
- the trajectory master chooses one complete path for every fixed-start cabin;
- CP-SAT checks or repairs concrete selections rather than reconstructing
  identities from an anonymous support;
- exact Passenger Assignment evaluates every accepted physical timetable.

The implementation starts as a primal restricted-master method. It becomes a
source of a global lower bound only after exact reduced-cost pricing covers the
complete trajectory universe of the declared no-wait problem. Until that gate
is passed, its validated integer solutions update only the upper bound.

The combined anytime certificate is

$$
LB
=
\max\{LB_{\mathrm{DDD}},LB_{\mathrm{traj}}\}
\le z^\star
\le UB,
$$

where $LB_{\mathrm{traj}}$ is absent until its pricing certificate is complete.

This plan specializes the exact-pricing direction left open in
[`rotation_passenger_flow_hybrid.md`](rotation_passenger_flow_hybrid.md).
Unlike that earlier one-rotation occurrence plan, the first column here is one
complete cabin trajectory over the current finite horizon. Cabins may still
make different Stop/Skip decisions in every rotation; no repeating template
is imposed.

The formal configuration LP, restricted-pool counterexample, pricing-corrected
bound, row/column certification levels, and waiting-domain argument live in the
standalone mathematical note
[`ddd_mathematical_derivations/main.tex`](../../../idp_report/notes/ddd_mathematical_derivations/main.tex),
Section `Whole-horizon trajectory decomposition and pricing`.

## Motivation and Current Evidence

The current fixed-$K$ DDD process intentionally starts with an anonymous cabin
flow. This produces an inexpensive optimistic passenger lower bound, but a
selected aggregate support need not decompose into $K$ complete physical cabin
paths with all resource headways.

On `five_station_circle_cw_half_skip_no_wait_v0` with $K=19$, 200 master--CP
rounds left the passenger lower bound unchanged at approximately $409{,}360$
passenger-seconds. The best upper bound in that experiment remained far above
it, while CP-SAT generated 200 selective path cuts. All anonymous masters were
easy and solved to optimality, but each new pointwise path cut allowed another
aggregate rematching. This is evidence that the missing structure is complete
trajectory identity rather than one more isolated support exclusion.

The implemented `DddTrajectorySlotPoolOptimizer` already demonstrates the
primal side of the idea. A pool extracted from complete CP-SAT candidates can
select one trajectory per cabin, assign direct-ride passengers, separate
cross-cabin incompatibilities, and improve a validated incumbent. Its current
restricted pool is deliberately not a lower-bound model because omitted
trajectories restrict the feasible set.

The next experiment should therefore preserve that working primal mechanism,
make the pool persistent and dual-aware, and test whether exact no-wait pricing
can search the missing whole-horizon trajectories without enumerating them.

## Scope

The first exactness target is deliberately narrow:

- exact fixed fleet cardinality $K$;
- fixed initial cabin placement and start times;
- one deterministic circulation pattern in the current movement network;
- Stop/Skip decisions at every supported visit;
- finite current horizon and existing tail semantics;
- no additional Waiting;
- the canonical scalar Passenger Waiting-Time or Journey-Time objective;
- current aggregate demand groups with integer Passenger quantities that may
  split across compatible direct rides;
- current direct-ride Passenger Assignment semantics;
- integer canonical time ticks and independently validated headways.

The first tranche does not include optimized initial placement, continuous
arbitrary Waiting, dynamic turnbacks, rope changes, passenger transfers, fleet
size selection inside one master, or a claim of integer optimality through
branch-and-price.

## Bound Contract

For a minimization problem, a complete physical timetable evaluated with the
canonical Passenger objective gives an upper bound:

$$
z^\star\le z(\bar x)=UB.
$$

A restricted set of trajectories $P'_c\subset P_c$ can only make the master
more restrictive. Therefore neither its integer optimum nor its LP optimum is
a global lower bound for the original problem:

$$
\min \operatorname{RMP}(P')
\not\le z^\star
\quad\text{in general}.
$$

The LP value becomes a valid trajectory-relaxation lower bound only after
pricing proves that no omitted trajectory/load column has negative reduced
cost for every required cabin start class. Let $J'\subseteq J$ be the current
set of valid conflict/resource rows. If the column universe exactly represents
every admissible no-wait cabin trajectory and relaxed Passenger load pattern,
then

$$
LB_{\mathrm{traj}}
=
\min \operatorname{LP}(P,J')
\le z^\star.
$$

Missing valid conflict rows can weaken this LP value but do not invalidate its
lower-bound direction. If $J'=J$, the value is the full declared trajectory-
master root LP. Missing columns do invalidate either claim unless complete
pricing or a separately proved reduced-cost bound accounts for them.

Exact pricing can already certify a corrected lower bound before column
convergence. Let $z_{\mathrm{RMP}}$ be the current restricted-master LP value
and let

$$
\rho_c=\min_{q\in Q_c}\bar c_{cq}
$$

be the exactly solved minimum reduced cost for cabin $c$. Because every cabin
has one convexity equation with right-hand side one, dual correction gives

$$
LB_{\mathrm{price}}
=
z_{\mathrm{RMP}}
+\sum_{c\in C}\min\{0,\rho_c\}
\le z^\star.
$$

At column convergence every $\rho_c\ge-\varepsilon_{\mathrm{price}}$ and the
corrected value approaches the RMP LP value within the declared numerical
tolerance. This bound is reported only when every $\rho_c$ is itself certified
by an exact pricing solve; heuristic reduced costs never enter it.

Every result records one of:

```text
PRIMAL_POOL_ONLY
  restricted columns; validated integer solutions may update UB only

TRAJECTORY_RELAXATION_BOUND
  complete pricing for the declared route-load universe under valid active
  rows; the pricing-corrected relaxation may update LB

FULL_ROOT_LP_CERTIFIED
  complete pricing and complete root conflict separation; the full declared
  trajectory-master root LP is solved

BRANCH_PRICE_CERTIFIED
  complete node pricing and separation; integer gap or optimality certified
```

No-Wait columns remain feasible when Waiting is allowed and can therefore
supply an upper bound for a waiting-enabled instance. They cannot certify its
trajectory lower bound because an omitted waiting trajectory may improve the
objective.

## Canonical Objects

### Whole-horizon trajectory column

For cabin $c$, a column $p\in P_c$ contains:

```text
column_id
instance_fingerprint
cabin_start_id
movement_network_id
route_option_ids by visit
exact event ticks
stop_skip_signature
resource occupancy intervals
direct-ride and onboard-segment coefficients
horizon and tail state
waiting_domain
source provenance
validation status
```

The column starts at the exact fixed placement of cabin $c$ and covers the
complete modeled horizon. It is individually movement-feasible. Joint
cross-cabin headways are master conflicts rather than internal column
conditions.

Columns use deterministic signatures and IDs. Physically identical columns
generated by DDD recovery, CP-SAT, pricing, or local mutation deduplicate to
one object while retaining all provenance.

### Passenger load pattern

Passenger continuity must remain tied to one selected cabin trajectory from
boarding through alighting. Supplying anonymous capacity on a physical
station-time leg would allow a Passenger flow to switch cabins silently and
would not reproduce the current direct-ride semantics.

For exact Dantzig--Wolfe pricing, associate a load pattern $\ell$ with a
movement trajectory $p$. The first bound-producing version uses extreme
points of the continuous single-cabin Passenger relaxation. It records
quantities $b_{p\ell g r}\ge0$ of demand group $g$ using direct ride $r$ on
$p$ and satisfies every onboard-capacity constraint internally:

$$
\sum_g\sum_{r:\,e\in r}b_{p\ell g r}\le Q
\qquad\forall\text{ onboard segment }e\text{ of }p.
$$

The mathematical pricing column is thus $q=(p,\ell)$. Fractional load patterns
are intentional: their convex combinations recover a Passenger LP relaxation
and therefore a valid lower bound for the integer Passenger problem. Pricing
integer load patterns could later convexify each single-cabin integer loading
set more strongly, but is not required for the first certificate. The
implementation may factor movement trajectories and load patterns so that
resource intervals are not duplicated. An empty load pattern always exists.

### Persistent column pool

`DddTrajectoryColumnPool` is append-only during one solve and supports:

- insertion with independent validation;
- deterministic deduplication;
- active/inactive column flags without deleting audit history;
- per-cabin and per-start-class indexing;
- resource-interval and Passenger-service indexing;
- primal source, pricing iteration, reduced cost, and validation provenance;
- checkpoint serialization independent of a live solver model.

### Hybrid coordinator

Use separate solver components:

```text
DddAggregateBoundOptimizer
DddTrajectoryRestrictedMaster
DddTrajectoryPricingOracle
DddTrajectoryConflictSeparator
CpSatTrajectoryValidator
HybridFixedKBoundOptimizer
```

The coordinator owns the shared global $LB$, $UB$, incumbent, budgets, column
pool, conflict pool, DDD discretization version, and certificate status. The
existing DDD optimizer and trajectory optimizer remain independently
benchmarkable.

## Restricted Trajectory Master

### Cabin selection

Let

$$
\lambda_{cp}\in\{0,1\}
$$

indicate that cabin $c$ uses whole-horizon trajectory $p$. Fixed-$K$ and fixed
starts give

$$
\sum_{p\in P'_c}\lambda_{cp}=1
\qquad\forall c\in C,
$$

with $|C|=K$. A cabin never changes identity between rotations because the
entire path is contained in its selected column.

### Passenger coupling

The first primal implementation retains the current extended formulation. For
every generated trajectory $p$, direct-ride variables $f_{gcpr}\ge0$ assign
demand group $g$ to ride $r$ of cabin $c$. Capacity on every onboard segment
$e$ is

$$
\sum_g\sum_{r:\,e\in r}f_{gcpr}
\le Q\lambda_{cp}.
$$

Demand balance is

$$
\sum_{c,p,r}f_{gcpr}+u_g=d_g
\qquad\forall g,
$$

and the objective uses the canonical ride cost plus the configured unserved
penalty. This is already close to `DddTrajectorySlotPoolOptimizer` and is the
preferred Phase-1/2 implementation because it is compact for a restricted
trajectory pool.

Adding one movement trajectory to this extended master creates a block of ride
variables and capacity rows, not merely one scalar variable. Before claiming
exact column generation, establish one of two equivalent mechanisms:

1. price integrated columns $q=(p,\ell)$ containing a movement trajectory and
   one extreme point of its relaxed Passenger load polytope; or
2. prove that block pricing of $p$ plus its generated Passenger variables and
   rows attains the same minimum reduced cost.

The first mechanism is the mathematical reference. Let
$\theta_{cp\ell}\ge0$ select integrated column $(p,\ell)$ in the LP. Then

$$
\sum_{p,\ell}\theta_{cp\ell}=1
\qquad\forall c,
$$

with the movement-selection projection

$$
\lambda_{cp}=\sum_\ell\theta_{cp\ell}.
$$

and demand coverage is

$$
\sum_{c,p,\ell,r}b_{p\ell g r}\theta_{cp\ell}+u_g=d_g.
$$

The restricted factorized master remains the preferred primal MIP. The
integrated formulation is the lower-bound reference. They need not have
identical LP relaxations: the existing integer Passenger model already has a
fractional relaxation counterexample. Tiny enumeration must instead verify
the exact relationship being claimed and that the bound master preserves
every complete integer movement-and-Passenger solution. This prevents an
anonymous Passenger rematching relaxation from being mistaken for the
intended direct-ride model.

### Resource conflicts

Two fixed-time trajectories have deterministic resource intervals. A basic
incompatibility row is

$$
\lambda_{cp}+\lambda_{dq}\le1.
$$

Prefer stronger resource cliques when their validity is proven:

$$
\sum_{(c,p)\in Q_{r,I}}\lambda_{cp}\le1.
$$

Resource-time rows should be expressed through the same half-open intervals,
point-headway semantics, horizon activation, and integer ticks as CP-SAT and
the complete validator. Pair rows remain an exact fallback.

Do not materialize all pair conflicts eagerly. Index positive or newly added
columns by resource and sweep their intervals. After every LP or integer
solve, add a deterministic strongest batch of violated rows. Every integer
candidate requires complete separation before it can update $UB$.

## Column Pricing

### Reduced cost

Solve the LP relaxation of the current restricted master and extract its dual
values. For an integrated candidate $q=(p,\ell)$ of cabin $c$, the reduced
cost has the form

$$
\bar c_{cq}
=
c_{cq}
-\alpha_c
-\sum_g\sum_r \sigma_g b_{p\ell g r}
-\sum_j \mu_j b_{cqj},
$$

where:

- $\alpha_c$ is the dual of the one-column equation;
- $\sigma_g$ values served demand of group $g$;
- $\mu_j$ prices a currently active resource or conflict row;
- $b_{cqj}$ is the new column's coefficient in that row;
- $c_{cq}$ is the exact Passenger and optional operating cost of the load
  pattern under the declared objective.

A column with

$$
\bar c_{cq}<-\varepsilon_{\mathrm{price}}
$$

is added. Pricing terminates only when every required cabin start class is
proved to have minimum reduced cost at least $-\varepsilon_{\mathrm{price}}$.

### No-wait pricing graph

With fixed starts and no additional Waiting, a route-option sequence uniquely
determines all later event ticks. Pricing is therefore a resource-constrained
shortest-path or dynamic program on a layered acyclic movement graph:

$$
(k,s,t)\longrightarrow(k+1,s',t+\tau_o).
$$

Each route-option arc contributes:

- Stop/Skip-dependent time and any operating cost;
- the Passenger opportunities opened at its exact event times;
- additive resource-row dual terms;
- the exact terminal and horizon state.

The pricing oracle jointly chooses the route sequence and a feasible load
pattern that maximizes demand-dual reward net of Passenger cost. With direct
rides and a small cabin capacity this may be implemented as a
resource-constrained dynamic program over the route label and onboard load
state. It is more difficult than movement-only shortest-path pricing. The
heuristic phase may instead generate a movement path first and solve its
single-cabin Passenger loading subproblem second, but that sequential method
cannot certify the minimum reduced cost unless its equivalence is proven.

Dominance may discard label $L_2$ at the same layered state when $L_1$ has no
greater reduced cost and no worse retained resource state. Every dominance
rule requires a proof and exhaustive comparison against enumeration on tiny
instances.

A pair row is defined over movement selections $\lambda_{cp}$ and
$\lambda_{dq}$. A genuinely new movement trajectory has coefficient zero in
an existing pair row; a new row is separated if it later receives positive
weight together with a conflicting trajectory. A newly generated load pattern
for an already known movement trajectory inherits all rows containing that
trajectory, and their dual contribution must be priced. An extensible
resource row defines membership for future movement trajectories and its
coefficient must likewise be included during pricing.

Additive resource-time rows are pricing-friendly. Membership in a dynamically
extended maximal clique may be nonadditive because a new column can join the
clique only if it conflicts with every existing member. The implementation
order is therefore:

1. use additive extensible resource-time rows where possible;
2. keep pair rows and fixed cliques as the exact separation fallback;
3. extend a clique to future columns only when its membership predicate can be
   priced exactly;
4. fall back to an exact CP-SAT or MILP pricing oracle if an active extensible
   row would otherwise lose required conflict information;
5. treat a heuristic pricing result as column generation for $UB$ only, never
   as proof of pricing completion.

### DDD relation

DDD supplies movement states, route options, reachability bounds, canonical
ticks, Passenger cost envelopes, and useful dual or support information. The
no-wait exact pricing graph is not restricted to the currently materialized
DDD time cells if that would exclude a legal physical trajectory.

This distinction is mandatory:

- exact physical columns are safe for primal solutions;
- a pool restricted to current DDD time points is only a primal restriction;
- a trajectory LP lower bound requires pricing over every admissible no-wait
  route sequence and relaxed load pattern, or a separately proved optimistic
  column relaxation that represents the omitted configurations.

DDD time refinement may still guide graph construction and later Waiting
pricing, but it must not silently turn a restricted column pool into a claimed
lower bound.

## Row-and-Column Loop

For one current root master:

```text
repeat:
    solve restricted-master LP
    separate violated conflicts among positive columns
    if conflict rows were added:
        continue

    price every fixed-start cabin class
    if improving columns were added:
        index their resource intervals
        continue

    LP row-and-column fixed point reached
```

At configurable intervals, solve the restricted master as a MILP under a
short primal budget:

```text
select one trajectory per cabin
complete conflict separation
assemble movement plan
run independent movement validation
solve exact fixed-movement Passenger Assignment
update UB if improved
```

CP-SAT is called only when the selected columns need exact joint checking,
bounded timing repair, or an explanatory conflict. It does not choose the
master's Stop/Skip support again unless explicitly running a separate primal
neighborhood.

The first exact-pricing milestone stops with a certified root relaxation and a
validated incumbent. The earlier restricted-pool prototype remains
primal-only. Proving the integer optimum requires branch-price-and-cut: pricing
and conflict separation must be repeated at every branch node under a
pricing-compatible branching rule. That is a later gate, not part of the
first prototype.

## Combined Anytime Process

The top-level fixed-$K$ solve uses independent channels:

1. Run the anonymous DDD master to obtain an early $LB_{\mathrm{DDD}}$ and
   candidate supports.
2. Run the existing unrestricted CP-SAT bootstrap to obtain early complete
   movement plans.
3. Insert validated CP-SAT, DDD-recovered, all-stop, and deterministic local
   variants into the trajectory pool.
4. Solve and separate the integer restricted trajectory master to improve
   $UB$.
5. Solve its LP and generate dual-guided columns.
6. Once exact pricing is available, update

   $$
   LB\leftarrow\max\{LB_{\mathrm{DDD}},LB_{\mathrm{traj}}\}.
   $$

7. Feed selected trajectories, Passenger demand duals, and conflict
   provenance back to CP-SAT neighborhoods and DDD diagnostics.
8. Continue within one shared wall-clock budget and atomically checkpoint both
   bound channels.

The channels need not alternate one-for-one. An adaptive scheduler allocates
the next budget slice to the component with the best recent bound or incumbent
gain per second. The first version uses a deterministic fixed schedule so the
algorithm remains reproducible.

## Waiting Extension

Waiting is added in two explicitly different stages.

### Primal waiting repair

Given selected no-wait route sequences, CP-SAT or the exact timing model may
insert bounded Waiting at legal holding locations. Every repaired result is
re-evaluated with exact Passenger Assignment and may update $UB$. Repaired
whole-horizon trajectories return to the pool as distinct columns.

This stage gives no waiting-enabled trajectory lower bound.

### Exact waiting pricing

For a waiting domain $w\in\{0,\ldots,W_v\}$, pricing later adds holding arcs

$$
(k,s,t)\longrightarrow(k,s,t+w).
$$

Enumerating every tick globally is avoided through DDD-refined candidate
times, interval labels, or exact dominance. A waiting-enabled lower bound is
reported only if the pricing oracle proves coverage of every allowed waiting
choice. If it searches only selected DDD points, its result remains
`PRIMAL_POOL_ONLY`.

## Public API and Result Schema

Add an optimizer mode rather than overloading the EAN headway-generation enum:

```text
FixedKPassengerOptimizerMode
  DDD_AGGREGATE
  DDD_TRAJECTORY_HYBRID
  EAN_REFERENCE
```

The hybrid configuration contains at least:

```text
total_time_limit_seconds
trajectory_master_time_slice_seconds
trajectory_lp_time_slice_seconds
pricing_mode = OFF | HEURISTIC | EXACT_NO_WAIT
pricing_tolerance
maximum_columns_per_pricing_round
conflict_batch_size
clique_separation_enabled
cp_validation_time_limit_seconds
waiting_repair_mode
random_seed
checkpoint_directory
```

The result extends the existing fixed-$K$ certificate with:

```text
trajectory_bound_status
trajectory_pool_size by cabin and provenance
restricted_master_integer_objective
validated_trajectory_upper_bound
trajectory_lp_value
trajectory_pricing_best_reduced_cost
trajectory_pricing_corrected_lower_bound
pricing_calls and proof statuses
generated_columns by round
separated pair and clique rows by round
time to first and best trajectory incumbent
time spent in master LP, master MIP, pricing, separation, CP, and recourse
global LB/UB/gap trajectory over wall time
```

Progress uses a fixed-width single line and always distinguishes restricted
values from certified global bounds, for example:

```text
TRJ r=012 C=184 R=37 rc=-2.31e+02 LB=4.09e+05 UB=6.89e+05 GAP=40.6%
```

An RMP LP value is never printed in the global `LB` field before the exact
pricing gate succeeds.

## Implementation Phases

### Phase 0: Freeze the experiment and certificate contract

- use `five_station_circle_cw_half_skip_no_wait_v0`, fixed starts, $K=19$,
  Journey Time as the primary case;
- add one tiny exhaustive ring and the current Three-Station case;
- freeze demand, horizon, objective ID, solver seeds, and equal wall-clock
  budgets;
- record current DDD, CP-SAT, trajectory-slot, eager EAN, and delayed EAN
  metrics;
- add schema assertions preventing restricted-pool objectives from entering
  the global lower-bound field.

Exit criterion: one benchmark command produces directly comparable bound and
incumbent traces for every enabled backend.

### Phase 1: Persistent whole-horizon column infrastructure

- extract the current trajectory-slot candidate representation behind the
  canonical column and pool interfaces;
- retain the current optimizer behavior through an adapter;
- persist columns across DDD rounds instead of rebuilding a transient pool;
- add deterministic IDs, provenance, resource indices, checkpoint roundtrip,
  and exact reconstruction tests;
- seed from all existing validated CP-SAT and DDD movement plans.

Exit criterion: the refactored restricted master reproduces the current
trajectory-slot result and objective, and every selected solution passes the
existing movement and Passenger validators.

### Phase 2: Primal Passenger master and route-load bound reference

- retain the current trajectory-keyed direct-ride variables and onboard
  capacity rows;
- reproduce the canonical direct-ride Passenger objective;
- define the integrated trajectory-plus-load-pattern reference formulation;
- export stable LP duals for cabin choice, demand coverage, and active
  resource rows;
- compare the factorized primal LP with the integrated bound reference on tiny
  enumerated instances and document their exact relation;
- retain exact integer fixed-movement Passenger recourse for final scoring.

Exit criterion: for every fixed trajectory selection in tiny tests, the new
primal master and existing Passenger Assignment agree on the integer
objective; every complete integer solution maps into the bound reference; the
full generated reference agrees with direct enumeration; duals pass sign and
finite-difference checks.

### Phase 3: Heuristic dual-guided pricing

- build the layered no-wait movement-pricing graph;
- solve the single-cabin Passenger loading problem on each generated path;
- generate negative-reduced-cost candidates heuristically;
- validate and insert every generated physical column;
- alternate LP solves, conflict separation, pricing, and short integer solves;
- use all results for $UB$ only.

Exit criterion: on the Five-Station case, pricing generates Passenger-relevant
columns not already present in route-diversity seeds and improves the matched-
budget incumbent or reaches the same incumbent with materially fewer CP calls.

Stop condition: if the RMP is dominated by nearly duplicate columns or does
not improve the primal trace over the existing CP candidate pool, do not build
exact pricing before diagnosing the column definition.

### Phase 4: Exact no-wait pricing gate

- implement an exact joint route-and-load DP, CP-SAT, or MILP pricing oracle;
- compare its minimum reduced cost with exhaustive trajectory enumeration on
  tiny instances for randomized dual vectors;
- compute the dual-corrected lower bound from every complete set of exact
  cabin pricing results;
- prove every state reduction and dominance rule;
- solve every cabin start class and return explicit optimality status;
- reject pricing certificates on time limit, incomplete search, or unsupported
  conflict-row vocabulary.

Exit criterion: exhaustive tiny tests show identical minimum reduced costs and
columns, and a complete set of exact cabin pricing results can safely mark the
pricing-corrected value as `TRAJECTORY_RELAXATION_BOUND`. Root-LP completion is
reserved for Phase 5.

### Phase 5: Exact alternating row-and-column root solve

- separate fractional resource conflicts and cliques;
- price against all active dual rows;
- repeat until neither a violated row nor a negative-reduced-cost column
  exists;
- handle numerical tolerances and duplicate columns deterministically;
- combine the resulting bound with the anonymous DDD lower bound.

Exit criterion: on all exhaustively enumerable cases, the generated root LP
equals the full-column, full-row root LP. Every reported bound satisfies the
known integer optimum.

### Phase 6: Hybrid fixed-$K$ coordinator

- introduce the public optimizer mode and shared budget;
- retain separate DDD and trajectory progress, checkpoints, and provenance;
- exchange validated plans, seeds, demand-dual pricing signals, and conflict
  explanations;
- implement deterministic scheduling first and evidence-based adaptive budget
  allocation later;
- return the best certified interval even on interruption.

Exit criterion: an interrupted run reloads without losing any completed bound
or incumbent update, and disabling the trajectory backend reproduces the
current DDD result.

### Phase 7: Waiting-enabled primal extension

- repair selected route sequences with bounded legal Waiting;
- return repaired columns to the pool;
- recompute all resource intervals and Passenger costs;
- compare No-Wait and Wait-enabled upper-bound improvement;
- keep $LB_{\mathrm{traj}}$ scoped to No-Wait until exact waiting pricing is
  independently completed.

Exit criterion: every waiting-enabled incumbent passes complete validation and
is labelled with the correct bound domain.

### Phase 8: Conditional exact and general extensions

Only after the root method passes its performance gates, consider:

- branch-price-and-cut for integer optimality;
- optimized initial placement columns or a separate placement master;
- multiple circulation patterns and dynamic turnbacks;
- transfer-capable Passenger flow;
- outer fleet-size search over independently certified fixed-$K$ intervals;
- exact waiting pricing.

## Tests

### Unit tests

- deterministic column signatures and deduplication;
- fixed-start compatibility and complete-horizon coverage;
- exact reconstruction of Stop/Skip and event ticks;
- resource-interval equality with the existing validator;
- Passenger service-leg coefficients and capacity;
- pair and clique conflict validity;
- reduced-cost arithmetic and dual signs;
- pricing-corrected lower-bound arithmetic;
- pricing dominance safety;
- checkpoint roundtrip and provenance.

### Exhaustive mathematical tests

For tiny rings, enumerate every no-wait Stop/Skip sequence and compare:

- complete trajectory universe;
- complete extreme-point load-pattern universe for tiny fractional
  demand/capacity relaxations;
- exact pricing minimum reduced cost under randomized duals;
- generated versus full master LP;
- full-pool primal MIP versus the exhaustively enumerated physical integer
  optimum on tiny cases;
- independently evaluated Passenger objective;
- all reported $LB\le z^\star\le UB$ relations.

Use deliberately conflicting columns, identical Passenger offers, horizon-edge
events, Stop/Skip merges, and multiple columns with equal reduced cost.

### Regression tests

- current DDD-only behavior is unchanged when the hybrid is disabled;
- current `DddTrajectorySlotPoolOptimizer` result is reproduced through its
  adapter;
- CP-SAT and EAN validation remain authoritative;
- No-Wait and Waiting certificates cannot be combined accidentally;
- restricted-pool infeasibility never becomes global infeasibility;
- solver time limits never masquerade as pricing optimality.

## Benchmark and Acceptance Matrix

Measure at equal total wall-clock budgets:

| Case | Purpose |
|---|---|
| tiny exhaustive ring | mathematical equivalence and pricing proof |
| Three-Station fixed-$K$ No-Wait | regression and overhead |
| Five-Station circle, $K=19$, Skip/No-Wait | primary identity-gap case |
| Five-Station circle at lower and higher feasible $K$ | density sensitivity |
| bounded-Wait variant | primal repair only, separate bound domain |

Report:

- time to first finite lower bound;
- time to first and best validated upper bound;
- $LB$, $UB$, absolute and relative gap over time;
- root LP before and after exact pricing;
- columns by source and cabin;
- pricing calls, best reduced costs, and proof status;
- separated pairs and cliques;
- master LP/MIP, pricing, CP, recourse, and validation time;
- model rows, columns, nonzeros, peak RSS, and checkpoint size.

Proceed beyond heuristic pricing only if the trajectory method materially
improves the matched-budget upper-bound trace or demonstrates a stronger
certified root lower bound on the primary case. A negative result is retained
as evidence that adaptive cohort disaggregation or the continuous EAN should
remain the principal exact model.

## Risks

- The number of columns is exponential; pricing must exploit the layered
  route structure rather than enumerate complete trajectories.
- Passenger-aware pricing may become a resource-constrained shortest-path
  problem with weak dominance.
- Extensible clique membership and inherited pair rows for new load patterns
  can make pricing nonadditive and force an exact CP-SAT/MILP oracle.
- Dense near-capacity cases may create a difficult set-packing master even
  without Big-$M$ order variables.
- Whole-horizon columns can be too rigid for long horizons; rolling horizons
  or compatible path fragments are later alternatives, not first-version
  shortcuts.
- Waiting multiplies time variants and must not be introduced before the
  No-Wait pricing experiment establishes value.
- A strong root LP does not imply easy integer optimization; integer
  optimality would require branch-price-and-cut.
- A good upper bound does not prove that Skip-Stop is better; comparison
  claims require matched objective definitions and certified intervals for
  both operating modes.

## Thesis Integration

If the primal phases succeed, describe them as:

> a passenger-guided restricted whole-horizon trajectory master with delayed
> resource-conflict separation and exact fixed-timetable evaluation.

Use **column generation** only after reduced-cost pricing is implemented. Use
**exact root column generation** only when every pricing subproblem terminates
with proof and the declared trajectory universe is complete. Use
**branch-price-and-cut** only after pricing and separation operate at every
branch node.

The thesis should distinguish:

- anonymous DDD flow as an early scalable relaxation;
- complete trajectory identity as a primal and alternative LP-bound channel;
- restricted-pool objectives from certified lower bounds;
- Passenger-demand duals as pricing guidance;
- row generation for cross-cabin resource conflicts;
- CP-SAT as validator, repair engine, and optional exact pricing oracle;
- No-Wait and Waiting bound domains;
- validated operational improvement from mathematical optimality evidence.

The principal empirical question is not whether branch-and-price can
eventually prove every instance. It is whether complete trajectory identity
can deliver materially better passenger timetables and a useful certified
root bound before the current anonymous DDD loop accumulates hundreds of
support-specific cuts.

## Assumptions

- The physical `Scenario` and `EanMovementNetwork` remain the source of truth.
- The first column universe uses exact current no-wait timing and finite
  current-horizon semantics.
- Fixed-$K$ means exactly $K$ active complete trajectories.
- Fixed initial placement is part of the first instance definition.
- Passenger objectives and units use the canonical existing contract.
- Every upper bound passes complete movement validation and exact Passenger
  recourse.
- Every trajectory lower bound records complete pricing provenance.
- The anonymous DDD lower bound remains available even if trajectory pricing
  is interrupted or abandoned.

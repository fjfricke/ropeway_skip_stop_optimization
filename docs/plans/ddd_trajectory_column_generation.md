# DDD-Guided Whole-Horizon Trajectory Column Generation

Status: **exact no-wait root prototype implemented; scalable pricing and
compatible-column generation remain experimental**

Implementation checkpoint (2026-08-16): in addition to the Phase-1
`restricted_primal` kernel, a guarded exhaustive tiny-instance oracle, an exact
single-cabin no-wait route--load pricing MILP, and a standalone root
row-and-column prototype are available. Randomized-dual tests compare pricing
against complete enumeration. Solver dual bounds from interrupted pricing are
used conservatively in the reduced-cost correction; only exact pricing may
claim convergence. The scalable Five-Station experiment remains open because
short pricing calls generate improving but mutually incompatible columns and
their corrected bound is weaker than the independent DDD bound. The proof
channel now records each pricing MILP's incumbent, certified reduced-cost
lower bound, gap, model size, node count, and the resulting aggregate bound
correction. Proof and post-proof pricing expose separate `MIPFocus` settings.
The proof default remains Gurobi's balanced mode (`0`) because matched 2- and
5-second experiments found stronger bounds than explicit bound focus (`3`);
post-proof column enumeration defaults to feasibility focus (`1`).

Pair-specific conflict rows require special care. Their coefficient is defined
only for the generated trajectory IDs named by the row. The current pricing
MILP does not encode equality to every named trajectory. It therefore prices
the omitted-column universe by excluding the current pool with exact route
No-Goods. This is not heuristic diversity: RMP dual feasibility proves all
current columns have nonnegative reduced cost, while every omitted column has
zero coefficient in the fixed pair rows. Hence the complete minimum is
`min(0, omitted-column minimum)`. Removing these proof exclusions without
pricing the pair-row membership produces artificially negative reduced costs
for existing columns and is invalid as a convergence test. Extensible
resource-window rows remain priced directly through their physical membership
predicate.

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

where $LB_{\mathrm{traj}}$ is absent until every cabin supplies either an exact
pricing value or a certified lower bound on it.

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
tolerance. More generally, if pricing returns a proved lower bound
$\underline\rho_c\le\rho_c$, then replacing $\rho_c$ in the correction by
$\underline\rho_c$ is conservative and remains valid. A MIP timeout may
therefore contribute its finite solver `ObjBound`; its incumbent may add a
primal column but may not certify convergence. Purely heuristic reduced costs
never enter the correction.

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

#### Phase 1 evidence (2026-08-14)

Phase 1 is implemented.  The restricted master and its option/ride caches are
persistent across DDD rounds.  A separate CP-SAT primal-diversification
interval can request further complete schedules after the first incumbent.
Every archived route pattern is excluded only inside that heuristic CP-SAT
call.  Consequently, an exhausted diversification search proves only that no
new route pattern remains outside the archive; it neither cuts the DDD master
nor proves the physical problem infeasible.

On `five_station_circle_cw_half_skip_no_wait_v0`, fixed starts, $K=19$ and
Journey Time, ten archived route patterns produced 62 unique
cabin columns.  Against the same sequence of individually evaluated CP-SAT
candidates, the best individual objective was $688{,}161.64$ passenger-seconds.
The restricted master recombined columns to a fully validated objective of
$685{,}629.36$, an improvement of $2{,}532.29$ passenger-seconds (about
$0.37\%$).  Incremental restricted-master resolves after initial construction
took roughly $0.22$--$0.37$ seconds in this smoke run.  This is a positive
primal signal, not a lower-bound result; the certified DDD lower bound remained
$0$ in the short experiment.

The observation that most later complete schedules added only one new cabin
column also motivates Phase 2: dual and load information must show whether the
pool contains economically useful diversity rather than merely more route
fingerprints.

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

#### Phase 2 implementation status (2026-08-14)

The solver-independent factorized Passenger LP, size-limited integrated
load-pattern reference, and stable dual export are implemented.  Exhaustive
active-set enumeration generates every extreme point of each tiny
single-trajectory continuous load polytope.  Randomized tiny regressions show
that the factorized perspective LP and the integrated reference have the same
objective, including active cross-cabin incompatibility rows.  Demand duals
use the documented solver-native sign and pass a finite-difference check.

The production restricted-master evaluation now solves and records the
factorized LP after complete pair separation over the current column pool,
including its objective, solve time, and dual fingerprint.  This remains
`PRIMAL_POOL_ONLY`: the integrated reference enumeration is intentionally
capped and no omitted movement trajectory has yet been priced.  The next gate
is to consume these duals in heuristic no-wait pricing and demonstrate
Passenger-relevant new movement columns.

Two five-round Five-Station $K=19$ smoke runs ended with 57 movement options
and 3,176--3,190 direct-ride variables.  Depending on the nondeterministic
eight-worker CP-SAT archive, integer incumbent separation had discovered
10--87 incompatibilities, whereas complete LP pool separation found 117--257.
The row-clean factorized LP lay between $673{,}682.01$ and $685{,}459.16$;
the validated integer pool plan was $685{,}629.36$.  Thus the observed local
restricted-pool LP gap ranged from about $0.025\%$ to $1.74\%$; it is not the
global optimization gap.  In the fully timed final run, complete pair
separation and LP construction took $0.53$ seconds and Gurobi optimization
took $0.12$ seconds.  Dual extraction is therefore not the current runtime
bottleneck.  Formal matched comparisons must replay a frozen candidate archive
or use deterministic single-worker CP-SAT.

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

#### Phase 3 implementation status (2026-08-14)

The first heuristic-pricing variant is implemented as a joint physical
CP-SAT schedule search rather than as an independent single-cabin beam search.
For every structurally possible direct ride, it creates an availability
literal for the conjunction of board STOP, alight STOP, release time, and
Passenger horizon. Its objective uses the actual no-wait boarding or
alighting event time and the current restricted-master demand dual. CP-SAT
still contains every original resource interval, so every returned complete
schedule is physically feasible. Exact fixed-movement Passenger recourse
scores the result, its cabin trajectories enter the canonical pool, and the
next restricted-master solve may recombine them.

This implementation is deliberately a primal heuristic. It assigns the full
local load upper bound to every ride opportunity independently and does not
model shared cabin capacity, competing demand, or duals of pair-specific
conflict rows inside CP-SAT. Its objective is therefore a dual-guided proxy,
not a valid reduced cost. The bound status remains `PRIMAL_POOL_ONLY` and the
global DDD lower bound is unchanged.

In a five-round Eight-Worker smoke run on the Five-Station $K=19$ case, both
variants started from a 21-column pool with restricted LP and integer value
$694{,}914.10$. Restricted-primal alone retained this incumbent. Five
ten-second pricing calls, each followed immediately by an RMP resolve,
expanded the pool to 115 columns. Successive post-pricing restricted LP values
were $687{,}011.63$, $665{,}137.77$, $658{,}756.43$, $655{,}129.33$, and
$654{,}777.13$. The best fully validated integer Passenger plan reached
$663{,}475.60$, an improvement of $31{,}438.51$ passenger-seconds or
$4.52\%$. Total solve time increased from $8.70$ to $80.13$ seconds, of which
roughly 51 seconds were pricing model construction and search. This is a
strong primal signal, but formal matched-budget evidence still requires frozen
seed replay; single-worker CP-SAT did not find the initial Five-Station
incumbent within 30 seconds.

### Phase 4: Exact no-wait pricing gate

The exhaustive side of this gate is now implemented. A guarded tiny-instance
builder generates every locally feasible no-wait cabin trajectory, constructs
all pairwise cross-cabin incompatibility rows, and solves the complete
factorized Passenger LP and MIP. Completeness is explicit model provenance;
only a complete column set plus complete row separation can report
`FULL_ROOT_LP_CERTIFIED`. The runner
`benchmarks/run_ddd_trajectory_bound_reference.py` aborts on its trajectory or
pair-check limits instead of returning a partial value.

Initial physical Three-Station results have zero LP--MIP gap for Journey Time
and Waiting Time at $K\in\{3,4\}$ and horizons through 500 seconds. The largest
run contains 177 trajectories and 4,273 incompatibility rows. This supports
continuing the pricing investigation, but it is not yet evidence that the
relaxation is generally tight: demand/start variants and adversarial linear
column costs still need to expose possible fractional conflict-graph gaps.
The exact pricing side is now also implemented for fixed starts and No-Wait.
It chooses the complete Stop/Skip sequence, exact integer event ticks, and an
integral extreme point of the local direct-ride loading polytope. Passenger
counts use binary expansion, reducing up to $Q$ interchangeable unit binaries
per ride to $O(\log Q)$ bits. Earliest-event bounds remove a ride only when its
best possible marginal reduced cost is already nonnegative or its earliest
alighting lies beyond the service horizon. Both reductions are exact.

Five randomized dual vectors for every cabin in the exhaustive Three-Station
fixture give the same minimum reduced cost, route column, and Passenger load
as explicit enumeration. The exact root loop reaches the complete LP and MIP
value after two rounds for $K=3,H=250$ and $K=4,H=500$; these instances have
zero observed root integrality gap.

On `five_station_circle_cw_half_skip_no_wait_v0` with $K=19$, two-second
pricing calls do not prove any of the 19 cabin subproblems. Their Gurobi bounds
still yield a valid correction, but it is negative and hence dominated by the
known nonnegative objective bound. Nevertheless, every call returns a valid
negative-reduced-cost incumbent: the pool grows from 19 to 38 and then 57
trajectories in two rounds. The restricted LP decreases from $668{,}769$ to
$625{,}948$, while the validated integer upper bound stays at $668{,}769$.
The 176 incompatibility rows created in round two explain the failure: one
best column per cabin gives little compatible diversity.

Exit criterion: **met on the exhaustive tiny reference**. It is not a
scalability claim. The remaining practical gate is to obtain stronger pricing
bounds and several compatible/diverse improving columns per cabin without
losing the proof contract.

### Phase 5: Exact alternating row-and-column root solve

The first standalone implementation rebuilds every incompatibility pair among
the current columns, solves the factorized LP and finite-pool MIP, prices every
cabin, validates every returned physical trajectory, and repeats. It is exact
on the exhaustive fixtures. On pricing timeout, a valid negative-cost
incumbent is retained as a heuristic column and the solver objective bound is
used only for the conservative lower-bound correction.

The next implementation is split into a proof-producing row-and-column path
and two explicitly primal-only accelerators. Pair conflicts remain the exact
reference and fallback until equivalence of every current headway family with
the new resource rows has been tested exhaustively.

Implementation status, 16 August 2026: Phases 5A--5C are implemented behind
opt-in settings. `PAIR_ONLY` remains the default. The resource mode retains
the complete eager pair fallback, alternates LP solve and window separation,
prices every active window in the exact No-Wait MILP, and records window,
separation and extra-column metrics. Multiple columns are generated only after
the complete-universe proof-pricing call. In the current pair-row
implementation that call prices the omitted-column complement with exact
No-Goods and combines its result with the known nonnegative reduced costs of
the RMP columns. Incumbent-compatible replacement pricing
from Phase 5D remains conditional on the matched diversity experiment.

In the matched two-round Five-Station $K=19$ smoke run with two seconds per
proof-pricing call, Pair-only produced restricted LP values $668{,}769$ and
$626{,}423$. The resource mode added 21 windows in round two and raised its
restricted LP back to $668{,}769$, equal to the current validated incumbent.
Setup and separation remained below one second; total time stayed at roughly
77 seconds in both variants because pricing consumed 38 seconds per round.
The global certified lower bound nevertheless remained zero: none of the 19
pricing MILPs proved optimal, so the conservative pricing correction was
negative. This is strong evidence that the identity gap in the restricted
master is addressed, but the immediate bottleneck has moved to pricing bounds.

A ten-round bound-focused run (two seconds per cabin and round) confirmed that
additional root-CG rounds do not fix that bottleneck. The pool grew from 19 to
80 trajectories, fixed pair rows from 0 to 614, and resource windows from 0 to
104 in 396 seconds. The restricted LP and validated UB stayed at $668{,}769$,
while the final correction was $-1{,}463{,}733$ and the admitted global LB
therefore remained zero. In the last round every one of the 19 pricing MILPs
stopped after its root node; individual certified reduced-cost bounds ranged
from roughly $-66{,}000$ to $-101{,}000$. This is a systematic weak-pricing-
relaxation effect, not one pathological cabin.

Matched first-round pricing confirms that more time helps but does not yet
make the channel useful:

| Slice per cabin | `MIPFocus` | Pricing correction | Corrected value | Added columns |
| ---: | ---: | ---: | ---: | ---: |
| 2 s | 0 | $-1{,}588{,}322$ | $-919{,}553$ | 19 |
| 2 s | 3 | $-1{,}693{,}057$ | $-1{,}024{,}288$ | 19 |
| 5 s | 0 | $-1{,}240{,}224$ | $-571{,}455$ | 19 |
| 5 s | 3 | $-1{,}634{,}675$ | $-965{,}906$ | 19 |

Thus longer regression tests are useful for correctness and trend checks, but
running hundreds of unchanged rounds is not the next algorithmic lever. The
next bound milestone is a stronger pricing relaxation or an exact acyclic
dynamic-programming/shortest-path pricing formulation, benchmarked first on a
single representative cabin and frozen RMP dual vector.

That milestone was reached on 16 August 2026. The implemented
`TIME_EXPANDED_PATH` pricer enumerates only exactly reachable No-Wait nodes
$(k,s,t)$, selects one whole-horizon path, and sends continuous Passenger flow
on the same selected time arcs from a release-feasible STOP boarding arc to a
service-horizon-feasible STOP alighting arc. Arc-time costs are constants;
there are no Passenger-count--event-time products. Per-time-arc capacity rows
prevent Passenger flow from combining the boarding time of one fractional
route with the alighting time or capacity of another.

The Five-Station graph for one fixed start has only 457 reachable time nodes
over 37 visit layers and at most 24 nodes in one layer. On the frozen all-stop
RMP, cabin 0 changed from an unresolved 30-second compact-MILP gap of 4,472 to
an exact time-expanded optimum in 0.51 seconds. All 19 first-round pricing
problems then solved exactly in 8.97 seconds and produced the first positive
trajectory correction bound, $23{,}026$.

The matched ten-round Pair-only run is the new scalable checkpoint:

| Round | Columns before pricing | Certified LB | Validated UB | Gap |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 19 | $23{,}026$ | $668{,}769$ | 96.56% |
| 2 | 38 | $473{,}293$ | $668{,}769$ | 29.23% |
| 5 | 95 | $502{,}535$ | $668{,}769$ | 24.86% |
| 8 | 152 | $549{,}407$ | $659{,}493$ | 16.69% |
| 10 | 190 | $549{,}407$ | $572{,}136$ | 3.97% |

The run took 108 seconds, ended only at its configured iteration limit, and
solved all 190 cabin-pricing calls exactly. It generated 209 trajectories in
total and 2,385 current-pool Pair rows. This is the first Five-Station result
where the trajectory channel both beats the anonymous DDD bound and leaves a
small certified global gap.

Continuation to the actual fixed point required only eleven more rounds. In
round 20 the gap was already 0.045%; round 21 found no negative reduced-cost
trajectory for any cabin and therefore certified the complete Root-LP:

| Quantity | Fixed-point result |
| --- | ---: |
| Rounds | 21 |
| Generated trajectories | 372 |
| Current-pool Pair rows | 7,109 |
| Certified Root-LP lower bound | $556{,}628.822$ |
| Feasible integer upper bound | $556{,}809.568$ |
| Certified relative gap | $0.0325\%$ |
| Total runtime | 420 s |

Every one of the 399 proof-pricing calls solved exactly. The remaining gap is
therefore the restricted integer-master versus complete Root-LP integrality
gap, not missing trajectories or an uncertified pricing correction. Late-round
pricing remained near ten seconds for all 19 cabins combined, while master
work grew to about 31 seconds. Future performance work should consequently
target incremental Pair indexing and master reconstruction rather than a
larger default pricing budget.

Resource-window pricing is no longer the scalable default. It raised the bound
to $240{,}073$ by round four, but 142--161 active windows made pricing setup
exceed the two-second per-cabin budget; the run correctly ended `UNKNOWN` in
round six. Pair-only remains exact because current Pair rows name generated
columns, omitted trajectories have coefficient zero, and proof pricing uses
the exact current-pool complement. Physical windows remain an optional root
strengthening experiment pending sparse/delayed pricing membership generation.

The root loop also has a persistent continuation contract. After every
completed round it can atomically store the complete trajectory pool, monotone
global bounds, the best feasible integer option selection, full round history,
accumulated runtime, and any separated resource windows. Resume reconstructs
the master deterministically and starts with round `completed_rounds + 1`.
Instance fingerprint, objective, conflict-row mode, round numbering, bounds,
incumbent membership, and window ordering are checked before solving. The
round limit is total: a ten-round checkpoint resumed with a limit of 30 runs
rounds 11 through 30 without discarding the already certified bounds.

#### Phase 5A: Canonical resource-window rows

For every physical resource $r$, a trajectory contains zero or more protected
occupancy intervals. For a fixed canonical anchor tick $\tau$, define

$$
a_{r\tau,cp}
=
\#\{I\in\mathcal I_r(p):\tau\in I\}.
$$

The first No-Wait implementation supports capacity-one resource families for
which individual trajectory validation guarantees
$a_{r\tau,cp}\in\{0,1\}$. The valid master row is

$$
\sum_{c,p}a_{r\tau,cp}\lambda_{cp}\le b_r,
$$

with $b_r=1$ for the current headway resources. Capacity $b_r>1$ remains in
the type and proof contract but is not required by the first experiment.

Implementation objects:

- `DddTrajectoryResourceWindow`: stable resource ID, anchor tick, half-open
  interval convention, capacity, headway/occupancy provenance and waiting
  domain;
- `DddTrajectoryResourceWindowIndex`: exact coefficients for current columns,
  endpoint sweep separation and deterministic row IDs;
- `DddTrajectoryResourceWindowRow`: sparse master row plus provenance and
  completeness state;
- `DddTrajectoryResourceWindowPricingTerm`: the same membership predicate in
  the single-cabin pricing MILP;
- `DddTrajectoryConflictRowMode`:
  `PAIR_ONLY`, `RESOURCE_WINDOWS_WITH_PAIR_FALLBACK`; no resource-only exact
  mode is exposed until the fallback is empirically and mathematically
  redundant.

Half-open protected intervals are canonical. For the current directional
occurrence semantics, use

$$
[t^{\mathrm{enter}},t^{\mathrm{clear}}+h_r).
$$

For a point headway $h_r$ and event tick $t$, this reduces to $[t,t+h_r)$;
an anchor belongs exactly when
$t\le\tau<t+h_r$. Platform occupancy uses the existing entry/clear semantics
and is converted to the same protected-interval representation. Boundary
events at exactly $t+h_r$ do not conflict. All conversions use integer ticks;
there is no floating-point window comparison in the master or separator.

The separator considers only positive current master columns, groups
occurrences by physical resource and sweeps sorted entry/exit endpoints. At an
identical integer tick, exits are processed before entries, consistently with
the half-open convention $[s,e)$.
Whenever weighted occupancy exceeds $b_r$, it adds the canonical row anchored
at the first deterministic violating endpoint. Repeated separation of the same
solution is idempotent. Pair separation still runs afterwards and treats an
uncovered pair as a metric and, in strict verification mode, an internal
coverage error for supported resource families.

Every active resource-window row must be extensible to future columns. The
pricing MIP receives its dual and an exact binary membership expression. With
minimization convention $\mu_{r\tau}\le0$, the reduced cost includes

$$
-\sum_{r,\tau}\mu_{r\tau}a_{r\tau,cp},
$$

which is a nonnegative congestion penalty. A row may enter the certified
pricing correction only when the master coefficient builder and pricing
membership expression share the same canonical predicate and fingerprint.

For bounded Waiting, the row family remains valid, but its coefficient must be
derived from the selected entry and clear ticks including the actual wait. A
No-Wait endpoint formula may never be reused to certify the Waiting model.
Waiting support is therefore a separate capability flag and becomes
certificate-eligible only after exhaustive master/pricing coefficient tests
over all integer wait values. Direction-dependent or otherwise asymmetric
headways that cannot be represented by one protected-interval predicate remain
in the exact pair fallback.

#### Phase 5B: Alternating solve order and certificates

Each root round performs:

1. build or update the current restricted master;
2. solve its LP to optimality;
3. separate all violated active resource-window rows; if any are added, return
   to step 2 without pricing;
4. run pair-conflict separation as the exact fallback; if rows are added,
   return to step 2;
5. solve complete-universe pricing for every cabin using Passenger and active
   resource-window duals; computationally, fixed pair rows require pricing the
   omitted-column complement because their named RMP columns already have
   their pair duals in the master;
6. record exact reduced cost or a certified solver lower bound for every
   cabin, validate and add every improving incumbent column, then repeat;
7. declare root convergence only if separation is complete, every pricing
   problem is exact, and no reduced cost is below tolerance.

Missing valid rows relax the model and therefore preserve the lower-bound
direction. Missing columns do not; they are handled only through exact pricing
or the conservative solver-bound correction. `FULL_ROOT_LP_CERTIFIED` requires
both clean separation and exact no-negative-column pricing. The global bound
remains

$$
LB=\max\{LB_{\mathrm{DDD}},LB_{\mathrm{traj}}\}.
$$

#### Phase 5C: Multiple and diverse pricing columns

After the complete-universe proof pricing call, optionally enumerate up to $m$
additional negative-reduced-cost columns per cabin. The proof solve is never
subject to diversity constraints. Extra columns are obtained from a separate
model copy or a post-proof phase using deterministic no-good rows.

Supported diversity signatures, in priority order:

1. resource-window occupancy signature at merges;
2. Stop/Skip signature by circulation visit;
3. Passenger offer signature;
4. complete route-option sequence as the final duplicate key.

The selector first orders candidates by reduced cost, then greedily accepts a
candidate only if its Hamming distance in the configured signature reaches the
threshold; deterministic Pair-ID breaks ties. Configuration:

```text
columns_per_cabin_per_round = 1
diversity_mode = OFF | RESOURCE_WINDOWS | STOP_SKIP
minimum_diversity_distance = 1
extra_column_time_limit_seconds
```

Defaults reproduce the current single-column algorithm. Multiple-column
generation can reduce rounds and improve the finite-pool integer solution but
does not strengthen the certificate by itself. A timeout incumbent is a
primal column; only the complete-universe pricing optimum/bound enters $LB$.

#### Phase 5D: Incumbent-compatible primal pricing

An optional, separately reported heuristic fixes the current trajectories of
all cabins except $c$ and requires the new trajectory of $c$ to be compatible
with them. It searches a feasible one-cabin replacement, re-solves exact
Passenger recourse and cycles deterministically through cabins until a full
pass makes no improvement or its budget expires. These columns enter the
shared pool and can update $UB$, but neither infeasibility nor reduced cost in
this restricted neighborhood has lower-bound meaning.

#### Phase 5E: Diagnostics and matched experiment

Expose per round and per cabin:

- protected occurrences, active windows, separated rows and pair fallback
  coverage;
- pricing variables, linear/general constraints, incumbent, solver bound,
  pricing gap, proof status and self-conflict rounds;
- proof, diverse and incumbent-compatible columns separately;
- master LP, corrected trajectory bound, DDD bound, integer upper bound and
  certified global gap;
- build, separation, LP, MIP, proof-pricing and extra-column time.

Run four matched-budget variants on the Five-Station $K=19$ case:

1. pair-only, one column;
2. pair-only, up to five diverse columns;
3. resource windows plus pair fallback, one column;
4. resource windows plus pair fallback, up to five diverse columns.

Use identical all-stop seeds, solver parameters, one- and ten-second pricing
slices and total budgets of 2 and 10 minutes. The primary comparison is the
time trace of certified $LB$, validated $UB$ and gap; restricted-master LP
values alone are not compared as bounds.

#### Literature rationale

The path-master, exact pricing and branch-price certificate follow Barnhart et
al. (1998) and Desrosiers--Lübbecke (2005). Railway path column generation
with conflict cliques is used by Cacchiani--Caprara--Toth (2008, 2010).
Schälicke--Nachtigall (2025) is the closest direct analogue: complete train
paths are columns, clique shadow prices enter a MIP pricing problem and new
cliques are updated with new paths. Martin-Iradi--Ropke (2022) supports the
separate use of cut-and-price, Passenger feedback and Large Neighborhood
Search for integer solutions. Lamorgese--Mannino (2015) motivates local
station/merge decomposition but is not treated as a proof of this column
formulation.

Immediate implementation order:

1. canonical interval/window types and exhaustive coefficient tests;
2. sweep separator and master rows behind an opt-in mode;
3. exact pricing membership and randomized-dual oracle comparison;
4. complete alternating root loop and matched tiny-master proof;
5. multiple/diverse columns as an independent option;
6. incumbent-compatible primal pricing only if the diverse pool still fails
   to improve $UB$;
7. Five-Station matched experiment and decision gate;
8. parallel pricing only after model-size and license-safe concurrency
   measurements justify it.

Exit criterion: on all exhaustively enumerable cases, the generated augmented
root LP equals the explicitly complete column/window/pair master. Its integer
feasible set equals the pair-reference problem, every pricing coefficient
matches enumeration, and every reported bound satisfies the known integer
optimum. On Five-Station, proceed to the hybrid coordinator only if resource
rows strengthen the matched-budget certified lower-bound trace or the diverse
variant improves the validated upper-bound trace without excessive master
growth.

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
- half-open point-headway windows at $t$, $t+h_r-1$ and $t+h_r$;
- platform entry/clear occupancy conversion and capacity-$b_r$ rows;
- repeated use of one resource by a trajectory without double counting at one
  anchor;
- stable window IDs, anchor canonicalization and waiting-domain provenance;
- sweep separation versus brute-force weighted interval depth;
- duplicate-row suppression and idempotent repeated separation;
- every supported pair conflict covered by at least one window, with explicit
  fallback for unsupported families;
- pair and clique validity, including a fractional example cut by the clique
  but not by all pair rows;
- equality of master and pricing membership coefficients for every generated
  column/window combination;
- equality of master, pricing and validator coefficients for every bounded
  integer wait value on the exhaustive Waiting fixture;
- reduced-cost arithmetic and dual signs with nonzero resource-window duals;
- pricing-corrected lower-bound arithmetic;
- pricing dominance safety;
- proof pricing unaffected by extra-column diversity constraints, except for
  the exact current-pool complement required by fixed pair rows;
- deterministic $k$-best no-good exclusion, diversity selection and tie
  breaking;
- incumbent-compatible pricing accepted only as `PRIMAL_POOL_ONLY`;
- checkpoint roundtrip and provenance.

### Exhaustive mathematical tests

For tiny rings, enumerate every no-wait Stop/Skip sequence and compare:

- complete trajectory universe;
- complete extreme-point load-pattern universe for tiny fractional
  demand/capacity relaxations;
- exact pricing minimum reduced cost under randomized Passenger, convexity and
  resource-window duals;
- bounded-Wait coefficient equivalence on the complete tiny route--wait
  universe, while keeping its certificate domain separate from No-Wait;
- generated versus full augmented master LP;
- all compatible integer trajectory selections satisfy every enumerated
  resource-window row;
- complete augmented-master MIP has the same feasible selections and optimum
  as the pair-reference MIP;
- root convergence requires clean row separation after the last generated
  column;
- full-pool primal MIP versus the exhaustively enumerated physical integer
  optimum on tiny cases;
- independently evaluated Passenger objective;
- all reported $LB\le z^\star\le UB$ relations.

Use deliberately conflicting columns, identical Passenger offers, horizon-edge
events, Stop/Skip merges, three-or-more-column conflict cliques, repeated
resource visits and multiple columns with equal reduced cost.

### Regression tests

- current DDD-only behavior is unchanged when the hybrid is disabled;
- current `DddTrajectorySlotPoolOptimizer` result is reproduced through its
  adapter;
- CP-SAT and EAN validation remain authoritative;
- No-Wait and Waiting certificates cannot be combined accidentally;
- restricted-pool infeasibility never becomes global infeasibility;
- solver time limits never masquerade as pricing optimality;
- `PAIR_ONLY` reproduces the current root traces and generated columns;
- disabling diversity reproduces one column per cabin per round;
- adding valid windows never decreases a solved master LP value;
- interruption after separation or pricing retains only fully certified bound
  components;
- No-Wait window coefficients are never reused for a bounded-Wait certificate.

### Performance tests

- on complete Three-Station fixtures, sweep separation must match brute force
  and remain below the existing exhaustive pair-build time;
- on Five-Station, record row count, pair fallback count, master nonzeros and
  pricing size before enforcing any hard performance threshold;
- after the diagnostic baseline, require resource-window coefficient lookup to
  be amortized sublinear in the total column pool through resource grouping;
- reject a default switch if peak RSS or root-round wall time grows by more
  than 25% without a stronger certified bound or validated incumbent.

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

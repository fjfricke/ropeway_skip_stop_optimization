# Certified Fixed-K Bounds for Passenger-Guided Ropeway Operation

## Purpose

Build a general solver that receives one physical network, one demand profile,
one operating mode, and one exact active fleet size $K$, and returns the best
available certified objective interval

$$
LB(I)\le z^\star(I)\le UB(I),
$$

where

$$
I=(N,D,M,K,H,W,O)
$$

contains the physical network $N$, demand $D$, operating-mode domain $M$,
exact active fleet size $K$, horizon and boundary semantics $H$, waiting domain
$W$, and passenger objective $O$.

The Fixed-$K$ bound engine is the primary deliverable. Comparing All-Stop with
Skip-Stop, choosing a fleet size, or aggregating demand scenarios are outer
applications that may consume its certificates later; they must not be baked
into the core formulation.

This plan builds on:

- [`dynamic_discretization_cabin_passenger.md`](dynamic_discretization_cabin_passenger.md)
  for the DDD relaxation and refinement contract;
- [`ddd_stronger_cp_support_cuts.md`](ddd_stronger_cp_support_cuts.md) for
  CP-certified timed-flow feedback;
- [`ddd_adaptive_anytime_master.md`](ddd_adaptive_anytime_master.md) for
  interruption-safe master control;
- [`../findings/ddd_five_station_passenger_support.md`](../findings/ddd_five_station_passenger_support.md)
  for the empirical diagnosis motivating the next strengthening layers.

## Scope and fixed-K semantics

### Exact fleet cardinality

In this plan, Fixed-$K$ means exactly $K$ physically active cabin trajectories
enter the modeled operation:

$$
|C|=K.
$$

An available-fleet cap with optional activation,

$$
\sum_c a_c\le K,
$$

is a different optimization problem. It may later call the Fixed-$K$ engine
for several cardinalities, but it must not report a Fixed-$K$ certificate if
fewer than $K$ cabins may silently remain inactive.

The first implementation retains the current fixed-start fleet state. A later
extension may optimize the initial physical placement, but then the placement
variables and their feasibility proof become part of the same instance and
certificate.

### Operating-mode domain

The mode $M$ defines the allowed route decisions:

- `ALL_STOP`: every service decision is fixed to Stop;
- `SKIP_STOP`: every physically supported Stop/Skip choice remains available;
- later route domains may include turnbacks or rope changes.

The solver does not assume that Skip-Stop is useful. It solves the specified
domain and reports its own bounds.

### Objective identity

Every lower and upper bound must belong to exactly the same objective,
passenger model, demand, horizon, and units. Initially use the existing scalar
fixed-start passenger objective with its explicit unserved-passenger penalty
and either waiting-time or journey-time cost. Record the objective identity in
the certificate. Bounds from different objectives are never combined.

Lexicographic service-first objectives require a separate vector-bound
contract and are outside the first tranche.

### Waiting provenance

No-wait and bounded-wait instances have different feasible sets. Every cut,
support proof, bound, and checkpoint records its waiting domain. A proof from
the no-wait problem is never imported into a waiting-enabled solve unless its
validity for the larger domain is independently established.

## Required result contract

Every interrupted or completed solve returns:

```text
FixedKBoundResult
  instance_fingerprint
  fleet_cardinality = K
  fleet_semantics = EXACT_ACTIVE
  operating_mode
  objective_id
  waiting_domain
  status
  global_lower_bound
  validated_upper_bound
  absolute_gap
  relative_gap
  lower_bound_provenance
  upper_bound_provenance
  best_movement_plan
  best_passenger_plan
  final_discretization
  active_cut_pool
  refinement_partition
  complete_validation_certificate
  timing_and_size_metrics
```

The status vocabulary distinguishes at least:

- `OPTIMAL`: the certified gap is closed within tolerance;
- `FEASIBLE_WITH_GAP`: a validated incumbent and finite lower bound exist;
- `UNKNOWN_NO_INCUMBENT`: a finite lower bound exists but no plan was found;
- `EXACT_INFEASIBLE`: global Fixed-$K$ infeasibility was proved;
- `RELAXATION_INFEASIBLE`: a valid relaxation proved global infeasibility;
- `BUDGET_EXHAUSTED`: the current certificate remains open;
- `INVALID_INTERNAL`: an independently checked proof or incumbent failed.

Fixed-support CP infeasibility never becomes `EXACT_INFEASIBLE`; it excludes
only the conditioned support.

## Solver architecture

Use separate lower-bound and upper-bound channels connected by proof-safe
feedback:

```text
optimistic passenger DDD master
    -> certified lower bound and anonymous timed support
    -> exact CP-SAT support check
        -> infeasible core -> valid master strengthening
        -> feasible timetable -> complete validation
            -> exact passenger recourse -> upper bound
```

The master and primal solver have different responsibilities:

- the DDD MILP master supplies the global lower bound;
- CP-SAT supplies exact movement feasibility, support explanations, and primal
  schedules;
- exact fixed-timetable Passenger Assignment supplies the upper-bound value;
- independent replay and separation determine whether a timetable is admitted.

No heuristic score, restricted trajectory-pool dual bound, CP hint, surrogate
objective, or unseparated movement plan may update the global certificate.

## Lower-bound hierarchy

The current fully anonymous DDD master is the first relaxation, not the final
bound model. Strengthen it through a monotone hierarchy. Every level must
preserve all complete physical solutions and therefore satisfy

$$
\mathcal F_{\mathrm{physical}}
\subseteq
\mathcal F_{q+1}
\subseteq
\mathcal F_q,
$$

which implies

$$
LB_q\le LB_{q+1}\le z^\star.
$$

### Level 0: anonymous passenger DDD master

Retain:

- anonymous integer cabin flow on the partial time-space network;
- fixed-start supply and exact fleet cardinality $K$;
- optimistic direct-ride passenger multicommodity flow;
- layer-state earliest-time passenger costs;
- mandatory resource rows already valid on partial arcs;
- all accepted proof cuts from previous rounds.

This level must remain cheap enough to provide an early bound on every
instance. It is allowed to represent timed flows that cannot yet be decomposed
into complete cabin trajectories.

### Level 1: reusable resource-time inequalities

Generate resource inequalities without cabin-pair order binaries.

For a selected timed resource usage $i$ on unary resource $r$, derive an exact
or conservative release tick $e_i^-$, latest protected completion $d_i^+$,
and mandatory processing length $p_i$ under the configured waiting domain.
For an interval $[A,B)$, every usage forced completely into that interval
contributes its full resource work. A basic valid Hall row is

$$
\sum_{i:\ e_i^-\ge A,\ d_i^+\le B}p_i y_i\le B-A.
$$

The implementation must derive the coefficients from the same half-open
resource intervals used by CP-SAT and the complete validator. It must handle:

- point and occupancy headways;
- multiplicities of anonymous flow;
- horizon-conditional resource activation;
- multiple uses of the same resource by one route option;
- waiting-dependent entry and clearing offsets;
- exact integer tick endpoints.

Start with the sufficient full-containment row above. Add stronger energetic
minimum-overlap coefficients only after a separate proof and exhaustive small
tests.

Candidate windows are generated from distinct release and deadline endpoints,
not from every microsecond tick. Separation returns only violated or
CP-motivated undominated rows. Stable row IDs survive later DDD cell splits.

The local CP explainability diagnostic is a selector, not a proof of the Hall
row. A timed core is a candidate for this level only when its local CP core
touches the explaining resource set. The arithmetic interval-capacity proof is
still performed independently before adding a row.

### Level 2: timed-flow and support-region cuts

Retain exact CP-certified Timed-Flow Covers as the fallback:

$$
\sum_{(R,q)\in C}[Y_R\ge q]\le |C|-1.
$$

They remain valid under time-cell subdivision because $Y_R$ is reconstructed
as the sum of contained child arcs. Apply deterministic duplicate and
dominance filtering, cache region-to-child-arc matches, and record cross-round
support coverage.

Resource-window rows should replace a timed cover only when they dominate it
and have their own independent proof. Otherwise keep both families available
and measure their marginal lower-bound effect.

### Level 3: adaptive cohort and prefix disaggregation

Pure resource cuts cannot repair anonymous flows whose contradiction depends
on cabin continuity across several visits. Introduce trajectory identity only
where CP evidence requires it.

Let $\mathcal P$ be a partition of the $K$ fixed-start cabins into cohorts.
For a tracked cohort $g\in\mathcal P$, introduce flow

$$
y_{g,a}\in\mathbb Z_{\ge0}
$$

with

$$
y_a=\sum_{g\in\mathcal P}y_{g,a}
$$

and cohort-specific conservation

$$
\sum_{a\in\delta^-(v)}y_{g,a}
=
\sum_{a\in\delta^+(v)}y_{g,a}.
$$

The initial partition may contain one coarse cohort. A refinement splits a
cohort using deterministic physical information such as:

- fixed-start state or ring phase;
- reachability signature of the mixed CP core regions;
- required visit range and route-option signature;
- existing cabin-prefix provenance;
- a singleton split as the exact fallback.

Only the affected visit band and network corridor are disaggregated initially.
Boundary equations connect the tracked subnetwork back to aggregate flow. A
refinement is accepted only after proving that every complete physical plan
still projects into the refined master.

Partition refinement yields a monotone lower-bound sequence. Refinement never
merges previously distinguished cohorts during one certificate run. Cache and
checkpoint the partition independently from time discretization.

Mixed resource/trajectory cores trigger this level. Pure resource cores first
use Level 1. This routing prevents global cabin-index expansion for conflicts
that an anonymous packing row can already remove.

### Level 4: exact fallback and convergence path

The certificate-oriented mode must have a conceptually complete escalation:

1. split relevant time cells to exact integer event ticks;
2. refine every necessary cohort to singleton cabins;
3. extend tracked prefixes or visit bands as required;
4. separate every resource conflict using complete CP/validator semantics;
5. continue until the bound closes or an explicit computational budget ends.

Singleton cohort flow and exact time cells do not by themselves remove every
resource-order disjunction. Complete resource separation or exact CP-certified
cuts remain required. The implementation must therefore claim finite exact
convergence only after documenting the finite tick horizon, complete
refinement vocabulary, and complete separation rule.

## Upper-bound channel

### Independent bootstrap

Run an unrestricted Fixed-$K$ CP-SAT movement solve before or early in the
master loop. Every returned schedule is independently validated and evaluated
with exact integer Passenger Assignment. It may update $UB$ but never $LB$.

### Support-centered repair

After the master selects an infeasible support, search for a nearby complete
schedule by minimizing a support distance. Use the previous best schedule as
a hint and score every validated candidate with exact passenger recourse.

Certified positive CP distance bounds may create valid master distance cuts;
heuristic distances without a proof remain primal-only.

### Passenger-guided large-neighborhood search

If nearest-support CP repeatedly improves the timetable but spends most of its
budget proving distance optimality, add an optional primal-only LNS:

1. fix most trajectories from the current incumbent;
2. relax cabins serving poor-demand corridors or participating in conflicts;
3. reoptimize their routes and times in CP-SAT;
4. validate and solve exact Passenger Assignment;
5. retain only a strictly better validated incumbent.

LNS neighborhoods may use passenger shadow prices or unmet demand to choose
relaxed cabins. They never affect the lower bound unless a separate valid cut
is extracted from an exact infeasibility proof without neighborhood
restrictions.

### Trajectory pool

Keep a finite pool of exact cabin trajectories and optionally recombine them
with delayed pair-conflict separation. A validated pool solution is a global
upper bound. Restricted-pool infeasibility and its dual bound are not global
certificates.

## Adaptive round policy

Each Fixed-$K$ run uses one total wall-clock budget. Do not solve every master
or every CP diagnostic to the same fixed accuracy.

For each round record:

- global $LB$, validated $UB$, and gap;
- master incumbent and best-bound progress;
- time and gain attributable to each cut family;
- CP status, core size, local classification, conflicts, branches, and time;
- cohort partition and prefix size;
- time to first incumbent and each incumbent improvement;
- model variables, rows, nonzeros, nodes, and memory where available.

Round selection follows:

1. obtain a valid master bound;
2. obtain or improve a physical incumbent if none or stale;
3. classify a rejected support as pure resource or mixed trajectory;
4. apply the cheapest valid strengthening for that class;
5. stop strengthening a family whose rolling lower-bound gain per second is
   negligible;
6. escalate to cohort refinement when pointwise timed covers repeat without
   bound improvement;
7. finish with the best open certificate when the budget expires.

Master time limits grow adaptively only when the open master gap, rather than
support infeasibility, is the measured bottleneck. A time-limited master best
bound remains valid if Gurobi reports it, but the next decomposition step may
use only a returned integral incumbent.

## Implementation phases

### Phase 0: canonical Fixed-K certificate API

- Introduce `DddFixedKBoundProblem` and `DddFixedKBoundResult` rather than
  encoding Fixed-$K$ semantics only through benchmark flags.
- Fingerprint network, demand, horizon, waiting, objective, fleet state, and
  operating-mode domain.
- Reject optional activation in the exact-cardinality mode.
- Centralize gap computation and bound provenance.
- Make checkpoints resume only an identical instance fingerprint.
- Export complete movement/passenger validation certificates.

Acceptance: existing fixed-start DDD examples reproduce their current bounds
and plans through the new API; mismatched objectives or fleet semantics fail
before solving.

### Phase 1: resource-window proof and separator

- Implement typed resource-task envelopes in integer ticks.
- Implement full-containment Hall-row generation and deterministic dominance.
- Use local explainability only to prioritize candidate resources/windows.
- Retain Timed-Flow Covers for every mixed or unproved case.
- Add per-row bound-lift and support-coverage metrics.

Acceptance: exhaustive tiny scheduling cases preserve every feasible exact
schedule; a controlled Five-Station A/B run measures lower-bound lift per
second against timed covers alone.

Stop this line of work if the new rows neither lift the bound nor reduce CP
support rejections under matched total budgets.

The first fixed-start $K=19$ A/B experiment reached exactly this stop
condition: entry-count and protected-interval energy separation checked 8,590
and 17,180 candidate windows respectively, found no violated row, left all 20
CP support rejections unchanged, and produced the same lower bound. The
implementation remains an opt-in proof-safe presolve; persistent row
materialization is deferred. Phase 2 is therefore the next lower-bound
experiment rather than further unconditional marginal-window engineering.

### Phase 2: adaptive cohort/prefix master

- Define a persistent cabin-cohort partition and refinement operations.
- Build cohort-specific flow only over selected visit bands/corridors.
- Derive safe aggregate/cohort boundary equations.
- Route mixed local CP cores to deterministic reachability-based splits.
- Reuse the existing prefix formulation where it already represents the
  required distinction.
- Add a singleton exact-fallback mode for small instances.

Acceptance: each accepted split leaves exhaustive small physical solutions
feasible, never decreases $LB$, and removes the triggering mixed support or
provides a strictly finer representation for the next proof.

### Phase 3: anytime primal improvement

- Keep bootstrap and nearest-support CP independently configurable.
- Add passenger-guided LNS only as a primal component.
- Reuse exact Passenger Assignment candidates and validated timetable caches.
- Record time-to-first and time-to-best upper bound.

Acceptance: every admitted incumbent passes complete movement and integer
passenger validation; disabling the phase leaves the lower-bound trajectory
unchanged.

### Phase 4: certificate-oriented escalation

- Combine resource rows, timed covers, time splits, and cohort refinement in
  one deterministic escalation policy.
- Add proof mode without heuristic cut-family stopping for small cases.
- Compare final small-instance bounds against the eager integrated EAN model
  or exhaustive enumeration.
- Document which finite refinement/separation assumptions are required for an
  `OPTIMAL` or `EXACT_INFEASIBLE` status.

Acceptance: small reference cases close to the same optimum as the exact
model; every early termination retains a valid open interval.

### Phase 5: initial-placement generalization

Only after fixed-start Fixed-$K$ bounds are useful:

- replace fixed cabin starts by a canonical finite set of initial physical
  slots or start-state counts;
- preserve exact cardinality $K$;
- let CP-SAT realize the anonymous placement jointly with movement;
- refine placement cohorts analogously to fixed-start cohorts;
- retain label symmetry breaking without imposing later FIFO order;
- validate the complete initial state and service-horizon movement.

This phase must not weaken or silently reinterpret the fixed-start certificate.

### Phase 6: outer design studies

Only after the per-instance Fixed-$K$ API is stable, build controllers that
call it for several operating modes, fleet sizes, lines, or demand scenarios.
They consume certificates but do not alter their meaning.

## Later comparison formulas

These formulas motivate the Fixed-$K$ result contract but are not part of the
core solver.

For All-Stop and Skip-Stop at the same exact $K$, define positive Skip-Stop
benefit for a minimization objective by

$$
\Delta_K=z^\star_{\mathrm{AS},K}-z^\star_{\mathrm{SS},K}.
$$

Its certified interval is

$$
LB(\Delta_K)
=LB_{\mathrm{AS},K}-UB_{\mathrm{SS},K},
$$

$$
UB(\Delta_K)
=UB_{\mathrm{AS},K}-LB_{\mathrm{SS},K}.
$$

Thus $LB(\Delta_K)>0$ proves a benefit without solving Skip-Stop to
optimality. Conversely, $UB(\Delta_K)\le\varepsilon$ proves that its maximum
possible benefit is practically bounded by $\varepsilon$.

For fleet sizing, compute the exact-$K$ Pareto family

$$
K\mapsto[LB_K,UB_K].
$$

Configuration $K_1$ certifiably dominates $K_2$ in passenger performance and
fleet size if

$$
K_1\le K_2
\qquad\text{and}\qquad
UB_{K_1}<LB_{K_2}.
$$

Do not call a fleet size optimal solely because a cap-$K$ model leaves some
cabins inactive.

## Demand-scenario semantics

The Fixed-$K$ engine solves one declared demand instance. Mathematical bounds
are conditional on that demand; they do not quantify statistical model error.

If operations may be independently reoptimized for scenarios $s$ with weights
$p_s$, their expected optimum has the valid interval

$$
\sum_s p_s LB_s
\le
\sum_s p_s z_s^\star
\le
\sum_s p_s UB_s.
$$

If one common timetable must serve all scenarios, independent scenario
optima cannot be aggregated. A joint stochastic or robust Fixed-$K$ problem
with shared first-stage movement decisions is required instead.

## Tests

### Certificate invariants

- every accepted physical solution maps to every active relaxation level;
- $LB$ never decreases after adding a valid cut or refining a partition;
- $UB$ changes only after complete movement and passenger validation;
- identical objective, demand, horizon, waiting, mode, and fleet fingerprints
  are required before bounds are compared or resumed;
- Fixed-$K$ results always contain exactly $K$ active cabin trajectories.

### Resource rows

- point, occupancy, and exit-switch resources;
- half-open endpoint equality at exact headway;
- multiple anonymous units in one timed region;
- horizon-inactive and horizon-optional usages;
- no-wait and bounded-wait envelopes;
- exhaustive comparison with tiny CP-SAT no-overlap schedules;
- DDD cell subdivision preserves stable-row meaning.

### Cohort refinement

- physical plans project into coarse and refined cohort models;
- deterministic split IDs and checkpoint replay;
- boundary conservation across a tracked visit band;
- split-to-singleton equivalence on tiny fixed-start instances;
- mixed cores do not incorrectly create pure resource rows;
- refinement-budget exhaustion returns an open certificate.

### End-to-end exact references

For small One-, Three-, and Five-Station cases, compare against the integrated
EAN or exhaustive enumeration:

- same feasible/infeasible classification;
- DDD lower bound never exceeds the exact optimum;
- validated upper bound never lies below it;
- proof mode closes to the same optimum within tolerance;
- All-Stop and Skip-Stop use identical physical and passenger semantics.

### Scaling matrix

Use non-constructed demand patterns across:

- lines and rings;
- low, medium, and near-capacity exact $K$;
- uniform, peaked, directional, and asymmetric demand;
- no-wait first, then bounded waiting;
- increasing station counts and horizons.

Report bound trajectories over wall time, not only final results.

## Performance and research gates

Track separately:

- time to first finite $LB$;
- time to first validated $UB$;
- best certified gap over time;
- lower-bound gain per resource row, timed cover, time split, and cohort split;
- CP rejection rate by local explanation class;
- anonymous, cohort, and prefix model sizes;
- fraction of runtime in master build, master optimization, CP feasibility,
  local diagnosis, primal repair, and passenger recourse;
- peak memory and checkpoint size.

Decision gates:

1. Keep resource-window cuts only if they improve matched-budget lower bounds
   or materially reduce repeated CP rejections.
2. Keep adaptive cohort refinement only if it strengthens bounds more cheaply
   than global cabin disaggregation on the reference matrix.
3. Move toward trajectory column generation only if selective disaggregation
   still enumerates supports without useful bound lift; complete pricing would
   then be required before claiming a global lower bound.
4. Keep CP-SAT/LNS as the primal channel even if it produces no proof cuts,
   provided it improves validated upper bounds efficiently.

## Non-goals

This plan does not initially attempt:

- variable fleet cardinality inside one solve;
- a fleet-cost calibration;
- robust optimization over uncertain demand;
- dynamic turnbacks or rope switching;
- passenger transfers;
- global periodic operation;
- an immediate replacement by Branch-and-Price;
- a claim that local merge capacity alone explains every anonymous-flow gap.

These extensions may consume the Fixed-$K$ solver later. They must not delay
the first goal: useful, reproducible, and provably valid bounds for one
physically defined Fixed-$K$ passenger-planning instance.

## Expected outcome

The intended result is an anytime Fixed-$K$ solver with two independently
improving certificates:

$$
LB_0\le LB_1\le\cdots\le z^\star
\le\cdots\le UB_1\le UB_0.
$$

Anonymous DDD provides the early scalable bound, resource-time inequalities
remove reusable packing violations, adaptive cohort refinement restores only
the trajectory identity needed by mixed cores, and CP-SAT plus exact Passenger
Assignment supplies valid incumbents. This per-instance engine is the required
foundation for every later statement about Skip-Stop usefulness or fleet size.

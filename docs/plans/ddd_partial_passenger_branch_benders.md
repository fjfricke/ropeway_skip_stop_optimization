# Strengthened partial Passenger Branch-and-Benders gate

Status: **root gate implemented and rejected; callback phases canceled**

The measured decision is recorded in
[`../findings/ddd_partial_passenger_benders_root_gate.md`](../findings/ddd_partial_passenger_benders_root_gate.md).
The 20% and 40% Passenger cores, ordinary dual cuts, core-point strengthened
cuts, and the exact residual coupling-component analysis all failed the hard
`K=20` gate. Per this plan's stop conditions, no Branch-and-Benders callback is
to be implemented for the current formulation.

This plan continues
[`ddd_arc_flow_passenger_benders.md`](ddd_arc_flow_passenger_benders.md). It does
not revive the already rejected outer-loop method unchanged. The measured
standard cuts left the Five-Station Architecture B, Skip-Stop, `K=20` lower
bound at zero after 50 root cuts, although the complete monolithic LP solved to
`525,730.908` in a few seconds. A callback that separates the same cuts would
move that failure into a branch-and-bound tree; it would not repair it.

The proposed experiment retains a deliberately small but exact part of the
Passenger model in the complete DDD movement arc-flow master, projects only the
remaining Passenger decisions, and tests stronger cuts before implementing a
callback. It is a possible production method only if the root gates below pass.

## Decision and scope

Version 1 solves the existing canonical Fixed-$K$, fixed-start, No-Wait problem:

- exactly $K$ cabin paths;
- complete DDD movement arc-flow and all physical resource constraints;
- Stop/Skip decisions in the Movement master;
- journey-time Passenger objective;
- a partial exact Passenger core in the master;
- LP recourse for globally valid lower bounds;
- exact Passenger-IP evaluation for validated upper bounds;
- one persistent Gurobi tree only after the strengthened root cuts have passed
  an independent cut laboratory.

It does **not** initially include OIP, a reservoir, optional cabin activation,
Waiting, branch-price, or heuristic merge neighborhoods. Waiting is a later
extension of the same recourse interface, not part of the decision whether the
basic method works.

The method is called **partial Passenger Branch-and-Benders-cut**. It is not
classical Benders, because part of the Passenger formulation remains in the
master. It is not Logic-Based Benders alone, because LP-dual user cuts remain
the proof mechanism. It is not Branch-Price-and-Cut, because the complete DDD
Movement arc set is present from the start.

## Why this is the remaining credible Benders experiment

The current evidence separates three facts:

1. The complete Movement arc-flow is easy to construct and solve for physical
   feasibility at `K=20` and `K=38`.
2. The complete Passenger block gives a strong relaxation, but dominates model
   size and memory.
3. Removing the entire Passenger block produces highly local and degenerate
   dual cuts that reconstruct the strong relaxation far too slowly.

The partial master addresses the third point directly. It preserves selected
Passenger/capacity coupling rows, while Pareto/core-point separation chooses a
strong cut among the many dual optima. A persistent callback can then preserve
Gurobi's incumbent heuristics and tree state. These mechanisms are plausible,
but none guarantees a breakthrough. The gates intentionally allow the method
to be rejected before callback engineering becomes expensive.

This direction is consistent with the literature, but the ropeway model needs
its own evidence:

- Schettini et al. use a tailored Branch-and-Benders method for demand-driven
  metro scheduling, including closed-form Pareto-optimal cuts. Their Passenger
  subproblem has stronger integrality properties than ours, so their result is
  evidence for the architecture rather than a transferable proof:
  [Computers & Operations Research 2022](https://doi.org/10.1016/j.cor.2021.105598).
- Martin-Iradi and Ropke combine column generation, separation, Passenger
  Benders cuts, and primal neighborhoods in integrated vehicle and Passenger
  planning. This supports a portfolio of independently valid proof and primal
  channels rather than expecting one decomposition component to do everything:
  [European Journal of Operational Research 2022](https://doi.org/10.1016/j.ejor.2021.04.048).
- Magnanti and Wong establish the core-point construction for selecting
  Pareto-optimal Benders cuts under dual degeneracy:
  [Operations Research 1981](https://doi.org/10.1287/opre.29.3.464).
- The general Benders review identifies weak cuts, degeneracy, stabilization,
  cut selection, and partial decomposition as central performance issues:
  [European Journal of Operational Research 2017](https://doi.org/10.1016/j.ejor.2016.12.005).

## Mathematical model

### Complete Movement master

Let $A_c$ be the complete DDD arc set of cabin $c$, and let
$x_{ca}\in\{0,1\}$ select Movement arc $a$. The master retains the current
complete arc-flow polytope

\[
x\in X_K^{\mathrm{move}},
\]

including one source-to-sink path per cabin, canonical Fixed-$K$ starts,
Stop/Skip compatibility, boundary semantics, and every required physical
resource clique. Nothing in Passenger decomposition may relax Movement safety.

Let $Q_I(x)$ be the exact integer Passenger objective for a fixed Movement
solution and $Q_{LP}(x)$ its LP relaxation. The original problem is

\[
z^*=\min_{x\in X_K^{\mathrm{move}}} Q_I(x).
\]

### Deterministic Passenger-core partition

Passenger demand groups are partitioned into a master core $G_C$ and residual
set $G_R$. The partition is deterministic and part of the instance
fingerprint. A group score may use only data available before optimization:

\[
\operatorname{score}(g)=
w_d d_g+w_p p_g+w_s\frac{1}{1+n_g^{\mathrm{ride}}}
+w_b b_g,
\]

where $d_g$ is demand mass, $p_g$ the unserved penalty, $n_g^{\mathrm{ride}}$
the number of compatible direct rides, and $b_g$ a deterministic
capacity-bottleneck score. Ties are resolved by the stable demand-group ID.

The initial policies to compare are:

- `NONE`: the already measured full projection, retained as a control;
- `DEMAND_MASS`: highest-demand groups up to a variable/nonzero budget;
- `SCARCE_RIDES`: groups with few compatible rides and high penalty;
- `HYBRID`: the normalized score above.

The budget is expressed as maximum Passenger variables and nonzeros, not only
as a percentage of groups. This prevents one large group from unexpectedly
recreating the monolithic model.

### Partial master and residual recourse

For $g\in G_C$, the existing normalized Passenger variables $y_C$ and their
flow rows remain in the master. They remain integer in the exact master. Their
loads consume the same cabin-interval capacities as residual passengers.
Writing $C(x)$ for the Movement-dependent interval capacity and $A_C,A_R$ for
the two load matrices, the master first enforces

\[
A_Cy_C\le C(x),
\]

while the residual recourse uses

\[
A_Ry_R\le C(x)-A_Cy_C.
\]

The first row prevents the core alone from overloading a cabin. The second
gives the residual passengers only the unused part; it does not create a second
copy of capacity.

For fixed $(\bar x,\bar y_C)$, residual LP recourse is written in the existing
normalized affine form

\[
Q_R^{LP}(\bar x,\bar y_C)=
\min\{c_R^\top y_R+c_0:\;
W_Ry_R\le h+T\bar x+U\bar y_C,\ y_R\ge0\}.
\]

The term $U\bar y_C$ is essential: it subtracts Passenger-core load from the
capacity available to residual demand. Core and residual passengers may never
receive separate copies of cabin capacity.

The master contains epigraph variables $\theta_R\ge0$ and $\eta\ge0$ with

\[
\eta\ge c_C^\top y_C+\theta_R,
\]

and minimizes $\eta$. For every dual-feasible recourse vector $\pi$, the
globally valid cut has the form

\[
\theta_R\ge
\alpha(\pi)+\beta(\pi)^\top x+\gamma(\pi)^\top y_C.
\]

Consequently, the Gurobi master bound is a valid lower bound for the original
integer problem:

\[
LB\le \min_x Q_{LP}(x)\le z^*.
\]

Retaining integer core variables may strengthen the master further, but no
bound may rely on an unproved claim that the complete fixed-timetable Passenger
polytope is integral. The odd-cycle counterexample remains a mandatory test.

### Validated upper bounds

At an integer Movement solution $\bar x$, the primal channel ignores the
master's possibly suboptimal core assignment and solves the **complete** fixed-
Movement Passenger IP:

\[
UB(\bar x)=Q_I(\bar x).
\]

Only a complete Movement validation followed by this exact evaluation may
update the global upper bound. CP-SAT or a complete arc-flow feasibility solve
may provide $\bar x$ and a MIP start; neither provides a Passenger bound by
itself.

### Exact integer closure

LP cuts alone close the projected Passenger-LP problem, not necessarily the
integer problem. Define a stable, injective signature $S(\bar x)$ for a feasible
binary cabin-path package and a binary distance $D(x,\bar x)$ that is zero if
and only if the same package is selected. Given a global Passenger floor $L$,

\[
\eta\ge Q_I(\bar x)-\bigl(Q_I(\bar x)-L\bigr)D(x,\bar x)
\]

is valid. It enforces the exact Passenger value for the evaluated Movement
package and relaxes to the global floor elsewhere. The signature/distance
implementation must be proved injective for feasible DDD paths; it may not
silently assume that selected-arc containment implies equality.

These logic cuts give finite exactness because the binary Movement set is
finite, but they may degenerate into enumeration. Their rate and repeated-
bottleneck coverage are therefore explicit experiment metrics, not a presumed
scaling solution.

## Strong cut families

### 1. Standard dual cut control

The existing normalized oracle and cut generator remain the correctness
reference. Every new cut is compared with the standard dual cut at the same
separation point. The control must reproduce the already observed weak `K=20`
behavior.

### 2. Magnanti-Wong/core-point cuts

When the recourse dual has multiple optima, solve an auxiliary dual problem:

1. require dual feasibility;
2. require the cut to be tight at the current point
   $(\bar x,\bar y_C)$ within tolerance;
3. among those dual optima, maximize the cut value at an interior core point
   $(x^0,y_C^0)$.

The core point is initialized from feasible points of the continuous partial
master and updated deterministically, for example

\[
(x^0_{t+1},y^0_{t+1})=
\lambda(x^0_t,y^0_t)+(1-\lambda)(\bar x_t,\bar y_{C,t}),
\qquad 0<\lambda<1.
\]

It need not be an integer timetable, but it must remain in the relative
interior of the relevant continuous master face for the formal Pareto-optimal
claim. A convex combination of suitable feasible master points preserves
feasibility. If relative-interior membership cannot be established, the result
is labeled only `CORE_POINT_STRENGTHENED`, not `PARETO_OPTIMAL`. The auxiliary
solution must still be dual-feasible; otherwise the resulting inequality is
rejected.

### 3. Coupling-aware multi-cuts

Residual demand groups cannot automatically receive independent cuts because
they share cabin capacities. Build a bipartite graph between residual demand
groups and the cabin-interval capacity rows they can use. Only different
connected components of this graph are separable. For components $j\in J$,

\[
\theta_R=\sum_{j\in J}\theta_j,
\qquad
\theta_j\ge
\alpha_j+\beta_j^\top x+\gamma_j^\top y_C.
\]

If all groups lie in one component, the implementation must fall back to one
global cut. Naive OD-wise cuts that duplicate shared capacity are invalid and
are forbidden.

### 4. Cut selection and promotion

The cut pool records violation, efficacy, support, angle/parallelism to recent
cuts, origin, and numerical range. A deterministic selector rejects duplicates
and nearly parallel low-efficacy cuts.

Repeatedly active residual demand groups may be promoted into $G_C$ only
between complete rebuilds, never by changing the formulation underneath an
active callback tree. Promotion creates a new fingerprint and forces the
master, recourse template, cut pool, and bounds to be rebuilt. Previously
validated Movement incumbents may be re-evaluated and reused; previous master
bounds may not be relabeled as bounds of the rebuilt formulation without a
fresh solve.

## Algorithm

### Root cut laboratory before callbacks

For a chosen core policy:

1. build the complete Movement plus partial Passenger master as a continuous
   root relaxation;
2. solve it to the configured root tolerance;
3. evaluate residual Passenger LP recourse;
4. generate standard, Pareto/core-point, and valid component multi-cuts;
5. select and add a bounded batch;
6. repeat until no violated cut remains, the cut limit is reached, or the
   wall-clock budget expires;
7. compare the result with the complete monolithic LP on the same fingerprint.

No callback work begins unless this laboratory reconstructs most of the known
strong root bound with materially fewer Passenger nonzeros.

### Persistent Branch-and-Benders-cut

After the root gate passes, one Gurobi MIP owns the complete Movement master,
Passenger core, valid cut pool, and MIP start.

- At `MIPNODE`, separate residual LP cuts at the root and then only at
  deterministic depths/frequencies when the estimated violation exceeds the
  tolerance. User-cut separation receives an explicit fraction of the total
  budget.
- At `MIPSOL`, first validate the complete Movement solution, then solve the
  complete fixed-Movement Passenger LP and IP. Add an LP cut if the epigraph is
  underestimated and an exact signature cut if LP and IP differ or if the
  master objective understates $Q_I(\bar x)$.
- A CP-SAT/arc-flow Movement package and its exact Passenger evaluation provide
  the initial validated upper bound and MIP start.
- Callback calls are serialized. The subproblem template is reused, but its
  fixed RHS is updated; rebuilding a complete Passenger model per callback is
  forbidden.
- All callback exceptions terminate with an internal-error status. They may not
  be swallowed by Gurobi and exported as a valid certificate.

At every event,

\[
LB=\texttt{ObjBound},\qquad
UB=\min_{\bar x\text{ exactly evaluated}}Q_I(\bar x),
\]

and the reported certified gap is

\[
\operatorname{gap}=\frac{UB-LB}{\max\{|UB|,\epsilon\}}.
\]

The Restricted or callback incumbent objective is not a validated $UB$ until
the complete Passenger IP has accepted it.

## Object-oriented implementation

The implementation extends the current decomposition kernel instead of adding
conditionals to `arc_flow.py`.

```text
optimization/ddd/
  passenger_partial_master.py
    DddPassengerCorePolicy
    DddPassengerCorePartition
    DddPassengerCoreSelector
    DddPartialPassengerMasterContribution

  passenger_pareto_cuts.py
    DddPassengerCorePoint
    DddParetoPassengerCutGenerator
    DddPassengerCouplingComponentIndex

  passenger_branch_and_benders.py
    DddBranchAndBendersConfig
    DddBranchAndBendersCallback
    DddBranchAndBendersOptimizer
    DddBranchAndBendersResult

  passenger_benders_certificate.py
    DddPassengerBendersBoundLedger
    DddPassengerBendersCertificateValidator
```

Existing components remain authoritative:

- `DddArcFlowProblemPreparer` for immutable Movement/Passenger preparation;
- `DddArcFlowMovementMasterBuilder` for the complete Movement model;
- `DddArcFlowPassengerDomain` for normalized Passenger algebra;
- `DddFixedMovementPassengerRecourseOracle` for LP/IP evaluation;
- `DddPassengerBendersCut` and its pool for immutable cut storage;
- `DddFixedKArcFlowOptimizer` and `DddArcFlowRelaxationOptimizer` as matched
  monolithic baselines.

The callback depends on narrow protocols for master-point extraction, recourse
evaluation, cut insertion, exact incumbent validation, and progress events.
The mathematical oracle must remain independently testable without Gurobi
callbacks.

New benchmarking modules:

```text
src/ropeway_skip_stop_optimization/benchmarking/
  ddd_partial_passenger_benders.py

benchmarks/
  run_ddd_partial_passenger_benders_gate.py
```

No option is added to the production Fixed-$K$ campaign runner until all gates
through `K=38` pass.

## Implementation phases and hard gates

### Phase 0: matched baselines and fingerprints

Freeze one canonical No-Wait fingerprint for Five-Station Architecture B and
run or import matched baselines:

| case | complete MIP budget | complete LP budget | required reference |
|---|---:|---:|---|
| Skip-Stop `K=20` | 10 min | 2 min | known optimum and LP `525,730.908` |
| Skip-Stop `K=38` | 60 min | 5 min | complete-LP bound curve and validated seed UB |
| Skip-Stop `K=39` | 60 min | 5 min | best certified LB and validated CP/arc-flow UB |

Record construction, presolve, root, first incumbent, node count, memory,
`LB(t)`, validated `UB(t)`, and fingerprint. Existing results may be reused only
if all semantic fingerprints match exactly.

### Phase 1: partial-master algebra

Implement partitioning, residual-capacity algebra, and a rebuild-only promotion
path. Do not implement callbacks.

Acceptance:

- exhaustive tiny instances give the same objective as the monolithic model
  when `G_C` plus recourse cover all groups;
- fixed $(x,y_C)$ recourse equals a directly constructed residual Passenger LP;
- `NONE` reproduces the current standard-cut control;
- every configured core respects its variable/nonzero budget;
- `ALL` reproduces the complete Passenger formulation.

### Phase 2: strong root-cut laboratory

Implement dual diagnostics, core points, Pareto cuts, coupling components, and
deterministic cut selection. Compare `NONE`, three fixed core budgets, standard
cuts, Pareto cuts, and valid multi-cuts.

Hard `K=20` gate after at most 30 separation rounds and 120 seconds:

- certified root LB at least 90% of `525,730.908`;
- at most 40% of the monolithic Passenger nonzeros in the partial master;
- no cut-validity or bound-monotonicity failure;
- a materially better bound curve than the old 50-cut zero-LB control.

If no configuration passes, stop. Branch-and-Benders is rejected for the
current formulation and no callback is implemented.

### Phase 3: root-only callback prototype

Run the passing configuration with root-node user cuts in a persistent Gurobi
model. Integer incumbent callbacks remain disabled; the objective is to verify
callback correctness, model reuse, and root performance.

Hard `K=38` gate after 300 seconds:

- either match or exceed the matched complete-LP lower bound using at most 60%
  of its measured peak RSS;
- or stay within 5% of that lower bound using at most 40% of its peak RSS;
- subproblem and cut work consume at most 30% of wall-clock time after template
  construction;
- all reported bounds pass the independent ledger validation.

Failure rejects the callback path even if `K=20` passed.

### Phase 4: exact integer callback

Add complete Passenger-IP incumbent evaluation, inject the validated seed, and
add signature logic cuts only when needed.

Hard gates:

- `K=20` reaches the known integer optimum and proves it within 10 minutes;
- every accepted incumbent independently replays through Movement validation
  and the monolithic fixed-Movement Passenger IP;
- the odd-cycle case triggers integer closure rather than falsely reporting LP
  optimality;
- no repeated identical Movement signature is evaluated twice;
- a callback time limit returns a valid interval, not a false optimal status.

### Phase 5: dense cases

Run `K=38` and `K=39` for one hour, followed by a four-hour headline run only
for the better configuration. Compare complete MIP, complete LP bound channel,
trajectory Root-CG bound, and partial Branch-and-Benders on common time points:

\[
30\text{s},\ 2\text{min},\ 5\text{min},\ 15\text{min},\ 60\text{min}.
\]

The method qualifies for the experiment portfolio if it does at least one of
the following without weakening the other certificate side:

- finds the first validated `K=39` Passenger incumbent substantially earlier;
- improves the best certified `K=39` LB by at least 20%;
- reaches a certified `K=39` gap below 25%;
- reaches a 5--15% gap, which is the aspirational thesis breakthrough target.

If it only shrinks memory while producing inferior bound and incumbent curves,
it remains a documented negative experiment rather than the main solver.

### Phase 6: Waiting only after No-Wait acceptance

Waiting changes ride compatibility, capacity occupation, and recourse coupling.
It is added only if Phase 5 accepts the method. Start with a finite exact Waiting
domain shared by the complete baseline and decomposed model. Re-run all tiny
equivalence, cut-validity, and `K=20` gates before any larger case. A No-Wait
cut may be reused only if its validity is proved for the enlarged Waiting
domain; otherwise it is discarded.

## Automated tests

### Algebra and partitioning

- stable core selection and fingerprint under input-order permutation;
- exact variable/nonzero budget enforcement and deterministic tie-breaking;
- residual capacities equal total capacity minus core load;
- no duplicated capacity between core and residual models;
- `NONE` and `ALL` boundary policies;
- rebuild-only promotion invalidates incompatible cuts and master bounds.

### Cut validity

- exhaustive evaluation of every generated cut over all feasible Movement
  solutions of tiny instances;
- cut tightness at its generation point;
- Pareto cut is dual-feasible, tight at the current point, and no weaker at the
  configured core point than the control cut;
- multi-cuts are created only for disconnected coupling components;
- deliberately shared capacity forces a single component;
- duplicate, low-efficacy, and badly scaled cuts are rejected deterministically.

### Integer correctness

- Passenger LP/IP equality cases need no unnecessary logic cut;
- the odd-cycle LP/IP-gap fixture cannot terminate with an integer-optimal
  status from LP cuts alone;
- stable Movement signatures are injective over enumerated feasible paths;
- exact signature cuts are globally valid on the exhaustive tiny domain;
- exact Passenger evaluation is conditioned only on Movement, not on the
  partial master's incumbent core assignment.

### Callback and certificates

- mocked `MIPNODE` and `MIPSOL` event ordering;
- one reused recourse template with correctly updated RHS;
- exception propagation and no silent callback failure;
- wall-clock accounting includes build, seed, callback, recourse, validation,
  and finalization;
- `LB` monotone nondecreasing and validated `UB` monotone nonincreasing within
  tolerance;
- interruption at every phase yields either a valid interval or an explicit
  internal/unknown status;
- event-stream and cut-pool roundtrip; resume rebuilds the Gurobi tree but
  safely restores validated incumbents and globally valid cuts.

### Regression

- unchanged objectives for existing tiny complete arc-flow tests;
- matched `K=20` monolithic objective;
- frontend and JSON schema distinguish master incumbent, validated Passenger
  UB, Gurobi bound, recourse LP value, and exact recourse IP value;
- existing complete arc-flow, relaxation, Root-CG, and CP seed paths remain
  selectable and unchanged.

## Progress and result schema

The terminal and Optimization Lab show:

- phase, callback location, node, depth, elapsed and remaining time;
- certified `LB`, validated `UB`, absolute and relative gap;
- current master relaxation/incumbent objective, explicitly not mislabeled as
  a validated UB;
- core groups, core variables/nonzeros, residual groups;
- recourse LP/IP calls, cache hits, mean/max duration;
- standard/Pareto/multi/logic cuts generated, accepted, rejected, and active;
- last cut violation and efficacy;
- seed provenance and exact validation status;
- peak RSS when available.

Every output stores the complete semantic fingerprint, core policy and budget,
cut configuration, Gurobi parameters, random seeds, thread count, software
versions, and bound provenance.

## Stop conditions and fallback

This plan is falsifiable. Stop development when the first applicable condition
holds:

- the `K=20` root gate fails;
- useful core sizes retain more than 40% of monolithic Passenger nonzeros;
- strong-cut separation dominates runtime without closing the root bound;
- the `K=38` root callback cannot beat the matched memory/bound trade-off;
- integer signature cuts mostly enumerate Movement solutions;
- exact recourse at incumbents becomes the dominant runtime;
- the one-hour `K=39` curve is dominated by both complete arc-flow and the
  existing independent bound/primal portfolio.

The fallback production portfolio remains mathematically sound:

- complete arc-flow MIP for smaller instances and strong primal search;
- complete arc-flow LP/barrier and trajectory Root-CG as independent certified
  lower-bound channels, taking the maximum valid LB;
- CP-SAT or Movement arc-flow schedules followed by exact Passenger IP as the
  validated upper-bound channel, taking the minimum valid UB;
- longer runs only when the recorded curves show continuing progress.

Negative gate results are still useful thesis evidence: they explain why full
projection failed, quantify how much Passenger structure must remain to retain
the relaxation, and justify the selected solver portfolio without claiming a
universal decomposition breakthrough.

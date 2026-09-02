# Passenger decomposition for the fixed-K DDD arc-flow model

Status: **recourse and outer-loop reference implemented; standard LP cuts rejected as production path**

The narrowly scoped follow-up experiment is specified in
[`ddd_partial_passenger_branch_benders.md`](ddd_partial_passenger_branch_benders.md).
It retained selected Passenger/capacity structure and required a strong `K=20`
root-cut gate before any Branch-and-Benders callback. That gate failed, so the
callback path was not implemented; see
[`../findings/ddd_partial_passenger_benders_root_gate.md`](../findings/ddd_partial_passenger_benders_root_gate.md).

## Implementation checkpoint (2026-08-25)

The first two decision gates now have executable implementations:

- `DddArcFlowProblemPreparer` builds the complete time-expanded cabin networks
  and resource cliques once and shares them between formulations;
- `DddArcFlowMovementMasterBuilder` owns the cabin-flow and resource rows;
- `DddFixedKMovementArcFlowOptimizer` solves the complete physical Movement
  model without Passenger variables;
- `DddFixedMovementPassengerRecourseOracle` evaluates the same fixed Movement
  plan with both the Passenger LP relaxation and the exact Passenger IP;
- `run_ddd_passenger_decomposition_diagnostic.py` generates a reproducible
  corpus of valid Movement plans and records LP/IP gaps.

Initial Five-Station Architecture B evidence is:

| case | Movement model | Movement result | Passenger LP/IP result |
|---|---:|---|---|
| Skip-Stop `K=20` | 21,630 arc binaries; 13,525 flow rows; 14,270 resource rows | feasible in less than one second with the feasibility objective | three distinct plans, all exact LP/IP gap `0.0%` |
| Skip-Stop `K=38` | 40,646 arc binaries; 25,390 flow rows; 26,908 resource rows | feasible after about five solver seconds | LP = IP = `399,287.271`, no fractional rides |

The complete `K=38` diagnostic including preparation and two Passenger solves
took about 14.4 seconds. This passes the first Movement-only gate decisively and
provides favorable evidence for the recourse gate. It does **not** prove general
Passenger integrality: the repository's odd-cycle counterexample remains valid.

At that checkpoint, the next implementation phase was the normalized reusable
Passenger LP template and mathematically verified affine cut extraction. The
following checkpoint records the result of that phase.

## Cut and relaxation checkpoint (2026-08-25)

Phases 3 and 4 have now been implemented as a mathematical reference:

- the former monolithic Passenger block is represented once by
  `DddArcFlowPassengerDomain`;
- the monolithic MIP, reusable fixed-Movement LP/IP recourse, and Benders
  oracle consume this same normalized algebra;
- LP dual cuts are globally validated on an exhaustive binary toy domain and
  tight at every generation point;
- the existing monolithic tiny optimum remains unchanged after the refactor;
- `DddOuterLoopLpBendersSolver` supports both integer Movement masters and a
  continuous root-precut mode.

The resulting computational evidence changes the recommendation:

| method and case | budget/result | certified LB | validated UB |
|---|---|---:|---:|
| outer integer LP-Benders, SS `K=20` | 11 cuts, 120 s | `0.0` | `1,304,194.909` |
| outer continuous root precuts, SS `K=20` | 50 cuts, 73.8 s | `0.0` | n/a |
| complete monolithic LP, SS `K=20` | optimal in 3.6 solver seconds; Movement and Passenger solution integral | `525,730.908` | n/a |
| complete LP dual simplex, SS `K=38` | 120 solver s, about 143 s including construction; no primal LP solution | `80,948.930` | `399,287.271` from the validated All-Stop schedule |
| complete LP barrier without crossover, SS `K=38` | 180 solver s, about 205 s including construction; no primal LP solution | `315,436.671` | `399,287.271` |

Thus the full `K=20` relaxation is already exact and strong, while standard
dual Benders cuts reconstruct it extremely slowly because Gurobi returns
highly local, degenerate dual optima. Separating the same cuts inside a
Branch-and-Benders callback would preserve correctness but is not presently a
credible performance improvement.

For `K=38`, the full LP is computationally difficult but produces a meaningful
dual bound before finding a primal-feasible LP solution. Barrier estimated
roughly 6 GB for its factorization, explaining why this approach will not
scale unchanged to much larger networks. Nevertheless, its 180-second bound
reduces the certified interval to approximately 21 percent and is the strongest
general bound observed for this case.

Gurobi explicitly defines `ObjBound`/`ObjBoundC` for an LP as the best known
objective bound after the solve; in minimization this is a lower bound, and the
two attributes coincide for LP models. Therefore the time-limited barrier and
dual-simplex values above are valid certificates, not heuristic progress
numbers. See the [Gurobi model-attribute reference](https://docs.gurobi.com/projects/optimizer/en/current/reference/attributes/model.html#attr:ObjBound).

The revised next step is:

1. use `DddArcFlowRelaxationOptimizer` as the production lower-bound channel;
2. test LP method and budget profiles separately from integer optimization;
3. retain Movement-only plus exact Passenger-IP evaluation as the primal/UB
   channel;
4. investigate compact or partial Passenger structure that preserves more of
   the strong monolithic relaxation;
5. revisit Pareto/core-point Benders cuts only as a measured strengthening
   experiment, not as the default algorithm;
6. do not implement Branch-and-Benders callbacks until a strengthened cut
   family raises the `K=20` root lower bound materially.

## Objective

Determine whether the complete fixed-K DDD movement arc-flow can be combined
with a projected passenger model to solve dense Skip-Stop instances such as
Five-Station Architecture B with `K=38` more effectively than the current
monolithic movement-and-passenger MILP.

The immediate objective is not to commit to one Benders variant. It is to
implement one reusable decomposition kernel with enough diagnostic evidence to
choose between:

1. classical LP Benders;
2. logic-based or integer Benders;
3. a hybrid Branch-and-Benders-cut / branch-and-check algorithm.

The implementation must preserve certified global lower and upper bounds. A
heuristic passenger evaluation may improve an incumbent, but may never enter a
certificate as if it were exact.

## Motivation from the current implementation

The monolithic `DddFixedKArcFlowOptimizer` gives Gurobi all time-expanded
movement arcs and integer passenger-flow variables in one model. On the current
Five-Station Architecture B results:

| case | movement variables | passenger variables | total constraints | result |
|---|---:|---:|---:|---|
| Skip-Stop, `K=20` | 21,630 | 158,925 | 288,435 | optimal in seconds |
| Skip-Stop, `K=38` | 40,646 | 299,332 | 543,288 | no useful root progress in 10 minutes |

The passenger block accounts for most variables and constraints at `K=38`.
The fixed-timetable passenger model, by contrast, evaluates stored schedules in
well below the monolithic solve time. This makes movement/passenger projection
a plausible response to a measured coupling and root-processing bottleneck.

This does **not** establish that movement-only `K=38` is easy. That is the first
required diagnostic.

## What the research says

### Closest railway analogue

Schettini et al. study individual metro scheduling with passenger waiting and
short-turning. Their tailored exact method projects passenger variables and
adds Benders cuts inside the branch-and-cut tree. They explicitly report that
the monolithic model and an automatic Benders implementation can fail to solve
the root relaxation of larger instances, while their tailored method solves
more instances, with better gaps and lower average runtime. Their key enabling
properties are:

- a path-based movement master;
- passenger subproblems that are always feasible;
- a proof that the fixed-schedule passenger matrix is totally unimodular;
- closed-form, Pareto-optimal Benders cuts;
- separation inside solver callbacks so that the MILP is not restarted after
  every cut.

See [A Benders Decomposition Algorithm for Demand-Driven Metro Scheduling](https://doi.org/10.1016/j.cor.2021.105598).

This is strong evidence that Branch-and-Benders can address exactly the kind of
large passenger block and root-relaxation failure observed in our `K=38` run.
It is not a direct transfer because our capacity-coupled direct-ride passenger
model lacks their integrality property.

### Recent integrated rail and transit models

Recent work continues to use Benders or Branch-and-Benders for integrated
timetabling, rolling-stock, service-pattern, and passenger-assignment models:

- Pan et al. prove total unimodularity of their scenario subproblems before
  applying classical Benders, and combine single- and multi-cut strategies:
  [New Exact Algorithm for the Integrated Train Timetabling and Rolling Stock Circulation Planning Problem with Stochastic Demand](https://doi.org/10.1016/j.ejor.2024.02.017).
- Wang et al. combine a path/column-pool formulation, multi-commodity passenger
  flow, Branch-and-Benders, and a separate LP for stronger closest cuts on a
  seven-line metro case:
  [A Line Planning Approach with Passenger Assignment Considering Cross-Line Operations and Flexible Train Composition](https://doi.org/10.1016/j.trc.2025.105489).
- Yang et al. retain partial passenger information in the timetable master,
  decompose the remaining passenger-flow decisions, and strengthen the root
  relaxation with valid inequalities:
  [Integrated Demand-Side Management and Timetabling for an Urban Rail Transit Line](https://doi.org/10.1016/j.trb.2025.103351).
- A periodic timetabling study combines column generation, delayed conflict
  separation, passenger Benders cuts, and primal large-neighborhood search. It
  also reports that adding many passenger cuts can reduce the number of primal
  search iterations, illustrating that cuts have a real computational cost:
  [A Column-Generation-Based Matheuristic for Periodic and Symmetric Train Timetabling with Integrated Passenger Routing](https://arxiv.org/abs/1912.06941).

The consistent lesson is not that any decomposition is automatically faster.
Successful methods retain a useful relaxation in the master, exploit the
subproblem structure, generate strong cuts, and combine proof progress with a
separate primal mechanism.

### General Benders and logic-based guidance

The main Benders survey identifies the standard failure modes of a naive
implementation: weak early cuts, oscillating master solutions, repeated MILP
solves, dual degeneracy, tailing off, and long periods without an improved
upper bound. It recommends decomposition-specific strengthening, cut selection,
warm starts, partial decomposition, and in-tree separation:
[The Benders Decomposition Algorithm: A Literature Review](https://doi.org/10.1016/j.ejor.2016.12.005).

Magnanti and Wong show that alternate dual optima can yield cuts of very
different strength and introduce Pareto-optimal cut selection:
[Accelerating Benders Decomposition](https://doi.org/10.1287/opre.29.3.464).

Hooker's logic-based Benders work establishes the appropriate framework when
the subproblem remains integer or combinatorial. It also emphasizes two points
that matter here: a useful subproblem relaxation should remain in the master,
and the strength of the explanatory cuts determines whether the method scales:
[Logic-Based Benders Decomposition for Large-Scale Optimization](https://arxiv.org/abs/1910.11944).

Gurobi has no automatic Benders decomposition. A custom implementation is a
branch-and-cut model using lazy constraints and, optionally, user cuts in
callbacks. Therefore cut derivation and certificate correctness remain our
responsibility. See the [Gurobi callback documentation](https://docs.gurobi.com/projects/optimizer/en/current/reference/python/callback.html).

## Consequence for this project

Branch-and-Benders is promising enough to be the **target architecture if the
diagnostic gates pass**, but it should not be the first unvalidated code path.
Unlike the most directly comparable exact metro paper, the repository already
contains a formal counterexample proving that the fixed-movement direct-ride
passenger LP is not integral in general; see
[`../findings/ean_fixed_movement_passenger_integrality.md`](../findings/ean_fixed_movement_passenger_integrality.md).

Consequently:

- LP Benders cuts are valid global lower-bounding cuts;
- LP Benders alone solves only the projected passenger-LP relaxation;
- exact integer passenger evaluation is still required at integer Movement
  candidates;
- exact convergence requires globally valid integer/logic cuts or an explicit
  reformulation that restores passenger integrality;
- the first production candidate is therefore a hybrid of LP Benders and
  branch-and-check, not pure classical Benders.

## Mathematical decomposition

### Movement master

Let `A` be the time-expanded movement arcs and let

\[
x_a\in\{0,1\},\qquad a\in A,
\]

select exactly one physically feasible path for every cabin. The master keeps:

- cabin-flow conservation;
- fixed-K and fixed-start semantics;
- route-domain restrictions for All-Stop or Skip-Stop;
- all eager resource-clique constraints;
- the current no-wait horizon semantics;
- a nonnegative recourse approximation `theta`.

The projected master is

\[
\min\; \theta
\]

subject to the complete movement polytope

\[
x\in X_{\mathrm{move}}
\]

and a growing set of passenger cuts

\[
\theta\ge \alpha^k+\sum_{a\in A}\beta_a^k x_a,
\qquad k\in\mathcal C.
\]

Because unserved demand is allowed with a finite penalty, every physically
feasible movement plan has a feasible passenger assignment. Version 1 therefore
needs optimality cuts but no passenger-feasibility cuts.

### LP passenger recourse

For a fixed, possibly fractional Movement vector `x_bar`, the continuous
passenger recourse has the normalized form

\[
Q_{LP}(\bar x)
=
\min_q
\left\{
c^\top q+c_0:
Wq\le h+T\bar x,
Eq=0,
q\ge0
\right\}.
\]

The rows include:

- passenger-flow conservation over the chosen time-expanded cabin path;
- ride activation by movement arcs;
- demand-group bounds;
- cabin interval capacities;
- the objective constant for unserved demand.

For an optimal dual solution `(pi, lambda)`, the subproblem produces a globally
valid affine lower bound

\[
\theta
\ge
c_0+\pi^\top h+\pi^\top T x.
\]

All signs and constants must be generated from a canonical affine-row
representation. They must not be reconstructed ad hoc from Gurobi constraint
senses inside a callback.

### Integer passenger recourse

For a binary movement schedule `x_bar`, the exact recourse is

\[
Q_I(\bar x)
=
\min_{q\in\mathbb Z_+}
\left\{
c^\top q+c_0:
Wq\le h+T\bar x,
Eq=0
\right\}.
\]

It supplies a valid global upper bound

\[
UB\leftarrow\min\{UB,Q_I(\bar x)\}.
\]

If the master claims `theta_bar < Q_I(x_bar)`, the integer Movement candidate
must be rejected by a valid logic cut.

The first exact fallback is the incumbent-specific integer optimality cut. Let
`S(x_bar)` be the selected movement arcs and let `L` be a valid global passenger
objective floor. Then

\[
\theta
\ge
Q_I(\bar x)
-
\bigl(Q_I(\bar x)-L\bigr)
\sum_{a\in S(\bar x)}(1-x_a).
\]

If every selected arc remains selected, the same schedule is present and the
exact recourse value is enforced. As soon as one selected arc changes, the cut
falls back to `L`. This cut is globally valid and provides finite convergence
over a finite movement master, but it may be weak.

Later strengthened cuts should replace the complete selected-arc support by a
proved sufficient passenger explanation, for example:

- an OD/time-window coverage set;
- a cabin-interval capacity bottleneck;
- an odd-cycle or cover explanation from the Passenger MIP;
- a minimal set of Stop arcs supporting the relevant ride alternatives.

No strengthened logic cut may be enabled before its global validity is tested
against exhaustive tiny Movement schedules.

## The three solution concepts

### Concept A: classical outer-loop LP Benders

Algorithm:

1. solve the Movement master with the current cuts;
2. solve the LP passenger recourse for the resulting `x`;
3. add a violated dual cut;
4. restart the master until no LP cut is violated.

Purpose in this project:

- reference implementation for cut algebra;
- deterministic debugging and cut inspection;
- proof that the projected LP matches the monolithic LP relaxation;
- measurement of iteration counts, degeneracy, and cut strength.

It is not the final exact algorithm because the Passenger LP is not integral in
general. It may still be a useful lower-bound engine and may be exact on many
empirical instances.

Use it when:

- validating the decomposition;
- solving tiny enumerated cases;
- measuring the projected relaxation independently of callback behavior.

Do not use it alone for a thesis claim of integer optimality.

### Concept B: outer-loop logic-based / integer Benders

Algorithm:

1. solve the Movement master;
2. solve exact integer passenger recourse;
3. update the validated upper bound;
4. add an exact no-good optimality cut or a stronger proved explanation cut;
5. restart the master.

This is exact over the finite DDD Movement domain. Its practical performance is
almost entirely determined by the strength of the logic cuts. The fallback cut
above may enumerate passenger-distinct movement plans and is therefore a
correctness baseline, not a scaling strategy.

Use it when:

- the empirical Passenger LP/IP gap is material;
- strong passenger bottleneck explanations can be derived;
- callback complexity is not yet justified;
- exactness of the logic cuts must be debugged visibly iteration by iteration.

Abandon or strengthen it if many consecutive candidates differ slightly but
produce the same passenger bottleneck and upper bound.

### Concept C: hybrid Branch-and-Benders-cut / branch-and-check

This keeps one Gurobi branch-and-bound tree alive:

- at selected `MIPNODE` callbacks, solve LP passenger recourse for the
  fractional Movement vector and add violated global user cuts;
- at every relevant `MIPSOL` callback, solve exact integer passenger recourse;
- add any violated LP cut as a lazy constraint;
- if `theta` still underestimates integer recourse, add a valid integer logic
  cut as a lazy constraint;
- accept and externally record a candidate as an upper bound only after exact
  passenger evaluation and complete Movement validation.

This combines Gurobi's branching and primal heuristics with projected Passenger
cuts, avoids repeatedly restarting the master, and directly addresses the
observed large-root bottleneck. It is the most promising final exact method if
the subproblem and cut gates pass.

Its risks are:

- many expensive subproblem calls at fractional nodes;
- weak or highly degenerate LP cuts;
- callback serialization and reduced solver parallel efficiency;
- certificate errors if a cut is locally rather than globally valid;
- a huge tree if integer logic cuts remain incumbent-specific.

Use it when the outer-loop prototype demonstrates valid useful LP cuts and the
integer oracle is consistently cheap. Do not implement it first merely because
the literature reports good results on models with integral passenger
subproblems and tailored closed-form cuts.

## Recommended algorithmic target

The recommended target is a **two-layer hybrid**:

```text
complete DDD Movement master
  + cheap static passenger lower-bound rows
  + LP Benders user cuts at selected node relaxations
  + exact Integer-Passenger checks at integer Movement solutions
  + logic-based lazy cuts only for the remaining LP/IP discrepancy
  + independent complete incumbent validation
```

This gives the LP layer responsibility for most lower-bound progress and uses
the more expensive integer layer only to restore exactness. It also permits a
clean intermediate result if the integer layer is too weak: a valid global
lower bound for the original integer model still follows from the Passenger-LP
relaxation, while every exactly evaluated Movement plan remains a valid upper
bound.

## OO architecture

The current `arc_flow.py` mixes network preparation, Movement-model assembly,
Passenger-model assembly, Gurobi configuration, progress callbacks, extraction,
and certificate handling. Benders should not be added as another conditional
branch in that class.

Use composition around immutable model descriptions and small solver adapters:

```text
optimization/ddd/
  arc_flow_network.py               existing time-expanded network types
  arc_flow_preparation.py           shared immutable prepared problem
  arc_flow_movement_master.py       movement-only Gurobi model and extraction
  passenger_recourse.py             normalized LP/IP recourse template
  passenger_benders_cuts.py         immutable cuts and cut generators
  passenger_benders_outer_loop.py   reference classical/logic loop
  passenger_branch_and_benders.py   callback strategy
  arc_flow.py                       compatibility facade / monolithic baseline
```

Benchmark-specific corpus and experiment code belongs under `benchmarking/`,
not in the optimization package:

```text
benchmarking/
  ddd_passenger_decomposition.py

benchmarks/
  run_ddd_passenger_decomposition_diagnostics.py
```

### Shared prepared problem

`DddPreparedArcFlowProblem` is a frozen data object containing:

- the validated `DddFixedKTrajectoryProblem`;
- all deterministic cabin time-expanded networks;
- stable Movement-arc order and `arc_by_id`;
- resource cliques and boundary intervals;
- a normalized passenger recourse description;
- movement, passenger, and complete fingerprints;
- construction metrics.

`DddArcFlowProblemPreparer` is the only builder of this object. Monolithic,
movement-only, outer-loop Benders, and Branch-and-Benders must receive the same
prepared object so comparisons cannot accidentally use different domains.

### Movement master

`DddMovementMasterBuilder` creates `DddMovementMaster`, which owns:

- the Gurobi model;
- Movement variables indexed by stable arc ID;
- the recourse variable `theta`;
- flow and resource rows;
- extraction of binary or fractional Movement vectors;
- Movement MIP-start application;
- conversion of a binary solution to `DddReferenceSolution`;
- model-size metrics.

The builder accepts a small configuration value object rather than booleans:

```python
class DddPassengerEmbeddingMode(StrEnum):
    NONE = "none"
    MONOLITHIC_INTEGER = "monolithic_integer"
    PROJECTED_RECOURSE = "projected_recourse"
```

This keeps movement-only diagnostics and the existing monolithic reference on
the same construction path.

### Passenger recourse template and oracle

`DddPassengerRecourseTemplate` is solver-independent metadata:

- recourse variables and objective coefficients;
- normalized equality and inequality rows;
- every affine dependence on Movement arc variables;
- stable row and variable IDs;
- objective constant and global floor;
- fingerprint.

`DddPassengerRecourseModelBuilder` builds one reusable Gurobi model from the
template. `DddPassengerRecourseOracle` updates affine RHS values for a new
Movement vector instead of rebuilding the model.

The oracle exposes one typed operation:

```python
evaluate(
    movement: DddMovementVector,
    domain: DddPassengerRecourseDomain,
) -> DddPassengerRecourseResult
```

The result contains:

- status and objective;
- LP duals when requested;
- exact integer assignment when requested;
- fractionality diagnostics;
- solve time and reuse count;
- a recourse fingerprint and the evaluated Movement signature.

Separate LP and integer models may share the immutable template but not mutable
Gurobi state. This allows safe caching and avoids changing variable types inside
a callback.

### Cut value objects and generators

`DddPassengerBendersCut` is immutable and solver-independent:

- stable cut ID;
- cut kind;
- constant `alpha`;
- sorted sparse coefficients by Movement arc ID;
- generation point and source objective;
- global-validity flag and proof provenance;
- numerical violation method;
- fingerprint.

Cut generators implement a narrow protocol:

```python
class DddPassengerCutGenerator(Protocol):
    def separate(
        self,
        movement: DddMovementVector,
        theta_value: float,
        recourse: DddPassengerRecourseResult,
    ) -> tuple[DddPassengerBendersCut, ...]: ...
```

Initial implementations:

- `DddLpDualCutGenerator`;
- `DddIntegerIncumbentCutGenerator`;
- later `DddPassengerCapacityExplanationCutGenerator`.

`DddPassengerCutPool` owns deduplication, violation filtering, deterministic
ordering, serialization, and cut metrics. Neither a callback nor an outer loop
should contain cut algebra.

### Solve strategies

Do not use a deep optimizer inheritance hierarchy. Provide three composed
strategies with the same result contract:

- `DddOuterLoopLpBendersSolver`;
- `DddOuterLoopIntegerBendersSolver`;
- `DddBranchAndBendersSolver`.

Each receives:

- a `DddMovementMasterBuilder`;
- LP and/or Integer `DddPassengerRecourseOracle`;
- cut generators and a cut pool;
- an incumbent validator;
- a common budget and progress sink.

All return `DddPassengerDecompositionResult`, including:

- certified LB and validated UB;
- root-LP and integer status separately;
- best Movement and Passenger plans;
- cut counts by kind and callback location;
- LP/IP recourse calls, cache hits, and runtimes;
- master sizes and node metrics;
- time to first and best incumbent;
- complete provenance and fingerprints.

### Callback isolation

`DddBranchAndBendersCallback` should be a small adapter, not the algorithm:

1. read the allowed Gurobi callback state;
2. construct a typed `DddBendersSeparationRequest`;
3. call a thread-safe `DddPassengerSeparationService`;
4. translate already validated affine cuts to `cbCut` or `cbLazy`;
5. publish metrics.

The callback must not build the passenger model, derive coefficients, write
files, or run independent validation. Gurobi models should use one solver
thread for the first callback prototype; parallel behavior is evaluated only
after correctness is established.

## Implementation phases and decision gates

### Phase 0: preserve the dirty baseline

Before implementation:

- finish or separately commit the current fixed-K Arc-Flow, start-policy, and
  live-progress work;
- complete the interrupted full regression after the progress changes;
- retain the current monolithic optimizer as an unchanged benchmark path;
- do not mix the known `K=39` independent-passenger mismatch into the Benders
  work; diagnose it separately before using `K=39` in acceptance results.

### Phase 1: shared preparation and movement-only diagnostic

Refactor preparation and movement-master assembly without changing the
monolithic mathematical model.

Add the embedding modes `NONE`, `MONOLITHIC_INTEGER`, and
`PROJECTED_RECOURSE`. In `NONE`, use a feasibility objective and extract the
first and best complete Movement plan.

Required runs:

- All-Stop and Skip-Stop `K=20`;
- Skip-Stop `K=22`;
- Skip-Stop `K=38` with the balanced fixed starts;
- the known All-Stop schedule as a Movement MIP start.

Gate:

- if Movement-only `K=38` reaches a valid Movement incumbent and completes its
  root relaxation comfortably, continue with passenger projection;
- if it stalls similarly to the monolithic model, passenger decomposition is
  not the main remedy and the experiment stops before callback work.

### Phase 2: Passenger LP/IP corpus diagnostic

Reuse the existing fixed-movement Passenger optimizer to evaluate a corpus of
validated Movement plans in both domains:

- all stored All-Stop and Skip-Stop solutions for `K=17..22`;
- the All-Stop `K=38` plan interpreted in the Skip-Stop domain;
- CP-SAT movement seeds where available;
- deliberately diverse Stop/Skip plans from different solver seeds;
- the existing odd-cycle counterexample.

Record:

\[
\operatorname{gap}_{pass}(m)
=
\frac{Q_I(m)-Q_{LP}(m)}{\max(1,|Q_I(m)|)},
\]

fractional ride count, maximum fractional distance, binding demand/capacity
rows, and LP/IP runtime.

Gate:

- zero empirical gaps do not override the formal counterexample, but indicate
  that LP cuts may do nearly all practical work;
- recurring material gaps require the integer logic layer from the beginning;
- a slow integer oracle rules out checking every callback incumbent and
  requires throttling or stronger master-side passenger structure.

### Phase 3: normalized recourse template

Extract the Passenger block currently assembled in `_add_passengers()` into
the solver-independent template and reusable oracle.

Acceptance:

- for every fixed binary Movement plan, template-LP and template-IP match the
  existing independent fixed-movement evaluator;
- the template embedded in the monolithic model reproduces the existing
  monolithic objective and size within expected refactoring noise;
- updating a reused subproblem is measurably cheaper than rebuilding it;
- all objective constants, row senses, dual signs, and Movement coefficients
  survive a serialization roundtrip.

### Phase 4: deterministic outer-loop LP Benders

Implement classical outer-loop LP Benders as the mathematical reference.

Acceptance on tiny fully enumerable instances:

- every generated cut is valid for every enumerated Movement schedule;
- the cut is tight at its generation point within tolerance;
- the converged Benders value equals the monolithic model with continuous
  passenger variables;
- LB is monotone, never exceeds the monolithic integer optimum, and survives
  checkpoint resume;
- duplicate dual optima do not create duplicate cuts.

Benchmark `K=20`, `K=22`, and `K=38` for cut count, LB progression, master
runtime, recourse runtime, and tailing off.

Gate:

- proceed only if LP cuts raise the lower bound substantially faster than the
  monolithic model establishes its root bound;
- if standard dual cuts tail off, test core-point/Pareto cut selection before
  implementing callbacks;
- if even strengthened cuts remain weak, Branch-and-Benders will not repair the
  relaxation and should not be implemented.

### Phase 5: exact outer-loop integer layer

Add exact Passenger-IP evaluation and the incumbent-specific integer
optimality cut. This is the correctness oracle for the future callback method.

Acceptance:

- the odd-cycle instance closes the known LP/IP gap;
- exhaustive tiny instances converge to the monolithic integer optimum;
- no candidate is accepted as a validated UB before exact Passenger-IP
  evaluation;
- the exported LB remains based only on globally valid LP and logic cuts;
- repeated rediscovery metrics expose weak integer cuts rather than hiding
  them.

Gate:

- if few integer cuts are needed after LP convergence, proceed to in-tree
  separation;
- if the solver enumerates near-identical schedules, first derive capacity or
  OD/time-window explanation cuts;
- do not move a weak outer loop into a callback and expect it to become strong.

### Phase 6: Branch-and-Benders-cut prototype

Run one Gurobi Movement master with:

- `LazyConstraints=1`;
- exact LP and IP recourse at `MIPSOL`;
- optional LP user cuts at `MIPNODE` only when the node relaxation is optimal;
- deterministic cut batching and per-node throttling;
- a one-thread correctness profile;
- a shared wall-clock budget including all subproblem solves.

Start with incumbent-only separation. Add fractional-node cuts only after the
lazy-only variant is correct and measured. A root pre-cut phase may solve the
continuous Movement master and add LP cuts before branching, reducing callback
traffic.

Acceptance:

- identical optimum and certificate to the monolithic model on tiny cases;
- identical projected LP bound to Phase 4;
- every accepted incumbent has exact Passenger-IP and independent validation;
- callback and external LB/UB histories satisfy `LB <= UB` at all times;
- interruption returns a valid certified interval;
- `K=20` is not materially slower than the monolithic baseline;
- `K=22` improves either proof time or incumbent time;
- `K=38` establishes a meaningful nonzero lower bound and imports the complete
  All-Stop-derived Skip-Stop upper bound within the screening budget.

### Phase 7: strengthening only from evidence

Evaluate separately:

1. multi-cuts versus one global Passenger cut;
2. core-point or Pareto-optimal LP cuts;
3. a partial passenger master relaxation;
4. OD/time-window capacity explanation cuts;
5. cut aging and active-pool management;
6. callback throttling and subproblem caching;
7. primal neighborhoods using exactly evaluated Movement plans.

Shared cabin capacities couple OD groups, so per-OD multi-cuts are not
automatically valid as independent recourse functions. Any decomposition by OD
must explicitly allocate shared capacity or dualize the coupling first.

## Tests

### Unit tests

- normalized affine row evaluation for binary and fractional Movement vectors;
- LP-dual cut sign, constant, tightness, and violation;
- deterministic sparse cut IDs and duplicate suppression;
- incumbent-specific integer cut at the generating schedule and after one arc
  change;
- objective-floor behavior;
- reused oracle RHS updates with no stale values;
- LP and IP model isolation;
- cache keys include complete Movement and recourse fingerprints;
- callback request throttling and budget exhaustion;
- progress events distinguish master, LP recourse, IP recourse, and validation.

### Exhaustive mathematical tests

On tiny complete Movement domains:

- enumerate every feasible Movement vector;
- evaluate exact Passenger-IP and Passenger-LP;
- verify every LP and logic cut against every vector;
- compare outer-loop LP Benders to monolithic Passenger-LP;
- compare outer-loop integer Benders and Branch-and-Benders to monolithic
  Passenger-IP;
- include the formal odd-cycle Passenger case.

These tests are the primary defense against an invalid global lower bound.

### Regression tests

- existing monolithic Arc-Flow results remain unchanged;
- shared preparation reproduces stable arc, clique, candidate, row, and
  fingerprint IDs;
- independent EAN passenger validation agrees with every accepted incumbent;
- All-Stop and Skip-Stop use identical starts for `K <= K_max_AS`;
- balanced high-K boundary starts retain the existing boundary semantics;
- frontend and terminal distinguish monolithic, outer-loop, and in-tree
  certificates.

### Experimental matrix

Run all methods under identical total budgets:

| case | monolithic | movement-only | outer LP Benders | outer hybrid | Branch-and-Benders |
|---|---:|---:|---:|---:|---:|
| AS `K=20` | yes | yes | yes | yes | yes |
| SS `K=20` | yes | yes | yes | yes | yes |
| SS `K=22` | yes | yes | yes | yes | yes |
| SS `K=38` | yes | yes | yes | conditional | conditional |

Report build, presolve/root, first Movement candidate, first validated Passenger
UB, LB history, recourse calls, cuts, nodes, memory, and final certified gap.

## Decision rule

Adopt hybrid Branch-and-Benders as the main fixed-K solver only if all of the
following hold:

1. Movement-only `K=38` is materially easier than the monolithic model.
2. Passenger LP recourse is fast and its cuts noticeably improve the projected
   master bound.
3. Exact Passenger-IP recourse is fast enough for selected integer candidates.
4. The integer correction layer needs few cuts or has strong explanations.
5. The method improves either time to a useful UB or certified gap on both
   `K=22` and `K=38`, not only on a tiny demonstration.

Otherwise:

- if Movement-only is hard, return to a trajectory or alternative-graph
  Movement master;
- if LP cuts are weak, strengthen the master or use a passenger-guided primal
  neighborhood rather than callbacks;
- if the LP/IP Passenger gap dominates, investigate partial capacity allocation
  in the master or stronger logic cuts;
- if monolithic solving becomes competitive after a complete All-Stop
  Passenger MIP start, retain the simpler monolithic production solver.

## Recommendation

Branch-and-Benders-cut is sufficiently well supported by closely related rail
research to justify a serious prototype. It is **not yet justified as the next
large implementation tranche** without the Movement-only and recourse-cut
gates. The scientifically strongest and lowest-risk sequence is:

```text
shared preparation
-> movement-only K=38
-> passenger LP/IP corpus
-> reusable recourse oracle
-> exact outer-loop cut validation
-> hybrid branch-and-check
-> optional fractional-node Branch-and-Benders cuts
```

This sequence does not throw away callback work if Branch-and-Benders succeeds,
and it avoids building a sophisticated callback around weak or invalid cuts if
it does not.

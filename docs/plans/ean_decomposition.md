# EAN Scaling and Decomposition Roadmap

Status: **research plan**

## Goal

Evaluate decomposition and delayed constraint generation without weakening the
exactness claims of the current integrated EAN passenger MILP. The integrated
model remains the reference implementation and certification path.

## Phase 0: Stabilize the Immediate Baseline and Locate the Bottleneck

The immediate production baseline has been selected: affine stop/skip timing,
first-slot activation, and objective-aware boarding-time projection are the
defaults. Historical formulations remain selectable as benchmark references.
Repeated-seed validation remains useful, but it no longer blocks this phase.
Do not wait for every speculative phase in
`ean_structural_reformulation.md`: the purpose of this diagnosis is to decide
whether those phases are worth implementing.

The four-case diagnostic runner and callback metrics are implemented. The
remaining Phase-0 work is to execute and interpret the controlled scaling
ladder.

Create a scaling ladder with increasing station count, demand, and cabin
density. For every level, measure the same resource-limited cases:

```text
integrated movement and passenger model
movement and headways without passenger assignment
integer passenger optimization for a fixed movement plan
LP relaxation for the same fixed movement plan
```

The fixed-movement integer and LP cases use the independent compact passenger
optimizer with the movement plan extracted from the integrated run. They build
no movement or headway variables and share exactly the same feasible direct
rides.

The movement-only case uses the canonical movement model with objective zero.
It diagnoses construction cost and the difficulty of finding and certifying
feasibility. Its objective bound and gap are not comparable to the passenger
objective and must not be interpreted as proof progress for the integrated
problem.

Separate model construction, presolve, root relaxation, incumbent search, and
proof progress. Record variables, constraints, nonzeros, headway pairs,
ordering binaries, passenger candidates, peak memory, first incumbent, final
incumbent, bound, gap, and runtime.

Use callback metrics rather than parsing solver text. Record candidate
generation, movement-model construction, passenger-model construction, and
MIP-start application separately. The scaling runner should write one
machine-readable result containing all four cases for an example and solver
budget. Existing passenger benchmark and frontend JSON contracts remain
unchanged.

Use the measurements to select the next branch:

- if movement-only is already difficult, first test safe same-cabin precedence
  and conservative pair classification from `ean_formulation_and_search.md`,
  then consider shared precedence, delayed headways, or the CP prototype;
- if fixed-movement passenger assignment becomes difficult at larger scale,
  prioritize passenger strengthening or a different exact solution method;
- if both isolated models are easy but the integrated model is difficult,
  prioritize coupling methods such as neighborhood search or logic-based
  decomposition;
- if Python construction or artifact memory dominates, optimize materialization
  before changing the mathematical algorithm.

Maintain tiny production-path instances that solve to proven optimality. Every
later exact method must agree with these instances before a scaling benchmark
is interpreted.

## Candidate Decomposition Boundaries

Let \(z\) denote stop/skip decisions, \(a\) visit and horizon activations,
\(o\) headway-order decisions, \(t\) event times, \(w\) waiting, and \(x,u\)
served and unserved passenger decisions. Two decomposition boundaries are
plausible and must not be conflated.

### Boundary A: Scheduled Movement and Passenger Assignment

```text
master:
  stop/skip, activation, headway order, event times, waiting

subproblem:
  passenger assignment for the complete fixed movement plan
```

For a complete movement plan \(m=(z,a,o,t,w)\), the implemented compact
passenger optimizer evaluates

\[
  Q_{\mathrm{pass}}(m)
  =
  \min_{x,u}
  f(m,x,u).
\]

This boundary is attractive when movement scheduling is manageable and
passenger assignment is the dominant difficulty. Every master solution is
already physically and temporally feasible, and the passenger subproblem is
small. It is therefore well suited to:

- exact evaluation of movement plans;
- passenger-optimized starts;
- local branching and large-neighborhood search;
- alternating or heuristic movement/passenger optimization.

Its weakness for exact Benders is the continuous timing in the master.
Passenger candidate availability and the coefficients of Waiting-Time and
Journey-Time costs depend on \(t\). Two schedules with the same stop/skip
vector may have different passenger values. A no-good or optimality cut on the
binary stop/skip vector alone is therefore not valid, and classical LP-dual
cuts are not automatic because the subproblem objective coefficients change
with the master times.

Prefer Boundary A when:

- full movement plans are cheap to generate;
- timing is nearly determined by the movement decisions;
- the main purpose is incumbent improvement rather than a global proof;
- passenger assignment, rather than timing or headways, becomes difficult at
  larger scale.

### Boundary B: Discrete Movement Structure and Timing plus Passengers

```text
master:
  discrete movement structure

subproblem:
  timing, waiting, and passenger optimization
```

For a discrete movement structure \(y=(z,a,o)\), define

\[
  Q_{\mathrm{structure}}(y)
  =
  \min_{t,w,x,u}
  f(t,w,x,u)
\]

subject to every timing, headway, horizon, release, capacity, and passenger
constraint implied by \(y\). The subproblem therefore finds the best schedule
and passenger assignment for the selected structure instead of evaluating one
externally fixed schedule.

This removes continuous timing degeneracy from the master. A cut on \(y\) is
logically sound because all possible timings for that discrete structure have
already been optimized. Timing-infeasible structures can produce
IIS- or cycle-based feasibility cuts, and integer optimality or explanatory
passenger cuts can be attached to one discrete structure or a responsible
subset of its decisions.

The drawback is that the subproblem is itself a MILP because passenger
assignment is not integral in general. The placement of headway-order
variables is especially important:

- if \(o\) remains in the subproblem, the master is smaller but the subproblem
  retains the large headway-order search;
- if \(o\) is fixed by the master, the timing part becomes much closer to a
  system of linear difference constraints, but the master may contain a very
  large number of order binaries.

Prefer Boundary B when:

- many materially different schedules exist for one stop/skip structure;
- passenger cost depends strongly on optimized event times;
- the fixed-structure timing/passenger subproblem solves quickly;
- exact logic-based cuts and timing-feasibility explanations are the goal.

### Comparison

| Property | Boundary A: fixed schedule | Boundary B: fixed structure |
|---|---|---|
| Master variables | movement binaries and continuous times | discrete movement structure |
| Subproblem | passenger assignment | timing, waiting, passenger assignment |
| Existing implementation | compact fixed-movement optimizer | not yet implemented |
| Subproblem size | very small in current benchmarks | unknown; must be measured |
| Master feasibility | already physically timed | may require timing-feasibility cuts |
| Passenger time costs | constants in one evaluation | optimized inside the subproblem |
| Binary no-good cuts | difficult to generalize over times | valid for the complete discrete structure |
| Classical LP Benders | obstructed by time-dependent costs and integer assignment | still not classical while passengers remain integer |
| Best immediate use | evaluation, starts, LNS | logic-based or branch-and-check decomposition |

Boundary A is already known to solve the isolated passenger problem in
milliseconds. This does not show that it is the best exact decomposition:
it leaves the observed movement, timing, and headway coupling in the master.
Boundary B is theoretically cleaner for logic-based Benders, but only if its
larger subproblem is consistently easy.

### Boundary Diagnostic

Before implementing a Benders master, add one fixed-structure diagnostic that
solves the same scenario at three levels:

1. fix the complete movement plan, including all times, and optimize only
   passengers;
2. fix stop/skip, activation, and headway orders, then optimize timing,
   waiting, and passengers;
3. fix only stop/skip and activation, then optimize headway orders, timing,
   waiting, and passengers.

Introduce a typed `EanMovementStructure` for this experiment. It contains
stop/skip decisions, visit activations, and the selected headway orders but no
continuous event times. Extract it directly from the solved movement model;
do not infer headway orders afterward from event times that may be equal within
solver tolerance.

Use the same extracted integrated incumbent and passenger candidate
configuration in all three cases. Record model size, setup time, first
incumbent, runtime, objective, bound, gap, and LP fractionality.

Select the boundary from the result:

- if levels 2 and 3 are fast, use a small stop/skip master;
- if only level 2 is fast, headway orders must be represented or classified in
  the master;
- if only level 1 is fast, retain Boundary A for neighborhood search and do
  not begin a full exact decomposition;
- if level 2 is fast but the order master is too large, use a hybrid master
  containing stop/skip, activation, and only critical or unresolved headway
  orders.

## Phase 1: Passenger-Coupling Cut Design

The compact fixed-movement passenger optimizer and its LP mode are implemented.
Use their matched LP/IP measurements to design decomposition cuts; do not add a
separate repair heuristic while the complete integer subproblem remains fast.

Start with movement patterns from the Three- and Five-Station scaling ladder.
For each pattern, record the LP/IP objective gap, LP fractionality, exact solve
time, and which demand or cabin-capacity rows are binding. Then derive and test:

- valid LP lower-bounding cuts from demand and capacity duals;
- logic-based optimality cuts from the exact passenger solve;
- stronger combinatorial cuts for repeated stop/capacity conflicts.

The general direct-ride LP is nonintegral, so LP dual cuts alone do not certify
the integer passenger value. If the exact fixed-movement problem later becomes
difficult at larger scale, evaluate restricted repair or path/column methods
then, rather than adding them preemptively.

### Movement-Plan Corpus

Do not add another physical topology before using the existing scenario
families. The initial corpus should use:

```text
three_station_v0
five_station_v0
five_station_circle_cw_half_skip_no_wait_v0
five_station_circle_cw_half_skip_wait_v0
```

These cover a small and a larger bidirectional ring plus a directed circle,
with and without waiting. The registered no-skip/no-wait variants are useful
as deterministic controls but contribute little movement-pattern diversity.

For every selected scenario, collect and deduplicate movement plans by their
stop/skip and waiting signature:

- the deterministic earliest all-stop plan;
- Journey-Time integrated incumbents at short and full budgets;
- Waiting-Time integrated incumbents at short and full budgets;
- additional incumbents from controlled solver seeds once seed support exists.

The current examples all release uniform or near-uniform all-OD demand at the
service start. Before drawing conclusions about LP integrality or useful cuts,
add benchmark-only demand profiles on the existing topology:

- staggered release batches across the service horizon;
- asymmetric OD peaks that create directional or station-specific capacity
  competition;
- one lower-load control where most cabin-capacity rows are slack.

Implement these as data-driven benchmark scenario transforms rather than
copying physical example classes or adding frontend examples. Add a
seven-station topology only after the cut experiment works on the existing
families and a larger conflict graph is needed for scaling.

## Phase 2: Progressive Wait Search

Evaluate progressive waiting as a low-cost primal search strategy before
implementing a full decomposition. For guaranteed feasible-set nesting, build
the full-wait artifact once and solve restricted stages by fixing or capping
its existing wait variables:

```text
wait = 0
optional small cap
full configured wait bound
```

A solution from a smaller cap is a feasible incumbent for every larger cap.
Its lower bound is not transferable. Reload the incumbent between stages and
compare the complete schedule against a direct full-wait solve under the same
total time budget.

A separately built `NO_WAITING` artifact has different checkpoint and variable
sets, including missing platform-exit wait checkpoints. It may provide a
partial name-based heuristic start, but it is not a guaranteed feasible
incumbent for the full-wait artifact.

Use only a small fixed cap schedule initially. Do not claim that headway-pair
count varies monotonically with the cap: current pair generation does not use
the numeric wait cap. Keep progressive waiting only if it reproducibly improves
the final incumbent or time to a target objective. Do not retain it merely
because an early restricted stage solves quickly.

## Phase 3: Delayed Exit-Switch Headways

If Phase 0 identifies headway materialization or movement search as a dominant
bottleneck, prototype delayed generation for selected exit-switch or rope-merge
headway pairs using an external solve loop:

```text
solve current generated model
inspect incumbent movement
detect every delayed headway violation
add the exact missing disjunctions
reload compatible start values
repeat until no violation remains
```

Keep station and platform constraints eager initially. Report intermediate gaps
as bounds for the current generated model, not for the complete problem.
Compare the final verified result against the eager model on exact small cases.

Prefer the external loop for the first experiment because omitted disjunctions
may require new precedence variables. A callback that adds only constraints
cannot create missing variables. Continue only if the number of generated pairs
and the total solve time are materially lower and the number of separation
rounds remains small.

## Phase 4: Neighborhood Matheuristics

Before building a complex exact decomposition, evaluate local branching or
large-neighborhood search for strong feasible skip plans:

1. Start from an all-stop, greedy skip, or previous incumbent plan.
2. Fix most movement, stop/skip, and waiting decisions.
3. Release a neighborhood defined by stations, cabins, time windows, or a
   bounded number of changed stop decisions.
4. Reoptimize the resulting integrated subproblem with Gurobi.
5. Evaluate the accepted movement with the fixed-movement passenger evaluator.
6. Move or enlarge the neighborhood until the total time budget is exhausted.

Neighborhood solutions are feasible incumbents but do not provide a global
optimality certificate. Validate them with the same movement and passenger
checks as exact solutions. Keep this path if it reaches materially better
incumbents or a larger network size than direct integrated search.

## Phase 5: Conditional Decomposed Exact Search

Implement exact decomposition only after the boundary diagnostic selects
Boundary A, Boundary B, or the hybrid order-master variant. Do not assume that
either split automatically yields useful Benders cuts: stop/skip decisions
change candidate availability, times change passenger costs, and shared
capacities make the passenger problem multi-commodity.

Choose the method from the Phase 0 and Phase 1 evidence:

- do not use classical LP Benders as an exact method for the general passenger
  model; the direct-ride fixed-movement LP already has a formal fractional
  counterexample;
- use LP dual information only for valid lower-bounding cuts whose limitations
  are explicit;
- use branch-and-Benders when an LP subproblem supplies valid bounds but
  integrality must be recovered inside the search;
- use logic-based Benders when the passenger subproblem remains genuinely
  integer;
- for Boundary B, derive timing-feasibility cuts from an IIS or positive cycle
  before falling back to a complete structure no-good cut;
- for Boundary A, treat the fixed-movement evaluator primarily as an exact
  oracle for search unless globally valid timing-dependent lower bounds have
  been derived;
- abandon Benders if cuts are weak, iterations repeatedly rediscover similar
  movements, or direct neighborhood search gives better incumbents at the
  target scale.

Do not combine Benders, delayed headways, and progressive waiting in the first
prototype. Validate each component independently before composing them.

The final reported result is exact only when:

- all full-wait variables and constraints are active;
- no delayed physical violation remains;
- passenger assignment is integral and fully feasible;
- the reported bound and gap belong to that certified model.

## Skip-Benefit Experiment Campaign

Start the large experiment campaign once at least three network sizes produce
useful feasible solutions and bounds under one stable protocol. Compare skip
against all-stop with identical demand, fleet, horizon, waiting policy, service
requirements, and solver budget.

Use the available-, dispatched-, and peak-fleet definitions from
`ean_fleet_activation_and_depots.md`. Complete the optional-dispatch model
before drawing final conclusions about fleet efficiency; fixed-start runs may
still be used for controlled same-fleet comparisons.

Maximize served demand lexicographically before minimizing waiting or journey
time, or enforce the same minimum served demand in both cases. Otherwise a
lower journey-time objective may merely result from leaving more passengers
unserved. Report OD-level and fairness metrics in addition to the aggregate
objective.

For minimization with lower bounds \(L\) and feasible incumbents \(U\), bound
the true skip benefit by:

```text
L_all_stop - U_skip
<= optimal_all_stop - optimal_skip
<= U_all_stop - L_skip
```

A positive lower endpoint certifies a benefit from skip without proving both
models optimal. Stop adding micro-reformulations once two consecutive changes
fail to improve model size, root progress, incumbent quality, peak memory, or
the largest useful network. At that point continue with the best decomposition
or heuristic path, or begin the separate full-day model work.

## Alternative Solver and Modeling Prototypes

Do not replace the current Gurobi EAN MILP merely because a solver is marketed
for railway planning. Railway frameworks and commercial planning systems do
not provide a drop-in optimizer for the combined ropeway movement, stop/skip,
waiting, headway, capacity, and passenger-assignment problem. Keep the
integrated Gurobi model as the exact reference, bound source, and certification
path while evaluating structurally different backends on isolated subproblems.

### CP Movement and Headway Prototype

The most promising alternative prototype is a CP formulation of movement and
headways with fixed or absent passenger assignment:

```text
CP movement and headway plan
-> fixed-movement passenger evaluator
-> optional Gurobi or SCIP repair and certification
```

Model cabin visits as optional interval activities, stop/skip and waiting as
alternative durations or optional activities, and physical conflicts as
sequence or `noOverlap` constraints. This avoids manually materializing many
pairwise Big-M disjunctions and lets a CP solver propagate temporal conflicts
directly.

Evaluate these backends:

- **IBM CP Optimizer** as the primary CP prototype because interval variables,
  optional activities, sequence variables, and `noOverlap` match the movement
  and headway structure closely.
- **OR-Tools CP-SAT** as the open-source CP alternative. All event times must be
  scaled to exact integers, and the experiment must account for the resulting
  time discretization or common time unit.

The first prototype must exclude integrated passenger routing. Give it the
same movement horizon, cabins, route alternatives, waiting rules, and physical
headways as the reference movement model. Compare feasibility, movement
objective proxies, runtime, memory, and the largest solvable network.

Continue beyond the prototype only if CP solves at least one planned network
size that the movement-only MILP cannot solve within the same resource limit,
or improves time or peak memory by roughly a factor of three without changing
the modeled semantics. Otherwise retain the result as a documented negative
experiment and continue with the Gurobi decomposition roadmap.

### SCIP and GCG Research Backend

Use SCIP, optionally with GCG, only when custom decomposition becomes the
research focus. It is suitable for:

- user-defined Benders or logic-based cuts;
- branch-and-price and path-based passenger columns;
- delayed constraint generation inside a solver framework;
- inspecting decomposable block structure.

Do not port the complete integrated model merely to compare generic MIP
performance with Gurobi. Start from the fixed-movement passenger evaluator or
another subproblem whose decomposition structure has already been measured.

### Heuristic Backend

Hexaly can be evaluated for large approximate movement or integrated planning
when obtaining strong incumbents matters more than certified optimality. Any
solution must be checked by the existing validators and, where required,
repaired or certified by the exact backend. Do not compare a heuristic
incumbent directly with a Gurobi optimality gap as if both reported the same
guarantee.

### Railway Frameworks and Industrial Tools

LinTim is useful as a railway-optimization reference architecture and source
of established periodic event-scheduling formulations, but it is not a solver
replacement for the current ropeway model. Viriato, RailSys, and OpenTrack are
planning or simulation environments rather than suitable research backends for
custom stop/skip decomposition. Use them only for methodological comparison or
external validation if that later becomes necessary.

## Evaluation Order

1. Establish the scaling ladder around the selected production baseline; do
   not require speculative structural phases first.
2. Run integrated, movement-only, and fixed-movement passenger diagnostics
   with the implemented Phase-0 runner.
3. If movement/headways dominate, test safe fixed precedence before delayed
   generation or a movement-only CP prototype.
4. Run the decomposition-boundary diagnostic before selecting a master and
   subproblem split.
5. If incumbent search remains limiting beyond the implemented
   passenger-optimized all-stop start, benchmark multiple structural starts
   and same-artifact progressive waiting independently.
6. If coupling dominates, test neighborhood search before a complex exact
   decomposition.
7. Attempt only the Benders variant justified by the measured fixed-schedule
   and fixed-structure subproblems; do not default to classical LP Benders.
8. Evaluate SCIP/GCG or Hexaly only after identifying a concrete decomposition
   or large-scale heuristic role.
9. Combine successful components only after each independently agrees with the
   integrated reference on exact small instances.
10. Run the skip-benefit campaign with equal service conditions and report
    certified benefit intervals wherever the available bounds permit them.

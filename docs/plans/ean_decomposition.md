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

The three-case diagnostic runner and callback metrics are implemented. The
remaining Phase-0 work is to execute and interpret the controlled scaling
ladder.

Create a scaling ladder with increasing station count, demand, and cabin
density. For every level, measure the same resource-limited cases:

```text
integrated movement and passenger model
movement and headways without passenger assignment
passenger optimization for a fixed movement plan
```

For the initial diagnostic, obtain the fixed-movement case by fixing movement
variables through the canonical `EanMovementModel` inside the integrated
passenger model. Use the movement plan extracted from the integrated run and
disable the all-stop MIP start for this case. Replace that diagnostic with the
independent Phase 1 evaluator once it exists.

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
machine-readable result containing all three cases for an example and solver
budget. Existing passenger benchmark and frontend JSON contracts remain
unchanged.

Use the measurements to select the next branch:

- if movement-only is already difficult, first test safe same-cabin precedence
  and conservative pair classification from `ean_formulation_and_search.md`,
  then consider shared precedence, delayed headways, or the CP prototype;
- if fixed-movement passenger assignment is difficult, prioritize the
  passenger evaluator and its exact solution method;
- if both isolated models are easy but the integrated model is difficult,
  prioritize coupling methods such as neighborhood search or logic-based
  decomposition;
- if Python construction or artifact memory dominates, optimize materialization
  before changing the mathematical algorithm.

Maintain tiny production-path instances that solve to proven optimality. Every
later exact method must agree with these instances before a scaling benchmark
is interpreted.

## Phase 1: Fixed-Movement Passenger Evaluator

Build a destination-layered event-expanded passenger model for a fixed movement
and timing plan.

The network should contain demand sources, station waiting events, boarding,
cabin-interval ride arcs, alighting, destination sinks, and an unserved option.
Destination layers preserve OD identity and share cabin capacities:

```text
sum(flow on cabin interval over all destinations) <= cabin capacity
```

The shared capacities make this a multi-commodity model. Its continuous LP is
not automatically integral.

Record:

- model size and runtime;
- whether every flow is integral;
- fractional arcs and paths;
- flow-to-path decomposition size;
- objective agreement with the integrated model for the same fixed movement.

This evaluator is the common prerequisite for Benders, passenger repair,
movement-only CP, large-neighborhood search, and scalable skip-benefit
experiments. Build it before committing to any one decomposition algorithm.

## Phase 2: Exact Passenger Certification

If the LP is fractional, solve an exact restricted integer repair over active
arcs or decomposed paths. Treat a repaired solution as exact only when it is
feasible for the complete fixed-movement passenger assignment problem.

If restricted repair is insufficient, evaluate path-based column generation
and then branch-and-price only if exact integer assignment remains a bottleneck.
The LP may still serve as a lower bound, diagnostic, or MIP-start generator.

Use the following gate:

- if the LP is consistently integral and objective-equivalent, classical
  LP-based decomposition becomes a candidate;
- if the LP is fractional but exact repair is fast, retain the LP as a bound
  and use repair for incumbents;
- if the exact fixed-movement passenger problem is itself difficult, improve
  its path or column representation before attempting integrated Benders.

## Phase 3: Progressive Wait Search

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

## Phase 4: Delayed Exit-Switch Headways

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

## Phase 5: Neighborhood Matheuristics

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

## Phase 6: Conditional Decomposed Exact Search

Represent movement, timing, stop/skip, and waiting decisions in a master and
evaluate passenger cost in the fixed-movement subproblem. Do not assume that
this automatically yields useful Benders cuts: stop/skip decisions change
candidate availability and costs, and shared capacities make the passenger
problem multi-commodity.

Choose the method from the Phase 1 and 2 evidence:

- attempt classical LP Benders only if the relevant passenger LP is integral
  and its dual information yields valid cuts for the chosen master;
- use branch-and-Benders when an LP subproblem supplies valid bounds but
  integrality must be recovered inside the search;
- use logic-based Benders when the passenger subproblem remains genuinely
  integer;
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
4. If passenger assignment dominates, build the fixed-movement evaluator,
   measure LP integrality, and add exact repair only when needed.
5. If incumbent search remains limiting beyond the implemented
   passenger-optimized all-stop start, benchmark multiple structural starts
   and same-artifact progressive waiting independently.
6. If coupling dominates, test neighborhood search before a complex exact
   decomposition.
7. Attempt only the Benders variant justified by the measured passenger
   subproblem; do not default to classical LP Benders.
8. Evaluate SCIP/GCG or Hexaly only after identifying a concrete decomposition
   or large-scale heuristic role.
9. Combine successful components only after each independently agrees with the
   integrated reference on exact small instances.
10. Run the skip-benefit campaign with equal service conditions and report
    certified benefit intervals wherever the available bounds permit them.

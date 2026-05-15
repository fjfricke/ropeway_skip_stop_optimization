# EAN Decomposition and Constraint Generation Concepts

Status: **concept**

## Goal

Collect decomposition-style ideas for improving the continuous EAN passenger
optimizer without giving up exactness.

The current integrated MILP solves these decisions together:

```text
cabin movement
stop/skip decisions
event timing
station/platform constraints
rope and switch headways
passenger routing
passenger waiting/journey objective
capacity constraints
```

This is exact but large. The concepts below explore whether some structure can
be handled outside the initial eager model:

```text
Concept 1: passenger-flow subproblem and possible Benders cuts
Concept 2: delayed exit-switch headway constraint generation
Combined concept: delayed headways plus passenger-flow/Benders
```

These are research/architecture concepts. The current integrated MILP remains
the reference implementation until a concept is validated against it.

## Concept 1: Passenger Flow and Benders

### Core Idea

Split movement decisions from passenger assignment.

```text
Master problem:
  decides movement, stop/skip, timing, and physical feasibility

Passenger subproblem:
  takes a fixed master solution and assigns passengers optimally
```

The master objective uses an auxiliary variable:

```text
min movement_cost(y) + theta
```

Where:

```text
y      = movement, stop/skip, timing decisions
theta  = lower approximation of passenger_cost(y)
```

For the current waiting-time and journey-time objectives, `movement_cost(y)` is
usually zero, so the master is effectively minimizing `theta`.

The passenger subproblem computes:

```text
Q(y) = minimum passenger cost for the fixed movement plan y
```

Benders cuts then force:

```text
theta >= valid lower bounds on Q(y)
```

### Why It Could Help

The passenger assignment for a fixed movement plan is much more structured than
the full stop/skip/timing problem. If we can model it as a continuous
event-expanded flow LP, Gurobi can solve it without passenger-slot binaries.

Potential benefits:

```text
fewer binaries in the main search
faster evaluation of fixed movement plans
clean separation between physical movement and passenger assignment
access to LP dual values for Benders optimality cuts
better route-based diagnostics and metadata
possible MIP-start or incumbent-repair support for the current MILP
```

### Passenger Subproblem Shape

The passenger subproblem should be an event-expanded passenger flow LP.

Nodes represent passenger-relevant events:

```text
release event
station/platform waiting event
board event
onboard/cabin segment event
alight event
destination sink
unserved sink
```

Arcs represent allowed passenger movement:

```text
wait arcs
board arcs
ride arcs
alight arcs
served sink arcs
unserved penalty arcs
```

The model is continuous:

```text
0 <= flow_arc <= arc_capacity
flow balance at each node
shared physical capacity constraints
min sum(cost_arc * flow_arc)
```

### Not a Pure Min-Cost-Flow Problem

The fixed-movement passenger assignment is not automatically a standard
single-commodity min-cost-flow problem because passengers have OD identities:

```text
A -> D
B -> E
C -> A
```

A single unlabeled flow can ensure that the correct total amount enters and
leaves the network, but it cannot ensure that passengers starting at `A` end at
`D`.

To preserve OD semantics, we need one of these structures:

```text
one layer per OD group
one layer per destination
another state-expanded encoding of passenger labels
```

Those layers share the same physical cabin capacities:

```text
sum(flow on physical cabin arc over all layers) <= cabin_capacity
```

That coupling makes the subproblem more general than a plain single-commodity
min-cost-flow, even though it remains flow-like.

### Always-Feasible Subproblem

The decomposed subproblem should preserve the current "always evaluable"
semantics by allowing unserved passengers with a high penalty.

Each demand group gets an unserved option:

```text
OD source -> unserved sink
```

This means:

```text
every master solution can be evaluated
no feasibility cuts are needed initially
only optimality cuts are needed
```

The penalty should be horizon-based rather than arbitrarily huge:

```text
unserved_penalty ~= horizon_seconds * penalty_factor
```

### Objective Split

For waiting-time objective:

```text
cost on wait arcs
or equivalent cost on board/sink arcs derived from board_time - release_time
```

For journey-time objective:

```text
cost from release to arrival
or equivalent cost on served sink arcs derived from alight_time - release_time
```

For unserved passengers:

```text
cost = unserved_penalty
```

The decomposed objective is:

```text
min_y movement_cost(y) + Q(y)
```

Implemented in the master as:

```text
min_y movement_cost(y) + theta
theta >= Benders cuts approximating Q(y)
```

### Cut Types

Initial logic-based cut:

```text
if y == y_k:
  theta >= Q(y_k)
```

This is valid but weak. It is useful for a first prototype because it does not
require deriving a full dual expression.

Classical Benders optimality cut:

```text
min c(y)^T f

s.t.
  A f = b
  B f <= u(y)
  f >= 0
```

The dual solution can produce a stronger cut:

```text
theta >= dual_balance_terms
       + dual_capacity_terms depending on u(y)
       + possible objective/timing terms
```

Timing-dependent objectives are the hard part. Passenger costs can depend on
master event times:

```text
board_time - release_time
alight_time - release_time
wait duration
journey duration
```

The first prototype should therefore fix a full movement and timing plan, solve
the passenger LP, and validate it before attempting strong timing-sensitive
Benders cuts.

### Solver Strategy

Use direct `gurobipy` first, not `gurobi-optimods`, for the project core.

Reasons:

```text
we already depend on gurobipy
we need model status, runtime, bounds, and dual values
we need control over parameters such as NetworkAlg
we may need shared capacity constraints beyond pure min-cost-flow
we should keep solver metadata aligned with the existing EAN optimizer
```

`gurobi-optimods` remains useful as a reference implementation for plain
min-cost-flow, but its high-level API does not expose enough model internals for
Benders work.

### Roadmap

```text
1. Build fixed-movement passenger flow LP as a separate module.
2. Validate against the current MILP on fixed movement solutions.
3. Benchmark fixed-movement passenger assignment runtime.
4. Use as evaluator, diagnostic tool, or MIP-start helper.
5. Only then prototype Benders cuts.
```

Likely module:

```text
src/ropeway_skip_stop_optimization/optimization/ean/flow/
```

## Concept 2: Delayed Exit-Switch Headway Generation

### Core Idea

Reduce the initial EAN passenger MILP size by generating selected rope headway
constraints only when they are actually violated.

The first target is:

```text
exit-switch merge headway constraints on rope resources
```

These are conflicts where two paths join into one shared resource. The main
operational bottleneck is expected to be at stations/platforms, not on the rope.
If an exit-switch conflict appears, the model should normally resolve it by
shifting timing or waiting upstream.

This is not Benders decomposition. It is delayed row generation for a subset of
physical headway constraints.

### Keep Eager

The relaxed master should still include the constraints that shape core
operation:

```text
station/platform headways
boarding and alighting feasibility
service and skip timing
passenger assignment and capacity constraints
event ordering along each cabin path
fixed starts and horizon logic
```

Keeping these eager prevents the master from finding unrealistically good
solutions that ignore primary station bottlenecks.

### Delay Initially

The first experiment should omit only:

```text
exit-switch merge headway constraints
```

The missing rule is:

```text
two active traversals using the same merge/exit-switch resource
must be separated by at least the configured headway
```

### Exactness Condition

The delayed approach is exact only if the solve loop terminates with no delayed
headway violation remaining.

```text
solve relaxed model
detect violated exit-switch headways
add exact missing constraints
repeat
stop only when no violation remains
```

During intermediate iterations, Gurobi's reported MIP gap applies only to the
currently generated relaxation. It must not be reported as the full-model gap
until no delayed violations remain.

### Proposed Solve Loop

Use an external solve loop first, not a Gurobi lazy callback.

Reason:

```text
headway disjunctions usually need an ordering binary per conflict pair
new variables are awkward or impossible to add safely in a lazy callback
an external loop can add both the ordering variable and its constraints
```

Algorithm:

```text
1. Build the EAN passenger model without delayed exit-switch headways.
2. Solve the model with the selected solver policy.
3. Inspect the incumbent solution.
4. For each exit-switch merge resource:
     collect active traversal events
     sort by traversal time
     find pairs closer than required headway
5. Add the exact disjunctive headway block for each violated pair.
6. Re-solve the same model.
7. Repeat until no delayed violation remains or a configured iteration/time
   limit is reached.
```

The exact disjunction for a violated pair is the same semantics as in the eager
model:

```text
event_a before event_b:
  time_a + headway <= time_b

or

event_b before event_a:
  time_b + headway <= time_a
```

with an ordering binary deciding which side is active.

### Violation Detection

For each delayed resource:

```text
active_events = events with their activation variable close to 1
sort active_events by traversal time
check neighboring events for headway violations
```

For one-dimensional separation on a shared resource, checking neighbors after
sorting is enough to find violations in an integer incumbent.

Required metadata per delayed candidate:

```text
resource_id
event_a / event_b identifiers
activation variable references
time variable references
required headway seconds
existing eager/delayed status
```

### Logging and Diagnostics

Every delayed-headway iteration should log:

```text
iteration index
solver status
objective
best bound
MIP gap for the current relaxation
number of delayed violations found
number of delayed constraints added
number of delayed ordering binaries added
max violation seconds
resource ids with the most violations
```

Exported metadata should distinguish:

```text
relaxed_gap
full_model_verified_gap
delayed_headway_iterations
delayed_headway_constraints_added
delayed_headway_max_violation_seconds
full_headway_verified
```

### Roadmap

```text
1. Add headway constraint family accounting.
2. Classify resources as station, platform, rope segment, exit-switch merge,
   or other.
3. Add optimizer option delayed_headways = none | exit_switch_merge.
4. Implement independent violation detector.
5. Add external solve/detect/add loop.
6. Benchmark against the eager full model.
```

## Combined Concept: Delayed Headways plus Passenger Flow

### Core Idea

The two concepts can be combined because they affect different parts of the
model:

```text
Delayed exit-switch headways:
  delay selected physical headway constraints in the movement model

Passenger-flow/Benders:
  move passenger assignment cost into a fixed-movement subproblem
```

Combined architecture:

```text
Master:
  movement, stop/skip, timing
  station/platform constraints eager
  exit-switch headways delayed
  theta for passenger cost

Subproblem A:
  delayed exit-switch verifier
  finds violated rope/merge headways
  adds missing headway constraints

Subproblem B:
  passenger flow LP
  evaluates passenger_cost(y)
  adds Benders optimality cuts for theta
```

### Iteration Order

Prefer checking delayed headways before solving the passenger-flow subproblem.

```text
1. Solve master relaxation.
2. Check delayed exit-switch headways.
3. If violated:
     add headway constraints
     re-solve master
4. If headways are verified:
     solve passenger-flow subproblem.
5. Add passenger optimality cuts.
6. Repeat until headways are verified, passenger cuts are satisfied, and the
   target gap/optimality condition is reached.
```

Reason:

```text
Passenger-flow costs for a physically invalid movement plan are usually less
useful because the plan will be cut off by headway constraints anyway.
```

It is possible to evaluate passenger flow for invalid movement plans for
diagnostics or caching, but the first exact algorithm should avoid mixing
physical infeasibility and passenger-cost information.

### What This Becomes

The combined approach is a branch-and-cut/Benders hybrid:

```text
delayed physical constraint generation
+ Benders-style passenger optimality cuts
+ master MILP
```

It is legitimate, but gap reporting becomes more delicate.

### Certification Requirements

A final solution is fully certified only if:

```text
all eager master constraints are satisfied
no delayed exit-switch headway violation remains
the final movement plan has been passenger-flow evaluated
theta is tight enough under the generated passenger cuts
the reported MIP gap refers to the fully generated model state
```

Intermediate logs must distinguish:

```text
relaxed master bound
headway-verified incumbent
passenger-evaluated incumbent
full verified gap
```

### Recommended Roadmap

Do not implement the combined concept first. Validate the parts separately.

```text
Phase 1:
  Delayed exit-switch headways alone.
  This is closest to the current integrated MILP.

Phase 2:
  Fixed-movement passenger flow LP alone.
  This validates passenger semantics and runtime.

Phase 3:
  Use passenger flow as evaluator, diagnostic tool, or MIP-start helper.

Phase 4:
  Combine delayed headways and passenger-flow/Benders only if both individual
  components show value.
```

Reason:

```text
If the combined experiment is slow, it would be unclear whether the bottleneck
is weak headway generation, weak passenger cuts, slow flow LPs, or an overly
optimistic master relaxation.
```

## Shared Decision Criteria

Continue with a concept only if it preserves exactness and improves at least
one meaningful benchmark dimension:

```text
model build time
initial variable/constraint count
root relaxation time
time to first useful incumbent
time to verified 10% gap
best verified incumbent under a fixed time budget
quality of exported diagnostics
```

Small examples must match the current eager integrated MILP before any concept
is used for larger benchmarks.

## Main Risks

Weak cuts:

```text
Logic-based passenger cuts or delayed headway cuts may require many iterations.
```

Confusing gaps:

```text
Relaxed-model gaps are not full-model gaps until all delayed constraints and
passenger cuts needed for certification are present.
```

Subproblem complexity:

```text
Passenger assignment is not pure single-commodity min-cost-flow because OD
identity and shared cabin capacities interact.
```

Implementation size:

```text
Both concepts require careful metadata and tests to avoid diverging from the
current integrated MILP semantics.
```

## Concept 3: Progressive Wait plus Delayed Cuts

### Core Idea

Use a no-wait or limited-wait model only as a warm-start generator, then solve
the full-wait problem with delayed headway generation and, later, passenger-flow
Benders cuts.

This concept separates three roles:

```text
progressive wait:
  creates good incumbent starts

delayed headway generation:
  adds selected physical headway constraints only when violated

passenger-flow/Benders:
  evaluates or approximates passenger assignment cost for fixed movement plans
```

The no-wait stage must not permanently fix orderings or constraints in the
full-wait model. It only provides start values for compatible variables.

### Motivation

Waiting makes many ordering relations decision-dependent. A static
preprocessing classifier can therefore become conservative quickly, because a
pair that is fixed in the no-wait model may become invertible once station
waiting is allowed.

A progressive solve keeps the useful part of the no-wait model:

```text
good stop/skip pattern
reasonable event times
reasonable passenger assignment
reasonable initial ordering values
```

but restores the complete full-wait feasible region before certification.

### Phase 0: No-Wait Warm Start

Build and solve a restricted model:

```text
wait variables fixed to zero, or no-wait station mode
station/platform headways eager
passenger assignment integrated or approximated
target gap/time limit chosen for fast incumbent generation
```

Export only start values that remain meaningful in the full-wait model:

```text
stop/skip variables
event-time variables
passenger assignment variables when ids are compatible
order variables derived from the resulting event times
```

Do not export no-wait-specific fixed-order assumptions as constraints.

### Phase 1: Full-Wait Master with Delayed Headways

Build the full-wait movement/passenger model:

```text
wait variables enabled
wait-specific platform-exit headway resources enabled
station/platform headways eager
selected exit-switch or rope-merge headways delayed
```

Load the Phase 0 solution as a partial MIP start:

```text
set compatible stop/skip starts
set compatible event-time starts
set compatible passenger assignment starts
set wait starts to zero
set order starts from the Phase 0 event-time order where possible
ignore variables that do not exist in both models
```

Then solve with an external delayed-headway loop:

```text
1. solve current full-wait model
2. inspect the incumbent movement plan
3. detect delayed exit-switch or rope-merge headway violations
4. add exact missing headway disjunctions for violated pairs
5. re-solve
6. stop only when no delayed headway violation remains
```

This phase is exact only after all delayed headway violations are eliminated.
Intermediate MIP gaps refer to the current relaxation, not to the fully verified
model.

### Phase 2: Passenger Flow or Final Integrated Proof

There are two possible certification paths.

Pragmatic path:

```text
use the headway-verified full-wait incumbent as a MIP start
solve the complete integrated MILP with all required constraints
report the final Gurobi gap only for this full model
```

Decomposition path:

```text
master keeps movement, stop/skip, timing, wait, and generated headways
passenger-flow subproblem evaluates Q(y)
theta represents passenger cost in the master
passenger optimality cuts tighten theta
```

The decomposition path should check delayed headways before passenger flow:

```text
1. solve master
2. verify delayed headways
3. if violated, add headway constraints and re-solve
4. if physically verified, solve passenger-flow subproblem
5. add passenger optimality cuts
6. repeat until both physical constraints and passenger cuts are satisfied
```

Passenger-flow costs for physically invalid movement plans are less useful,
because such plans will be removed by delayed headway constraints anyway.

### Exactness Conditions

The final solution is certified for the full-wait problem only if:

```text
full-wait variables and constraints are active
no delayed headway violation remains
all generated headway disjunctions are included
passenger assignment is either integrated or passenger-flow cuts make theta tight
the reported bound/gap belongs to the final generated model state
```

Phase 0 alone does not provide a valid bound for the full-wait problem. It is a
warm-start heuristic.

### Bound Monotonicity with Wait Limits

For a minimization objective, increasing the maximum allowed waiting time
expands the feasible set:

```text
W_i < W_j  =>  F(W_i) subset F(W_j)
```

Therefore the true optimal objective is monotone nonincreasing:

```text
z*(W_j) <= z*(W_i)
```

A feasible solution from the smaller-wait model remains feasible for the
larger-wait model. It can therefore be used as a MIP start and provides a valid
incumbent upper bound for the larger-wait model.

The opposite is not true for lower bounds. A solver lower bound obtained for
the smaller-wait model is not automatically a valid lower bound for the
larger-wait model, because the larger-wait optimum may be lower. Progressive
wait primarily helps with incumbents and warm starts, not with certifying the
final lower bound of the full-wait problem.

### Upper-Bound and Lower-Bound Roles

The progressive workflow should keep the roles of incumbents and cuts separate.

Progressive wait mainly improves the primal side:

```text
restricted wait solve -> feasible solution for larger wait model
                     -> MIP start
                     -> incumbent upper bound
```

If Gurobi accepts the MIP start, an additional objective upper-bound constraint
is usually unnecessary. The incumbent already gives the solver a valid upper
bound and a complete solution structure.

Lower bounds for the full-wait problem must come from the formulation and cuts:

```text
LP relaxation of the current model
Gurobi cuts
slot-time relaxation strengthening
tight Big-M bounds
Benders passenger optimality cuts
generated delayed headway constraints
other valid inequalities
```

In the Benders variant, passenger cuts are lower-bound cuts on the passenger
cost approximation:

```text
theta >= valid lower approximation of Q(y)
```

They prevent the master from assigning an unrealistically low passenger cost to
movement plans. This strengthens the master lower bound.

Delayed headway constraints also tighten the relaxation once generated, but
their bound is only a bound for the currently generated model. A reported gap is
meaningful for the full problem only after the delayed headway verifier finds no
remaining violations.

The intended division is:

```text
progressive wait and MIP starts -> better upper bounds
strengthening and cuts          -> better lower bounds
final certification             -> both bounds on the verified full model
```

### Implementation Notes

Prefer an external solve loop before callbacks.

Reasons:

```text
delayed headway violations may need new ordering binaries
adding variables inside callbacks is awkward and solver-restricted
an external loop keeps model mutation explicit and easier to test
partial MIP starts can be rebuilt between iterations
```

The MIP-start loader should be tolerant:

```text
set values only for variables that exist in the current model
ignore missing variables from the no-wait model
initialize new wait and platform-exit variables conservatively
log loaded, skipped, and rejected start values
```

### Suggested Roadmap

```text
1. Implement no-wait -> full-wait partial MIP-start transfer.
2. Benchmark full-wait solves with and without the no-wait warm start.
3. Add delayed exit-switch headway generation without passenger-flow Benders.
4. Validate that delayed-headway final solutions match the eager model on small
   instances.
5. Build fixed-movement passenger-flow LP as an evaluator.
6. Only then combine delayed headways with passenger-flow/Benders cuts.
```

### Main Risks

MIP-start incompatibility:

```text
No-wait and full-wait artifacts can contain different headway checkpoints,
pairs, and variables. The transfer must be partial and name/id based.
```

Weak relaxed iterations:

```text
If too many headway constraints are delayed, the master may find unrealistically
good but physically invalid incumbents and require many iterations.
```

Misleading progress metrics:

```text
The no-wait objective, relaxed delayed-headway gap, and final full-wait gap are
not the same quantity and must be reported separately.
```

### Progressive Wait-Cap Selection Rules

The progressive wait workflow needs a rule for selecting the next waiting cap
\(W_{k+1}\) after solving a stage with cap \(W_k\). The rules below are ordered
from simplest to most structure-aware.

All rules are heuristic stage-selection policies. Exactness comes only from the
final full-wait solve.

#### Rule A: Fixed Geometric Schedule

Use a short, predetermined sequence:

```text
0s -> 30s -> 120s -> full
```

or a finer sequence:

```text
0s -> 15s -> 30s -> 60s -> 120s -> full
```

Derivation:

```text
small caps change the feasible ordering structure strongly
large caps mostly add escape room for difficult local conflicts
geometric growth reaches the full model quickly without too many stages
```

This rule is easy to debug and gives reproducible benchmark stages. It is not
instance-aware.

#### Rule B: Headway-Scaled Schedule

Choose caps from station headway scales:

```text
0
h_station
2 * h_station
4 * h_station
full
```

where `h_station` can be the maximum or a robust representative station
headway in the instance.

Derivation:

```text
waiting below one station headway mostly repairs local timing
waiting around two to four headways allows limited local reordering
larger waits should be left to the final full-wait model
```

This is more physical than fixed seconds and transfers better across instances
with different station speeds or cabin spacing requirements.

#### Rule C: Result-Adaptive Schedule

After solving a stage with cap \(W_k\), inspect how the cap was used.

Useful metrics:

```text
max_used_wait
p95_used_wait
share_wait_at_cap
objective_improvement_from_previous_stage
delayed_headway_violations
delayed_headway_constraints_added
accepted_mip_start_quality
```

Example rule:

```text
if W_k == 0:
    W_{k+1} = 30s
elif share_wait_at_cap > 10%:
    W_{k+1} = min(2 * W_k, full)
elif p95_used_wait > 0.7 * W_k:
    W_{k+1} = min(2 * W_k, full)
elif objective_improvement_from_previous_stage > 2%:
    W_{k+1} = min(2 * W_k, full)
else:
    W_{k+1} = full
```

Derivation:

```text
if many waits hit the cap, the current cap is probably binding
if the objective still improves substantially, extra wait is likely useful
if the cap is rarely used and improvement is small, intermediate stages are
less likely to produce a better incumbent
```

This rule adapts to demand and headway tightness. It controls incumbent
generation, but it does not directly control model complexity.

#### Rule D: Complexity-Budget Schedule

Select the next cap by estimated growth in headway-ordering complexity.

Let \(\eta\) index headway resources and let \(P_\eta(W)\) be the set of
checkpoint candidates that can be relevant at resource \(\eta\) under wait cap
\(W\). A conservative pair-count proxy is:

```text
H_pair(W) = sum_eta binom(|P_eta(W)|, 2)
```

If a headway-pair classifier exists, use the more relevant count:

```text
H_var(W) = number of variable-order headway pairs under wait cap W
```

`H_var(W)` is a better proxy because fixed-order pairs do not require ordering
binaries.

Choose the largest candidate cap whose estimated growth stays within a budget:

```text
W_{k+1} = max { W > W_k :
                H_var(W) <= alpha * H_var(W_k) + beta }
```

Fallback when no classifier exists:

```text
W_{k+1} = max { W > W_k :
                H_pair(W) <= alpha * H_pair(W_k) + beta }
```

Example parameters:

```text
alpha = 1.5
beta  = 25,000 variable-order pairs
```

Derivation:

```text
headway ordering is a main MILP complexity driver
each variable-order headway pair usually adds one binary ordering variable
and two disjunctive timing constraints
larger wait caps widen time windows and make more order inversions possible
therefore wait caps can be interpreted as controlled expansion of the
headway-ordering search space
```

The monotonic relationship is conceptual:

```text
W_i < W_j  =>  feasible set expands
larger W can make more headway pairs potentially relevant or variable
```

The actual Gurobi runtime is not guaranteed to be monotone in this proxy.
Presolve, heuristics, and branching can make a larger model solve faster in
individual cases. The proxy is still useful because it tracks an explicit
source of binary decisions.

#### Rule E: Combined Result and Complexity Schedule

Use complexity as a hard budget and result metrics as a reason to spend more or
less of that budget.

Example:

```text
candidate_grid = [0, 10, 20, 30, 45, 60, 90, 120, 180, full]

if share_wait_at_cap > 10% or objective_improvement > 2%:
    alpha = 2.0
else:
    alpha = 1.3

choose largest W in candidate_grid with:
    H_var(W) <= alpha * H_var(W_k) + beta

if no intermediate W satisfies the rule:
    go to full
```

Derivation:

```text
result metrics indicate whether more wait is operationally useful
complexity metrics limit how much additional ordering search space is opened
the final full-wait stage still restores the complete feasible region
```

This is the preferred research variant once a cheap headway-metadata estimator
or pair classifier exists.

#### Required Estimator

The complexity-budget rules require an estimator that is much cheaper than a
full MILP solve.

Minimum estimator:

```text
build EAN headway metadata for candidate W
count checkpoints, candidates, and all headway pairs
do not build the Gurobi model
```

Improved estimator:

```text
run conservative headway-pair classifier
count fixed-order, variable-order, and redundant pairs
estimate ordering binaries from variable-order pairs
```

Diagnostics to log per candidate \(W\):

```text
wait_cap_seconds
headway_candidates
headway_pairs_total
headway_pairs_fixed
headway_pairs_variable
headway_pairs_redundant
estimated_ordering_binaries
estimated_added_ordering_binaries
selected_next_wait_cap
selection_rule
```

#### Recommendation

Implement progressively:

```text
1. fixed geometric schedule for debugging
2. result-adaptive rule using actual wait usage
3. complexity-budget rule once pair classification or metadata estimation is
   available
4. combined result-and-complexity rule for benchmarks
```

The full-wait final stage is mandatory in every schedule if the result is meant
to certify the original model.

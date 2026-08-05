# CP-SAT Feasibility Gate before Passenger Row-and-Column Optimization

Status: **research idea and staged prototype plan**

## Decision Summary

Evaluate a two-solver architecture for a fixed cabin count \(K\):

```text
complete CP-SAT movement feasibility
    |
    +-- INFEASIBLE: certify that K is movement-infeasible
    |
    +-- UNKNOWN: retain an open certificate and optionally continue with Gurobi
    |
    `-- FEASIBLE:
          solve passenger assignment on the fixed CP-SAT movement
          use both solutions as a valid incumbent and warm start
          optimize passengers with Gurobi and exact merge row-and-column generation
```

CP-SAT is not called inside every row-and-column round. It first solves the
complete movement-feasibility problem, including all headways, for one fixed
\(K\). Gurobi is used afterward only to improve the passenger objective over
all movement plans for that already known feasible \(K\).

The proposal has two distinct purposes:

1. avoid the potentially long row-and-column infeasibility tail at
   \(K_{\max}+1\);
2. provide the integrated passenger MILP with a fully valid movement and
   passenger incumbent before optimization starts.

This plan complements
`ean_fixed_k_delayed_merge_headways.md`; it does not replace its exact
row-and-column algorithm.

## Motivation

The delayed-merge experiment indicates that conflict sparsity can make
row-and-column generation very effective for feasible schedules. In the
Five-Station diagnostic, the merge-relaxed solution violated only a tiny
fraction of the omitted pair universe.

The asymmetry appears at an infeasible cabin count. Let

\[
  \mathcal F_0(K)
  \supseteq
  \mathcal F_1(K)
  \supseteq
  \cdots
  \supseteq
  \mathcal F_{\mathrm{full}}(K)
\]

be the successive row-and-column relaxations. For \(K>K_{\max}\),

\[
  \mathcal F_{\mathrm{full}}(K)=\varnothing,
\]

but many intermediate relaxations may remain feasible. The outer algorithm
can therefore discover different invalid merge orders over many re-solves and
approach the eager model before proving infeasibility.

A complete CP-SAT scheduling model attacks the decision problem directly:

\[
  \text{Does any physically valid movement plan exist for this fixed }K?
\]

It can represent shared resources through global scheduling constraints
instead of explicitly materializing every pairwise Big-\(M\) disjunction.
This does not remove NP-hardness, but it may provide substantially stronger
propagation for dense feasible and infeasible resource schedules.

## Scope

The first prototype includes:

- exactly \(K\) active cabins;
- fixed initial placement;
- deterministic current line and ring circulation patterns;
- Stop and Skip alternatives;
- station Waiting;
- the complete finite movement horizon;
- every current movement, activation, timing, platform, rope, merge, and
  horizon constraint;
- complete extraction into the existing movement-plan representation;
- validation by the existing independent movement and headway validators.

The first prototype excludes:

- Passenger Assignment inside CP-SAT;
- passenger-dependent service requirements;
- optimized initial placement;
- variable cabin count inside one CP-SAT solve;
- dynamic turnbacks, rope transfers, or depot routing;
- claims about continuous-time exactness before the timing-grid proof is
  complete;
- replacement of the integrated Gurobi passenger optimizer.

Passenger demand does not belong in the feasibility gate as long as unserved
passengers remain allowed. The gate certifies physical movement feasibility,
not passenger-service quality.

## Complete CP-SAT Movement Model

### Time representation

Choose a common exact time unit \(\Delta\). Every input duration, headway,
bound, release time, and horizon value must satisfy

\[
  q/\Delta\in\mathbb Z.
\]

CP-SAT then uses integer event times

\[
  T_{cv}=t_{cv}/\Delta.
\]

Before calling the formulation exact, prove that the current temporal model
has the integer-time property after scaling. For a fixed selection of
activities and resource orders, the current movement model is expected to
reduce predominantly to difference constraints with integer right-hand
sides. If any constraint breaks this property, either choose an exact common
denominator or classify the first prototype as grid-feasible rather than
continuous-time exact.

### Movement precedence

For every active movement transition \((u,v)\),

\[
  T_{cv}-T_{cu}\geq \tau_{cuv}.
\]

Conditional Stop, Skip, activation, horizon, and Waiting semantics use
enforced linear constraints with the same logical meaning as the reference
EAN model.

### Optional Stop and Skip activities

Every visit contains the same exclusive route choice as the reference model:

\[
  z^{\mathrm{stop}}_{cv}
  +
  z^{\mathrm{skip}}_{cv}
  =
  a_{cv}.
\]

The selected activity activates its corresponding timing transitions and
resource usages. Inactive activities have canonical times or are omitted
where CP-SAT optional intervals make this safe.

### Point-headway resources

For an active candidate \(i\) using resource \(r\) with symmetric headway
\(h_r\), introduce an optional interval

\[
  I_{ir}
  =
  [T_{ir},T_{ir}+h_r).
\]

All active intervals of one physical resource participate in

\[
  \operatorname{NoOverlap}(I_{ir}:i\in C_r).
\]

For two active candidates this is equivalent to the disjunction

\[
  T_{ir}+h_r\leq T_{jr}
  \quad\lor\quad
  T_{jr}+h_r\leq T_{ir}.
\]

This representation is suitable for current symmetric point headways.
Sequence-dependent, asymmetric, entry/clearance, or candidate-specific
headways require an explicit equivalence proof or a different CP
representation.

### Platform and Waiting occupancy

Represent a platform occupation by its actual active interval, including
Waiting where required:

\[
  I^{\mathrm{platform}}_{cv}
  =
  [T^{\mathrm{entry}}_{cv},T^{\mathrm{clear}}_{cv}).
\]

Use `NoOverlap` for capacity one or `Cumulative` for a proven larger physical
capacity. Preserve the current distinction between point separation and
resource occupancy; do not approximate both with one interval type.

### Merge resources

Service and Skip candidates that reconverge on the same physical resource
must enter one common CP-SAT resource constraint. Optional presence is tied to
the same route activation used by the EAN. The CP model must not reproduce the
current checkpoint-kind shortcut if the canonical network provides stronger
resource provenance.

### Initial and horizon semantics

The CP model must reproduce:

- every supplied fixed start;
- initial rope and station occupancy;
- events already active at \(t=0\);
- all candidate and pair horizon filters;
- the same safety margin and terminal treatment as the EAN artifact.

A schedule is not accepted merely because all intervals inside the horizon
are nonoverlapping. Boundary-spanning resource occupations and all
horizon-relevant successors must agree with the reference validator.

## Correctness Contract

The gate returns exactly three statuses:

```text
FEASIBLE
INFEASIBLE
UNKNOWN
```

`FEASIBLE` requires:

1. a complete extracted movement plan;
2. exact satisfaction of the selected CP time grid;
3. successful independent movement validation;
4. successful complete headway separation with no violation.

`INFEASIBLE` may update a mathematical \(K\)-bound only if:

1. CP-SAT completed an infeasibility proof;
2. the CP model is proven equivalent to the reference movement model for the
   supported scope;
3. no time limit, numerical approximation, omitted boundary condition, or
   unsupported resource semantic is involved.

Every other termination is `UNKNOWN`. In particular, a time limit without an
incumbent is not evidence of infeasibility.

For the supported fixed-\(K\) model, monotonic capacity inference additionally
requires the deletion property:

\[
  K+1\text{ feasible}\Rightarrow K\text{ feasible}.
\]

Test this contract explicitly rather than assuming it across future mandatory
service or passenger constraints.

## Passenger Incumbent Construction

When CP-SAT returns a valid movement plan \(m^{CP}\), solve the implemented
fixed-movement passenger problem:

\[
  Q_{\mathrm{pass}}(m^{CP})
  =
  \min_{x,u} f(m^{CP},x,u).
\]

The result is a valid integrated incumbent but not an optimum over movement
plans. Record separately:

- CP movement-feasibility time;
- fixed-movement Passenger Assignment time;
- passenger objective of the seed;
- served and unserved demand;
- all extracted warm-start values.

An optional later CP seed objective may minimize a movement-only surrogate,
such as total Waiting or deviation from an all-stop seed. It must remain
lexicographically subordinate to feasibility and must not be presented as a
passenger objective.

## Handoff to Gurobi Row-and-Column Generation

For a `FEASIBLE` gate result, initialize the exact integrated optimizer from:

- CP Stop/Skip decisions;
- CP visit and horizon activations;
- CP Waiting and event times;
- CP initial state;
- fixed-movement Passenger Assignment;
- CP resource order for every pair that is already materialized.

Store the complete CP resource order in a typed lookup keyed by canonical
candidate-pair and resource identity. When a delayed merge pair is generated
later, initialize its new order binary from this lookup.

The Gurobi model remains free to change every nonfixed decision. The CP
schedule is a MIP start, not a restriction.

Run the exact hybrid algorithm from
`ean_fixed_k_delayed_merge_headways.md`:

1. eager physical core and passenger model;
2. delayed merge-conflict universe;
3. complete separation after every Gurobi solve;
4. original order binary and both original disjunctive rows for each selected
   violated pair;
5. final complete validation before accepting feasibility or an objective.

The CP gate does not weaken or substitute the row-and-column correctness
contract.

## Outer Search over \(K\)

Keep capacity certification and passenger optimization logically separate.

### Capacity mode

Use analytic lower and upper bounds first. Probe fixed \(K\) values with the
complete CP gate:

```text
known feasible lower bound
    -> exponential or bounded expansion
    -> first proven infeasible upper bound
    -> binary refinement
```

A `FEASIBLE` result raises the lower bound. An `INFEASIBLE` result lowers the
upper bound. `UNKNOWN` leaves an open interval and must not be crossed as if it
were a proof.

Passenger optimization is unnecessary when the only requested output is a
capacity certificate.

### Passenger-search mode

Treat \(K\) as an externally selected design parameter. For each selected
\(K\):

1. run the feasibility gate;
2. construct the passenger seed if feasible;
3. run integrated Gurobi row-and-column optimization;
4. report the best valid objective and proof state for that \(K\).

Passenger quality is not necessarily monotone in exactly active \(K\), so a
poor passenger result at one \(K\) does not bound another \(K\). A later
Optuna or racing policy may choose the next \(K\), but must compare equal or
explicitly normalized computational budgets.

## Budget and Portfolio Policy

The first implementation is sequential:

```text
CP gate -> passenger seed -> Gurobi optimization
```

Expose separate budgets:

```text
cp_feasibility_time_limit
fixed_passenger_time_limit
gurobi_optimization_time_limit
```

Suggested policy:

- use a short CP budget for \(K\) well below the current capacity upper bound;
- use a larger CP proof budget near the suspected \(K_{\max}+1\);
- on CP `UNKNOWN`, optionally continue with Gurobi rather than discarding the
  \(K\)-probe;
- retain every valid CP schedule and passenger incumbent in checkpoints.

Parallel CP-SAT/Gurobi portfolio solving is a later experiment. It requires
explicit thread partitioning and a safe incumbent-exchange mechanism; running
both solvers at full thread count is not a valid comparison.

## Public Interfaces and Result Data

Add an optional solver-independent feasibility interface:

```text
FixedKMovementFeasibilitySolver
FixedKMovementFeasibilityRequest
FixedKMovementFeasibilityResult
```

The result records:

```text
status
solver
exact_time_grid
time_unit
setup_seconds
solve_seconds
validation_seconds
conflicts
branches
wall_time_seconds
movement_plan
validation_certificate
unsupported_features
```

Keep CP-SAT configuration out of the core EAN configuration until the
prototype passes equivalence tests. The optional dependency must not affect
existing Gurobi users or import paths when it is absent.

Add benchmark selection rather than changing defaults:

```text
--fixed-k-feasibility-solver gurobi_eager
--fixed-k-feasibility-solver gurobi_delayed
--fixed-k-feasibility-solver cp_sat
--cp-feasibility-time-limit ...
```

The integrated passenger optimizer continues to select its own Gurobi
headway-generation mode independently.

## Implementation Phases

### Phase 0: Equivalence audit

- enumerate every movement, timing, headway, occupancy, initial, and horizon
  constraint family in the reference model;
- classify its direct CP-SAT representation;
- prove the common time unit and integer-time property;
- identify unsupported asymmetric or boundary semantics;
- define a shared validator-based acceptance certificate.

No performance claim is allowed before this phase is complete.

### Phase 1: Fixed-start movement-only prototype

- create the CP-SAT builder from the canonical EAN movement network and
  resource usages;
- support fixed starts, Stop/Skip, Waiting, point headways, platform
  occupancy, and the current horizon;
- extract and validate a complete movement plan;
- expose build and solve metrics through a benchmark-only entry point.

### Phase 2: Capacity comparison

Compare CP-SAT with eager and delayed Gurobi on small exact reference cases and
then on the current Three- and Five-Station fixed-start cases. Include both
known feasible and proven infeasible \(K\) values.

The primary question is not only time to first feasible schedule. Measure time
to a mathematical infeasibility proof near the capacity boundary.

### Phase 3: Passenger handoff

- run fixed-movement Passenger Assignment on the CP schedule;
- map the full movement and passenger plan into a Gurobi MIP start;
- retain CP resource orders for dynamically generated pair starts;
- compare Gurobi progress with and without the CP seed under equal Gurobi
  budgets;
- keep CP preprocessing time visible in total wall-clock comparisons.

### Phase 4: OIP feasibility

Only after fixed-start equivalence and performance are established:

- add OIP phase and position decisions;
- reproduce complete initial-state canonicalization;
- compare fixed-start and OIP CP model size, propagation, and proof time;
- reject any implementation that introduces label-dependent feasibility.

### Phase 5: Operational integration decision

Adopt the gate in the production \(K\)-finder only if it provides either:

- materially faster infeasibility proofs near \(K_{\max}+1\); or
- sufficiently better valid starts that total
  CP-plus-passenger-plus-Gurobi wall time improves.

Otherwise retain it as an experimental solver and continue with Gurobi
row-and-column generation alone.

## Tests and Experimental Acceptance

### Exactness tests

- CP and eager Gurobi agree on feasible/infeasible status for every tiny
  enumerated instance;
- CP schedules pass complete movement and headway validation;
- Stop/Skip activation and reconvergence use the same physical resources;
- Waiting extends platform occupancy exactly;
- initial and horizon-boundary conflicts are reproduced;
- time scaling is exact for every registered example;
- `UNKNOWN` never updates a capacity bound.

### Structural tests

- one shared point resource produces one global scheduling constraint;
- inactive optional activities do not occupy resources;
- resource IDs and candidate activation agree with the canonical artifact;
- fixed starts reproduce byte-stable cabin and visit identities;
- extracted CP orders initialize existing and later generated Gurobi order
  variables consistently.

### Performance experiments

For each solver and \(K\), record:

- setup, presolve, solve, validation, and total wall time;
- declared integer variables, intervals, and global constraints;
- Gurobi variables, rows, nonzeros, and materialized pairs;
- first feasible time;
- infeasibility proof time;
- CP conflicts and branches;
- Gurobi incumbent, bound, and gap;
- peak RSS;
- passenger seed quality;
- Gurobi improvement with and without the CP seed.

Use at least:

- one tiny case solved exhaustively;
- One-Station feasible and infeasible boundary cases;
- Three-Station fixed-start Skip+Wait;
- Five-Station Circle fixed-start Skip+Wait;
- one dense \(K\) below the best known feasible capacity;
- the first suspected \(K_{\max}+1\) case.

### Acceptance criteria

The prototype is successful if:

1. all supported cases are exact against eager Gurobi and independent
   validation;
2. CP-SAT proves at least one relevant dense infeasible case materially
   faster than delayed Gurobi, or its valid seed materially improves total
   passenger-optimization wall time;
3. the model does not require explicit materialization of the full pairwise
   Big-\(M\) headway universe for symmetric resources;
4. optional use leaves all existing Gurobi behavior and tests unchanged.

## Risks

- CP-SAT may find feasible schedules quickly but still struggle to prove
  infeasibility.
- The current continuous-time model may contain semantics that do not admit a
  simple exact common tick.
- `NoOverlap` may not represent every candidate-specific clearance relation.
- Repeated circulation visits can dominate interval count even after
  eliminating explicit pair rows.
- OIP may reintroduce severe cabin-label and initial-state symmetry.
- A feasibility-only CP schedule may be a poor passenger seed.
- Maintaining two exact movement formulations creates verification and
  maintenance cost.
- CP preprocessing time may exceed the Gurobi time it is intended to save on
  easy feasible cases.

These risks are why the method remains an optional gate with an independent
equivalence test rather than a new default.

## Thesis Positioning

If successful, describe the architecture as:

> an exact fixed-fleet CP-SAT feasibility gate followed by a
> passenger-oriented continuous-time MILP with outer row-and-column generation
> of merge headway disjunctions.

Do not describe the gate itself as Benders decomposition. The two solvers are
sequential and CP-SAT does not return cuts to the Gurobi master. The method is
also not column generation in the CP stage.

Report the principal hypothesis explicitly:

- global CP resource propagation is expected to help certify dense movement
  feasibility or infeasibility;
- sparse row-and-column generation is expected to help optimize passengers
  once feasibility and a valid incumbent are already known.

Negative results remain relevant: they determine whether the difficult
boundary is feasibility proof, passenger optimization, OIP symmetry, or
finite-horizon event count.

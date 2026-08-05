# Passenger-Guided Rotation-Flow Hybrid

Status: **proposed research and implementation plan**

## Decision Summary

Develop an optional fixed-\(K\) planning method that selects and chains
one-rotation stop/skip templates while routing aggregate passenger demand in
the same restricted master. Cabins may select a different template after
every rotation. Waiting is not enumerated as part of every structural
template; it is introduced only through timed occurrences, holding
transitions, or conflict-driven timing repair.

The first version is a primal matheuristic:

```text
physical movement network + fixed K + demand
    -> structural one-rotation templates
    -> timed rotation-occurrence pool
    -> anonymous cabin flow + passenger flow master
    -> complete conflict separation
    -> minimal merge-waiting / continuous EAN repair
    -> exact fixed-movement passenger evaluation
    -> validated incumbent for the current EAN R&C model
    -> repaired occurrences returned to the pool
```

Before implementing this complete timed-occurrence loop, test the deliberately
simpler
[`zero_wait_passenger_master_timing_cuts.md`](zero_wait_passenger_master_timing_cuts.md):
the passenger master fixes additional waiting to zero, while a complete
waiting-enabled timing subproblem returns infeasible-core cuts or a realized
plan. The richer occurrence pool is justified only if this smaller experiment
shows that repair is useful but zero-wait ranking remains informative.

It does not replace the current EAN row-and-column generation (R&C). The
rotation master searches globally useful service combinations and supplies
incumbents. The existing EAN retains continuous retiming, complete physical
semantics, exact headway separation, and any mathematical certificate.

Do not call a restricted-pool result globally optimal, and do not interpret
restricted-pool infeasibility as mathematical infeasibility. Exact
branch-price-and-cut is explicitly out of scope until the heuristic prototype
demonstrates that a modest pool produces materially better search progress.

## Motivation

The current EAN R&C omits only selected headway disjunctions. All cabin
visits, stop/skip alternatives, continuous event times, waiting semantics, and
passenger decisions are already represented. When a delayed pair is
violated, the model adds one order binary and its two original disjunctive
rows.

This is exact and conservative, but it preserves most of the cabin-indexed
model:

\[
O(K\lvert V\rvert)
+
\text{generated headway-order structure}.
\]

Near a dense merge or the capacity boundary, repeated separation may
eventually materialize a large fraction of the eager pair universe. Cabin
labels and per-visit timing remain present even when many cabins perform
similar rotations.

The proposed formulation changes the modeled unit. A column is not a local
headway order binary but a one-rotation operating offer. The master selects
only useful timed occurrences, chains them into anonymous cabin flows, and
routes passengers over the selected service. Fixed timed occurrences have
static resource conflicts, so their master needs neither continuous event
times nor pairwise Big-\(M\) order decisions.

Passenger routing must be present in the master. A movement-only rotation
master can prefer operationally easy patterns that serve demand poorly. The
selection must see unserved demand, waiting time, journey time, transfers, and
capacity while choosing stop/skip templates.

## Relation to the Current R&C Model

### Current EAN R&C

Let \(C_E\) be the eager core and \(C_M\) the omitted merge constraints. At
iteration \(q\),

\[
\mathcal F_{\mathrm{full}}
\subseteq
\mathcal F_q.
\]

Therefore, for the minimization model:

- the relaxed objective is a valid lower bound;
- relaxed infeasibility implies full-model infeasibility;
- a completely separated incumbent is feasible for the full model;
- finite materialization recovers the eager formulation.

### Restricted rotation master

Let \(P'\subset P\) be the generated occurrence pool and \(C'\subset C\) the
currently separated conflicts. Missing columns restrict the solution space,
while missing conflicts relax it. These effects have opposite directions.
Without exact pricing and complete separation, the restricted master provides
no global bound with a reliable direction.

The result contract is therefore:

```text
FEASIBLE_HEURISTIC
  selected plan passed complete movement and headway validation

POOL_INFEASIBLE
  no solution exists in the current pool; says nothing about the full problem

REPAIR_FAILED
  the selected pattern could not be repaired within the configured budget

INVALID_INTERNAL
  a supposedly repaired plan failed independent validation
```

Only the existing exact EAN solve may return mathematical `INFEASIBLE`,
`OPTIMAL`, or a certified optimality gap.

## Canonical Objects

### `EanRotationTemplate`

An immutable, cabin-independent structural description of one return from a
chosen reference state to the same compatible state:

```text
template_id
movement_network_id
pattern_id
reference_state_id
route_option_ids
stop_skip_signature
minimum_event_offsets
minimum_duration
resource_usage_prototypes
passenger_service_prototypes
source_provenance
```

A template contains minimum travel and service timing but no arbitrary
additional waiting and no cabin ID.

For current deterministic rings, a template represents one complete ring
rotation. For a deterministic line circulation, it represents one complete
return to the compatible boundary state. A template is valid only if its
terminal state can legally start another supported template.

### `EanRotationOccurrence`

A realizable time placement of one template:

```text
occurrence_id
template_id
start_state_id
end_state_id
start_time
end_time
realized_event_times
realized_waiting
resource_occupancy_intervals
passenger_event_nodes
source_provenance
validation_status
```

An occurrence may be:

- a nominal minimum-time realization;
- extracted from an existing `EanMovementPlan`;
- shifted on an allowed time lattice;
- produced by conflict-driven timing repair;
- produced by a later pricing or neighborhood subproblem.

Different waiting values or start times are different occurrences. The pool
must deduplicate occurrences using a canonical signature over template,
event times, activation, and resource occupancy.

### `EanRotationTransition`

A legal connection from occurrence \(a\) to occurrence \(b\):

\[
\operatorname{endState}(a)=\operatorname{startState}(b),
\qquad
\operatorname{endTime}(a)\leq\operatorname{startTime}(b).
\]

The transition records whether the same cabin continues immediately or waits
at an explicitly permitted holding state. Cabins may choose any compatible
next template; repeating the same template is only one allowed special case.

### `EanRotationPool`

Stores templates, occurrences, transitions, generation provenance, validation
status, and deterministic IDs. The pool is append-only during one optimization
run. Rejected or dominated occurrences remain auditable but are not offered to
the master.

## Anonymous Cabin Flow

Use a directed occurrence-transition graph. A binary variable \(y_a\) selects
occurrence \(a\), and a binary connection variable \(z_{ab}\) selects a legal
continuation when explicit continuity is required.

Flow conservation at an occurrence is:

\[
y_a
=
\sum_{b:(b,a)\in T}z_{ba}
=
\sum_{b:(a,b)\in T}z_{ab},
\]

with explicit source and sink arcs for the finite planning horizon. The source
injects exactly \(K\) cabin paths:

\[
\sum_{a\in A^{\mathrm{start}}}z_{\mathrm{src},a}=K.
\]

The sink receives exactly \(K\) paths, subject to the selected horizon and tail
semantics.

This formulation removes cabin-label symmetry. Cabin IDs are reconstructed
after the solve by deterministic flow decomposition and are used only for
`EanMovementPlan`, replay, export, and final validation.

For fixed initial placement, each physical initial slot supplies one unit of
flow and only compatible first occurrences may consume it. For optimized
initial placement, initial-state capacity and separation must be represented
by explicit start occurrences or a separately validated initial-placement
layer. The first experiment uses fixed initial placement.

## Integrated Passenger Flow

Each selected occurrence exposes station-time service nodes and ride arcs.
Stop occurrences expose boarding, alighting, and through-service arcs; skipped
stations expose only through movement.

For aggregate demand group \(d\) and passenger arc \(g\), let

\[
f_{d,g}\geq 0
\]

be the routed passenger volume. Passenger flow conservation is enforced on
station-time nodes. Unserved demand \(u_d\) completes the demand balance.

Ride-arc capacity is linked to the selected cabin occurrence:

\[
\sum_d f_{d,g}
\leq
Q\,y_{a(g)}.
\]

Passenger waiting arcs, transfers, boarding, alighting, and continuation
across the artificial rotation boundary must use the same semantics as the
existing passenger model. A rotation boundary must not force passengers to
alight. Through-passenger continuity is represented by a service continuation
arc tied to the selected occurrence transition. If a reference state is not a
legal passenger-transfer location, aggregate flow must not switch between
cabins there.

Use lexicographic objectives:

1. minimize unserved demand or its configured penalty;
2. minimize passenger journey-time objective under the current project
   semantics;
3. minimize total operational waiting;
4. optionally minimize the latest cabin completion time.

Demand is aggregated by current OD and release-time groups. Do not create one
commodity per physical passenger. Generate only passenger arcs supported by
the current pool; passenger-path generation remains a later option if the
explicit aggregate flow becomes dominant.

## Timing and Waiting

### Structural templates do not enumerate waiting

For template \(p\), event \(e\) has a minimum relative offset
\(\bar\tau_{p,e}\). A realized occurrence has

\[
t_{a,e}
=
s_a+\bar\tau_{p,e}+D_{a,e},
\]

where cumulative delay is

\[
D_{a,e}
=
\sum_{q\preceq e} w_{a,q}.
\]

Waiting is allowed only at physical holding points supported by the movement
network and current EAN semantics.

### Canonical waiting location

When multiple holding points produce the same downstream shift, prefer the
latest safe holding point before the affected merge. This is an exact
dominance reduction only when moving the wait later:

- preserves every downstream event time;
- does not violate platform occupancy or an upper bound;
- does not remove a passenger boarding opportunity;
- does not change a resource or route decision between the two locations.

Otherwise retain both alternatives.

### Minimal-delay timing repair

For a fixed template sequence and fixed merge precedence, event timing is a
difference-constraint system. With nondecreasing timing cost, use the earliest
feasible schedule. Waiting is then induced by tight travel, service, passenger,
or headway arcs rather than searched as arbitrary continuous slack.

Unknown merge precedence remains disjunctive. The repair model creates order
decisions only for conflicts found in the selected occurrence set. It jointly
minimizes the necessary delay across all affected and later rotations; a
single-pass greedy shift is not considered exact because delay may improve one
later merge while worsening another.

Passenger costs must be recomputed after any continuous repair. A nominal
master objective is not the final objective when event times change.

## Conflict Treatment

### Eager safety core

Keep in every occurrence and transition:

- physical route continuity;
- minimum travel and service time;
- legal stop/skip activation;
- station and platform occupancy internal to the occurrence;
- initial-state compatibility;
- horizon and tail semantics;
- deterministic same-stream ordering that is intrinsic to the occurrence;
- passenger capacity and flow conservation.

### Delayed inter-occurrence conflicts

Two fixed occurrences have static resource occupancy intervals. The initial
master may omit inter-occurrence merge conflicts. After every integer
incumbent:

1. decompose the selected flow into cabin paths;
2. construct a complete provisional `EanMovementPlan`;
3. run the independent complete headway separator;
4. add every newly discovered conflict or a deterministic strongest batch;
5. prefer a maximal valid conflict clique

   \[
   \sum_{a\in C}y_a\leq1
   \]

   over only pairwise rows when clique validity is proven;
6. optionally generate minimally delayed repaired occurrences;
7. re-solve within the shared total budget.

An already materialized conflict that remains violated is an internal
consistency error.

The master may use resource-time bucket rows only when every included
occupancy interval is represented conservatively. Final feasibility always
requires the continuous complete separator.

## Hybrid Feedback Loop

The restricted master and current EAN cooperate:

1. Seed the occurrence pool from all-stop, existing feasible movement plans,
   and selected time shifts.
2. Solve anonymous cabin flow and aggregate passenger flow jointly.
3. Separate all selected inter-occurrence resource conflicts.
4. Generate repaired occurrences or reject incompatible combinations.
5. Assemble the best fully separated selection into an `EanMovementPlan`.
6. Re-solve the existing fixed-movement passenger model to obtain an exact
   evaluation under realized times.
7. Pass the plan as a MIP start to the current fixed-\(K\) EAN R&C model.
8. Fix or neighborhood-restrict template choices initially, but allow
   continuous retiming and exact waiting.
9. Extract improved one-rotation occurrences from every validated EAN
   incumbent and return them to the pool.
10. Repeat until the global experiment budget expires.

The best reported solution is always the best independently validated
movement-and-passenger plan, regardless of which component produced it.

## Occurrence Generation Strategies

Implement in increasing order of complexity.

### 1. Extraction and deterministic shifts

- extract rotations from existing `EanMovementPlan` instances;
- create the nominal all-stop pool;
- enumerate supported structural stop/skip templates for small current rings;
- create a bounded deterministic set of global or local time shifts;
- deduplicate and independently validate every occurrence.

### 2. Conflict-driven repair generation

For a selected conflicting pair, generate alternative occurrences by:

- delaying either stream by the exact missing clearance;
- placing delay at the latest proven safe holding point;
- propagating the delay through the occurrence and following transition;
- re-evaluating passenger event times.

Generate both precedence directions unless topology proves one.

### 3. Passenger-guided neighborhood generation

Use the current solution to identify:

- high unserved demand;
- high passenger waiting;
- overloaded service legs;
- skips that block valuable boarding or alighting;
- stops that delay many through passengers with little boarding value.

Mutate one or a short sequence of rotation templates, repair timing locally,
and insert validated resulting occurrences.

### 4. Heuristic pricing

Use dual or reduced-cost-like prices from the restricted LP to guide a
one-rotation shortest-path, CP-SAT, or small EAN subproblem. It may generate
promising columns but does not establish that no improving column exists.

### 5. Exact pricing research gate

Only after the heuristic benchmark succeeds, investigate:

- exact reduced-cost pricing;
- conflict-clique dual representation;
- branching rules compatible with pricing;
- complete conflict separation at branch nodes;
- exact passenger-path treatment.

This is branch-price-and-cut and is a separate research project, not an
incremental optimization flag.

## Public Configuration

Add a separate planner selection rather than overloading the existing headway
generation enum:

```text
EAN_R_AND_C
ROTATION_PASSENGER_HYBRID
```

The hybrid configuration includes:

```text
fixed_k
initial_placement_mode
total_time_limit_seconds
pool_seed_sources
maximum_occurrences
time_shift_policy
conflict_batch_size
repair_time_limit_seconds
ean_refinement_time_limit_seconds
passenger_objective
random_seed
```

All heuristic limits and seeds must be exported. The progress display reports:

- templates and occurrences in the pool;
- selected rotations and reconstructed cabin paths;
- master variables, rows, nonzeros, and solve time;
- passenger arcs, routed and unserved demand;
- separated pair and clique conflicts;
- generated repair occurrences;
- EAN refinement incumbents;
- best validated passenger objective and elapsed time.

## Implementation Phases

### Phase 0: Reproducible experiment contract

- freeze comparison examples, fixed \(K\), demand, horizon, solver parameters,
  machine metadata, and total wall-clock budget;
- record current eager and delayed EAN R&C build, root, incumbent, bound, and
  validation metrics;
- add result schemas that distinguish pool status from mathematical solver
  status.

Exit criterion: one command reproduces the baseline and writes comparable
machine-readable metrics.

The linked zero-wait passenger-master experiment precedes Phases 1--6. Reuse
its validated template extraction, timing-subproblem, feasibility-cut, bound,
and repair metrics rather than implementing parallel concepts.

### Phase 1: Templates, occurrences, and extraction

- introduce the canonical immutable objects;
- derive one-rotation templates from `EanMovementNetwork`;
- extract and normalize rotations from existing movement plans;
- implement deterministic IDs, signatures, deduplication, and transition
  compatibility;
- reconstruct a movement plan from a manually selected occurrence chain.

Exit criterion: extract/reconstruct round trips preserve stop/skip decisions,
event times, resource usages, and passenger service semantics byte-stably
where IDs are expected to remain stable.

### Phase 2: Integrated restricted master

- implement anonymous fixed-\(K\) cabin flow for fixed initial placement;
- expose occurrence service arcs;
- add aggregate passenger flow, demand balance, capacity, and the current
  passenger objective;
- reconstruct cabin IDs only after the solve;
- independently evaluate the selected fixed movement with the existing
  passenger solver.

Exit criterion: on conflict-free small cases, the master and existing
fixed-movement passenger model agree on served demand and objective within
configured numerical tolerances.

### Phase 3: Delayed occurrence-conflict separation

- index occurrence resource intervals incrementally;
- separate selected pairs with the complete headway semantics;
- add pair rows and proven clique rows;
- require a final clean separation before `FEASIBLE_HEURISTIC`;
- export all rounds and conflict provenance.

Exit criterion: every accepted master plan passes the current movement and
headway validators; deliberately conflicting selections are rejected.

### Phase 4: Waiting repair and new occurrences

- implement the minimal-delay timing subproblem;
- restrict waits to legal holding points;
- propagate delay across later events and rotation transitions;
- re-solve passenger assignment on realized event times;
- insert validated repaired occurrences into the pool.

Exit criterion: repair never silently changes passenger cost, horizon
semantics, or downstream event times, and every produced occurrence is
independently valid.

### Phase 5: EAN refinement and feedback

- translate the best pool plan into a partial MIP start;
- run fixed-\(K\) EAN R&C with continuous timing;
- support a restricted template neighborhood followed by an unrestricted
  refinement when budget permits;
- extract new rotations from every improving validated EAN incumbent.

Exit criterion: the handoff is lossless for the original plan, and the hybrid
never reports an EAN result before final complete validation.

### Phase 6: Passenger-guided pool improvement

- add deterministic stop/skip and short-sequence neighborhoods;
- rank generation targets by passenger marginal value and conflict burden;
- compare simple neighborhood generation with heuristic dual-guided pricing;
- add pool aging only after preserving reproducibility and incumbent
  reconstructability.

Exit criterion: at equal total wall time, the method improves either time to a
validated incumbent or final passenger objective on the predefined scaling
cases.

### Phase 7: General network extension

- allow compatible circulation-pattern changes and physical rope transfers;
- define templates between repeatable network boundary states rather than
  assuming a ring;
- preserve passenger continuation and legal transfer semantics;
- keep internal line conflicts in local occurrences and coordinate only shared
  resources in the master where possible.

This phase depends on the network-builder migration and is not part of the
initial ring experiment.

## Tests

### Unit tests

- template return-state and transition compatibility;
- free template change after every rotation;
- deterministic occurrence signatures and deduplication;
- waiting propagation into the next rotation;
- latest-safe-holding dominance preconditions;
- passenger boarding and alighting only at stops;
- through passengers across a rotation boundary;
- capacity linkage to selected occurrences;
- fixed-\(K\) anonymous flow and deterministic flow decomposition;
- pair conflict and clique validity;
- `POOL_INFEASIBLE` never mapped to mathematical infeasibility.

### Small exact comparisons

For One-, Three-, and Five-Station current examples:

- construct a complete small occurrence universe;
- compare the selected optimum against the eager EAN where enumeration is
  genuinely complete;
- verify identical movement/headway feasibility;
- compare served demand and passenger objective;
- test Skip/No-Skip and Wait/No-Wait;
- test one cabin changing templates across consecutive rotations.

These tests establish implementation equivalence only for the enumerated
small universe. They do not imply complete pricing on larger cases.

### Regression

- existing EAN eager and R&C modes remain unchanged;
- existing `EanMovementPlan`, passenger export, replay, and validators accept
  reconstructed plans;
- the complete current test suite remains green.

## Experimental Acceptance

Use equal total wall-clock budgets and identical passenger data. At minimum
record:

| Metric | EAN R&C | Rotation hybrid |
|---|---:|---:|
| Artifact/pool build time | required | required |
| Initial variables/rows/nonzeros | required | required |
| Peak RSS | required | required |
| Time to first validated incumbent | required | required |
| Best validated passenger objective over time | required | required |
| Served and unserved demand | required | required |
| Total operational waiting | required | required |
| Conflicts and separation rounds | required | required |
| EAN refinement time | n/a | required |
| Solver bound and gap | certified where available | EAN only |

Initial experiments:

1. fixed-\(K\), fixed-start Three-Station Ring with Skip+Wait;
2. fixed-\(K\), fixed-start Five-Station Ring with Skip+Wait;
3. at least one lower-density and one near-capacity \(K\);
4. OIP only after fixed-start results justify continuation.

The prototype is considered promising if it consistently produces valid plans
and, on at least one difficult scaling case, gives a materially earlier
validated incumbent or a better final passenger objective than the EAN R&C
baseline at the same total wall time. Failure to beat the baseline is a valid
research result and stops exact pricing work.

## Thesis Integration

If implemented, describe the method as:

> a passenger-guided restricted rotation-flow matheuristic with delayed
> inter-occurrence conflict separation and exact EAN retiming

Do not describe it as exact column generation unless reduced-cost pricing is
complete, and do not describe it as Logic-Based Benders unless a formal
master/subproblem value function and valid inference cuts are implemented.

The thesis comparison must explain:

- local order-variable R&C versus rotation-trajectory columns;
- why the current R&C preserves valid lower bounds;
- why a restricted occurrence pool does not;
- how anonymous cabin flow removes label symmetry;
- why passenger routing belongs in the service-selection master;
- how waiting and continuous repair change passenger costs;
- which results are validated incumbents and which carry solver certificates.

Relevant methodological precedents include:

- Lusby et al., resource-based set packing and branch-and-price for railway
  junction routing
  ([paper](https://doi.org/10.1287/trsc.1100.0362));
- Schälicke and Nachtigall, complete train-path columns with dynamically
  maintained conflict cliques
  ([paper](https://arxiv.org/abs/2306.13431));
- Martin-Iradi and Ropke, line-path column generation combined with integrated
  passenger routing and matheuristic improvement
  ([paper](https://doi.org/10.1016/j.ejor.2021.04.041)).

## Risks and Stop Conditions

- Fixed timed occurrences may be too brittle on a dense ring; stop if pool
  growth is dominated by nearly identical time shifts without improving
  incumbents.
- Passenger multi-commodity flow may replace headways as the model-size
  bottleneck; profile before adding passenger-path generation.
- Dense near-capacity selection may become a hard set-packing problem even
  without Big-\(M\); compare root and incumbent behavior rather than only row
  counts.
- Continuous repair may systematically invalidate the master passenger
  ranking; if so, move timing earlier into occurrence generation instead of
  adding increasingly inaccurate objective corrections.
- Do not proceed to exact pricing if extraction, repair, and feedback fail to
  beat the existing EAN within equal budgets.
- Do not generalize to dynamic turnbacks or multi-line routing before the
  fixed-start ring prototype produces independently validated benefit.

## Assumptions

- The first implementation uses fixed \(K\) and fixed initial placement.
- Every cabin may select a different compatible template after each rotation.
- Same-template repetition is permitted but never required.
- The physical `Scenario` and derived `EanMovementNetwork` remain the source
  of truth.
- The current complete movement, passenger, and headway validators remain
  authoritative.
- Passenger demand is aggregate and may be split according to current model
  semantics.
- The finite planning horizon and tail semantics are preserved exactly.
- Global optimality and mathematical infeasibility remain responsibilities of
  the existing exact model until complete branch-price-and-cut exists.

# Fixed-K EAN with Delayed Merge Headways

Status: **proposed implementation and experiment plan**

## Decision Summary

Introduce an exact hybrid headway-generation mode for the integrated EAN:

```text
EAGER_CORE_WITH_DELAYED_MERGES
```

The initial MILP contains the complete movement, fixed-fleet, timing,
waiting, passenger, and non-merge safety model. It also contains every
headway whose order is topology-proven, local to one branch, or not safely
classifiable. Only original headway disjunctions whose unresolved ordering is
caused by a proven reconvergence of distinct route streams are omitted.

After every solve, a complete separator checks the omitted merge-conflict
universe. Violated pairs are materialized as their original order binary and
two original disjunctive rows, the incumbent is installed as a partial warm
start, and the model is solved again. A result is feasible only after a final
complete separation reports no violation.

This is exact outer row-and-column generation, not a timing-repair heuristic
and not a Gurobi lazy-constraint callback. It extends the existing delayed
headway machinery but keeps a strong eager core instead of initially omitting
all headways.

Development is deliberately staged:

1. fixed \(K\) and fixed initial placement to isolate the merge hypothesis;
2. fixed \(K\) and optimized initial placement (OIP) after the first stage is
   validated;
3. comparison of several exact \(K\) values only after the per-\(K\) solver is
   reliable.

## Motivation and Current Evidence

The current experiments indicate that cabin count alone is not the dominant
difficulty:

- the Five-Station Circle without Skip solves exactly with \(K=38\) in about
  1.5 seconds;
- the same topology with Skip and only \(K=19\) still has a large gap after
  more than 30 minutes;
- fixed-movement passenger assignment is fast, while the integrated
  stop/skip, timing, headway, and passenger model is difficult;
- OIP38 and OIP76 can be built, but the large eager integrated models make
  essentially no search progress.

The structural hypothesis is that a deterministic corridor has an inherited
order, whereas a stop/skip reconvergence introduces pairwise alternatives

\[
t_i^{\mathrm{clear}}+h_r\leq t_j^{\mathrm{enter}}
\quad\lor\quad
t_j^{\mathrm{clear}}+h_r\leq t_i^{\mathrm{enter}}.
\]

There may be few physical merge locations, but every location induces many
potential cabin-visit pairs. The eager formulation therefore pays
\(O(n_r^2)\) order binaries and twice as many rows at a resource containing
\(n_r\) candidates, even though only a small number of temporal neighbours
may be relevant in the final schedule.

This remains a hypothesis until the fixed-start ablation measures:

- the size of the proven merge-conflict universe;
- the number of merge pairs actually materialized;
- build time, root time, time to first incumbent, and progress at equal
  budgets;
- exact agreement with the eager model on solved reference cases.

## Scope

The first implementation supports:

- current deterministic line and ring circulation patterns;
- fixed starts and later OIP;
- exactly \(K\) cabins;
- Stop and Skip options that reconverge at the current station exit;
- optional station waiting;
- the current operational and passenger horizons;
- the integrated Journey-Time passenger objective;
- the canonical `EanMovementNetwork`;
- the existing complete headway separator and dynamic constraint pool.

The first implementation does not include:

- variable fleet cardinality inside one solve;
- greedy backward or forward timing repair;
- approximate collision acceptance;
- dynamic turnbacks, rope transfers, or depot routing;
- generalized Benders cuts;
- a Gurobi callback that attempts to introduce new variables;
- a claim that every `EXIT_SWITCH` checkpoint is a merge.

## Fixed-\(K\) Contract

### Fixed initial placement

The diagnostic model contains exactly the \(K\) supplied cabin starts. No
fleet activation decision is present. Initial phases, positions, and times are
data.

This stage isolates the effect of delayed merge ordering from OIP symmetry and
placement decisions. It is already nontrivial: the fixed-start Five-Station
Circle with Skip is a difficult integrated passenger model.

### Optimized initial placement

The target model contains exactly \(K\) cabin identities and optimizes their
initial phases and positions. All cabins are active:

\[
a_c=1
\qquad
\forall c\in\{0,\ldots,K-1\}.
\]

Where the shared fleet API still requires activation variables, they are fixed
to one. Prefer omitting them entirely when that does not duplicate the fleet
model. Do not instantiate \(U>K\) potential cabins and choose \(K\) from them.

The existing initial-state canonicalization remains active:

- cabin IDs are ordered by complete initial-state category;
- continuous position or entry time breaks ties inside one category;
- this ordering applies only at \(t=0\) and does not forbid later overtaking.

The fixed-start solution is used as the first OIP warm start. This provides a
known feasible placement without restricting the OIP search.

## Constraint Partition

Partition the full model into an eager core \(C_E\) and a delayed merge set
\(C_M\):

\[
\mathcal F_{\mathrm{full}}
=
\{x:C_E(x),C_M(x)\}.
\]

The initial hybrid model is

\[
\mathcal F_0=\{x:C_E(x)\}.
\]

Only constraints with complete topology-derived merge provenance may enter
\(C_M\). Unknown or inconclusive cases remain in \(C_E\).

### Constraints that remain eager

| Family | Required treatment |
|---|---|
| Visit and transition activation | Keep complete |
| Stop/Skip selection | Keep complete |
| Minimum and exact travel times | Keep complete |
| Waiting bounds and semantics | Keep complete |
| Horizon activation | Keep complete |
| Fixed-\(K\) fleet constraints | Keep complete |
| OIP phase and position constraints | Keep complete |
| OIP symmetry breaking | Keep complete |
| Passenger boarding/alighting | Keep complete |
| Cabin capacity and demand coverage | Keep complete |
| Passenger release and selected-time constraints | Keep complete |
| Initial rope and station separation | Keep complete |
| Platform entry safety | Keep complete |
| Platform exit and waiting occupancy | Keep complete |
| One-branch and no-skip resource safety | Keep complete |
| Topology-proven ordered corridor headways | Keep, preferably directed and adjacent |
| Horizon-boundary headways | Keep complete |
| Unclassified resource conflicts | Keep complete |

These constraints prevent the relaxed model from obtaining an artificial
solution by overlapping cabins everywhere, violating station occupancy, or
changing the physical movement model. Only the merge-order search is delayed.

### Constraints eligible for delayed generation

A pair is eligible only when its nonredundant ordering role is caused by:

1. two distinct incoming route families;
2. reconvergence on the same state or physical resource;
3. no topology-proven predecessor order that already fixes the pair;
4. candidate activation and time semantics supported by the complete
   separator.

Eligible roles are:

```text
CROSS_STREAM_MERGE
MERGE_PROPAGATED
```

`CROSS_STREAM_MERGE` is the first shared resource after reconvergence.

`MERGE_PROPAGATED` is a downstream occurrence that reimposes the same
unresolved order before any waiting, buffering, branch, or unequal timing
effect can absorb or change the relative separation. The delayed unit is
therefore a merge-conflict family rather than only one exit-switch row.

A family ends at the first point where:

- waiting or buffering may change relative timing;
- another branch or merge occurs;
- a different resource headway creates an independent conflict;
- the circulation boundary is not proven continuous;
- provenance is incomplete.

The first version is conservative. If a downstream pair cannot be proven to
be a propagated copy, it remains eager or becomes a separately classified
merge family.

## Conflict Provenance

Extend the headway/resource analysis with immutable provenance:

```text
conflict_role
resource_id
checkpoint_id
merge_family_id
incoming_route_family_ids
reconvergence_state_id
deterministic_corridor_id
proof_reason
original_candidate_ids
```

Required roles:

```text
ORDERED_CORRIDOR
BRANCH_INTERNAL
CROSS_STREAM_MERGE
MERGE_PROPAGATED
UNCLASSIFIED
```

Classification must use `EanRouteOption`, resource usage, and movement-state
provenance. The checkpoint kind alone is insufficient. In particular:

```text
EXIT_SWITCH != automatically a merge
```

The classifier must report counts by resource, checkpoint, family, and role
before any solver model is built.

## Ordered-Corridor Core

Where topology and activation semantics prove one fixed order

\[
c_1\prec c_2\prec\cdots\prec c_n,
\]

prefer adjacent directed headways:

\[
t_{c_q}^{\mathrm{clear}}+h_r
\leq
t_{c_{q+1}}^{\mathrm{enter}}
\qquad q=1,\ldots,n-1.
\]

Non-adjacent separation follows by transitivity only if:

- the same candidates are active under the relevant route choices;
- headway and occupancy semantics are compatible;
- no Waiting or branch permits reordering;
- horizon filtering does not break the implication.

Otherwise retain the existing original pairs. This reduction is exact but is
kept as a separately measurable optimization category. The first delayed
merge experiment may use the unchanged eager core to isolate the effect of
merge generation.

## Hybrid Artifact and Public Configuration

Add a public generation mode:

```text
EAGER_ALL_PAIRS
DELAYED_ALL_VIOLATIONS
EAGER_CORE_WITH_DELAYED_MERGES
```

The existing defaults remain unchanged until the new mode passes all
acceptance gates.

The hybrid artifact stores:

- all checkpoints and candidates;
- materialized eager-core pairs;
- delayed merge-resource and family provenance;
- the exact delayed candidate universe without persistent pair
  materialization;
- explicit coverage scope;
- pattern and network IDs used for classification.

Do not mark a hybrid artifact as `COMPLETE`. Add an explicit hybrid coverage
description rather than overloading `SPARSE` in a way that loses the eager
subset. A downstream consumer must be able to distinguish:

```text
complete eager artifact
fully sparse artifact
hybrid eager-core/delayed-merge artifact
hybrid artifact with final separation certificate
```

The delayed universe must not materialize all pair combinations during
artifact construction. A violated canonical `HeadwayPair` is created only
when selected for augmentation.

## Outer Row-and-Column Generation

This method uses an outer solve loop because each new disjunction requires a
new binary variable. Gurobi lazy-constraint callbacks can add rows over
existing variables but cannot provide the required dynamic column generation.

### Initial solve

1. Build the full non-headway model.
2. Build all eager-core headways.
3. Register delayed merge candidate expressions and activation semantics in
   the dynamic constraint pool.
4. Apply the fixed-start or OIP warm start.
5. Solve with the remaining total budget.

### Complete merge separation

For every delayed resource or family:

1. collect candidates whose visits are active in the incumbent;
2. apply Stop/Skip activation exactly;
3. apply platform waiting occupancy semantics exactly;
4. exclude candidates outside the active horizon;
5. evaluate leader-clear and follower-enter times;
6. check every required omitted original pair.

For two candidates \(i,j\), define:

\[
g_{ij}^{i\prec j}
=
t_j^{\mathrm{enter}}-t_i^{\mathrm{clear}},
\]

\[
g_{ij}^{j\prec i}
=
t_i^{\mathrm{enter}}-t_j^{\mathrm{clear}}.
\]

The pair is violated when:

\[
\max(g_{ij}^{i\prec j},g_{ij}^{j\prec i})
<
h_{ij}-\varepsilon.
\]

Use the existing physical tolerance of \(10^{-5}\) seconds unless numerical
experiments justify one shared project-wide change.

The implementation may use sorted sweeps to find violations, but final
certification must remain equivalent to exhaustive pair separation.

### Augmentation

Select at most a configured batch size, initially 10,000, ordered by:

1. descending violation amount;
2. stable merge-family ID;
3. stable canonical pair ID.

For each selected original pair add exactly:

- one order binary \(z_{ij}\);
- the two original Big-\(M\) disjunctive rows;
- the canonical pair ID to the duplicate-protected dynamic pool.

If a materialized pair remains violated in the next accepted incumbent, raise
an internal consistency error. Do not silently add it twice.

After augmentation:

1. reset the invalidated solver solution state;
2. install the previous movement, fixed fleet, OIP placement, and passenger
   decisions as a partial start where supported;
3. solve again with the remaining global budget.

### Termination

Return:

- `FEASIBLE` only after complete final separation finds no violation;
- `INFEASIBLE` when an augmented relaxation is mathematically infeasible;
- `UNKNOWN` when the budget expires without a fully separated incumbent;
- an optimal result only when the current relaxation is solved to optimality
  and its incumbent passes complete separation.

For a time-limited but fully separated incumbent, return a valid feasible
solution and the solver bound of the current relaxation. Label the optimality
status accurately.

## Correctness

Let \(D_q\subseteq C_M\) be the merge disjunctions materialized after round
\(q\). Then:

\[
\mathcal F_{\mathrm{full}}
\subseteq
\mathcal F_{q+1}
\subseteq
\mathcal F_q,
\]

where:

\[
\mathcal F_q
=
\{x:C_E(x),D_q(x)\}.
\]

Consequences for a minimization problem:

1. every intermediate best bound is a valid lower bound on the full optimum;
2. infeasibility of an intermediate relaxation proves infeasibility of the
   full model;
3. an incumbent passing complete separation is feasible for the full model;
4. if the current relaxation is optimal and its optimum passes separation,
   it is also optimal for the full model;
5. budget exhaustion without a separated incumbent is `UNKNOWN`, not
   infeasible.

Final certification runs the complete original headway separator, not only a
fast merge-local check. Any non-merge violation is an internal classification
or eager-core error.

## Metrics and Progress

Record per build:

- eager-core checkpoint, candidate, and pair counts;
- delayed checkpoint, candidate, family, and potential pair counts;
- counts by conflict role and resource;
- artifact and model-build time;
- variables, rows, nonzeros, and peak RSS;
- order binaries avoided initially.

Record per solve round:

- round number;
- solver status and runtime;
- incumbent and best bound;
- MIP gap;
- node count;
- all delayed violations found;
- new pairs materialized;
- cumulative materialized pairs;
- separation and augmentation time;
- model variables, rows, and nonzeros;
- remaining global budget.

Record final certification:

- complete separation performed;
- total active candidate pairs checked;
- remaining violations;
- eager-core violations;
- delayed merge violations;
- certificate status.

Visible progress should resemble:

```text
K=19 fixed-start round=3
merge violations=148 added=148 cumulative=1,934/186,420
model=... vars / ... rows
incumbent=... bound=... gap=...
remaining=1,124s
```

## Implementation Sequence

### Phase 0: Classification-only diagnostic

Phase 0 implements provenance and reports without changing an artifact, a
pair builder, a solver model, or any admissible solution. Its result is a
sidecar analysis consumed by humans and tests only. Phase 1 is the first phase
allowed to change pair generation.

#### Phase-0 design constraint: current candidates are route-agnostic

The current `EXIT_SWITCH` candidate is active for both Service and Skip. A
static original pair at such a checkpoint therefore does not identify whether
the two visits will later be:

```text
SERVICE / SERVICE
SKIP / SKIP
SERVICE / SKIP
SKIP / SERVICE
```

Consequently, Phase 0 must not falsely report an original pair as statically
cross-stream. It reports two distinct scopes:

```text
MERGE_RESOURCE_UNIVERSE
  every original pair at a topology-proven shared merge resource

CROSS_STREAM_CONDITIONAL
  the route combinations that are cross-stream after Stop/Skip decisions
  are known
```

The first is directly implementable with the existing candidates and dynamic
constraint pool: omit all pairs at a proven merge resource and separate the
original physical pairs after a solve. This remains exact, but its first
relaxation also omits same-branch pairs at that resource.

The second would preserve a stronger initial model, but requires either:

- separate Service- and Skip-activated candidates at the shared exit
  resource; or
- a proof that every same-branch instance is implied by retained upstream
  constraints.

Phase 0 determines which formulation Phase 1 should use. It does not silently
equate the two.

#### New analysis module

Add a solver-independent module:

```text
optimization/ean/merge_conflict_analysis.py
```

Keep it separate from `headway_classification.py`, whose existing purpose is
classifying individual materialized pairs from time bounds.

Proposed immutable types:

```text
EanMergeAnalysisRole
  ORDERED_CORRIDOR
  BRANCH_INTERNAL
  MERGE_RESOURCE
  MERGE_PROPAGATED
  UNCLASSIFIED

EanMergeProofStatus
  PROVEN
  REJECTED
  UNKNOWN

EanMergeResourceProof
  id
  status
  state_id
  checkpoint_id
  resource_id
  incoming_route_option_ids
  branch_resource_ids
  common_suffix_segment_ids
  continuation_resource_ids
  reason_codes

EanMergeFamilyAnalysis
  id
  direct_resource_proof
  propagated_checkpoint_ids
  family_end_reason
  candidate_count
  potential_original_pair_count

EanMergeConflictAnalysis
  scenario_id
  pattern_id
  resource_proofs
  families
  role_counts
  pair_count_accounting
  warnings
```

IDs and reason codes must be deterministic and independent of input tuple
ordering.

#### Step 0.1: Build the topology index

Input:

- `artifact.movement_network`;
- the selected `EanCirculationPattern`;
- `EanRouteOption.resource_usages`;
- segment paths;
- `artifact.headway_checkpoints`;
- `artifact.headway_candidates`;
- `artifact.resource_conflict_index`;
- timings and station Waiting modes.

For every pattern position:

1. group route options by `(from_state_id, to_state_id)`;
2. derive each option's ordered segment and resource sequence;
3. split the route into its branch-specific prefix and longest common suffix;
4. record the first common physical or compatibility resource;
5. map compatibility resources back to existing checkpoints;
6. reject inconsistent route targets or missing provenance as `UNKNOWN`.

For today's Skip station the expected structural shape is:

```text
SERVICE station resources ─┐
                            ├→ EXIT_SWITCH → common rope resource
SKIP bypass resources ──────┘
```

A no-Skip station with one route option is not a merge. Multiple options that
do not reconverge on the same target are not supported by the current
deterministic pattern and remain `UNKNOWN`.

#### Step 0.2: Prove direct merge resources

A checkpoint is `MERGE_RESOURCE/PROVEN` only when all conditions hold:

1. at least two distinct route options leave the same state;
2. those options reach the same deterministic successor state;
3. their branch-specific prefixes differ;
4. they share the checkpoint resource after reconvergence;
5. the shared resource applies to every relevant active route;
6. its time and activation semantics are supported by the existing complete
   separator;
7. no route bypasses the shared physical conflict.

The proof should normally identify the current active `EXIT_SWITCH`
compatibility resource and the common outgoing rope resource. It must not use
checkpoint kind alone.

The analyzer computes the potential original pair count without building
pairs:

\[
P_r=\binom{N_r}{2}
=
\frac{N_r(N_r-1)}{2},
\]

where \(N_r\) is the number of candidates at the merge checkpoint.

The report reconciles:

\[
P_{\mathrm{eager}}
=
P_{\mathrm{core}}+
P_{\mathrm{merge\ resource}}+
P_{\mathrm{unclassified}}.
\]

Any mismatch is an analysis error.

#### Step 0.3: Audit same-branch implications

For each proven merge resource, separately audit Service and Skip.

The audit asks whether retained constraints already imply the merge headway
when both visits take the same branch. A proof requires:

1. an upstream headway anchor active for that branch;
2. inherited order between the anchor and merge;
3. equal deterministic offsets for both cabins, or Waiting occupancy that
   explicitly preserves clearance;
4. an upstream headway at least as strong as the merge headway;
5. compatible activation and horizon semantics;
6. a valid boundary argument for first visits and initial placement.

Current expected proof patterns:

```text
SERVICE + no waiting
  platform-entry headway
  + equal service traversal time
  + station headway >= rope/exit headway

SERVICE + end-of-platform waiting
  platform-exit waiting-occupancy headway
  + equal post-platform traversal time

SKIP
  inherited incoming-rope order
  + equal skip traversal time
  + valid initial/boundary separation
```

The Skip proof must follow predecessor visits. It cannot assume that an
incoming rope remains separated when its own upstream merge constraint is
also planned for delay. Report this dependency explicitly. A cyclic
"merge A is implied by merge B, which is also delayed" is not an eager-core
proof.

Outputs per branch:

```text
same_branch_implication = proven | unknown | rejected
upstream_anchor_checkpoint_id
headway_margin_seconds
depends_on_delayed_family_ids
boundary_proof
reason_codes
```

This audit selects the recommended Phase-1 formulation:

- use route-conditional cross-stream delay only if both same-branch proofs are
  independent of delayed constraints;
- otherwise begin with merge-resource delay and report its weaker scope
  honestly;
- keep the whole resource eager if even the resource provenance or separator
  semantics are uncertain.

#### Step 0.4: Detect propagated reimposition

Removing the direct merge checkpoint may have little effect if a downstream
checkpoint immediately imposes the same unresolved order. For every proven
merge:

1. follow the common deterministic suffix;
2. propagate each event-time expression symbolically as
   \(t_{\mathrm{merge}}+\delta\);
3. compare activation, Waiting, horizon, and headway semantics;
4. label a downstream constraint `MERGE_PROPAGATED` only when both candidates
   receive the same fixed offset and the downstream row enforces the same or
   a weaker separation;
5. stop at Waiting, buffering, another route choice, another merge, unequal
   offsets, or incomplete provenance.

Record both:

- direct-only potential pair count;
- full proven-family potential pair count.

This reveals whether a direct exit-switch toggle would merely move the same
order decision to the next checkpoint.

#### Step 0.5: Produce machine and human reports

Add a build-only diagnostic entry point:

```text
python -m ropeway_skip_stop_optimization.benchmarking.ean_merge_conflicts
```

Inputs:

```text
--example
--artifact-construction network
--output
```

The diagnostic command constructs a candidate-only network artifact with the
existing `SparseHeadwayPairBuilder`. It must not build the normal eager
artifact first. Full, core, and merge pair counts are calculated
combinatorially per checkpoint and are compared with eager artifacts only in
small regression cases. This is required for OIP38 and OIP76, where merely
building the eager input would defeat the purpose of the diagnostic.

Outputs:

```text
merge_conflict_analysis.json
merge_conflict_analysis.md
```

The JSON is the stable machine-readable source. The Markdown contains:

- scenario, fleet mode, and actual \(K\);
- topology and route-option summary;
- resource proof table;
- eager/core/direct/propagated/unclassified candidate and pair counts;
- pair percentages without materializing omitted combinations;
- same-branch implication audit;
- warnings and unsupported cases;
- recommended Phase-1 scope;
- analysis runtime and peak RSS.

The command must not instantiate a Gurobi model or require a solver license.
The current package may still resolve the installed `gurobipy` dependency
through public exports; removing that import coupling is not a prerequisite
for this diagnostic.

#### Step 0.6: Unit and topology tests

Add:

```text
tests/test_optimization_ean_merge_conflict_analysis.py
tests/test_benchmarking_ean_merge_conflicts.py
```

Required cases:

- no-Skip state is `REJECTED`, not a merge;
- Service/Skip routes with a common successor and rope produce one stable
  proven merge resource;
- an ordinary exit switch with one route is not mislabeled;
- route alternatives with different targets are `UNKNOWN`;
- branch prefixes and common suffix are deterministic;
- shared physical `resource_id` is recognized;
- missing resource provenance remains eager;
- no-wait Service implication checks fixed offsets and headway dominance;
- Waiting Service implication uses platform-exit occupancy;
- Skip implication exposes dependencies on an upstream delayed merge;
- horizon or activation mismatch prevents a proof;
- propagated-family detection stops at Waiting and another decision;
- combinatorial counts reconcile exactly with existing eager artifacts;
- repeated analysis is byte-stable;
- the diagnostic runs without model construction or a solver license.

Do not add solver-equivalence tests in Phase 0 because no solver formulation
changes.

#### Step 0.7: Diagnostic matrix

Run on:

- Three Station fixed \(K=15\);
- Five Circle fixed \(K=19\), Skip/No-Wait;
- Five Circle fixed \(K=19\), Skip+Wait;
- Five Circle no-Skip \(K=38\);
- current OIP38 and OIP76 artifacts for build-only counts.

Store the interpreted measurements in `docs/findings`, not in this plan.

Verify that:

- no-Skip cases contain no unexplained merge families;
- current Skip stations are recognized through route/resource structure;
- every proposed delayed resource has a stable proof;
- ordinary exit-switch safety is not mislabeled;
- direct and propagated counts are reported separately;
- the analysis itself does not materialize the full or delayed pair universe;
- Phase 1 receives an explicit recommendation between resource-level and
  cross-stream-conditional delay.

#### Phase-0 acceptance gate

Proceed to Phase 1 only when:

1. pair accounting matches the current eager artifact exactly;
2. no-Skip reference cases yield zero delayed merge resources;
3. every delayed resource has `PROVEN` topology and separator semantics;
4. every unknown case remains eager;
5. the delayed universe is materially smaller than all eager headways;
6. the analyzer is cheap relative to artifact construction;
7. tests demonstrate deterministic output;
8. the report states whether same-branch constraints can safely stay eager.

Stop and revise the network provenance if the classifier cannot isolate a
useful merge universe without relying on checkpoint names or example-specific
IDs.

### Phase 1: Fixed-start hybrid builder

Add `EAGER_CORE_WITH_DELAYED_MERGES` for fixed starts:

- build the unchanged eager core;
- omit only proven merge families;
- retain delayed candidate indexes;
- expose unambiguous hybrid artifact coverage.

No OIP changes belong in this phase.

### Phase 2: Fixed-start iterative solve

Adapt the existing Fixed-\(K\) delayed loop and dynamic constraint pool to the
integrated passenger optimizer:

- total per-run budget rather than a fresh budget per re-solve;
- complete merge separation;
- deterministic batching;
- partial passenger and movement warm starts;
- final full separation;
- result and progress metrics.

Compare against eager at identical fixed starts and budgets.

### Phase 3: Exact small-case equivalence

For small One-, Three-, and Five-Station instances:

- compare eager and hybrid feasibility;
- compare exact optimal objectives;
- validate movement and passengers independently;
- assert complete final separation;
- assert that every dynamically added pair exists in the original eager
  universe;
- compare results with Waiting enabled and disabled.

Do not begin OIP integration before these tests pass.

### Phase 4: Fixed-\(K\) OIP

Add OIP with exactly \(K\) cabin objects:

- all cabins active;
- no optional fleet-selection search;
- complete initial-state ordering;
- initial placement constraints remain eager;
- fixed-start solution as an OIP warm start;
- delayed generation remains limited to merge families.

Test \(K=19\) before \(K=38\). Do not return to OIP76 in this phase.

### Phase 5: Multiple fixed-\(K\) evaluations

Only after one OIP Fixed-\(K\) run is reliable:

- evaluate selected \(K\) values as independent studies;
- cache results by scenario, demand, \(K\), configuration, and code version;
- warm-start neighbouring \(K\) values where valid;
- compare only fully separated feasible objectives;
- never rank fleets by an unseparated relaxed incumbent.

Optuna or another adaptive outer search remains optional and outside the
first acceptance gate.

## Tests

### Unit tests

- conflict classification for ordered corridor, branch internal, direct
  merge, propagated merge, and unclassified cases;
- stable merge-family and pair IDs;
- Service/Skip activation;
- point headways;
- platform waiting occupancy;
- exact horizon filtering;
- deterministic violation ordering;
- batch limits;
- duplicate augmentation rejection;
- materialized-pair violation detection;
- final full-separation certificate.

### Dynamic model tests

- one added disjunctive pair creates exactly one binary and two rows;
- a fixed-direction eager pair creates no delayed binary;
- repeated augmentation of the same pair fails;
- an eager-core pair can never enter the delayed pool;
- a route change after re-solve does not invalidate an already added original
  headway constraint;
- the total solve budget includes every solve, separation, and augmentation.

### Solver equivalence

- eager and hybrid return the same exact optimum on small cases;
- eager infeasibility is reproduced;
- hybrid infeasibility is reported only from an infeasible relaxation;
- a separated time-limit incumbent is feasible but not falsely labelled
  optimal;
- an unseparated time-limit incumbent returns `UNKNOWN`;
- full validation passes for every accepted solution.

### Regression

- existing eager mode remains unchanged;
- existing delayed-all Fixed-\(K\) capacity mode remains unchanged;
- all current tests remain green;
- serialized old results remain readable;
- frontend export distinguishes hybrid progress and certification.

## Experimental Acceptance

### Primary fixed-start experiment

Use Five-Station Circle \(K=19\):

- Skip/No-Wait;
- Skip+Wait;
- integrated Journey-Time objective;
- identical starts, MIP start, seed, threads, and time budget;
- eager all-pairs versus hybrid delayed merges.

Compare at 5, 15, and 30 minutes:

- setup time;
- root time;
- time to first incumbent;
- incumbent objective;
- best bound and gap;
- nodes;
- materialized fraction of the delayed universe;
- separation rounds and time;
- final certificate.

The approach proceeds to OIP when it provides a substantial improvement in
at least one central scaling metric without degrading correctness:

- materially faster first incumbent or bound progress;
- materially smaller initial model;
- only a minority of potential merge pairs materialized;
- a completely separated feasible solution inside the experimental budget.

Do not define success only as a lower setup time if branch-and-bound progress
does not improve.

### OIP experiment

After fixed-start acceptance:

1. Five Circle OIP, exact \(K=19\);
2. Five Circle OIP, exact \(K=38\);
3. only then larger line/ring cases.

Compare:

- fixed-start versus optimized placement objective;
- number of OIP placement decisions;
- time to first separated incumbent;
- merge pairs generated;
- root and total gap;
- improvement over the fixed-start warm start.

## Expected Outcomes and Stop Criteria

The expected positive outcome is:

- the eager core remains strong enough to produce meaningful schedules;
- few merge pairs are violated per incumbent;
- the cumulative materialized merge set is far smaller than the eager
  all-pairs set;
- model construction and root processing improve;
- Fixed-\(K\) OIP becomes usable without optional-fleet symmetry.

Stop or redesign when:

- propagated downstream constraints reproduce almost the complete pair set;
- most merge pairs are eventually materialized;
- separation dominates runtime;
- the relaxed core repeatedly chooses grossly colliding schedules;
- fixed-start search does not improve materially;
- OIP placement changes cause endless order oscillation;
- the eager core itself remains the measured bottleneck.

If only a few merge pairs are needed but repeated global re-solves dominate,
the next step is a restricted merge-order repair MIP or solver-specific
callback architecture with preallocated local order variables. Do not adopt
that complexity before the outer-loop measurements justify it.

## Thesis Integration

Document the method as:

> exact outer row-and-column generation for topology-proven merge headway
> disjunctions in a fixed-fleet event-activity network.

The thesis must distinguish it from:

- eager all-pairs headways;
- delayed generation of every headway family;
- heuristic relax-and-retime;
- Logic-Based Benders;
- Conflict-Based Search.

Include:

1. the fixed-\(K\) formulation;
2. eager/delayed constraint partition;
3. topology-derived merge provenance;
4. the monotone relaxation sequence and correctness proof;
5. the final-separation certificate;
6. fixed-start ablation results;
7. OIP results only after fixed-start validation;
8. build, solve, memory, and generated-pair measurements.

No claim that merge conflicts are the dominant bottleneck may be made before
the matched ablation supports it.

## Assumptions

- The physical scenario and canonical movement network remain the source of
  truth.
- The first version uses exactly \(K\) cabins.
- Fixed starts are diagnostic; OIP with exact \(K\) is the target.
- Every dynamically added pair is an unchanged original headway
  disjunction.
- Unknown conflict provenance stays eager.
- Feasibility requires complete final separation.
- The eager and delayed-all modes remain available as references.
- Passenger assignment remains integrated during the principal comparison.
- Greedy trajectory shifting is not part of this plan.

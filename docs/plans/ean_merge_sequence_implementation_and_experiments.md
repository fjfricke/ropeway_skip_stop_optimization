# Merge-Sequence EAN: Implementation and Experiment Plan

Status: **Tranches 0--2 implemented; isolated performance gate failed**

## Implementation Outcome

The plan's mandatory early stop condition was reached before chained or full
EAN integration:

- the canonical Merge Domain, explicit Pairwise FIFO reference, complete
  enumeration oracle, Pairwise, Lattice, Slot, and CP-SAT isolated
  formulations, tests, and benchmark runner were implemented;
- all isolated formulations returned the same objective on solved instances;
- the current EAN timing/resource structure rejected the tested
  same-Service-branch reorder even in legacy Pairwise mode, indicating that
  Platform Entry plus Platform Exit/Waiting occupancy already imply FIFO for
  the audited case; the explicit FIFO rows remain a semantic audit option;
- at \(10+10\), adversarial releases, the final reference run proved optimal
  in \(0.82\) s (Pairwise FIFO), \(2.05\) s (Lattice), and \(4.70\) s (Slots);
- at \(20+20\), 60 s each, all three found objective \(4833\), but certified
  bounds were approximately \(2525.19\) (Pairwise), \(2007.14\) (Lattice), and
  \(2445.52\) (Slots). The Lattice and Slot extended formulations therefore did
  not improve the proof gap;
- across \(5+5\) and \(10+10\) uniform, clustered, and adversarial cases,
  Pairwise was generally fastest; the isolated median gate did not approach
  the required twofold improvement.

According to Sections 20--22, Tranches 3--6 are therefore intentionally not
activated. In particular, the implementation does not omit production EAN
Pairs, does not introduce `PARTITIONED` artifacts, and does not expose a
partially certified Merge-Sequence Passenger model. The negative result and
the benchmark machinery are retained for reproducibility.

Conceptual parent:
[`ean_merge_sequence_reformulation.md`](ean_merge_sequence_reformulation.md)

## 1. Resolved Model Contract

The following physical semantics are decided and are no longer an experimental
assumption:

> Cabins cannot overtake on either branch of a Stop/Skip station. Waiting can
> change event times and gaps, but it cannot change the order of cabins that
> use the same branch.

Consequently, for the ordered input sequence \(\pi_r\) at merge sequence block
\(r\), route decision \(z_{ir}=1\) for Service and \(z_{ir}=0\) for Skip, the
two branch streams are the stable subsequences

\[
S_r=\operatorname{filter}(\pi_r,z_{ir}=1),
\qquad
P_r=\operatorname{filter}(\pi_r,z_{ir}=0).
\]

The order after reconvergence must be a stable merge:

\[
\pi_{r+1}\in\operatorname{shuffle}(S_r,P_r).
\]

No formulation may permit:

- Service/Service reordering;
- Skip/Skip reordering;
- reordering on the common Rope corridor after reconvergence;
- artificial Waiting on the Skip branch.

Service and Skip cabins may pass one another because they use different
branches. That cross-branch interleaving is the merge decision.

### Consequence for legacy comparisons

Before performance comparisons, test whether the current Pairwise EAN already
implies this same-branch FIFO contract. If it does not, introduce an exact
`PAIRWISE_FIFO` reference. The current broader legacy model remains available
only for regression and must not be used as the objective-equivalence oracle
for the physical model.

## 2. Scope and Deferred Work

The first implementation supports:

- Fixed Starts;
- exactly Fixed \(K\);
- one deterministic `EanCirculationPattern`;
- current line and ring examples;
- Service/Skip reconvergence at the station exit;
- No-Wait first, then continuous bounded end-of-platform Waiting;
- current Constant and Leader-Behavior headway rules;
- Journey Time as the primary Passenger objective;
- complete independent movement and Passenger validation.

Deferred until the Fixed-Start gate passes:

- optimized initial placement;
- variable active fleet size in one solve;
- dynamic turnbacks and Rope transfers;
- more than two incoming branches;
- Passenger decomposition;
- Branch-Price-and-Cut;
- production-default changes.

## 3. Existing Code to Reuse

The implementation must extend the current EAN instead of introducing a
second movement model.

### Canonical topology

Reuse:

```text
optimization/ean/network.py
    EanMovementNetwork
    EanMovementState
    EanRouteOption
    EanResourceUsage
    EanCirculationPattern
    EanResourceConflictIndex
```

`PhysicalMovementNetworkBuilder` already proves that the current Service and
Skip routes reconverge and continue through one Rope segment to the next
state. The merge analyzer adds FIFO and sequence-block provenance; it does not
rebuild physical topology.

### Candidate and timing expressions

Reuse:

```text
HeadwayCandidate
HeadwayCheckpointDefinition
headway_time_expressions(...)
candidate_inactive_expr(...)
```

The current `EXIT_SWITCH` candidate is active for either Service or Skip and
uses the visit's `stop` variable to determine behavior. Do not duplicate the
physical event merely to create route-specific candidates.

### Existing order propagation

`EanHeadwayOrderFamilyIndex` currently traces a pair's order back to its last
route-choice boundary and reuses one order binary on downstream resources.
Extract its predecessor and boundary traversal into a shared immutable
provenance service. The Pairwise Shared and Merge-Sequence formulations must
consume the same provenance.

### Independent safety certificate

Reuse `separate_all_headway_violations(...)`. It enumerates active candidates
without requiring persisted `HeadwayPair` objects and supports Constant and
Leader-Behavior rules. Every Merge-Sequence incumbent must pass it before it
can become a validated Upper Bound.

### Codebase compatibility audit

The implementation starts from these verified current boundaries:

| Current component | Current contract | Required change |
|---|---|---|
| `EanOptimizationConfig` | Boolean shared-order and diagnostic switches | Migrate order representation into one enum while retaining the shared-order CLI alias |
| `EanArtifactAssembler` | Checkpoints, Candidates, then Pairs | Insert Merge-Domain derivation between Candidates and partitioned Pair construction |
| `EanHeadwayPairScope` | `COMPLETE` or delayed-capacity `SPARSE` | Add `PARTITIONED`; do not reinterpret `SPARSE` |
| `EanHeadwayConstraintPool` | Original pair rows, dynamic augmentation, optional shared order families | Keep as owner of retained original pairs; add a sibling sequence formulation |
| `EanHeadwayOrderFamilyIndex` | Backward pair provenance on complete Fixed-Start artifacts | Extract reusable traversal, but do not treat pair-family sharing as a total-order proof |
| `EanFixedStartHeadwayClassifier` | Fixes direction only when conservative time bounds prove it | Reuse such classifications, but derive FIFO boundary order from physical starts/provenance rather than assuming the classifier provides it |
| `EanMovementVariables.all_variables()` | Enumerates flat movement dictionaries | Include structured merge variables explicitly |
| normal Passenger solver | Rejects `SPARSE` | Admit only exactly matched `PARTITIONED + MERGE_SEQUENCE` |
| `separate_all_headway_violations` | Complete Candidate-based physical check | Reuse unchanged as final headway certificate |
| `GurobiMipProgressRecorder` | Presolve, root, incumbent, node, Work, memory samples | Extend output fields; do not create a competing callback implementation |

The current Exit-Switch Candidate is already one route-agnostic physical event
with `ACTIVE` activation. Route-specific slot variables therefore select the
behavior of that event; they must not create duplicate Service and Skip
Candidates. The current Constant and Leader-Behavior rules are compatible with
adjacent sequence rows because the required separation is constant or depends
only on the selected leader behavior.

## 4. Public Formulation Configuration

Order representation is a mutually exclusive formulation category, not a set
of independent Boolean optimizations.

Add to `formulation_config.py`:

```text
EanHeadwayOrderFormulation
    PAIRWISE_EAGER
    PAIRWISE_SHARED
    PAIRWISE_FIFO
    MERGE_SEQUENCE
```

Default:

```text
PAIRWISE_EAGER
```

Migration:

- preserve the current CLI name `shared_merge_headway_order` as a deprecated
  compatibility alias for `PAIRWISE_SHARED` during the experiment branch;
- expose `PAIRWISE_FIFO` as the physical semantic reference if Experiment A
  proves that either legacy Pairwise mode permits same-branch reordering;
- keep triangle separation as an independent exact strengthening of
  `PAIRWISE_FIFO`, not another production formulation value;
- reject simultaneous explicit selection of the alias and another order
  formulation;
- keep delayed generation as a solve strategy, not as another static order
  formulation;
- serialize the resolved formulation, alias provenance, and fallback coverage.

The first Merge-Sequence implementation is supported only for Fixed Starts.
An explicit request under OIP raises a clear `NotImplementedError` rather than
silently falling back for the whole model.

## 5. Canonical Merge Domain

Add `optimization/ean/merge_sequence_domain.py`.

### Types

```text
EanMergeFamily
    id
    state_id
    station_id
    exit_checkpoint_id
    incoming_corridor_id
    outgoing_corridor_id
    service_option_id
    skip_option_id
    sequence_block_ids
    headway_rule_id
    proof

EanMergeSequenceBlockDefinition
    id
    family_id
    candidate_ids
    visit_keys
    predecessor_candidate_ids
    horizon_role

EanMergeOrderProof
    service_fifo
    skip_fifo
    outgoing_corridor_fifo
    predecessor_complete
    horizon_complete
    reasons

EanMergeSequenceDomain
    families
    sequence_blocks
    covered_candidate_ids
    eager_fallback_candidate_ids
```

All types are frozen dataclasses with stable sorted tuple fields and explicit
`validate()` methods.

The current `EanArtifactAssembler` builds Candidates and then immediately
builds Pairs. For the performance implementation this order must become:

```text
checkpoints -> candidates -> merge domain -> partitioned pairs -> artifact
```

The domain builder therefore accepts the already built network, visits,
checkpoints, and candidates without requiring an `EanBuildArtifact`. The
finished artifact stores immutable omission provenance and validates its
fingerprint against a deterministically rebuilt merge domain. This avoids a
circular dependency between artifact construction and pair omission.

### Builder

Add `EanMergeSequenceDomainBuilder`:

1. require one canonical circulation pattern;
2. locate states with exactly one Service and one Skip option;
3. verify common reconvergence and continuation from the movement network;
4. find the corresponding `EXIT_SWITCH` checkpoint;
5. group all cabin visits at one merge checkpoint into one deterministic
   finite-horizon sequence block;
6. map every downstream visit to its predecessor via cabin transitions;
7. attach headway rule and horizon semantics;
8. classify complete sequence coverage or eager fallback;
9. emit deterministic IDs independent of dictionary insertion order.

### Sequence-block definition

One physical Exit Switch is a continuously reused unary resource. The first
version therefore creates one sequence block per merge family over the whole
modeled horizon, containing all eligible cabin-visit candidates at that
checkpoint. Do not partition visits by equal `visit_index` or guessed
"rotations": cabins can start at different pattern phases and visits with
different indices can be temporal neighbours.

Block membership and predecessor mapping are derived through physical state,
cabin transitions, horizon activation, and the corridor event stream. A later
dynamic-routing implementation may need multiple blocks, which is why the
domain retains an explicit block type.

The Fixed Starts supply one local boundary order for every initially occupied
Rope segment or first Entry resource; there is no single global start order
when cabins begin at different pattern phases. Every subsequent interior
corridor input order is the previous merge output order transported through
successive `SwitchVisitDefinition` items of the same cabin. The corresponding
`SwitchTransition` verifies the physical state transition but is not itself a
cabin-visit mapping.

At the finite-horizon boundary this transport is a partial bijection:

- an initial input prefix can have no modeled predecessor merge;
- an interior output has exactly one modeled successor input;
- a terminal output suffix can have no modeled successor visit.

Every unmatched event must carry explicit `INITIAL_BOUNDARY` or
`TERMINAL_BOUNDARY` provenance. It may not be silently dropped or matched by
equal visit index.

### Coverage policy

The first version reformulates only direct `EXIT_SWITCH` merge resources.

Keep in the eager resource model:

- Platform Entry;
- Platform Exit and Waiting occupancy;
- Service Mechanism;
- initial Rope separation;
- horizon-boundary conflicts not covered by a complete sequence block;
- every unclassified or partially proven resource.

`Eager` here describes when the resource rows are built, not free order. For
Service/Service pairs, Platform Entry, Platform Exit/Waiting occupancy, and
Service Mechanism must use the input branch order and directed conditional
headways. They must not retain an independent two-way disjunction. Skip/Skip
order is likewise inherited until the direct merge. Only a Service/Skip pair
has a free cross-branch order at reconvergence.

Only after direct-merge equivalence is established may propagated downstream
pair families be removed in favor of the explicit corridor order.

If build metrics then show that the retained Service-only resources dominate,
add a second gated compression: the same stable-filter state that forms
\(S_r\) provides a compact Service subsequence, and adjacent Platform Entry,
Platform Exit/Waiting-occupancy, and Service-Mechanism rows are enforced on
that subsequence. This replaces directed all-pairs rows without introducing a
new order decision. It is not part of the first direct-merge correctness
prototype and receives its own equivalence tests and metrics.

## 6. Pairwise FIFO Reference

Add `optimization/ean/merge_pairwise_fifo.py`.

The purpose is to define the exact physical reference independently of the new
extended formulation.

For two events \(i,j\) entering a station in order \(i\prec j\):

- if both select Service, enforce \(i\prec j\) at the exit;
- if both select Skip, enforce \(i\prec j\) at the exit;
- if they select different branches, retain the two-way merge disjunction.

For fixed route decisions, these are ordinary directed rows. For endogenous
routes, use conditional propagation from the input-order binary to the output
order binary.

Positive headway timing already makes an integer directed cycle infeasible, so
triangle inequalities are not required for integer exactness. Keep the plain
Pairwise FIFO formulation as the semantic reference and test triangle rows as
an independent LP-strengthening option:

1. full triangle inequalities on tiny models;
2. delayed separation of violated 3-cycles for larger reference models.

For distinct events \(i,j,k\), a representative linear-order inequality is:

\[
o_{ij}+o_{jk}-1\le o_{ik}.
\]

Report both `PAIRWISE_FIFO` and `PAIRWISE_FIFO_TRIANGLES`. This distinguishes
the gain from correcting FIFO, strengthening transitivity, and using the
sequence extended formulation itself.

## 7. Merge Formulation Protocol

Add `optimization/ean/merge_sequence_formulation.py`.

```text
class EanMergeOrderFormulation(Protocol):
    build_domain(...)
    add_variables(...)
    add_constraints(...)
    apply_start(...)
    extract(...)
    metrics(...)
```

Implementations:

```text
EanPairwiseEagerMergeOrder
EanPairwiseSharedMergeOrder
EanPairwiseFifoMergeOrder
EanLatticeMergeOrder
EanSlotMergeOrder
```

The protocol receives existing event-time, route-activation, and horizon
expressions. It may not create duplicate Stop, Waiting, or movement-time
variables.

### Common result

```text
EanMergeOrderModel
    order_variables
    slot_variables
    state_flow_variables
    position_variables
    covered_pair_ids
    fallback_pair_ids
    build_metrics
```

`EanMovementVariables` gains an optional structured merge-order member. Do not
store every new variable in the flat `headway_order` dictionary.

Its `all_variables()` implementation must include every variable in that
structured member. The existing solver uses this method for aggregate model
operations; omitting sequence variables would silently make fixing and other
generic handling incomplete.

## 8. Isolated Fixed-Input Lattice Formulation

For known ordered Service and Skip streams

\[
S=(s_1,\ldots,s_m),
\qquad
P=(p_1,\ldots,p_n),
\]

create states

\[
V=\{(i,j):0\le i\le m,\ 0\le j\le n\}.
\]

East arc \((i,j)\to(i+1,j)\) schedules \(s_{i+1}\); north arc
\((i,j)\to(i,j+1)\) schedules \(p_{j+1}\). Add one unit of flow from
\((0,0)\) to \((m,n)\).

Each selected transition links its state time to the actual candidate time.
Consecutive selected events satisfy the resource headway.

This formulation is used first only in isolated and first-boundary merge
tests, where input identities and branch membership are fixed. It is the
cleanest mathematical gate but not yet the complete repeated-ring model.

## 9. Slot Formulation for Repeated Merges

For merge sequence block \(r\), create output slots
\(q=0,\ldots,N_r-1\).

Use route-specific assignment variables:

\[
x^{S}_{irq}=1
\quad\Longleftrightarrow\quad
i\text{ is Service and occupies slot }q,
\]

\[
x^{P}_{irq}=1
\quad\Longleftrightarrow\quad
i\text{ is Skip and occupies slot }q.
\]

Activation:

\[
\sum_q x^S_{irq}=z_{ir},
\qquad
\sum_q x^P_{irq}=a_{ir}-z_{ir}.
\]

Slot occupancy:

\[
\sum_i(x^S_{irq}+x^P_{irq})=u_{rq},
\qquad
u_{r,q+1}\le u_{rq}.
\]

Under Legacy Horizon all modeled candidates are active and every slot is
filled. Under Exact-Time Activation, \(u\) is the canonical active prefix.

### Slot time

Link `slot_enter[r,q]` and `slot_clear[r,q]` to the assigned candidate's
existing expressions. Prefer Gurobi indicator constraints in the first
correctness prototype; add a bounded convex-hull version only after the gate
measures indicator weakness.

### Leader-dependent headway

Current rules are either Constant or depend only on the leader's route
behavior. Define:

\[
h_{rq}
=h^S_r\sum_i x^S_{irq}
+h^P_r\sum_i x^P_{irq}.
\]

Then:

\[
\operatorname{enter}_{r,q+1}
\ge
\operatorname{clear}_{rq}+h_{rq}
-M(2-u_{rq}-u_{r,q+1}).
\]

This is linear and exactly represents `LeaderBehaviorHeadwayRule`. A future
Follower- or pair-dependent rule requires transition variables or eager
fallback.

Before creating Gurobi variables, compute a deterministic size estimate for
every block: projected assignment binaries, linking rows, nonzeros, and bytes
under a documented conservative coefficient-storage factor. Abort the
experimental formulation cleanly when the configured gate is exceeded. Pair
omission that merely creates a larger unbounded assignment matrix is not a
performance success.

### Stable branch order

The output slots must be a stable merge of the input corridor order.

Prototype and compare two exact encodings:

#### A. Conditional rank propagation

Derive one integer output position from the assignment. Reuse the input order
reference from the predecessor corridor. When two candidates select the same
branch, conditionally preserve their relative order.

#### B. Permutation-network transition

Represent the station as a stable two-color merge network whose state carries
the input position and numbers of emitted Service and Skip events. Link event
identity through sparse flow conservation.

The isolated chained-merge gate selects A or B. Do not choose solely by source
code size; compare root relaxation, model growth, and proof time.

## 10. Corridor Order Propagation

Add `optimization/ean/corridor_order.py`.

```text
EanCorridorOrderState
    corridor_id
    source_merge_block_id
    target_merge_block_id
    candidate_transition
    ordered_slots
```

For the interior mapped subset, the output slot of one merge is transported
through successive visits of the same cabin to the corresponding input event
at the next state. The static `SwitchTransition` validates that physical
movement. No new order decision is allowed on the Rope.

The initial boundary prefix and terminal boundary suffix are represented
explicitly and are not required to have a predecessor or successor inside the
model. Thus corridor transport is one-to-one on its declared interior domain,
not necessarily across every event in both finite-horizon blocks.

Tests must include cabins starting at different pattern phases and visits that
cross the horizon boundary. A mapping based only on equal visit indices is
invalid.

## 11. Model Coverage and Pair Materialization

The current `EanHeadwayPairScope` only distinguishes `COMPLETE` and `SPARSE`,
and the normal Passenger solver explicitly rejects `SPARSE`. Do not weaken
that guard. A model in which selected checkpoints are certified by a sequence
formulation needs a separate typed scope.

Add:

```text
EanHeadwayPairScope.PARTITIONED

EanHeadwayPairOmissionProvenance
    omitted_checkpoint_ids
    retained_checkpoint_ids
    estimated_omitted_pair_count
    merge_domain_fingerprint
    reason = "merge_sequence"
```

`PARTITIONED` describes how an artifact was built; it is not by itself a
safety certificate. `SPARSE` keeps its existing delayed-capacity meaning.

Final coverage depends on the selected solver formulation and therefore does
not belong to the canonical physical artifact. Add an additive model and
result certificate:

```text
EanHeadwayConstraintCoverage
    eager_complete_checkpoint_ids
    sequence_complete_checkpoint_ids
    sparse_checkpoint_ids
    omitted_pair_count_by_reason
    merge_domain_fingerprint
```

Store it on `EanMovementModel`, build metrics, and the optimization result. It
references the immutable artifact and merge-domain fingerprints.

### Correctness prototype

Initially build a complete artifact and partition its pairs in the Movement
model:

- eager pairs are sent to `EanHeadwayConstraintPool`;
- sequence-covered direct-merge pairs are withheld;
- the complete pair set remains available for equivalence tests.

### Performance implementation

After correctness is established, add a `PartitionedHeadwayPairBuilder` that
prevents pair materialization for sequence-covered checkpoints and writes the
omission provenance. Preserve deterministic pair-count estimates and complete
separation from candidates.

Update the normal solver guard as follows:

```text
COMPLETE
    accepted by all existing formulations

PARTITIONED
    accepted only by MERGE_SEQUENCE
    omission provenance must exactly match the rebuilt merge domain

SPARSE
    remains rejected by the normal Passenger solver
    remains reserved for the delayed Fixed-K Capacity optimizer
```

Unsupported combinations fail explicitly:

- the existing `EanHeadwayOrderFamilyIndex` and diagnostic merge relaxation
  continue to require `COMPLETE`;
- the delayed Fixed-\(K\) Capacity optimizer continues to require `SPARSE` in
  delayed mode and rejects `PARTITIONED`;
- `PAIRWISE_EAGER`, `PAIRWISE_SHARED`, and `PAIRWISE_FIFO` reject
  `PARTITIONED` artifacts;
- only `MERGE_SEQUENCE` may consume `PARTITIONED`, after exact
  fingerprint/provenance agreement.

A sparse or partially materialized artifact alone is never fully safe. A
solved result may be accepted as fully safe only when the model coverage
certificate accounts for every checkpoint and the final independent separator
is complete.

Validation behavior:

- `COMPLETE`: retain the current persisted-pair validation and additionally
  validate FIFO when that semantic version is active;
- `PARTITIONED`: always run complete candidate separation plus the independent
  Merge-Sequence/FIFO validator;
- `SPARSE`: retain the existing delayed-path behavior.

## 12. Movement-Model Integration

Refactor `_add_headway_constraints(...)` into orchestration over resource
families:

```text
EanHeadwayModelBuilder
    build_candidate_expressions(...)
    partition_resources(...)
    add_eager_pairwise_resources(...)
    add_merge_sequence_resources(...)
    build_coverage_certificate(...)
```

Do not add another monolithic branch to `movement_model.py`.

The existing `EanHeadwayConstraintPool` remains responsible for eager and
delayed original pairs. The new sequence builder owns only proven merge
resources.

Required Movement build metrics:

```text
merge_family_count
merge_sequence_block_count
sequence_covered_candidate_count
sequence_covered_pair_count
eager_fallback_pair_count
lattice_state_count
lattice_arc_count
slot_assignment_binary_count
active_slot_binary_count
sequence_constraint_count
headway_adjacent_row_count
fifo_propagation_row_count
sequence_build_seconds
```

Peak RSS is a process-level benchmark measurement and belongs in the runner
output rather than `EanMovementBuildMetrics`.

Update optimization metadata to distinguish:

```text
estimated_complete_headway_pair_count
artifact_materialized_headway_pair_count
model_pairwise_headway_row_count
sequence_covered_pair_count
```

The existing `headway_pair_count=len(artifact.headway_pairs)` is insufficient
for a partitioned model and must not be presented as total physical coverage.

## 13. MIP Starts and Extraction

### MIP start

From any independently validated `EanMovementPlan`:

1. sort active candidates at each merge by actual entry time;
2. reject ties inside the headway tolerance;
3. assign route-specific slots;
4. reconstruct lattice arcs where applicable;
5. verify stable same-branch order;
6. set starts only for compatible variables.

An incompatible seed is reported and ignored for sequence variables; it may
still seed the unchanged movement and Passenger variables.

### Extraction

Extract:

```text
EanMergeSequencePlan
    family_id
    sequence_block_id
    ordered_candidate_ids
    route_behaviors
    entry_times
    clear_times
    adjacent_required_headways
    adjacent_margins
```

Cross-check it against the ordinary `EanMovementPlan`. Sequence data is
diagnostic provenance, not a second source of movement truth.

Optimization metadata counts structured sequence variables separately. The
existing `headway_order_variable_count` continues to mean the size of the
legacy flat pairwise dictionary and must not silently change meaning.

## 14. Independent Validation

Add `EanMergeSequenceValidator` with these checks:

1. every active merge candidate occurs exactly once;
2. no inactive candidate occurs;
3. every slot prefix is canonical;
4. Service candidates preserve their input order;
5. Skip candidates preserve their input order;
6. every declared interior output-to-next-corridor mapping is one-to-one and
   every unmatched event has explicit boundary provenance;
7. adjacent point or interval headway is satisfied;
8. leader-dependent required headway is evaluated from extracted behavior;
9. Waiting is nonnegative, bounded, and Service-only;
10. all original headway candidates pass
    `separate_all_headway_violations(...)`;
11. fixed-movement Passenger reevaluation matches the integrated objective.

No incumbent enters the public Upper Bound unless all checks pass.

## 15. Test Plan

### 15.1 Domain unit tests

Add `tests/test_optimization_ean_merge_sequence_domain.py`:

- one Service/Skip reconvergence produces one family;
- no-Skip station produces no merge family;
- direct exit checkpoint is selected, Platform resources remain eager;
- candidates at different start phases map through transitions correctly;
- deterministic IDs survive input permutation;
- missing predecessor or horizon coverage causes eager fallback;
- multiple circulation patterns are rejected in version one;
- duplicate candidates and ambiguous transitions fail clearly.

### 15.2 Enumeration/property tests

Add `tests/test_optimization_ean_merge_sequence_enumeration.py`:

- lattice paths equal all \(\binom{m+n}{m}\) shuffles for \(m,n\le4\);
- every shuffle preserves both branch orders;
- every valid shuffle has exactly one lattice path;
- random fixed-input instances agree with brute force;
- Constant and Leader-Behavior rules agree with direct evaluation;
- continuous Waiting changes times but never same-branch order.

Use deterministic property-test seeds and retain failing instances as fixtures.

### 15.3 Pairwise FIFO tests

- construct a legacy-feasible same-branch reorder and determine whether the
  current model accepts it;
- `PAIRWISE_FIFO` rejects it;
- cross-branch overtaking remains feasible;
- triangle separation removes a directed 3-cycle;
- Pairwise FIFO and enumeration agree on tiny cases.

### 15.4 Slot/lattice model tests

- every active event receives exactly one route-specific slot;
- route-specific assignment agrees with `stop`;
- no holes appear in an active slot prefix;
- adjacent rows use the selected leader behavior;
- Skip cannot acquire Waiting;
- a second solve extracts the same stable deterministic sequence;
- MIP-start reconstruction round-trips.

### 15.5 Chained merge tests

- output order of merge A is input order of merge B;
- same-branch order survives A and B;
- cross-branch order may change independently at each station;
- cabin visit indices with different initial phases map correctly;
- a horizon-boundary event is neither duplicated nor lost.
- optional compact Service-subsequence rows agree with the directed all-pairs
  reference for point and Waiting-occupancy resources.

### 15.6 Integrated exactness tests

For One-, Three-, and small Five-Station cases compare:

- movement feasibility;
- optimum movement-only objective;
- Journey-Time Passenger optimum;
- Waiting-Time Passenger optimum;
- extracted route choices and event times;
- full separator result;
- fixed-movement Passenger reevaluation.

The oracle is brute force for tiny cases and `PAIRWISE_FIFO` for larger solved
cases. The broader legacy Pairwise model is reported separately if its feasible
set differs.

### 15.7 Regression

- default `PAIRWISE_EAGER` results remain unchanged;
- `PAIRWISE_SHARED` reproduces the current shared-order implementation;
- existing delayed headway and Capacity tests remain green;
- complete test suite passes;
- Ruff and `git diff --check` pass;
- frontend build remains green if output schemas change.

## 16. Benchmark Runner

Add:

```text
src/.../benchmarking/ean_merge_sequence.py
benchmarks/run_ean_merge_sequence_gate.py
```

CLI:

```text
--case isolated|chained|integrated
--formulation pairwise_legacy|pairwise_fifo|pairwise_shared|lattice|slots|cp_sat
--stream-size N
--k K
--waiting-headway-multiplier X
--route-mode fixed|endogenous
--release-pattern uniform|clustered|adversarial
--objective feasibility|total_delay|journey_time|waiting_time
--time-limit SECONDS
--threads N
--seed N
--output-dir PATH
--progress
```

Every output contains the complete instance fingerprint, resolved formulation,
coverage certificate, solver parameters, model metrics, progress samples,
validation result, and bound provenance.

Reuse the existing `GurobiMipProgressRecorder` and EAN build-progress callback
instead of creating a second callback stack. Extend their serialized samples
with merge stage and coverage fields while preserving the existing presolve,
root, incumbent, node, Work, and memory semantics.

## 17. Experimental Sequence

### Experiment A: semantic audit

Purpose: determine whether legacy Pairwise already enforces the newly fixed
FIFO semantics.

Cases:

- two Service cabins with unequal Waiting;
- two Skip cabins;
- one Service and one Skip cabin;
- three cabins creating a potential order cycle.

Output:

- accepted/rejected schedules;
- exact difference between `PAIRWISE_LEGACY` and `PAIRWISE_FIFO`;
- decision whether historical objectives remain comparable.

### Experiment B: isolated fixed-input merge

Matrix:

```text
stream sizes     5+5, 10+10, 20+20, 40+40
waiting          0, 0.5h, h, 2h
release pattern  uniform, clustered, adversarial
formulations     pairwise_fifo, pairwise_fifo_triangles, lattice, slots, cp_sat
```

Use feasibility and weighted total delay. Tiny cases also use complete
enumeration.

Development A/B settings:

- one solver thread;
- fixed seed;
- deterministic input order;
- 30 seconds up to \(10+10\);
- 120 seconds for \(20+20\) and \(40+40\);
- record Gurobi Work as well as wall time.

Gate:

- exact agreement on every solved case;
- no final validation failure;
- sequence formulation no worse than Pairwise FIFO at the root on median;
- at least 2x median proof-time improvement at \(20+20\), or at least two
  additional solved hard instances at equal budget.

### Experiment C: chained two- and five-merge microinstances

Purpose: select conditional-rank or permutation-network propagation.

Matrix:

```text
events           10, 20, 40
merges           2, 5
route mode       fixed, endogenous
waiting          0, h
```

Include `PAIRWISE_SHARED` and a FIFO-corrected shared-pair variant here, where
downstream order reuse actually exists. It is not informative in the isolated
single-merge benchmark.

Gate:

- exact agreement with small enumeration;
- model growth no worse than quadratic per merge for the selected
  implementation;
- no independent reordering on corridors;
- better root or proof behavior than Pairwise FIFO.

### Experiment D: integrated fixed-route EAN

Freeze route decisions from the same validated seed but reoptimize timing and
Passengers.

Cases:

1. Three-Station small merge fixture;
2. Five-Station architecture B, \(K=20\), No-Wait;
3. the same case with \(0.5h\) and \(h\) continuous Waiting;
4. Five-Station \(K=38\) build/root diagnostic.

This experiment isolates repeated sequence propagation and Passenger coupling.
Its bounds describe the restricted route problem. It may contribute a
validated Upper Bound to the endogenous-route problem after full validation,
but never a global Lower Bound for that larger feasible set.

### Experiment E: integrated endogenous Stop/Skip

Cases:

```text
Five-Station B
K               20, 38, 39
Waiting         0, 0.5h, h
Objective       journey_time
```

First budget: 15 minutes. Continue to one hour only if at least one of these
changes during the final five minutes:

- certified Lower Bound;
- validated Upper Bound;
- root relaxation progress;
- processed nodes with improving Best Bound.

Use identical seeds, start policy, horizon, demand, Passenger objective, solver
threads, and solver parameters for every formulation.

### Experiment F: thesis robustness

Only after Experiment E passes:

- Three-, Five-, and Six-Station topologies;
- low, medium, and concentrated demand;
- \(K\) below, at, and above the All-Stop frontier;
- No-Wait and selected bounded-Wait policies;
- at least three solver seeds for parallel production runs;
- 15-minute screening, one-hour regular, four-hour headline only for ongoing
  progress.

## 18. Comparison Metrics and Statistical Rules

For every run report:

```text
artifact build time
movement build time
passenger build time
peak RSS
variables / binaries / rows / nonzeros
root relaxation
root gap
time to first validated incumbent
best certified LB
best validated UB
absolute and relative gap
node count
Gurobi Work
sequence coverage and fallback
separator time and violation count
```

Do not compare objectives across different fingerprints or across legacy and
FIFO semantics when their feasible sets differ.

For a common minimization instance, the certified portfolio interval is:

\[
LB^*=\max_s LB_s,
\qquad
UB^*=\min_s UB_s.
\]

Restricted or fixed-route models do not contribute a global Lower Bound for
the endogenous-route problem. They may contribute a validated Upper Bound only
when the extracted schedule is feasible in the full problem.

## 19. Progress and Frontend Output

Terminal progress should show a stable line:

```text
MS K=039 stage=mip t=12:34 left=47:26 |
LB=... UB=... gap=... root=... nodes=... |
merge=85/85 slots=1640 fallback=0 violations=0
```

Frontend additions:

- resolved order formulation;
- FIFO semantic version;
- merge coverage percentage;
- sequence versus eager fallback counts;
- model-size comparison;
- Root/Incumbent/Gap timeline;
- validation badge;
- per-merge sequence viewer only after the solver experiment passes.

Do not implement the visual sequence viewer before the formulation gate.

## 20. Implementation Tranches

### Tranche 0: contract and audit

- encode FIFO semantic version;
- add adversarial same-branch reorder tests;
- document whether legacy differs;
- no solver-formulation change yet.

### Tranche 1: domain and provenance

- extract shared predecessor traversal;
- implement immutable merge domain and coverage;
- add domain tests and deterministic serialization.

### Tranche 2: isolated benchmark

- implement brute-force oracle;
- implement Pairwise FIFO, lattice, slots, and CP comparator;
- run Experiment B;
- stop if the gate fails.

### Tranche 3: chained sequence transition

- implement conditional-rank and permutation-network prototypes;
- run Experiment C;
- retain one implementation and delete the losing prototype unless it remains
  useful as a documented benchmark formulation.

### Tranche 4: EAN correctness integration

- add formulation category;
- refactor headway orchestration;
- integrate sequence-covered direct merges using complete artifacts;
- add extraction, warm start, and independent validation;
- run Experiment D.

### Tranche 5: performance integration

- avoid materializing sequence-covered pairs;
- add coverage certificate and memory metrics;
- measure retained Service-resource rows and enable compact Service-subsequence
  adjacency only if they are a demonstrated bottleneck;
- enable endogenous Stop/Skip;
- run Experiment E.

### Tranche 6: campaign and thesis

- add campaign config and live frontend fields;
- run robustness matrix;
- write mathematical proof, implementation details, and results into the
  thesis;
- consider a default change only after all acceptance gates pass.

Each tranche receives its own reviewable commit. Do not mix the current dirty
DDD/arc-flow work with Merge-Sequence commits.

## 21. Acceptance Criteria

The implementation is successful only when:

1. same-branch FIFO is enforced everywhere under the new semantic version;
2. tiny instances agree with brute force;
3. Pairwise FIFO and Merge Sequence have the same integer feasible projection;
4. every public incumbent passes complete headway and Passenger validation;
5. no sequence-covered conflict is silently absent;
6. the default legacy formulation remains reproducible;
7. at least one hard integrated case shows materially better certified gap
   progress at equal wall-clock budget;
8. model and experiment fingerprints are complete and reproducible;
9. the full test suite, Ruff, frontend build, and LaTeX build are green.

## 22. Stop Conditions

Stop before full EAN integration if:

- the isolated sequence formulations are weaker than Pairwise FIFO;
- continuous Waiting destroys the measured advantage;
- the chained transition requires super-quadratic growth at current case sizes;
- exact equivalence cannot be validated independently.

Stop before thesis campaign if:

- \(K=20\) regresses materially without compensating bound strength;
- \(K=38/39\) still shows no Root or incumbent progress;
- sequence coverage is low because most resources require eager fallback;
- memory grows beyond the current complete EAN baseline.

In that case retain the semantic FIFO correction and the negative formulation
result, and return to the certified solver portfolio rather than extending the
approach speculatively.

## 23. Decisions That Do Not Block Implementation

No additional user decision is required before Tranche 0. This plan adopts:

- Fixed Starts and Fixed \(K\) first;
- Journey Time as the primary integrated objective;
- No-Wait before bounded continuous Waiting;
- Legacy Horizon for the first fixed-cardinality correctness prototype;
- Exact-Time Activation as a later explicit compatibility test;
- Pairwise Eager as the unchanged production default during evaluation.

Any change to these choices should be made before Tranche 4, where it would
materially affect the integrated model.

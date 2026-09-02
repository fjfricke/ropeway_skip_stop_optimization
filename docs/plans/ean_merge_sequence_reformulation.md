# Merge-Sequence EAN Reformulation

Status: **isolated gate implemented and rejected for production integration**

Implementation detail and experiment execution are specified in
[`ean_merge_sequence_implementation_and_experiments.md`](ean_merge_sequence_implementation_and_experiments.md).

The physical FIFO assumption has been resolved: cabin order is preserved on
each individual Service or Skip branch; Waiting cannot reorder cabins on one
branch.

The isolated Pairwise, Lattice, Slot, and CP-SAT gate found no formulation
advantage. Pairwise FIFO was faster and had at least as strong a bound on the
tested larger case. The proposed production replacement below is therefore
retained as a researched hypothesis, not as recommended future work. See
[`../findings/ean_merge_sequence_gate.md`](../findings/ean_merge_sequence_gate.md).

## Decision Summary

The tested structural hypothesis was to replace the independent pairwise order
decisions at a proven Stop/Skip reconvergence by one explicit sequence decision
for the complete merge.

The experiment is deliberately narrower than a new end-to-end solver:

1. verify in topology provenance that the physically fixed FIFO contract is
   represented by every current station branch;
2. benchmark several exact formulations on isolated merge instances;
3. integrate the best formulation into the Fixed-\(K\), fixed-start EAN behind
   a separate formulation option;
4. compare it against Pairwise FIFO, the separately labelled legacy eager EAN,
   and delayed-pair EAN;
5. continue to larger networks only if the formulation improves both the root
   bound and primal progress.

The proposed formulation value is:

```text
MERGE_SEQUENCE
```

This is an exact reformulation only when all order-provenance assumptions are
verified. It is not a heuristic timing repair, not row generation, and not a
replacement for the passenger model.

The immediate recommendation is **yes, try this next**, but first as a small
formulation gate rather than by rewriting the complete EAN. The gate can be
completed quickly and directly tests the structural hypothesis that has
survived the previous EAN, DDD, Root-CG, CP-SAT, anonymous-flow, and Reservoir
experiments.

## Why This Experiment Comes Next

The current exact models exhibit two different regimes:

- All-Stop or small Fixed-\(K\) instances can solve quickly.
- Dense Skip-Stop instances near or above the All-Stop capacity frontier find
  weak bounds or poor incumbents and spend a long time at the root.

The difficult new physical operation in the second regime is repeated
reconvergence. At one Stop/Skip station, cabins split into two branches and
later request the same exit resource. The current pairwise model represents
each potentially conflicting pair independently:

\[
t_i^{\mathrm{clear}}+h_r\leq t_j^{\mathrm{enter}}
\quad\lor\quad
t_j^{\mathrm{clear}}+h_r\leq t_i^{\mathrm{enter}}.
\]

For \(N\) active merge events, this gives \(O(N^2)\) local order binaries and
two Big-M rows per unresolved pair. More importantly, the LP relaxation does
not naturally express that all selected pairwise choices must describe one
globally consistent queue.

At a physical merge, however, the decision is not a set of unrelated pairwise
choices. It is one output sequence. If the service branch supplies the ordered
stream

\[
S=(s_1,\ldots,s_m)
\]

and the bypass supplies

\[
P=(p_1,\ldots,p_n),
\]

then every physically valid merge order is a shuffle of \(S\) and \(P\) that
preserves the order inside each stream. There are

\[
\binom{m+n}{m}
\]

such interleavings. Independent pairwise decisions expose up to
\(2^{mn}\) cross-stream orientations before transitivity and timing eliminate
the inconsistent combinations. The exact search space is not exponential in
\(mn\); it is the set of monotone paths in an \(m\)-by-\(n\) lattice.

The purpose of the reformulation is therefore not merely to remove rows. It is
to present the solver with the correct combinatorial object.

## Relationship to Earlier Plans

This plan complements rather than supersedes the existing plans.

### Delayed merge headways

[`ean_fixed_k_delayed_merge_headways.md`](ean_fixed_k_delayed_merge_headways.md)
keeps the original pairwise disjunctions and generates only violated pairs.
That can reduce initial model size, but it does not strengthen the structure
once many conflicts have been materialized. Near the capacity frontier it may
eventually reconstruct most of the difficult pairwise model.

The merge-sequence formulation replaces the representation itself. Delayed
generation remains a useful baseline and may later be combined with sequence
blocks, but the first comparison must keep the two ideas separate.

### Alternative graph and complete EAN

An alternative graph chooses precedence arcs between conflicting operations.
The current EAN pair binaries are a MILP realization of this general idea. The
merge-sequence model exploits additional topology: the competing operations
arrive in a small, fixed number of internally ordered streams.

### DDD and complete time-expanded arc flow

DDD changes the time representation. It does not remove the need to decide
the order at a merge. The complete labelled waiting arc-flow experiment showed
that explicit time expansion can become too large before resource conflicts
are even solved. A compact continuous-time merge sequence can therefore be
used inside the EAN without expanding the entire waiting domain.

### Root-CG and Branch-Price-and-Cut

Trajectory Root-CG supplied useful Lower Bounds, especially for \(K=20\), but
its difficult integer master and conflict coupling remained. Full
Branch-Price-and-Cut would be a substantially larger implementation project.
The merge-sequence experiment targets the same conflict structure locally and
can be evaluated before committing to an exact branch-and-price tree.

### CP-SAT

CP-SAT is valuable for movement feasibility and primal schedules. Global
interval propagation may still be used as a comparison formulation in the
microbenchmark. It has not supplied the passenger-objective Lower Bounds that
the thesis requires, so it remains a seed and diagnostic channel rather than
the only optimizer.

## Literature Position

The proposal is a synthesis of established ideas, not a direct reproduction
of one published ropeway model.

### Alternative and disjunctive graphs

Mascis and Pacciarelli formulate blocking and no-wait job shops with an
alternative graph. A resource conflict is resolved by selecting precedence
arcs, and the selected graph determines schedule feasibility. This is the
closest classical foundation for the current EAN disjunctions:

- A. Mascis and D. Pacciarelli, *Job-shop scheduling with blocking and
  no-wait constraints*, European Journal of Operational Research 143(3),
  2002. <https://doi.org/10.1016/S0377-2217(01)00338-1>

D'Ariano, Pacciarelli, and Pranzo apply the alternative graph to microscopic
railway rescheduling and add implication rules to accelerate exact
branch-and-bound. Their results support exploiting derived precedence instead
of treating all order choices as independent:

- A. D'Ariano, D. Pacciarelli, and M. Pranzo, *A branch and bound algorithm
  for scheduling trains in a railway network*, European Journal of
  Operational Research 183(2), 2007.
  <https://doi.org/10.1016/j.ejor.2006.10.034>

### Fixed-width merge scheduling

Scheduling a constant number of incoming ordered traffic streams is more
structured than general job-shop scheduling. Besa Vial et al. give
polynomial-time algorithms for constant-\(k\) merge intersections and contrast
them with harder combined merge/crossing cases:

- J. J. Besa Vial, W. E. Devanny, D. Eppstein, and M. T. Goodrich,
  *Scheduling Autonomous Vehicle Platoons Through an Unregulated
  Intersection*, ATMOS 2016.
  <https://doi.org/10.4230/OASIcs.ATMOS.2016.5>

The ropeway problem is not identical: route membership is endogenous,
headways and ready times are continuous, the merge repeats across a horizon,
and passengers couple decisions across stations. The relevance is the
structural result: a merge of a fixed number of ordered streams should be
modeled as a sequence/interleaving problem, not as an arbitrary conflict
graph.

### Railway decomposition

Lamorgese and Mannino decompose real-time train dispatching into line and
station MILPs that communicate through exact feasibility cuts. This supports
the later option of treating each station merge as a specialized substructure,
but it does not by itself prescribe the sequence formulation proposed here:

- L. Lamorgese and C. Mannino, *An Exact Decomposition Approach for the
  Real-Time Train Dispatching Problem*, Operations Research 63(1), 2015.
  <https://doi.org/10.1287/opre.2014.1327>

### Precise novelty statement

The thesis may claim that the formulation is **inspired by** alternative
graphs, ordered-stream merge scheduling, and extended network formulations.
It must not claim that the complete integrated ropeway method is already an
established railway algorithm.

The potentially novel combination is:

- endogenous Stop/Skip membership;
- repeated merge operators along a cyclic cabin network;
- bounded service-branch waiting;
- continuous EAN timing;
- passenger assignment and journey-time objective;
- certified Lower and Upper Bounds from one exact MILP.

## Preconditions: What Must Be Proven First

The smallest lattice formulation is exact only if each incoming branch is
FIFO over the modeled merge family.

For every candidate merge resource, construct an immutable proof record:

```text
merge_family_id
incoming_stream_ids
upstream_anchor_resource_id
reconvergence_resource_id
candidate_event_ids
inherited_order_source
same_stream_overtaking_possible
waiting_location
proof_status
proof_reason
```

A stream may be declared order-preserving only when:

1. all cabins enter it through one already ordered predecessor resource;
2. the branch contains no passing location or second merge;
3. activation cannot remove the anchor that defines the order;
4. variable travel or waiting changes time gaps but cannot swap two cabins;
5. the horizon boundary does not introduce an untracked predecessor;
6. the current physical semantics, validation, and solver model agree.

This audit is especially important for the service branch. The physical
decision is already fixed: Waiting cannot cause overtaking. If the current EAN
nevertheless permits that order change, it is a legacy-model mismatch. The
FIFO-corrected pairwise formulation then becomes the exact reference; the
legacy model remains only a separately labelled regression baseline.

Possible outcomes are:

- `TWO_ORDERED_STREAMS`: use the lattice formulation;
- `K_ORDERED_STREAMS`: use its fixed-width generalization;
- `ORDERED_MEMBERSHIP_VARIABLE`: use the route-integrated sequence network;
- `GENERAL_ACTIVE_EVENTS`: use the more general slot formulation;
- `UNPROVEN`: retain the eager pairwise formulation.

## Mathematical Formulations to Benchmark

Let \(E_r\) be the active event candidates at merge resource \(r\). Each event
has an entry expression \(e_i\), a clearance expression \(c_i\), and an
activation expression \(a_i\). For a point headway,
\(e_i=c_i=t_i\). For an occupancy resource, the interval is
\([e_i,c_i]\).

### Baseline A: pairwise Big-M

For every unresolved pair \(i,j\):

\[
c_i+h_r\le e_j+M_{ij}(1-y_{ij}),
\]

\[
c_j+h_r\le e_i+M_{ji}y_{ij}.
\]

This is the current exact reference. It remains available throughout the
experiment.

### Baseline B: delayed pair generation

Begin without eligible cross-stream pairs, solve, separate all violations,
and add the original disjunctions. This tests whether sparsity alone is
sufficient.

### Candidate C: lattice interleaving for fixed branch membership

Assume the two active branch sequences are known:

\[
S=(s_1,\ldots,s_m),\qquad P=(p_1,\ldots,p_n).
\]

Construct the acyclic lattice with states

\[
V=\{(i,j):0\le i\le m,\;0\le j\le n\}.
\]

An east arc selects \(s_{i+1}\) as the next merged event; a north arc selects
\(p_{j+1}\). One unit of flow from \((0,0)\) to \((m,n)\) selects exactly one
interleaving and automatically preserves both internal orders.

For each selected arc, link the state time to the selected event time using a
solver-native indicator or a locally bounded convex-hull row. Along every
selected consecutive transition enforce:

\[
e_{\mathrm{next}}\ge c_{\mathrm{previous}}+h_r.
\]

The lattice uses \(O(mn)\) states and arcs. It may not reduce the asymptotic
count relative to all cross-stream pairs, but it removes inconsistent order
combinations and exposes a network-flow relaxation.

### Candidate D: position/slot formulation for general active events

Create at most \(N\) merge slots and assignment variables

\[
x_{iq}=1
\quad\Longleftrightarrow\quad
\text{event }i\text{ occupies merge slot }q.
\]

For a merge with exactly \(N\) active events:

\[
\sum_q x_{iq}=a_i,
\qquad
\sum_i x_{iq}=1.
\]

Link slot entry and clearance times to the assigned event:

\[
E_q=e_i,\quad C_q=c_i
\qquad\text{when }x_{iq}=1,
\]

then enforce only adjacent separation:

\[
E_{q+1}\ge C_q+h_r.
\]

Internal stream order is imposed by a compact cumulative-order network, not
by recreating every same-stream pair. Inactive candidates and optional horizon
events use an active slot prefix and canonical empty-slot values.

This variant handles route-dependent activation more naturally than the fixed
lattice, at the cost of \(O(N^2)\) assignment variables. With fixed activation,
the assignment substructure is a bipartite-matching polytope and is integral
before timing side constraints. Adjacent headways encode transitivity
explicitly.

### Candidate E: route-integrated merge sequence

At a Stop/Skip station, each upstream cabin-visit event selects exactly one of two
route-specific merge candidates:

\[
a_i^S+a_i^P=a_i.
\]

The integrated network must simultaneously:

1. select Stop or Skip;
2. extract the two branch subsequences from the inherited upstream order;
3. interleave the selected subsequences;
4. link the selected merge order to continuous event times.

Two implementations must be prototyped on generated microinstances:

- an acyclic state network with branch-extraction and merge arcs;
- a slot assignment with cumulative branch-rank variables.

Choose the smaller and stronger implementation empirically. Do not assume
that the most elegant fixed-membership lattice remains best after route
selection is endogenous.

### Candidate F: CP-SAT global-resource comparator

Build the same isolated merge with optional intervals and `NoOverlap`, plus
the branch precedences. This is not the target passenger optimizer. It reveals
whether propagation over a global unary resource dominates every MILP
formulation for the merge subproblem and provides primal schedules for the
EAN tests.

## Exactness Argument for the Ordered Two-Stream Case

The Phase-1 implementation must include a machine-checked version of the
following proof sketch.

### Sequence equivalence

Every monotone path from \((0,0)\) to \((m,n)\) contains exactly \(m\) east
arcs and \(n\) north arcs. Reading east as the next member of \(S\) and north
as the next member of \(P\) therefore produces every member exactly once and
preserves both internal orders.

Conversely, reading any order-preserving shuffle from left to right and taking
an east or north arc according to the event's stream constructs one unique
monotone path. Thus paths and feasible stream interleavings are in bijection.

### Headway equivalence

For a common resource with sequence-independent nonnegative headway \(h_r\),
enforcing separation only between consecutive slots makes the complete
sequence feasible. By transitivity, any earlier event clears before every
later nonadjacent event enters. Every feasible pairwise schedule also has one
chronological total order and therefore maps to a sequence satisfying the
adjacent rows.

The sequence and pairwise formulations consequently have the same integer
projection onto route and event-time variables under the proven assumptions.

This proof does not automatically cover:

- pair-dependent or direction-dependent headways;
- overlapping resource definitions with different entry and clearance
  semantics;
- a branch on which overtaking is possible;
- optional events whose activation is not represented exactly;
- simultaneous events permitted by a zero headway;
- untracked predecessor events at the horizon boundary.

Such cases need a specialized transition formulation or retain eager pairs.

## Waiting Semantics

The sequence model must not manufacture waiting where the physical model does
not permit it.

For a service event \(i\):

\[
t_i^{\mathrm{merge}}
=t_i^{\mathrm{ready}}+w_i,
\qquad
0\le w_i\le \bar w_i.
\]

For a no-wait or bypass event:

\[
t_i^{\mathrm{merge}}=t_i^{\mathrm{ready}}.
\]

The sequence only chooses who uses the merge next. Feasibility of that choice
is determined by the available physical waiting variables and travel-time
bounds. An impossible choice becomes infeasible; the formulation may not delay
a Skip cabin merely to satisfy its selected slot.

Test the policies:

\[
\bar w\in\{0,\;0.5h_r,\;h_r,\;2h_r\}.
\]

These values are structural diagnostics, not a claim that discrete waiting
levels are operationally sufficient. The final EAN waiting variable remains
continuous within the selected bound.

## Linking Repeated Merges

The largest potential gain comes from propagating order between stations.

After a merge, all cabins enter one non-overtaking rope corridor. Its output
order is therefore the inherited input order at the next station split. Do not
create a new independent order system for every downstream checkpoint.

Introduce:

```text
EanCorridorOrderState
EanMergeSequenceBlock
EanMergeSequenceLink
```

`EanCorridorOrderState` represents one ordered list of active cabin-visit
events on a deterministic corridor.

`EanMergeSequenceBlock` consumes the upstream order, Stop/Skip activation,
and branch timing and produces the order after reconvergence.

`EanMergeSequenceLink` reuses that output order until topology or waiting can
genuinely change it.

This converts a sequence of stations into a sequence of local permutation
operators rather than a collection of unrelated pairwise precedence binaries.
For a ring, fixed initial positions provide the first boundary order. Events
crossing the finite horizon retain explicit boundary candidates so that no
unmodeled cyclic assumption is introduced.

## OO Design

Keep topology proof, formulation, and solve orchestration separate.

```text
EanMergeFamilyAnalyzer
    derives merge families and FIFO/order provenance

EanMergeSequenceDomainBuilder
    maps candidate events to streams, cabin visits, and order states

EanMergeSequenceFormulation (Protocol)
    add_variables(...)
    add_constraints(...)
    extract_sequence(...)
    metrics(...)

PairwiseMergeFormulation
DelayedPairwiseMergeFormulation
LatticeMergeFormulation
SlotMergeFormulation
RouteIntegratedMergeFormulation

EanMergeSequenceValidator
    validates activation, permutation, internal order, timing, and headway

EanMergeFormulationBenchmark
    runs equivalent isolated and integrated cases
```

The canonical `EanMovementNetwork` remains the source of topology. The merge
domain must consume existing checkpoint/candidate expressions rather than
creating a second timing model.

Public configuration keeps representation and solve strategy separate:

```text
EanHeadwayOrderFormulation
    PAIRWISE_EAGER
    PAIRWISE_SHARED
    PAIRWISE_FIFO
    MERGE_SEQUENCE
```

Delayed merge generation remains a solve strategy over original pairs, not an
order-representation value. Pair omission for a complete Merge-Sequence model
uses a distinct `PARTITIONED` artifact scope; the existing `SPARSE` scope stays
reserved for delayed Fixed-\(K\) Capacity solving.

When `MERGE_SEQUENCE` cannot prove a family compatible, that family falls back
to the FIFO-corrected original-pair representation. It must not fall back to a
free legacy order if that would violate the physical branch contract. The
result records both the requested mode and actual coverage.

## Phase 0: Topology and Semantics Audit

### Tasks

1. Enumerate every current merge family for One-, Three-, and Five-Station
   cases.
2. Record branch candidates, route activation, waiting locations, and inherited
   predecessor order.
3. Compare physical assumptions, eager EAN constraints, validator behavior,
   and frontend replay.
4. verify that code, validation, and replay all enforce the resolved fact that
   service-branch Waiting cannot cause overtaking;
5. Generate a machine-readable provenance report.

### Acceptance

- every reformulated event belongs to exactly one proven family;
- no ordinary platform exit is mislabeled as a reconvergence;
- every claimed stream order has a graph proof;
- horizon-crossing predecessors are included;
- unproven cases remain eager.

## Phase 1: Isolated Merge Formulation Gate

Generate equivalent merge instances with:

```text
stream sizes        5+5, 10+10, 20+20, 40+40
waiting             0, 0.5h, h, 2h
release patterns    uniform, clustered, adversarial near-ties
route membership    fixed, then endogenous
objective           total delay, weighted event time, feasibility
```

Compare:

1. eager pairwise Big-M;
2. delayed pairwise generation;
3. fixed-membership lattice;
4. slot assignment;
5. route-integrated sequence;
6. CP-SAT `NoOverlap`.

Measure:

- variables, binaries, rows, and nonzeros;
- root LP and root gap;
- presolve reduction;
- nodes, conflicts, and cuts;
- time to first feasible solution;
- time to proof;
- peak RSS;
- exact objective and sequence agreement.

Gate to Phase 2 only if one sequence formulation:

- matches enumeration on all tiny instances;
- is never materially weaker at the root than the Pairwise FIFO reference;
- reduces median proof time by at least 2x on \(20+20\) or solves cases the
  pairwise model does not solve within the common budget;
- remains stable when Waiting is enabled.

If no formulation passes, stop. This negative result is cheaper and more
informative than another full EAN rewrite.

## Phase 2: Fixed-Routing EAN Integration

Freeze Stop/Skip decisions from existing valid schedules and replace only the
corresponding merge ordering.

Cases:

- Three-Station small exact cases;
- Five-Station architecture B, \(K=20\), No-Wait;
- the same case with \(0.5h\) and \(h\) Waiting;
- Five-Station \(K=38\) or \(K=39\) as build/root diagnostics.

This phase tests repeated merge/corridor linking without route-choice
coupling. Passenger assignment remains active so that timings are evaluated
under the real objective.

## Phase 3: Endogenous Stop/Skip Integration

Enable route-integrated sequence blocks at proven merges while keeping all
other EAN constraints unchanged.

Required exact comparisons:

- exhaustive tiny enumeration;
- Pairwise FIFO EAN optimum and feasibility;
- legacy eager EAN reported separately when its feasible set differs;
- extracted physical movement validation;
- exact fixed-movement passenger reevaluation;
- final complete headway separation over the original candidate universe.

The final separator is mandatory even though the formulation is intended to
be exact. It acts as an independent certificate during development.

## Phase 4: Campaign Gate

Run equal-wall-clock comparisons for:

```text
K = 20, 38, 39
Waiting = 0, 0.5h, h
time = 15 minutes
```

Only promising configurations continue to one hour. A four-hour run is
justified only when both bounds or node processing continue to improve.

Compare:

- eager pairwise EAN;
- Pairwise FIFO EAN;
- eager-core/delayed-merge EAN;
- merge-sequence EAN;
- CP-SAT seed plus merge-sequence EAN;
- the best existing DDD/Root-CG bound for the identical fingerprint.

For a minimization problem, combine independent exact certificates only when
the physical network, demand, \(K\), initial state, horizon, Waiting policy,
and passenger objective match exactly:

\[
LB^*=\max_s LB_s,
\qquad
UB^*=\min_s UB_s.
\]

## Tests

### Unit tests

- all monotone paths enumerate exactly all shuffles of two fixed streams;
- no path reverses either internal stream;
- each active event occupies exactly one slot;
- inactive route candidates occupy no slot;
- empty slots form a canonical suffix;
- adjacent headways imply all nonadjacent point headways;
- interval clearance is used instead of point time where required;
- asymmetric headways either receive a correct transition formulation or fall
  back to eager pairs;
- a Skip event cannot acquire artificial waiting;
- service waiting respects its continuous upper bound;
- duplicate or missing merge events are rejected;
- horizon-crossing events preserve the boundary order.

### Property tests

For random tiny release times, durations, route selections, and Waiting caps:

- compare every formulation with brute-force sequence enumeration;
- compare feasibility and optimum;
- validate extracted sequence and times independently;
- permute cabin IDs and obtain the same physical optimum.

### Integrated regressions

- One-Station cases remain unchanged;
- no-Skip resources fall back to directed corridor headways;
- Three-Station service/skip merge agrees with Pairwise FIFO EAN;
- Five-Station \(K=20\) No-Wait agrees with the exact Pairwise FIFO objective
  for the same start-policy and semantic fingerprint;
- Passenger objectives `journey_time` and `waiting_time` remain exact;
- all existing eager and delayed modes remain selectable.

## Expected Benefit

### What may improve

- stronger root relaxation through an explicit total merge order;
- fewer contradictory or symmetric partial order decisions;
- adjacent rather than all-pairs headway enforcement after sequencing;
- direct propagation of corridor order between stations;
- compact continuous Waiting without a complete time expansion;
- better primal schedules because each branch decision immediately implies a
  coherent downstream queue;
- a cleaner place for merge-specific cuts and CP-SAT seeds.

### Realistic expectation

For fixed branch membership, a substantial improvement is plausible because
the lattice exactly represents the relevant combinatorics. For endogenous
Stop/Skip, the gain is less certain because route selection, repeated visits,
and passenger assignment remain coupled.

A reasonable success target is:

- \(2\)- to \(10\)-fold faster root/proof work on merge-dominated small and
  medium cases;
- a materially better first incumbent and nonzero certified Lower Bound for
  dense \(K=38/39\) cases within 15 minutes;
- visible bound progress within one hour where the pairwise model stalls.

These are experiment targets, not promises.

### What it cannot guarantee

- polynomial solution of the complete passenger problem;
- easy optimization at every \(K\) near physical capacity;
- removal of route/passenger integrality;
- a good incumbent when the canonical start state is itself poor;
- scalability to arbitrary dynamic turnbacks or many incoming branches;
- improvement if pairwise merges are not the dominant measured bottleneck.

## Stop/Go Decision

Continue toward the full merge-sequence EAN only if:

1. topology proves two or a small fixed number of ordered incoming streams;
2. an isolated formulation decisively beats pairwise eager;
3. the improvement survives continuous Waiting;
4. fixed-routing EAN integration improves root or primal progress;
5. exact Pairwise FIFO equivalence holds on all solvable references.

Otherwise retain the result as a negative formulation study and return to the
certified portfolio:

- strongest EAN/DDD/Root-CG Lower Bound;
- CP-SAT or local fix-and-optimize for validated Upper Bounds;
- exact passenger reevaluation;
- systematic fixed-\(K\) comparison intervals.

## Thesis Deliverable

The thesis section should contain:

1. the original pairwise disjunctive formulation;
2. the proof that a validated merge family is an interleaving of ordered
   streams;
3. the lattice and slot extended formulations;
4. exactness conditions and fallback rules;
5. a diagram of the \((i,j)\) lattice for two small streams;
6. model-size and root-strength comparisons;
7. end-to-end Fixed-\(K\) Passenger results;
8. an explicit statement of whether the bottleneck hypothesis was confirmed.

The method should be described as an **ordered-stream extended formulation for
Stop/Skip reconvergence**, grounded in alternative-graph scheduling and
fixed-width merge scheduling. It should not be called Logic-Based Benders,
Branch-Price-and-Cut, or delayed row generation unless those mechanisms are
actually used in the evaluated implementation.

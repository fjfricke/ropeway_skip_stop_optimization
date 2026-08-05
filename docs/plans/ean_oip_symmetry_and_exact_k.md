# OIP Symmetry Breaking and Exact-K Solve Plan

Status: **in progress — exact symmetry items implemented; Exact-K remains planned**

## Goal

Make optimized-initial-placement (OIP) passenger models substantially easier
to solve without changing their feasible physical schedules or their
lexicographic passenger optimum. The immediate experimental target is the
five-station ring with skip, end-of-platform waiting, and up to 76 available
cabins.

The plan has two complementary parts:

1. remove equivalent solutions caused only by interchangeable cabin labels;
2. expose an exact fixed-fleet-size decomposition for experiments where the
   monolithic `UP_TO_AVAILABLE` model is too large.

The plan is separate from eager Headway build optimization. Sparse-matrix
construction has reduced OIP76 Headway build time from 1,073.434 seconds to
89.419 seconds, but the resulting Passenger model still contains 3,761,146
variables, 8,800,780 constraints, and 57,004,636 nonzeros. This plan targets
the subsequent MIP search.

## Correctness contract

All default OIP symmetry constraints must be exact for interchangeable cabins.
For every feasible original solution there must be a relabeling of complete
cabins -- initial state, movement decisions, waiting, Headway decisions, and
Passenger Assignment -- that satisfies the canonical constraints with the
same objective values.

The current model treats cabins as interchangeable because cabin IDs carry no
capacity, route, depot, availability, or cost attributes. If heterogeneous
cabins are introduced later, symmetry breaking must operate separately inside
equivalence classes and must not order cabins across different classes.

The following must remain possible:

- Stop/Skip decisions may differ between cabins;
- cabins may wait for different durations;
- cabins may overtake after service/skip branches merge;
- cabin order may change at later checkpoints;
- fewer than the available cabins may be active in
  `UP_TO_AVAILABLE` mode.

No constraint in this plan establishes a global cabin order after the initial
service boundary.

## Existing symmetry handling

### Active cabin prefix

The fleet model already imposes

\[
a_{c+1}\le a_c.
\]

Consequently, a solution with exactly \(K\) active cabins uses IDs
\(0,\ldots,K-1\). This removes the

\[
\binom{N}{K}
\]

equivalent choices of active labels. For OIP76 with \(K=38\), that is roughly
\(6.9\cdot10^{21}\) label-equivalent activation patterns.

This reduction remains mandatory for `UP_TO_AVAILABLE`. Exact-cardinality
models already fix all created cabins active.

### Discrete initial phase order

The fleet model already orders selected initial phases by cabin ID. If \(p_c\)
is the selected pattern position, active adjacent cabins satisfy

\[
p_c\le p_{c+1}.
\]

This removes permutations between different initial pattern positions but
currently treats a station state and its incoming rope state as the same
discrete phase.

### Initial rope order

For two cabins selected on the same initial rope segment, the model already
uses cabin-ID direction and a single directed rope Headway. The all-stop MIP
start relabels projected states consistently with phase and rope-time order.

### Passenger slot order

Passenger slot symmetry is already handled separately by `slot_symmetry`.
It must remain independent of fleet-label symmetry.

## Phase 1: Canonical full initial-state category — implemented

Refine the current phase key into a stable discrete initial-state category.
For the current deterministic circulation pattern, define an ordinal such as

\[
q_c=2p_c+r_c,
\]

where \(r_c\) distinguishes a station state from the incoming rope state. The
exact numeric convention is arbitrary, but it must be shared by model
construction, MIP-start relabeling, validation, replay, and extraction.

For active adjacent cabins impose

\[
q_c\le q_{c+1}.
\]

Implement this from existing one-hot `station_selected` and `rope_selected`
variables without adding a general integer variable unless a benchmark shows
that the explicit variable improves the formulation.

Expected effect:

- eliminates station/rope permutations that survive current phase ordering;
- adds only \(O(K)\) sparse constraints;
- expected Solve improvement: approximately 5--15 percent by itself, with
  high instance dependence;
- negligible change in overall model size.

## Phase 2: Canonical order within one initial category — implemented conservatively

Cabins in the same discrete category remain interchangeable. Direct their
shared boundary order by cabin ID.

For an initial rope category, retain the chronological exit time from the
preceding switch. For an initial station category, use the entry time at the
shared station-entry checkpoint. If \(y_{cq}\) selects category \(q\), an
adjacent conditional Headway has the form

\[
t^{\mathrm{entry}}_c+h_q
\le
t^{\mathrm{entry}}_{c+1}
+M(2-y_{cq}-y_{c+1,q}).
\]

This fixes only the order at the shared initial resource. A service cabin may
later wait while a skipping cabin passes it, and all subsequent merge orders
remain solver decisions.

Initial rope and serving platform-entry order are directed by cabin ID. On one
initial rope, category order makes the selected cabins a contiguous ID block,
so adjacent directed Headways are sufficient by transitivity. At a serving
resource, adjacent cabin IDs alone are not sufficient because an intervening
cabin may skip and therefore does not supply the transitive serving Headway.
The platform-entry formulation consequently retains all directed pairs unless
exact successor variables for the serving subsequence are introduced later.

Expected effect:

- removes the remaining factorial label symmetry inside initial categories;
- reduces initial boundary constraints from \(O(PK^2)\) to \(O(PK)\);
- the absolute row reduction is modest compared with 8.8 million total rows;
- expected Solve improvement: approximately 5--25 percent together with
  Phase 1, potentially more when many cabins begin in the same category.

## Phase 3: Feed initial precedence into Headway classification — implemented

The general eager Headway pool must not create an order binary for a pair whose
direction is already proven by canonical initial-state ordering. Extend the
Headway classifier with explicit provenance for initial boundary precedence:

```text
INITIAL_CATEGORY_ORDER
INITIAL_ROPE_ORDER
INITIAL_STATION_ENTRY_ORDER
```

For such pairs emit no duplicate general disjunction. Do not infer
later checkpoint precedence from cabin ID. A direction may propagate only
through a deterministic non-branching corridor for which no service/skip
merge or waiting opportunity can reverse order.

Expected effect for OIP76:

- likely removes tens of thousands rather than millions of order binaries;
- estimated model-size reduction: 1--3 percent;
- estimated Solve improvement: 5--20 percent because the removed decisions
  occur at the initial boundary and can influence downstream branching.

## Phase 4: Canonical inactive operational variables — implemented

When cabin \(c\) is inactive, fix its physically meaningless variables to
deterministic values. For a time variable

\[
t_{cv}\in[\ell_{cv},u_{cv}],
\]

add

\[
t_{cv}\le \ell_{cv}+(u_{cv}-\ell_{cv})a_c.
\]

The existing lower bound then gives \(t_{cv}=\ell_{cv}\) for an inactive
cabin and preserves the original interval when it is active. Likewise impose

\[
w_{cv}\le \bar w_{cv}a_c
\]

for waiting variables where this is not already implied tightly. Verify which
stop, route-active, visit-active, and horizon binaries are already forced by
the current activation equations before adding duplicate rows.

Implement the bounds from `EanModelTimeBounds`; do not introduce new global
Big-M values.

Expected effect:

- removes continuous degeneracy for inactive trajectories;
- adds only several thousand sparse rows in OIP76;
- expected Solve improvement: 5--20 percent, particularly when the best
  solution uses substantially fewer than 76 cabins;
- little benefit for exact models in which every created cabin is active.

### Implemented OIP38 build result (2026-07-22)

The three new exact reductions are independently selectable as
`oip_full_initial_state_symmetry`, `oip_initial_headway_precedence`, and
`oip_inactive_variable_canonicalization`. The active prefix and legacy phase
order remain structural baseline behavior.

For the five-station OIP38 skip+wait passenger build, initial precedence
removed 703 duplicate general Headway disjunctions and therefore 703 order
binaries. The completed model contained 1,149,938 variables, 2,881,339 rows,
and 17,560,366 nonzeros. Total Gurobi model construction took 37.826 seconds,
including 21.066 seconds for the eager Headway rows. These are build metrics;
they do not yet establish a branch-and-bound speedup.

The corresponding OIP76 build classified all
\(\binom{76}{2}=2{,}850\) visit-zero platform-entry pairs as redundant:

| Metric | Matrix baseline | With OIP symmetry | Change |
| --- | ---: | ---: | ---: |
| Variables | 3,761,146 | 3,758,296 | -2,850 |
| Headway-order binaries | 2,915,094 | 2,912,244 | -2,850 |
| Constraints | 8,800,780 | 8,805,178 | +4,398 |
| Nonzeros | 57,004,636 | 57,043,582 | +38,946 |
| Headway build | 89.419 s | 90.932 s | +1.7% |

The extra canonicalization rows therefore leave total model size essentially
unchanged while removing the initial branching decisions. Peak RSS was about
5.98 GiB (6,126.9 MiB) and total Gurobi model construction took 128.164
seconds. Whether the trade improves the solve requires a timed optimization
comparison; build metrics alone cannot establish that.

## Phase 5: Exact-\(K\) passenger decomposition

This phase remains future work and is not part of the implemented symmetry
change.

Add an experimental workflow that solves separate exact-cardinality passenger
models. For each selected fleet size \(K\), construct an artifact with exactly
\(K\) cabins and `EanFleetCardinalityMode.EXACT` rather than constructing 76
cabins and deactivating the unused suffix.

For the monolithic up-to model,

\[
z^*_{\le N}=\min_{0\le K\le N}z^*_K
\]

under the existing lexicographic objective:

1. minimize unserved demand;
2. minimize the selected passenger objective;
3. minimize active cabin count.

Comparing all relevant exact-\(K\) optima therefore recovers the monolithic
optimum. Partial exploration is still useful for finding a constructive
improvement over the 38-cabin reference, but must not be reported as a global
up-to-76 proof.

Headway-pair count is approximately quadratic in \(K\):

\[
N_{\mathrm{pairs}}(K)
\approx
2{,}915{,}094\left(\frac{K}{76}\right)^2.
\]

Approximate OIP76-derived sizes are:

| Exact fleet size | Estimated Headway pairs |
| ---: | ---: |
| 40 | 0.81 million |
| 45 | 1.02 million |
| 50 | 1.26 million |
| 60 | 1.82 million |
| 76 | 2.92 million |

The experimental search should:

1. start at \(K=38\) with the canonical all-stop seed;
2. test nearby values such as 39, 40, 42, and 45 first;
3. pass the best available movement/passenger incumbent to compatible larger
   models where a safe lifting exists;
4. record each exact-\(K\) bound, incumbent, gap, build time, presolve time,
   node count, and peak memory;
5. compare solutions lexicographically rather than by one combined floating
   objective.

Expected effect:

- strongest near-term method for finding an OIP result better than OIP38;
- removes all inactive-cabin variables and their label degeneracy per probe;
- can reduce pair count by more than 70 percent near \(K=40\);
- does not guarantee that every fixed-\(K\) model becomes easy;
- a complete sequential sweep may cost more total work than one monolithic
  solve, so probes should support parallel execution and resumable results.

## Phase 6: Branching and primal starts

Benchmark a search policy that prioritizes structural choices before local
ordering decisions:

1. cabin activation in the monolithic model;
2. initial state category and phase;
3. Stop/Skip decisions;
4. Headway order variables;
5. Passenger Assignment variables.

Use Gurobi branching priorities only as an experimental option until results
show consistent benefit. Do not assume manual priorities outperform Gurobi's
default pseudocost strategy.

Support multiple canonical MIP starts when available:

- the 38-cabin all-stop solution;
- periodic seeds for selected larger exact fleet sizes;
- validated seeds with different Stop/Skip patterns.

Every start must be relabeled by the same initial-category and within-category
order used by the model. Reject a noncanonical seed with a clear validation
error rather than silently discarding it.

Expected effect:

- primarily reduces time to the first strong incumbent;
- expected Solve improvement: 0--20 percent, occasionally more;
- limited expected effect on the final optimality proof.

## Phase 7: Inactive Headway-order variables

For a Headway pair between cabins \(i\) and \(j\), its order binary is
meaningless if either cabin is inactive. With active-prefix symmetry, both
cabins are active exactly when the larger-ID cabin is active, so the exact
canonical constraint

\[
o_{ij}\le a_{\max(i,j)}
\]

would force inactive pair orders to zero.

Do not enable this eagerly by default in the first implementation. It can add
one row per disjunctive pair -- up to roughly 2.9 million rows for OIP76 -- and
may trade symmetry reduction for a substantially larger LP. Implement it as a
separate measured option and compare:

- presolved variables and rows;
- root relaxation time;
- first incumbent time;
- node count and bound progression;
- peak RSS.

Expected effect is uncertain but potentially large. Retain it only if the
end-to-end Solve benefit clearly exceeds the construction and LP cost.

## Phase 8: Delayed Headways with structural capacity cuts

Revisit delayed exact violation generation only after adding strong aggregate
resource bounds. The initial sparse model should include certified rope and
station packing/throughput constraints so that the passenger objective cannot
gain unrealistically by activating a dense, Headway-free fleet.

The delayed method remains exact only when a feasible result receives a final
complete separation with no violation. It must remain distinct from eager
symmetry breaking and from Logic-Based Benders.

Expected effect:

- potentially avoids materializing most of the 2.9 million original pairs;
- high upside but high uncertainty because many separation rounds may still
  be required;
- pursue only after the simpler canonicalization and exact-\(K\) experiments.

## Secondary canonical objectives

The current Passenger OIP model already uses active cabin count as its third
hierarchical objective. Additional lower-priority objectives may be evaluated
for reproducibility and degeneracy reduction, for example:

- total waiting time;
- sum of otherwise unconstrained Headway-order binaries;
- a stable sum of selected initial-state ordinals.

Use Gurobi's hierarchical multiobjective mechanism. Do not emulate priority
with tiny coefficients that could change the primary optimum through numeric
tolerance. Expected performance benefit is small, roughly 0--10 percent; the
main benefit is deterministic tie breaking.

## Ideas excluded from general symmetry breaking

The following are not valid production-wide OIP symmetry constraints:

- forcing cabin 0 to start at station 0;
- fixing a global cabin order over the complete horizon;
- retaining only adjacent Headways after Stop/Skip overtaking becomes
  possible;
- sorting Stop/Skip patterns by cabin ID;
- quotienting ring rotations without proving symmetry of topology, station
  semantics, demand, and time data.

Scenario-specific graph automorphisms may later detect additional spatial
symmetry, but they are outside this plan.

## Architecture

Introduce a dedicated symmetry component rather than extending
`EanFleetModelBuilder` with unrelated inline constraints:

```text
EanFleetSymmetryBreaker
  - build_initial_categories(...)
  - add_active_prefix(...)
  - add_initial_category_order(...)
  - add_within_category_precedence(...)
  - canonicalize_seed(...)
  - validate_canonical_plan(...)
```

The component should return structured precedence provenance consumable by the
Headway classifier. Model construction, seed creation, extraction validation,
and experiment reporting must use the same category definition.

Expose independent configuration flags during evaluation:

```text
ACTIVE_PREFIX
INITIAL_PHASE_ORDER
FULL_INITIAL_STATE_ORDER
INACTIVE_VARIABLE_CANONICALIZATION
INACTIVE_ORDER_CANONICALIZATION
```

The already-safe active-prefix and phase-order behavior remains enabled. New
options become default only after equivalence and performance gates pass.

## Tests

### Mathematical equivalence

- exhaustively enumerate small one- and three-station OIP cases with and
  without the new symmetry constraints;
- compare feasibility and lexicographic optimum;
- relabel every unsymmetrized solution into a canonical solution;
- include mixed Stop/Skip, waiting, initial rope, initial station, and later
  overtaking cases;
- verify that heterogeneous equivalence classes are rejected or handled
  separately if cabin attributes are introduced.

### Constraint behavior

- active cabins form a prefix;
- category ordinals are nondecreasing;
- equal-category initial entries follow Cabin-ID order and Headway;
- a later merge can reverse that order;
- inactive time and waiting variables take their canonical values;
- initial directed pairs create no Headway order binary;
- different batch sizes and eager/delayed modes preserve semantics.

### MIP starts and outputs

- all-stop and periodic seeds are canonically relabeled;
- noncanonical starts receive a precise error;
- extracted fleet and movement plans pass replay and complete Headway
  validation;
- exact-\(K\) result aggregation applies the lexicographic objective correctly;
- checkpoint resume metadata records fleet size and symmetry configuration.

## Performance acceptance

Use OIP38 and OIP76-derived exact fleet sizes as the primary benchmark set.
Record separately:

- artifact, movement, Headway, and Passenger build time;
- original and presolved variables, binaries, rows, and nonzeros;
- root-relaxation time and bound;
- time to first feasible and best incumbent;
- incumbent objective tuple;
- explored nodes and best bound at fixed time checkpoints;
- peak RSS.

Adopt a new default symmetry component only if:

- all equivalence and full regression tests pass;
- all warm starts remain valid after canonical relabeling;
- no tested case has a worse optimum or invalid movement;
- the geometric mean search metric improves materially, or OIP76 obtains a
  materially stronger incumbent/bound without unacceptable memory growth.

## Recommended execution order

1. Extract the existing active-prefix, phase-order, rope-order, and seed
   relabeling logic into `EanFleetSymmetryBreaker` without changing the model.
2. Add station/rope category ordering and canonical station-entry order.
3. Connect proven initial precedence to Headway classification.
4. Add inactive operational-variable canonicalization.
5. Benchmark OIP38 and small equivalence cases after every change.
6. Add the exact-\(K\) passenger experiment runner and test \(K=39,40,42,45\).
7. Benchmark branching priorities and multiple starts.
8. Experiment with inactive order-variable fixing only behind an option.
9. Revisit delayed Headways with aggregate capacity cuts if exact-\(K\) models
   remain too hard.

The expected highest-value combination is full initial-state canonicalization
for every OIP model plus exact-\(K\) decomposition for the OIP76 passenger
experiment.

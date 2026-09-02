# Merge-Aware Branch-Price-and-Cut for Certified Skip-Stop Planning

Status: **root gate implemented; Branch-Price-and-Cut tree rejected by the
K=20/K=39 stop gate on 2026-09-02**

The implementation and measured decision are summarized in
[`../findings/ddd_merge_aware_root_gate.md`](../findings/ddd_merge_aware_root_gate.md).
The remaining tree/cohort sections below are retained as the conditional
design that was deliberately not activated after the failed gate.

This plan specifies the next exact algorithmic experiment after the matched
Five-Station Architecture-B bakeoff. It refines the conditional tree work in
[`ddd_dive_branch_price_cut.md`](ddd_dive_branch_price_cut.md): the immediate
next step is not a Branch-and-Price tree, but a merge-aware root master with
pricing-compatible rows and coordinated column generation. A tree is built
only after that root formulation passes the gates below.

The implementation remains exact-$K$, fixed canonical start, finite horizon,
and No-Wait first. Waiting is a later, explicitly gated extension.

## 1. Decision

Develop a **merge-aware Dantzig--Wolfe decomposition** in three layers:

1. an exact trajectory LP master with universal physical resource/merge rows;
2. exact single-cabin proof pricing plus coordinated compatible-batch pricing;
3. only after a successful root gate, a limited Branch-Price-and-Cut tree with
   branching on physical Stop/Skip and merge-precedence decisions.

The method is intended to combine the strongest observed properties of the
current formulations:

- complete trajectories remove anonymous-flow reconstruction ambiguity;
- DDD provides a finite exact No-Wait trajectory universe and a complete
  arc-flow reference;
- merge/resource rows expose the small number of physical coupling points;
- Gurobi solves the restricted LP/MIP and Passenger Assignment;
- exact pricing proves that no omitted trajectory can improve a node bound;
- coordinated pricing supplies compatible columns instead of many individually
  attractive but mutually unusable trajectories;
- explicit branching converts the trajectory LP certificate into a global
  integer certificate.

This is the most promising current route to a scalable certified method, but
it is not assumed to succeed. Each expensive stage has a quantitative stop
condition. If the root master cannot produce a competitive certified bound or
cannot leave its seed under matched budgets, no tree is implemented.

## 2. Why this is the next experiment

### 2.1 Evidence from the matched bakeoff

Under the fixed canonical No-Wait semantics used in the recent bakeoff:

| Instance | Formulation | Time | Certified LB | Validated UB | Gap |
|---|---|---:|---:|---:|---:|
| Five-Station B, $K=20$ | complete labeled DDD arc-flow | 24.6 s | 525,730.908 | 525,730.908 | 0% |
| Five-Station B, $K=20$ | shared Pairwise EAN | 30 min | 446,542.889 | 605,612.909 | 26.27% |
| Five-Station B, $K=39$ | complete labeled DDD arc-flow | 30 min | 407,377.355 | 1,441,586.411 | 71.74% |
| Five-Station B, $K=39$ | shared Pairwise EAN | 30 min | 311,588.732 | 1,536,000.000 | 79.71% |

The $K=39$ runs both remained effectively at the root and retained one weak
initial incumbent. Running the same complete MILPs longer may improve their
bounds, but it does not address the observed structural bottleneck: hundreds
of thousands of Passenger variables and dense cross-cabin conflicts are
present before the solver has learned a useful global schedule structure.

The earlier trajectory Root-CG experiments show the complementary failure:
independent pricing can find negative-reduced-cost trajectories, but the best
trajectory for each cabin can conflict with the best trajectories of other
cabins. Strong resource clique rows can then leave the restricted master at
its seed. Adding three sequential diverse columns per cabin did not resolve
this. A coordinated CP-SAT package moved the primal master, but did not
provide the missing proof bound.

The new method addresses exactly this mismatch:

- universal merge rows make the coupling visible to current and future
  columns;
- exact individual pricing retains a valid lower-bound correction;
- compatible-batch pricing deliberately finds columns that can coexist;
- branching is postponed until root pricing and master movement work.

### 2.2 Research basis

The overall architecture is standard Dantzig--Wolfe/Branch-and-Price:
[Barnhart et al. (1998)](https://doi.org/10.1287/opre.46.3.316) describe
branching, pricing, and column management for large-scale integer programs.

Relevant neighboring applications support the chosen decomposition unit:

- conflict-free AGV routing selects a complete route per vehicle and enforces
  inter-vehicle interference in a master; constrained shortest-path pricing
  generates routes
  ([Krishnamurthy et al. (1993)](https://doi.org/10.1287/opre.41.6.1077));
- railway rolling-stock and train-unit scheduling use path/configuration
  columns with custom branching and column inheritance
  ([Peeters and Kroon (2008)](https://doi.org/10.1016/j.cor.2006.03.019),
  [Lin and Kwan (2016)](https://doi.org/10.1016/j.trb.2016.09.007));
- periodic timetabling combines column generation, delayed conflict rows,
  Passenger decomposition, diving, and neighborhood search
  ([Martin-Iradi and Ropke](https://arxiv.org/abs/1912.06941));
- elevator destination dispatch uses whole-trip columns containing stops and
  Passenger pickups, demonstrating that Passenger/service decisions can be
  priced together in a route column
  ([Torres Duran and Bierlaire (2023)](https://www.strc.ethz.ch/2023/TorresDuran_Bierlaire.pdf));
- train dispatching decompositions show the value of separating network-level
  choices from local resource feasibility and generating only required rows
  ([Lamorgese and Mannino (2015)](https://doi.org/10.1287/opre.2014.1327)).

Conveyor and Personal Rapid Transit merge-control literature additionally
supports the physical abstraction: merge order, safe insertion slots, FIFO
within each branch, and local holding are the dominant coupling decisions.
Those methods do not solve the present Passenger objective and therefore do
not replace the exact master; they justify making merges explicit instead of
treating every pair of events as unrelated.

The literature validates the method family, not performance on this ropeway
model. Repeated rotations, Stop/Skip choices at every visit, Passenger demand,
and dense high-$K$ merge interactions remain project-specific.

## 3. Exact problem contract

For the first production gate, one problem instance fixes:

- a physical `EanMovementNetwork` and deterministic circulation pattern;
- one demand profile and one Passenger objective;
- exactly $K$ active cabins;
- the same canonical physical start state for every compared formulation;
- Stop-only or Stop/Skip route domain;
- No-Wait movement;
- finite horizon and tail semantics;
- integer DDD ticks with exact conversion to physical seconds;
- a complete fingerprint over all of the above.

The result is conditional on this fixed start policy. It is not an optimized
initial-placement certificate. All-Stop and Skip-Stop may be compared only
when their physical network, demand, start state, horizon, and objective
fingerprints match except for the declared route-domain policy.

## 4. Mathematical formulation

### 4.1 Whole-horizon trajectory columns

Let $C$ be the cabin set and $P_c$ the complete finite set of admissible
whole-horizon No-Wait trajectories for cabin $c$. A trajectory fixes:

- every movement arc and event tick;
- Stop/Skip at every visit;
- every physical resource-entry and release occurrence;
- offered Passenger rides and their capacities;
- the declared fixed start and horizon boundary.

The master selects one trajectory per cabin:

\[
\sum_{p\in P_c}\lambda_{cp}=1
\qquad \forall c\in C,
\]

with $\lambda_{cp}\in[0,1]$ in the LP and $\lambda_{cp}\in\{0,1\}$ in the
integer master.

Passenger-flow variables remain explicit in the master initially. If
$x_{g,r}$ assigns demand group $g$ to ride $r$, the existing demand,
compatibility, capacity, and direct-ride constraints are reused. An LP
Passenger solution contributes to a lower bound; only an integral/exactly
evaluated Passenger solution on a complete physical schedule contributes to
an upper bound.

### 4.2 Canonical merge/resource rows

Let $R$ denote physical headway resources and $T_r$ the finite set of relevant
DDD event ticks on resource $r$. For constant headway $h_r$, define a
canonical half-open conflict window

\[
W(r,t)=[t,t+h_r).
\]

For each occurrence $o$ of trajectory $p$, let its protected resource interval
be

\[
I_o=[e_o,\ell_o+h_o),
\]

where $e_o$ is resource entry, $\ell_o$ is physical clearance, and $h_o$ is
the applicable follower separation. For trajectory $p$, let

\[
a_{cp}^{r,t}
=
\left|\{o:\operatorname{resource}(o)=r,\ t\in I_o\}\right|.
\]

The universal occupancy row

\[
\sum_{c\in C}\sum_{p\in P_c} a_{cp}^{r,t}\lambda_{cp}\le 1
\]

is valid for generated and omitted columns because its coefficient is
computed from physical trajectory content, not from a finite list of column
IDs.

Not every possible window is added eagerly. A separator inspects the current
fractional or integer RMP solution, finds violated physical windows, and adds
the strongest deterministic batch. Once added, the row is priced forever.

For resource rules whose separation depends on leader behavior, the first
implementation creates typed directed windows/state-expanded rows. A row is
admitted into the proof master only if a future trajectory's coefficient can
be computed locally and exactly by the pricing oracle. Otherwise that rule
remains represented by exact pair separation and cannot close a node against
omitted columns.

### 4.3 Merge provenance and FIFO

At a Stop/Skip station, cabins preserve order within the Service branch and
within the Skip branch. Only the interleaving of these stable subsequences at
the outgoing merge is a decision.

For every physical merge family $m$, record:

- incoming common-corridor occurrence;
- Service and Skip branch occurrences;
- outgoing common-corridor occurrence;
- stable predecessor and successor provenance;
- resource/headway rule and horizon role.

This provenance is used for three purposes:

1. omit redundant same-branch pair decisions already implied by FIFO;
2. generate exact outgoing resource-window coefficients;
3. define physical merge-precedence branching later.

The isolated Lattice and Slot merge formulations are not adopted as the
master. Their gate was slower/weaker than Pairwise FIFO. The retained useful
idea is the canonical merge domain and FIFO provenance, not their extended
variable systems.

### 4.4 Restricted master and exact proof pricing

Let $\widehat P_c\subset P_c$ be the current column pool and let
$z_{\mathrm{RMP}}$ be the optimal restricted LP value. Given all master
duals, exact single-cabin pricing computes

\[
\rho_c^*=
\min_{p\in P_c}
\left(c_{cp}-\pi_c-\sum_j \mu_j a_{cp}^{j}
-\text{Passenger dual contribution}\right).
\]

Here every extensible row $j$ has an exact trajectory coefficient oracle. If
pricing is interrupted, its certified objective bound
$\underline\rho_c\le\rho_c^*$ is retained. The node lower bound is

\[
LB_{mathrm{node}}
=
z_{\mathrm{RMP}}
+\sum_{c\in C}\min\{0,\underline\rho_c\}.
\]

The node LP is closed only if every cabin is proved to have nonnegative
reduced cost within tolerance. Heuristic or coordinated pricing is never used
to assert omitted-column nonnegativity.

### 4.5 Why individual pricing is necessary but insufficient

Individual exact pricing is sufficient for the lower-bound correction, but
not necessarily for useful RMP progress. Cabin $c_1$ and cabin $c_2$ can each
produce a highly attractive trajectory that occupies the same merge window.
Both columns are valid, yet the master cannot select them together. Repeating
this independently can create severe tailing-off or leave the master near its
seed.

The algorithm therefore retains individual pricing for proof and adds a
separate compatibility channel for progress.

### 4.6 Coordinated compatible-batch pricing

The first coordinated method is a two-stage deterministic batch selector:

1. exact/k-best pricing returns up to $L$ negative-reduced-cost candidates per
   cabin, preserving certified minima;
2. a small compatibility MILP selects at most one candidate per cabin and
   maximizes total reduced-cost improvement while enforcing all current
   universal resource rows and exact pair conflicts among candidates.

If no useful batch exists, a bounded joint cohort-pricing MILP is run for a
physically chosen cohort $B\subseteq C$, initially 2--4 cabins around the
highest-dual merge windows:

\[
\min
\sum_{c\in B}\bar c_{c,p(c)}
\]

subject to one complete trajectory per cohort cabin and exact internal
resource compatibility. Cabins outside the cohort enter only through current
master dual prices, not through fixed guessed trajectories.

The returned batch may add multiple compatible columns in one RMP round. Its
role is acceleration:

- a negative compatible batch can improve the RMP and later the restricted
  MIP;
- failure to find a batch proves nothing;
- its objective bound does not replace the sum of exact single-cabin pricing
  bounds;
- a full CP-SAT schedule package remains a primal-only seed/repair source.

An alternative true bundle-column decomposition, where one column represents
several cabins, is explicitly deferred. Overlapping bundles complicate the
set-partitioning master and branch semantics and are justified only if the
cohort accelerator passes but independent columns remain fundamentally weak.

### 4.7 Integer certificate

At the root, the algorithm yields

\[
LB_{\mathrm{root}}
\le z_K^*\le UB,
\]

where $UB$ is independently validated. A fractional root solution does not
prove integer optimality. Branch-Price-and-Cut partitions the complete column
universe. At every open node $n$, exact node pricing supplies $LB_n$. The
global tree bound is

\[
LB_{\mathrm{tree}}=
\min_{n\in\mathcal O}LB_n.
\]

With no open nodes and a validated incumbent, the result is integer optimal.
Under a time limit, the exported certified interval is

\[
LB_{\mathrm{tree}}\le z_K^*\le UB.
\]

The restricted-master MIP best bound is never exported as a global lower
bound.

## 5. Algorithm

### 5.1 Root loop

For one fixed-$K$ instance:

1. Build the canonical DDD trajectory problem and immutable merge domain.
2. Insert one or more fully validated physical seed packages.
3. Solve the restricted Passenger LP to optimality.
4. Separate violated universal merge/resource windows.
5. Re-solve until no current-column row violation remains.
6. Run exact single-cabin proof pricing for every unresolved cabin.
7. Retain each negative pricing incumbent and its certified lower bound.
8. Run candidate compatibility selection; if needed, run selected joint
   cohort pricing.
9. Add the deterministic accepted column batch and return to Step 3.
10. Periodically solve a warm-started restricted MIP and validate every
    incumbent independently.
11. Close the root only when all omitted-column pricing domains are certified
    nonnegative after the final row separation.

Rows and columns alternate until both are closed. Adding a new row invalidates
the previous reduced-cost certificate; adding a new column requires a new RMP
solution and dual vector.

### 5.2 Stabilization and anti-tailing-off

Use stabilization only after the unstabilized reference passes tiny exactness
tests:

- box or convex-combination stabilization around a dual center;
- deterministic serious/null-step updates based on actual RMP improvement;
- k-best negative columns from each solved pricing problem;
- column acceptance by reduced cost, compatibility contribution, and novelty;
- periodic unstabilized exact pricing before any certificate is declared.

Stabilized duals guide column discovery. The final node certificate always
uses the true current RMP duals.

### 5.3 Restricted primal search

The primal channel runs independently of proof pricing:

- restricted master MIP after material pool growth and at root closure;
- merge-corridor fix-and-optimize neighborhoods;
- Stop/Skip dives based on fractional master decisions;
- optional coordinated CP-SAT package repair;
- exact Passenger evaluation and full movement/headway validation.

Only a complete validated schedule updates $UB$. Every accepted trajectory is
stored in the global pool and can subsequently help all compatible nodes.

### 5.4 Limited Branch-Price-and-Cut tree

Tree work starts only after the root gates pass. Version 1 uses:

- deterministic best-bound node selection with depth tie-breaking;
- global immutable trajectory and cut pools;
- node-local branch domains and local rows;
- warm-started RMP bases when compatible;
- exact node pricing before pruning;
- at most 20, then 50, then 200 processed nodes.

Preferred branch order:

1. `SERVICE_DECISION(c, visit)`: Stop versus Skip;
2. `MERGE_PRECEDENCE(c_i,c_j,merge_occurrence)`: one cross-branch cabin before
   the other;
3. `MOVEMENT_ARC(c,arc)`: use versus avoid;
4. event-time threshold only if movement/service decisions are integral.

Branching on a generated $\lambda$ variable is avoided because omitted
equivalent trajectories can evade it and cabin-label symmetry creates weak
trees. Every branch decision must:

- partition the complete parent trajectory universe;
- filter existing columns;
- be imposed inside single-cabin or cohort pricing;
- serialize to a deterministic fingerprint;
- support contradiction detection without solving.

Merge precedence is introduced only where both sides can be represented
exactly in pricing. It applies to cross-branch interleavings; same-branch FIFO
is already physical structure, not a branch decision.

## 6. Correctness boundaries

### 6.1 Globally valid proof components

- exact restricted LP objective;
- universal merge/resource rows with future-column coefficient oracles;
- globally valid branch-domain restrictions;
- exact or solver-certified single-cabin reduced-cost bounds;
- minimum certified bound over the open tree frontier;
- independent complete movement and Passenger validation for upper bounds.

### 6.2 Primal-only or heuristic components

- coordinated CP-SAT schedule packages;
- compatibility batch selection over a finite candidate list;
- time-limited joint cohort pricing without complete proof;
- dives and fix-and-optimize neighborhoods;
- restricted MIP best bounds;
- pool-local trajectory pair conflicts that lack omitted-column coefficient
  semantics.

These components may improve $UB$ or generate useful columns. They may not
close pricing, prune a node, or raise the global $LB$ by themselves.

### 6.3 Runtime invariants

After every RMP, separation, pricing batch, node update, and checkpoint:

\[
LB\le z_{\mathrm{RMP}}+\varepsilon,
\qquad
LB\le UB+\varepsilon,
\]

\[
LB_t\ge LB_{t-1}-\varepsilon,
\qquad
UB_t\le UB_{t-1}+\varepsilon.
\]

At tree level, the global lower bound may rise only when the certified open
frontier changes. A certificate violation terminates with
`INTERNAL_CERTIFICATE_ERROR`; the suspect bound is not exported.

## 7. OO architecture

Do not create a second trajectory or Passenger model. Extract reusable
interfaces around the existing implementation.

### 7.1 Canonical merge layer

Add:

```text
optimization/ddd/trajectory_merge_domain.py
    DddTrajectoryMergeFamily
    DddTrajectoryMergeOccurrence
    DddTrajectoryMergeProvenance
    DddTrajectoryMergeDomain
    DddTrajectoryMergeDomainBuilder
```

The builder consumes the existing movement network, circulation pattern,
resource checkpoints, and fixed-start problem. It owns no Gurobi objects.

### 7.2 Extensible row layer

Generalize the current resource-window implementation:

```text
optimization/ddd/trajectory_master_rows.py
    DddTrajectoryMasterRowKind
    DddTrajectoryMasterRowScope
    DddTrajectoryMasterRow
    DddTrajectoryCoefficientOracle
    DddTrajectoryMasterRowPool

optimization/ddd/trajectory_merge_rows.py
    DddTrajectoryMergeWindowRowFactory
    DddTrajectoryMergeWindowSeparator
    DddTrajectoryDirectedHeadwayRowFactory
```

`DddTrajectoryMasterRowScope` distinguishes:

- `UNIVERSAL`: coefficient defined for every admissible future column;
- `NODE_UNIVERSAL`: universal inside one branch domain;
- `POOL_LOCAL`: only the named current columns are covered.

Only the first two scopes enter a node certificate. Existing
`trajectory_resource_windows.py` becomes a compatibility facade or is
gradually migrated; there must not be two implementations of interval
endpoint semantics.

### 7.3 Pricing services

Keep `DddTrajectoryExactPricingOptimizer` as the proof oracle and add typed
inputs rather than cloning it:

```text
optimization/ddd/trajectory_pricing_context.py
    DddTrajectoryPricingContext
    DddTrajectoryPricingRowTerm
    DddTrajectoryPricingProofResult

optimization/ddd/trajectory_compatible_batch.py
    DddTrajectoryPricedCandidate
    DddTrajectoryCompatibilityBatchOptimizer
    DddTrajectoryCompatibilityBatchResult

optimization/ddd/trajectory_cohort_pricing.py
    DddTrajectoryCohortSelectionPolicy
    DddTrajectoryCohortPricingProblem
    DddTrajectoryCohortPricingOptimizer
    DddTrajectoryCohortPricingResult
```

The proof result and the compatible-batch result are different types so a
heuristic result cannot accidentally certify a bound.

### 7.4 Reusable node-CG engine

Refactor the orchestration in
`trajectory_root_column_generation.py` only after behavior is covered by
characterization tests:

```text
optimization/ddd/trajectory_node_column_generation.py
    DddTrajectoryNodeCgProblem
    DddTrajectoryNodeCgState
    DddTrajectoryNodeCgResult
    DddTrajectoryNodeColumnGenerationSolver
```

The existing root solver becomes a thin adapter using an empty branch domain.
This avoids maintaining separate root and node pricing loops.

### 7.5 Tree and certificates

Add only after the root gate:

```text
optimization/ddd/trajectory_branch_price_cut.py
    DddTrajectoryBranchNode
    DddTrajectoryNodeQueue
    DddTrajectoryBranchPriceCutConfig
    DddTrajectoryBranchPriceCutSolver

optimization/ddd/trajectory_anytime_certificate.py
    DddTrajectoryNodeCertificate
    DddTrajectoryTreeFrontier
    DddTrajectoryAnytimeCertificate
```

Reuse the implemented `DddTrajectoryBranchDomain` and candidate evaluator.
Extend them with merge precedence only after exact pricing support exists.

### 7.6 Application boundary

Add one benchmark/application runner, not solver logic in CLI code:

```text
benchmarking/ddd_merge_aware_bpc.py
benchmarks/run_ddd_merge_aware_bpc.py
```

The runner accepts the same prepared `DddFixedKTrajectoryProblem` used by the
complete arc-flow and current Root-CG baselines. It exports one common
fingerprint and matched formulation metadata.

## 8. Implementation tranches

### Tranche 0: freeze references and measurements

1. Save immutable matched K=20 and K=39 bakeoff summaries.
2. Add a complete DDD **LP relaxation** run under the same fingerprints. Do
   not compare a trajectory LP against a MIP best bound containing solver
   cuts as if they were the same relaxation.
3. Record initial seed, root LP, first incumbent, bound timeline, model size,
   and resource/Passenger fractionality.
4. Characterize the current Root-CG on the same prepared instance.

Deliverable: `DddMergeAwareRootReference` JSON for tiny, K=20, and K=39.

### Tranche 1: canonical merge domain and coefficient oracle

1. Derive merge families and occurrences from the canonical movement network.
2. Prove stable same-branch FIFO and common-corridor provenance.
3. Implement exact half-open resource-window membership for a trajectory.
4. Wrap current resource rows in the typed universal/local scope.
5. Make exact pricing consume every active universal row coefficient.

No solver behavior changes by default in this tranche.

Stop if coefficient equality cannot be demonstrated against complete tiny
trajectory enumeration.

### Tranche 2: delayed universal merge rows

1. Add deterministic fractional and integer merge-window separation.
2. Alternate RMP solve, separation, and re-pricing correctly.
3. Compare pair-only, current resource-clique, and merge-aware universal rows.
4. Retain only rows that strengthen or compact the reference relaxation
   without invalidating pricing.

Stop if the new master cannot reproduce the exhaustive/complete arc-flow LP
on tiny instances.

### Tranche 3: compatible candidate batching

1. Expose k-best negative pricing incumbents without weakening proof status.
2. Build the finite compatibility MILP over priced candidates.
3. Add the best deterministic jointly compatible batch.
4. Track whether each added column was proof-minimal, secondary negative, or
   compatibility-selected.

Acceptance requires fewer stalled rounds and actual RMP movement on K=39
relative to independent pricing under the same wall-clock budget.

### Tranche 4: bounded joint cohort pricing

1. Rank merge windows by dual magnitude, fractionality, and repeated conflict.
2. Select deterministic 2-, then 3-, then 4-cabin cohorts.
3. Solve exact internal movement compatibility with the current reduced-cost
   objective and a strict sub-budget.
4. Import all resulting trajectories into the global pool.
5. Preserve single-cabin proof pricing as the only reduced-cost certificate.

Stop if cohort pricing consumes more time than it saves in RMP rounds or does
not improve either RMP progress or validated UB on K=39.

### Tranche 5: stabilization and primal polishing

1. Add dual stabilization with mandatory final unstabilized pricing.
2. Run restricted MIP only after material pool growth, root convergence, or a
   configured incumbent-stagnation interval.
3. Add merge-corridor fix-and-optimize using the global column pool.
   **Implemented; experimental K=20/K=39 gate pending.**
4. Validate and persist every improved incumbent.

This tranche should yield the strongest root certificate and primal result
before any tree development.

### Tranche 6: limited Branch-Price-and-Cut pilot

1. Extract the reusable node-CG service.
2. Implement deterministic node queue and checkpointing.
3. Add Stop/Skip branching first.
4. Add merge precedence only after exhaustive sibling-partition tests.
5. Run 20/50/200-node pilots with a common global pool.

Proceed to a full tree only if the certified global LB rises materially or a
validated UB improves beyond the root-only method under matched time.

### Tranche 7: bounded Waiting

Waiting is not represented by three arbitrary global choices. Add it after
the No-Wait method passes:

- finite exact waiting ticks $w\in\{0,\Delta,2\Delta,\ldots,W_{\max}\}$;
- waiting state inside the trajectory pricing network;
- platform occupancy from entry through release;
- waiting-dependent outgoing merge occurrence;
- unchanged FIFO within the Service branch;
- exact future-column coefficients for every waiting-expanded resource row.

DDD refinement may begin with a coarse waiting grid and insert necessary ticks,
but a certified result requires either complete grid coverage for the declared
domain or a valid discretization bound. No-Wait columns remain valid warm
starts.

## 9. Tests

### 9.1 Mathematical unit tests

- half-open window endpoints at $t$, $t+h-1$ tick, and $t+h$;
- constant and leader-dependent headway coefficients;
- Service/Service and Skip/Skip FIFO provenance;
- cross-branch merge precedence remains undecided until selected;
- horizon entry/tail occurrences receive the correct coverage;
- identical coefficient from row factory, RMP builder, and pricing oracle;
- stable row IDs and fingerprints independent of insertion order.

### 9.2 Exhaustive tiny references

Enumerate every trajectory for 2--4 cabins on One-/Three-Station fixtures and
compare:

- complete configuration LP;
- complete labeled DDD arc-flow LP;
- generated merge-aware root LP;
- pricing minimum for randomized dual vectors;
- pricing-corrected node bound;
- branch sibling union and intersection;
- complete tree integer optimum.

Required numerical relation:

\[
LB_{\mathrm{priced}}
\le z_{\mathrm{full\ LP}}
\le z_{\mathrm{integer}}
\le UB_{\mathrm{validated}}.
\]

At exact root convergence, the generated and complete configuration LP values
must agree within tolerance.

### 9.3 Coordinated pricing tests

- two individually negative conflicting columns are not selected together;
- a less negative compatible combination is selected when it improves total
  batch value;
- candidate batching is deterministic under permuted inputs;
- cohort pricing respects all internal headways and branch domains;
- timeout/no batch does not alter proof status;
- imported cohort columns are deduplicated globally;
- the single-cabin proof bound is unchanged by heuristic batch failure.

### 9.4 Tree/certificate tests

- children are disjoint and cover the parent universe;
- existing and future columns obey identical branch filtering;
- node pruning requires certified pricing or bound dominance;
- global frontier LB is monotone;
- restricted-MIP bounds never enter the global certificate;
- checkpoints reproduce queue order, pools, bounds, and incumbent;
- deliberate coefficient/certificate corruption fails closed.

### 9.5 Regression

- existing Root-CG behavior remains available;
- complete DDD arc-flow K=20 result remains unchanged;
- EAN and merge-sequence isolated gates remain unchanged;
- frontend and terminal distinguish root LP, global tree LB, RMP objective,
  and validated UB;
- the full test suite stays green before enabling the new mode in campaigns.

## 10. Experimental gates

### Gate A: exact root equivalence

Cases:

- exhaustive tiny fixtures;
- Five-Station B, $K=20$, No-Wait, identical fixed-start fingerprint.

Compare complete configuration LP where enumerable, complete arc-flow LP,
pair-only Root-CG, merge-aware Root-CG, and integer reference.

Accept if:

- no certificate invariant fails;
- exact pricing reproduces exhaustive reduced costs;
- generated root LP matches the intended complete trajectory LP;
- K=20 reaches a root gap below 1% relative to the known integer optimum
  under the same fingerprint;
- runtime is not more than twice the complete DDD baseline on K=20 without a
  compensating formulation-strength benefit.

### Gate B: K=39 root scalability

Budget: first 15 minutes, then 60 minutes only if progress is visible.

Compare:

- complete DDD arc-flow;
- existing pair-only trajectory Root-CG;
- universal merge rows with independent pricing;
- universal merge rows plus compatible batches;
- plus cohort pricing and stabilization.

Measure curves, not only endpoints:

- certified LB and RMP objective over time;
- validated UB over time;
- time to leave the seed;
- columns per round and compatible accepted columns;
- row count and active merge windows;
- pricing correction and number of unresolved cabins;
- Passenger versus movement time;
- peak memory and master size.

Accept the merge-aware root method only if, within 60 minutes, it satisfies all
of:

1. nonzero and competitive certified LB against the equivalent complete
   arc-flow LP reference;
2. RMP does not remain at the single seed;
3. at least one genuine Skip-Stop incumbent better than the periodic seed, or
   a clear quantified reason why the Passenger master rather than column
   compatibility is the remaining bottleneck;
4. no proof/primal scope ambiguity.

### Gate C: limited tree value

Run 20, 50, and 200 nodes on K=20 and K=39. Compare root-only versus tree at
the same total time.

Accept full Branch-Price-and-Cut development if the pilot:

- raises the global certified LB by at least 10% of the root integer gap, or
- improves the validated UB materially through node incumbents while keeping
  a correct frontier certificate, and
- processes nodes without pricing time exploding superlinearly.

If neither happens, stop tree work and retain the root method as a bound
engine plus a separate exact/heuristic primal method.

### Gate D: policy evidence

After the algorithmic gates, run matching All-Stop/Skip-Stop pairs around the
All-Stop capacity frontier. For minimization:

\[
LB(\Delta_K)=LB_{AS,K}-UB_{SS,K},
\]

\[
UB(\Delta_K)=UB_{AS,K}-LB_{SS,K}.
\]

`LB(Delta_K) > 0` proves a minimum Skip-Stop Passenger benefit. Above
$K_{\max}^{AS}$, distinguish:

1. the movement-capacity claim: All-Stop infeasible, Skip-Stop feasible;
2. the demand claim: certified comparison of the best available All-Stop
   fleet with exact-$K$ Skip-Stop.

## 11. Runtime profiles and progress

Profiles count setup, separation, pricing, RMP, MIP, validation, and
checkpointing in one wall-clock budget.

| Profile | Root budget | Cohort cap/round | Restricted MIP | Tree nodes | Intended use |
|---|---:|---:|---:|---:|---|
| unit | 30 s | 2 s | 2 s | 0 | tests |
| screening | 15 min | 15 s | 60 s | 0 | formulation gate |
| regular | 60 min | 60 s | 300 s | 50 | K/demand comparison |
| headline | 4 h | 300 s | 1,800 s | 200+ | selected thesis cases |

Terminal and frontend show without jitter:

- certified global/root/node LB, RMP objective, validated UB, and gap;
- root round or node/depth/open frontier;
- active pricing tier and exact/certified/unresolved cabin counts;
- individually priced, batch-selected, and cohort-generated columns;
- universal, node-universal, and pool-local rows;
- merge family/window currently separated or priced;
- restricted MIP status and last genuine incumbent improvement;
- time in Passenger LP, separation, proof pricing, cohort pricing, MIP, and
  validation;
- remaining total budget and checkpoint sequence.

Heartbeat samples retain the last valid bounds. They never replace them by
zero or a dash merely because the current phase has no new solver sample.

## 12. Thesis deliverables

Document the method as **merge-aware Branch-Price-and-Cut with coordinated
column generation**, not as Logic-Based Benders and not as a generic EAN
reformulation.

The mathematical chapter contains:

- exact-$K$ trajectory master and Passenger coupling;
- physical merge/resource-window inequalities;
- FIFO proof within Service and Skip branches;
- reduced-cost pricing and corrected node bound;
- proof/primal separation for coordinated batches;
- physical branching rules and global tree certificate;
- finite bounded-Waiting extension;
- policy-improvement interval and capacity-extension distinction.

The experiment chapter reports negative as well as positive gates:

- complete DDD and EAN bakeoff;
- failed isolated Lattice/Slot merge sequence gate;
- independent-pricing incompatibility at K=39;
- contribution of universal rows, compatible batches, cohort pricing,
  stabilization, and branching;
- time curves for LB, RMP, UB, and gap;
- exact-K and available-fleet policy conclusions across demand profiles.

## 13. Stop conditions and alternatives

Stop before tree implementation if:

- universal row coefficients cannot be priced exactly;
- generated root LP disagrees with exhaustive references;
- K=39 corrected LB collapses to the objective floor;
- compatible/cohort pricing does not move the RMP under the one-hour gate;
- Passenger coupling dominates after movement compatibility is fixed and no
  smaller exact Passenger master is found.

If the last case occurs, the next experiment is not more branch nodes. Test a
Passenger decomposition or route-load pattern columns against the same root
LP reference. If merge rows remain weak, test an alternative-graph/resource-
precedence formulation locally. If only the incumbent is weak, use
deterministic fix-and-optimize/ALNS as a primal supplement while retaining the
certified root/tree LB.

Longer complete-MILP runs remain a baseline. They are preferable whenever
their bound/incumbent curves dominate this method under matched fingerprints
and budgets. The new method is accepted by measured certificate progress, not
by architectural novelty.

## 14. Assumptions

- First implementation: fixed canonical starts, exact $K$, No-Wait, one
  deterministic circulation pattern, finite horizon.
- Different Stop/Skip choices remain possible in every rotation; no periodic
  route template is imposed.
- Cabins cannot overtake within one physical branch; Service and Skip streams
  may interleave at their merge.
- Passenger Assignment stays explicit and exact at first.
- Exact single-cabin pricing remains the proof oracle even when coordinated
  pricing generates columns.
- No tree is built until the merge-aware root gate succeeds on K=20 and K=39.
- Waiting is added only as a finite, declared, exactly priced domain after the
  No-Wait method is stable.

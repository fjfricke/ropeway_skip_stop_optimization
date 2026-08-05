# Merge-Relaxed EAN with Monotone Backward Repair

Status: **proposed research and implementation plan**

## Decision Summary

Test whether the integrated optimized-initial-placement (OIP) EAN becomes
practically solvable when the disjunctive order decisions created by
stop/skip reconvergence are removed from the MILP and repaired afterwards.
The intended pipeline is:

```text
full physical network + demand + OIP
    -> classify exact corridor and merge-conflict families
    -> solve merge-relaxed passenger MILP
    -> repair merge conflicts from latest to earliest
    -> normalize the complete repaired history at its minimum time
    -> extract the resulting initial fleet state
    -> re-optimize passengers on the fixed repaired movement
    -> complete independent validation
```

The key hypothesis is structural. On a deterministic corridor, cabin order is
preserved and adjacent directed headways suffice. At a reconvergence of two
route streams, the model must otherwise choose between many pairwise orders:

\[
t_i+h_{ij}\leq t_j
\quad\lor\quad
t_j+h_{ji}\leq t_i.
\]

Those merge-order disjunctions are expected to cause a disproportionate share
of the large branch-and-bound tree. The experiment must establish this rather
than assume it.

This method is a **heuristic relax-and-repair algorithm with a valid lower
bound**, not an exact replacement for the eager model. A merge-relaxed optimum
is a lower bound for the unchanged full objective. Only a repaired plan that
passes complete separation is a feasible upper bound. Failure to repair does
not prove infeasibility.

The existing eager all-pairs mode remains the default and reference. The
existing delayed-violation generator also remains distinct: delayed generation
eventually restores every violated original disjunction and is exact, whereas
this method intentionally solves a relaxation and then performs a directed
timing repair without returning to the full integrated MIP.

## Research Questions and Stop Criteria

The implementation answers five questions in order:

1. **Concentration:** How many current order binaries belong to genuine
   cross-stream merge-conflict families rather than ordered corridors?
2. **Relaxed solvability:** Does removing only those families materially reduce
   build time, root difficulty, time to incumbent, and time to a small gap for
   OIP38, OIP76, and larger networks?
3. **Repairability:** Are relaxed solutions normally repairable by monotone
   backward shifts without changing stop/skip choices?
4. **Passenger quality:** After exact fixed-movement passenger reassignment,
   how close is the feasible repaired objective to the relaxed lower bound and
   to available eager baselines?
5. **Fleet sweet spot:** Which exact active cabin count gives the best repaired
   passenger result, and what is the smallest fleet within a declared quality
   tolerance of that result?

Do not build a sophisticated repair search before question 2 is answered. Stop
after the diagnostic phase if the correctly defined relaxation does not
materially improve the solver measurements. Stop after the first repair phase
if most relaxed incumbents require changing discrete route choices rather than
retiming.

## Scope

The first implementation supports the current deterministic line and ring
circulation patterns with:

- fixed starts and optimized initial placement;
- stop and skip route options that reconverge;
- optional station waiting;
- the current finite operational and passenger-evaluation horizons;
- the current journey-time passenger objective;
- the canonical `EanMovementNetwork` and compatibility resources.

Dynamic turnback choice, dynamic rope transfer, depots, and arbitrary route
selection are outside the first implementation. The provenance types must not
preclude them, but no repair correctness claim is made for them.

## Terminology and Conflict Taxonomy

The current checkpoint kind alone is insufficient to identify a merge.
`EXIT_SWITCH` can represent ordinary safety on a deterministic stream as well
as stop/skip reconvergence. Classification must derive from route-option and
resource provenance.

Introduce a stable conflict taxonomy:

```text
ORDERED_CORRIDOR
  both candidates belong to one topology-proven order-preserving stream

BRANCH_INTERNAL
  both candidates use the same incoming route family before reconvergence

CROSS_STREAM_MERGE
  candidates arrive through distinct incoming route families that reconverge
  on the same movement state or physical resource

MERGE_PROPAGATED
  a downstream pair whose disjunction reimposes the same unresolved merge
  order before any event can absorb or legitimately change relative timing

UNCLASSIFIED
  provenance is insufficient; retain the original full disjunction
```

Every classified pair receives immutable provenance containing:

- conflict role;
- physical resource and checkpoint;
- reconvergence state and merge-family ID when applicable;
- incoming route-family IDs;
- downstream deterministic-corridor ID when applicable;
- classification proof/reason;
- original pair ID and candidate IDs.

Classification is conservative. `UNCLASSIFIED` always remains constrained.
No rule may classify all `EXIT_SWITCH` pairs as merges.

### Merge-conflict families

Removing only the first disjunction at a merge may have no effect if the same
pair is constrained again at the next checkpoint after equal deterministic
travel. Therefore the unit of relaxation is a merge-conflict family, not one
checkpoint row.

A `CROSS_STREAM_MERGE` pair starts a family. A downstream pair belongs to the
same family only while all of the following are proven:

1. both candidates continue on the same non-branching corridor;
2. their relative event-time expression changes only by identical fixed
   offsets;
3. no permitted waiting or route decision can absorb or change their relative
   timing;
4. the downstream disjunction therefore enforces exactly the unresolved merge
   order already omitted upstream.

Such pairs are `MERGE_PROPAGATED`. The family ends at a branch, a legal waiting
or buffering state, a circulation boundary that is not proven continuous, or
any point where the proof is inconclusive. Headways after the family end remain
in the relaxed model unless independently classified into another family.

The classifier must report both direct-only and full-family counts so the
diagnostic experiment can show whether a direct merge toggle merely moves the
same conflict downstream.

## Mathematical Relaxation Contract

Let the full integrated model be

\[
\min J(x,p)
\quad\text{subject to}\quad
(x,p)\in\mathcal F,
\]

where `x` contains movement, OIP, stop/skip, waiting, and order decisions, and
`p` contains passenger decisions. Partition the headway constraints into
retained constraints \(C_R\) and proven merge-conflict families \(C_M\).
The relaxed feasible region is

\[
\mathcal F_{\mathrm{relax}}
=
\{(x,p): C_R\text{ and every non-headway constraint hold}\}.
\]

Because only original constraints are removed,

\[
\mathcal F\subseteq\mathcal F_{\mathrm{relax}}
\quad\Longrightarrow\quad
J_{\mathrm{relax}}\leq J^*.
\]

If repair and passenger reassignment produce a completely validated plan with
objective \(J_{\mathrm{repair}}\), then

\[
J_{\mathrm{relax}}
\leq J^*
\leq J_{\mathrm{repair}}.
\]

This bound is reported only when the relaxed solve has the corresponding
solver certificate. An incumbent from an unfinished relaxed solve is not a
lower bound; use Gurobi's best bound. If the time origin or demand definition
is changed rather than translated equivalently, do not compare these values.

## Relaxed MILP Formulations

Provide three experimental modes in addition to the unchanged full model:

```text
FULL_EAGER
DIRECT_MERGE_ABLATION
MERGE_FAMILY_RELAXATION
MERGE_FAMILY_CORRIDOR_COMPACT
```

`DIRECT_MERGE_ABLATION` removes only `CROSS_STREAM_MERGE` pairs and exists only
to detect downstream reimposition. It is never the proposed production
heuristic.

`MERGE_FAMILY_RELAXATION` removes `CROSS_STREAM_MERGE` and
`MERGE_PROPAGATED` families but leaves every other current pair and formulation
unchanged. It isolates the effect of the intended relaxation from an exact
corridor reformulation.

`MERGE_FAMILY_CORRIDOR_COMPACT` adds the exact structural reduction that makes
merge-free streams cheap. For every topology-proven fixed order

\[
c_1\prec c_2\prec\dots\prec c_K,
\]

enforce only adjacent directed headways

\[
t_{c_{q+1},r}\geq t_{c_q,r}+h_r.
\]

Transitivity removes non-adjacent rows only when all relevant activation,
waiting-occupancy, and horizon conditions are identical or are included in the
proof. Otherwise retain the original rows. No global order is inferred across
a stop/skip merge, and no later overtaking is prohibited.

The pair artifact and solve result must explicitly identify the model as
merge-relaxed. It must not use `COMPLETE` coverage and must not be accepted by
normal full-model validation paths without a repair certificate.

## Monotone Backward Repair

### Base schedule

Extract one relaxed incumbent with all discrete decisions fixed:

- active cabins and OIP choices;
- stop/skip route choices;
- visit activation and horizon decisions;
- retained headway orders;
- the movement time solution.

Passenger assignments from this incumbent are diagnostic only. Retiming can
move a departure before a passenger release time, so final passenger
feasibility is established by a new fixed-movement assignment.

Run the complete existing separator over all original candidate pairs. Group
violations by merge-family ID and reject any violation classified outside the
omitted families as an internal inconsistency.

For every active omitted pair, derive a deterministic chronological direction
from the relaxed event times, with stable candidate ID as the tie-breaker. An
already satisfied pair becomes a protected directed relation immediately. A
violated pair receives the same minimum-change direction by default and becomes
protected as soon as its repair is selected. At one resource, store only the
adjacent relations of the resulting total order when transitivity and identical
activation semantics prove that sufficient. This prevents a later shift from
destroying an omitted merge headway that happened to be satisfied in the
relaxed incumbent.

### Uniform order-ideal repair

The first repair implementation follows the proposed latest-to-earliest rule.
For a violated merge with events \(a\) and \(b\), assume

\[
t_a\leq t_b<t_a+h.
\]

Preserving the chronological order requires the earlier event to move earlier
by at least

\[
\delta=h-(t_b-t_a).
\]

Construct a shift set \(S\) containing \(a\), but not \(b\), and close it
under:

1. movement predecessors whose constraints would otherwise be violated;
2. all earlier events in each already ordered rope/resource stream;
3. both ends of equality-linked events that must move together;
4. boundary occupancy and waiting semantics represented by the original
   candidate time expressions;
5. every protected direction of an omitted merge pair.

Exact rope travel is an equality in the current EAN. Therefore closure may
propagate forward along the same cabin after the selected merge and then
backwards through the order on another shared resource. The shifted set is not
assumed to be a literal timestamp prefix. It is a closure in the active event
dependency graph and may span a large part of a long horizon.

The essential condition is that `S` is an order ideal: for every retained
directed safety relation \(u\prec v\),

\[
v\in S\Longrightarrow u\in S.
\]

Apply

\[
t'_v=
\begin{cases}
t_v-\delta,&v\in S,\\
t_v,&v\notin S.
\end{cases}
\]

Then a retained headway has only three possible cases:

- both events are shifted, so its difference is unchanged;
- only its leader is shifted, so its separation increases;
- only its follower is shifted, which the order-ideal condition excludes.

Therefore the repair creates no new retained headway violation. The same
argument holds for one-sided minimum-duration movement arcs when the shift set
is predecessor-closed. Exact-duration arcs are safe only because equality
closure shifts both endpoints. Protected omitted merge relations obey the same
order-ideal argument, so an already satisfied or repaired merge cannot become
violated again even when equality closure propagates beyond the pivot time.

Do not stop a shift between an exit-switch event and its next switch event. In
the current model their difference equals the physical rope travel time;
stopping there would introduce fictitious waiting on the rope. A uniform
repair is valid only after complete equality and resource-order closure.

If closure includes \(b\), the uniform shift cannot alter the violated relative
time. Mark that direction blocked and try the reverse merge orientation. If
both directions are blocked, return a repair failure for this discrete
incumbent; do not silently change route choices in the first implementation.

### Slack-minimal repair

Uniform prefix shifts are the correctness baseline, but can move more history
than necessary. The second implementation uses one nonnegative advance
variable \(z_v\) per active event:

\[
t'_v=t_v-z_v.
\]

For a retained ordered headway \(i\prec j\), define incumbent slack

\[
\sigma_{ij}=t_j-t_i-h_{ij}\geq0.
\]

Headway preservation is exactly

\[
z_j-z_i\leq\sigma_{ij}.
\]

For a minimum-duration movement arc \(u\to v\) with duration \(d_{uv}\), use

\[
z_v-z_u
\leq
t_v-t_u-d_{uv}.
\]

Maximum-duration and equality constraints add the reverse inequalities needed
to preserve their bounds. A selected merge orientation \(a\prec b\) adds

\[
z_a-z_b
\geq
h-(t_b-t_a).
\]

Solve all currently selected merge repairs together while minimizing a stable
movement measure, initially

\[
\min
\left(
W\max_v z_v+
\sum_v w_v z_v
\right),
\]

with deterministic weights and a dominating `W`. This consumes available
slack before propagating a shift further backwards. With fixed orientations,
the model contains no order binary and no Big-M. Benchmark a direct reverse
graph propagation against a small continuous Gurobi model; retain the graph
path only if it covers every current timing semantic exactly.

The latest-to-earliest chronological orientation is the baseline. For a
blocked or expensive conflict, evaluate both orientations with the continuous
repair model and choose the feasible one with smaller lexicographic repair
cost.
Do not introduce a global binary merge-order MIP in this plan.

### Iteration and termination

Process the unresolved family with the latest violated merge time. Once a
family direction has been selected, add it to the protected relation graph.
After each uniform repair, or after a deterministic batch in slack-minimal
mode:

1. update all affected time expressions and waiting values;
2. rerun full separation over the affected prefix;
3. confirm that no protected family became violated;
4. continue with the next latest violation.

Because every processed relation becomes protected and order-ideal shifts
preserve protected relations, the uniform method processes at most the finite
set of active omitted relations unless closure blocks a selected direction. An
iteration cap remains mandatory. A repeated protected conflict, attempted
duplicate orientation, or protection violation is an internal consistency
failure rather than a normal loop.

### Horizon propagation

Increasing the event horizon can enlarge equality/resource closure. In a dense
zero-slack stream, one merge correction may propagate through several stations
and rotations and touch most modeled events. Choosing `t_min` as the eventual
simulation origin removes an artificial nonnegative-time obstruction, but it
does not make this computation local and does not prevent passenger-relevant
events from moving.

Measure closure size as a primary scaling metric. The slack-minimal variant is
the intended remedy: positive temporal or headway slack attenuates the shift,
whereas a fully saturated corridor correctly transmits it. If closure is
consistently horizon-wide, replace repeated set expansion by the single
batched difference-constraint solve; do not repeatedly scan the same history.

## Time Origin and Reconstructed Initial State

Backward repair may produce negative event times. OIP has no externally fixed
initial placement, so negative time is not a physical failure. After complete
repair define

\[
t_{\min}=\min_v t'_v
\quad\text{and}\quad
\hat t_v=t'_v-t_{\min}.
\]

This is a global translation; every travel time and headway difference is
unchanged. The new simulation start is the complete fleet state

\[
X(t_{\min})=
\bigl(x_1(t_{\min}),\ldots,x_K(t_{\min})\bigr),
\]

not merely the cabin owning the earliest event. For every active cabin,
reconstruct:

- movement state or rope segment at `t_min`;
- continuous position or residual time to its next checkpoint;
- selected incoming route where needed;
- station occupancy and waiting state;
- resource order and boundary headways.

If a cabin trajectory is not represented back to `t_min`, prepend its
deterministic circulation history until the state is reconstructible. If
prepending would require an unknown dynamic route decision, the first-stage
method reports unsupported rather than inventing a state.

Maintain two explicit clocks in results and exports:

```text
simulation time
  starts at the normalized t_min = 0

evaluation time
  starts when the original passenger-demand window begins
```

If the original demand begins at time zero, its normalized release times are

\[
\hat r_p=r_p-t_{\min}.
\]

Thus `-t_min` is an unscored warm-up interval. Translating movement, demand,
evaluation horizon, and tail together preserves the original optimization
instance and its lower-bound comparison. Resetting demand independently to
the new zero defines a different experiment and must be labeled as such.

For fixed-start instances, this rebasing is not permitted unless the resulting
state equals the prescribed start. Fixed-start repair must respect its original
time and placement bounds or report failure.

## Passenger Re-optimization and Objective Certificate

After movement repair and normalization:

1. freeze the complete movement plan;
2. rebuild passenger candidates against the repaired event times;
3. solve the existing exact fixed-movement passenger assignment;
4. validate capacity, boarding, alighting, transfers, release times, and the
   complete journey-time objective;
5. combine its objective with the relaxed solver bound.

Report:

\[
\text{certified gap}
=
\frac{J_{\mathrm{repair}}-LB_{\mathrm{relax}}}
{\max(1,|J_{\mathrm{repair}}|)}.
\]

If fixed-movement passenger assignment is infeasible, the repaired movement is
still a physical movement solution but not a feasible solution of the
passenger instance. The result status must distinguish those cases.

## Adaptive Fixed-K Fleet Search

### Motivation

The merge-relaxed MILP can make additional cabins look artificially valuable.
Same-stream rope headways remain enforced, but omitted cross-stream merge
families temporarily remove part of the physical congestion cost. With an
optional fleet and no activation cost, the relaxed passenger objective may
therefore activate every available cabin even when a smaller fleet produces a
better plan after repair.

Fleet selection must consequently use complete Fixed-K evaluations. For one
exact active count `K`, define

\[
\widehat J(K)
=
\min\{J_{\mathrm{passenger}}(s):
s\text{ is a fully repaired and validated incumbent at exact }K\}.
\]

An unrepaired relaxed objective is never a fleet-selection score. The exact-K
contract uses the existing active cabin prefix and fixes

\[
a_c=1\quad(c<K),
\qquad
a_c=0\quad(c\geq K).
\]

The fixed-K evaluator should repair several diverse relaxed incumbents when
available, because the relaxed optimum can be harder to repair than a slightly
worse relaxed solution.

### Optuna as outer study controller

Implement an optional persistent Optuna study runner instead of hard-coding a
coarse then fine grid. Optuna selects only the integer `K`; one trial executes
the complete fixed-K pipeline:

```text
suggest K
  -> merge-relaxed exact-K solve
  -> extract selected incumbent pool
  -> repair every admitted incumbent
  -> normalize and reconstruct its OIP state
  -> solve fixed-movement passengers
  -> validate
  -> return the best repaired passenger objective for K
```

Use a seeded `TPESampler` initially. The repaired objective may be discontinuous
because stop/skip decisions and repair feasibility change discretely, so do not
assume a smooth or unimodal function and do not use binary or ternary search.
Seed the study with a small deterministic anchor set containing the known
all-stop fleet, the configured maximum, available analytical capacity bounds,
and one or two interior values. Anchors initialize the sampler; they are not a
separate coarse-search phase.

Cache evaluations by the complete experiment key

```text
(scenario fingerprint, demand fingerprint, K, formulation configuration,
 solver configuration, repair configuration, code/version fingerprint)
```

so a duplicate suggestion never launches another Gurobi run accidentally.
Repeated trials are allowed only when the experiment explicitly adds solver
seeds as a search or replication dimension.

Persist studies and per-trial artifact references. A local serial runner may
use SQLite. Parallel studies require a concurrency-safe RDB backend and an
explicit allocation of Gurobi threads and licenses. The initial scientific
comparison runs serially with one fixed solver seed so Optuna learns variation
in `K`, not variation between solver runs.

### Trial score and failure handling

A completed feasible trial returns `J_repair(K)` and stores all subordinate
metrics as trial attributes. A trial without a validated passenger plan stores
its explicit failure status and is excluded from the feasible score set. Do not
convert repair failure into mathematical infeasibility.

Generic median or percentile pruning is disabled initially. Intermediate
relaxed incumbents are not calibrated predictors of the final repaired
objective. Early termination is permitted only for a documented rule:

- the trial cannot produce a relaxed incumbent in its budget;
- all admitted incumbents are repair-blocked;
- the fixed trial budget is exhausted;
- a valid relaxed lower bound proves that the trial cannot improve the current
  target required by the active study stage.

The last rule is certificate-based, not an Optuna performance heuristic. Store
whether each termination was safe, heuristic, or budget-induced.

### Two-stage sweet-spot definition

Do not hide the fleet trade-off behind an arbitrary weighted sum
`passenger_objective + lambda * K`. Run two linked single-objective stages.

Stage A estimates the best repaired passenger quality:

\[
J_{\mathrm{best}}
=
\min_K \widehat J(K).
\]

Stage B searches for the smallest validated fleet within a declared tolerance
`epsilon`:

\[
K_{\varepsilon}
=
\min\left\{
K:
\widehat J(K)
\leq
(1+\varepsilon)J_{\mathrm{best}}
\right\}.
\]

Stage B reuses every completed Stage-A evaluation and directs new trials toward
the unresolved lower-K quality boundary. The default scientific output is the
observed Pareto table `(K, J_repair(K))`, not only Optuna's selected trial.
Multi-objective Optuna sampling may be added as a comparison, but is not the
initial implementation because pruning and finite-budget interpretation are
clearer in the two single-objective stages.

`J_best` is an incumbent-based reference unless every relevant fixed-K trial is
certified optimal. Therefore label `K_epsilon` as the smallest fleet within
epsilon of the **best repaired solution found**, not necessarily of the unknown
global optimum.

### Neighbor warm starts and budgets

Before one fixed-K solve, retrieve the nearest completed feasible study trial:

- for `K+1`, retain the first `K` active trajectories and initialize the new
  cabin in the largest proven initial rope gap;
- for `K-1`, remove a cabin with low passenger contribution and high repair
  burden, then preserve the remaining prefix through deterministic relabeling;
- transfer compatible stop/skip, times, waiting, and passenger assignments as
  partial starts only.

Every trial in one comparison tier receives the same total wall-clock budget,
including build, relaxed solve, incumbent extraction, repair, normalization,
passenger assignment, and validation. A later promotion tier may grant longer
budgets to promising `K` values, but its results are recorded as a different
fidelity and never silently replace equal-budget comparisons.

## Public Configuration and Result Contract

Add one opt-in top-level strategy; keep all internal variants experimental:

```text
EAGER_FULL
MERGE_RELAXED_BACKWARD_REPAIR
```

The merge strategy configuration contains:

- relaxation variant (`direct`, `family`, `family_corridor_compact`);
- repair variant (`uniform_order_ideal`, `slack_minimal`);
- relaxed MILP time limit and MIP-gap policy;
- repair iteration and wall-clock budgets;
- headway and numerical tolerances;
- orientation rule and two-orientation fallback;
- normalization and passenger-reassignment policy;
- deterministic progress and artifact-output settings.

The optional fleet-study configuration contains:

- exact integer `K` bounds and deterministic anchor values;
- TPE seed and startup-trial count;
- Stage-A and Stage-B trial/time budgets;
- quality tolerance `epsilon`;
- number and diversity rule of relaxed incumbents repaired per `K`;
- persistence URL, study name, resume policy, and cache policy;
- single-trial solver threads and optional promotion-fidelity settings.

Use explicit statuses:

```text
REPAIRED_PASSENGER_FEASIBLE
  full movement and passenger validation passed

REPAIRED_MOVEMENT_ONLY
  physical repair passed, passenger reassignment did not produce a solution

RELAXED_INCUMBENT_NO_REPAIR
  a relaxed incumbent exists but repair exhausted its budget or was blocked

RELAXED_NO_INCUMBENT
  no relaxed incumbent was found in the budget

UNSUPPORTED_INITIAL_STATE
  the normalized complete fleet state cannot be reconstructed

INVALID_INTERNAL
  a retained constraint or final independent validation failed
```

None of these statuses except a separately proven full-model result may be
reported as mathematical infeasibility.

Store the relaxed artifact, omitted merge families, relaxed incumbent, repair
trace, normalized movement, passenger result, and final certificate as
distinct objects. A downstream caller must not confuse a relaxed incumbent
with a physically feasible plan.

## Metrics and Progress

### Classification and build

- candidates and original pairs by checkpoint and resource;
- pairs and binaries by conflict role;
- direct merge and propagated-family counts;
- retained, directed, adjacent-only, and omitted counts;
- artifact time, model-build time, peak RSS, rows, columns, binaries, and
  nonzeros.

### Relaxed solve

- presolve reductions;
- root relaxation and root time;
- first-incumbent time and objective;
- best incumbent, best bound, gap, node count, and solve status;
- stop/skip, waiting, active-cabin, and OIP summary.

### Repair

- initial violations by family, resource, and magnitude;
- selected orientation per conflict;
- closure size or nonzero shift-vector size per iteration;
- requested and propagated delta;
- maximum, sum, and passenger-weighted advance;
- absorbed slack by constraint type;
- new `t_min` and warm-up duration;
- blocked orientations, repeated conflicts, iterations, and repair time;
- complete final separator result.

### Passenger and certificate

- passenger reassignment time and status;
- relaxed incumbent objective, relaxed lower bound, repaired objective;
- absolute and relative certified gaps;
- unserved passengers if permitted by the original objective;
- comparison with eager and reservation-decoder baselines.

### Fleet study

- suggested, cached, running, completed, pruned, and failed trial counts;
- exact `K`, study stage, fidelity, source anchor, and warm-start source;
- best feasible `J_repair(K)` and number of repaired incumbents per `K`;
- all failure statuses and termination reasons;
- current `J_best`, epsilon threshold, smallest qualifying `K`, and unresolved
  lower-K candidates;
- complete observed `(K, J_repair(K))` Pareto table.

Progress must show separately:

```text
classification -> build -> relaxed solve -> separation
-> backward repair -> normalization -> passenger assignment -> validation
```

The outer study adds a compact line with trial number, `K`, stage, current
best repaired objective, current epsilon fleet, trial elapsed time, and total
remaining study budget. Gurobi output remains nested under the active trial.

## Implementation Phases

### Phase 0: Read-only conflict census

Implement provenance and classification without changing any model. Run the
full current artifacts through the classifier and report role/family counts.
Manually inspect deterministic samples from every category and compare direct
merge counts with propagated-family counts.

Deliverable: a finding in `docs/findings` showing whether the merge hypothesis
is large enough to justify solver work.

### Phase 1: Controlled relaxation ablation

Add the three relaxation variants while leaving the eager model unchanged.
Require explicit relaxed artifact scope and prohibit normal production solve
paths from claiming full feasibility. Run build-only and bounded solve
experiments before implementing repair.

Decision gate: continue only if full-family relaxation materially improves at
least time to first incumbent or root progress on OIP38/OIP76, and verify that
direct-only ablation does not merely recreate the same disjunction downstream.

### Phase 2: Uniform monotone repair

Build the directed active-event dependency graph, implement order-ideal
closure, process conflicts latest-to-earliest, and independently re-separate
after every repair. Support movement-only normalization and complete initial
state reconstruction.

Decision gate: most small and OIP38 relaxed incumbents must repair without
changing stop/skip choices and pass complete movement validation.

### Phase 3: Slack-minimal batched repair

Add shift variables or the equivalent graph propagation, consume existing
slack, evaluate both orientations only when needed, and repair compatible
conflicts in deterministic batches. Compare movement displacement and runtime
against uniform closure.

### Phase 4: Passenger recourse and certificate

Integrate normalized demand clocks, exact fixed-movement passenger assignment,
objective bounds, exports, CLI progress, and result statuses. No repaired
passenger result is accepted without independent full validation.

### Phase 5: Adaptive Fixed-K fleet study

Add the persistent Optuna controller only after one fixed-K evaluation is fully
reproducible. Implement cached exact-K trials, deterministic anchors, TPE
sampling, two-stage epsilon selection, neighbor warm starts, equal-budget
accounting, progress, and Pareto export. Validate the controller first against
an exhaustive small-K sweep.

### Phase 6: Scaling and optional local recourse

Only if earlier phases succeed, allow bounded local recourse when both timing
orientations fail: unfix stop/skip and waiting choices for the involved merge,
cabins, and neighboring visits, solve that neighborhood, then resume backward
repair. This is a later heuristic and must be measured separately. Do not turn
it into a global CBS, Benders, or alternative-graph search in this plan.

## Testing

### Classification tests

- same incoming option is `BRANCH_INTERNAL`;
- distinct reconverging options are `CROSS_STREAM_MERGE`;
- identical downstream fixed offsets create `MERGE_PROPAGATED`;
- waiting, branching, or insufficient proof ends propagation;
- ordinary exit-switch pairs are not mislabeled as merges;
- shared physical `resource_id` across topology objects is handled correctly;
- IDs and provenance are byte-stable under repeated builds.

### Repair proof tests

- shifting an order ideal preserves every retained headway;
- shifting a non-ideal set reproduces the expected counterexample;
- leader-only boundary separation increases;
- equality-linked events move together;
- waiting slack absorbs upstream propagation;
- closure containing both merge events blocks that direction;
- reverse orientation succeeds when valid;
- latest-to-earliest processing never invalidates a certified later merge;
- duplicate/no-progress detection terminates deterministically.

### Normalization tests

- global translation preserves all movement and headway differences;
- every cabin has a reconstructed state at `t_min`;
- mid-rope position and residual travel are preserved;
- station occupancy and waiting at the boundary are preserved;
- demand, evaluation horizon, and tail translate consistently;
- fixed starts reject an incompatible rebase.

### End-to-end equivalence and safety

- a conflict-free relaxed solution remains unchanged and validates;
- repaired small instances pass the complete original separator;
- fixed-movement passenger reassignment validates independently;
- the relaxed best bound never exceeds the eager optimum on solved small
  instances;
- repaired objective never claims a certificate without a valid relaxed bound;
- eager and delayed-generation regressions remain unchanged.

### Fleet-study tests

- every trial fixes exactly the requested active cabin prefix;
- the returned trial value always belongs to a completely validated repaired
  passenger plan;
- duplicate `K` suggestions hit the cache for an identical experiment key;
- a changed demand, formulation, repair policy, or code fingerprint invalidates
  that cache entry;
- queued anchors execute deterministically and are not duplicated;
- failed repairs remain visible and are not labeled infeasible;
- Stage B returns the smallest observed `K` satisfying the epsilon threshold;
- an exhaustive small range and the Optuna study produce the same observed
  sweet spot once every `K` has been evaluated;
- persistent studies resume without losing artifact references or metrics;
- neighbor warm starts cannot alter the final fixed-K validation contract.

## Experimental Matrix

Run each stage first movement-only and then with the journey-time passenger
model.

### Existing reference cases

- one-station ring, including the known small capacity boundary;
- three-station ring with skip and waiting;
- five-station ring with skip and waiting at K=38;
- five-station OIP76 with the current symmetry settings;
- corresponding fixed-start cases where available.

### Scaling cases

Create deterministic generated rings and lines with 5, 10, and 20 stations,
constant physical parameters, and demand scaled by station count. Test fleet
sizes 38, 76, 152, and, after earlier gates pass, 295. Preserve demand density
and report candidate growth so topology and passenger scaling are not
conflated.

For fleet selection, use the Optuna study over the full admissible integer
range instead of declaring a coarse/fine grid. Publish every actually evaluated
`K`, the deterministic anchors, trial budgets, cache hits, study seed, and
stopping reason. On small cases also execute the exhaustive integer sweep to
quantify any evaluation savings and detect sampler bias.

### Comparisons

For every tractable case compare:

1. `FULL_EAGER`;
2. `DIRECT_MERGE_ABLATION`;
3. `MERGE_FAMILY_RELAXATION`;
4. `MERGE_FAMILY_CORRIDOR_COMPACT`;
5. uniform repaired movement;
6. slack-minimal repaired movement;
7. repaired fixed-movement passenger solution.
8. Optuna-selected best-quality and epsilon-sweet-spot fleets against the
   exhaustive small-case frontier.

Use identical solver parameters, MIP starts, threads, seeds, time budgets, and
hardware. Separate build time from solve time. Preserve raw Gurobi logs and
machine-readable summaries.

The approach is considered promising when the full-family compact relaxation
reliably produces useful OIP76 incumbents substantially earlier than the full
model, the majority of tested incumbents repair within a small fraction of the
MILP time, and the repaired passenger objective has a practically useful gap
to the relaxed bound. Exact numeric thresholds belong in the experiment
protocol after the Phase 0 census, not in the implementation contract.

## Thesis Integration

Add a method section with:

1. the topology-derived distinction between ordered corridors and
   cross-stream reconvergence;
2. the merge-relaxed lower-bound formulation;
3. the order-ideal theorem for uniform backward shifts;
4. the slack-minimal difference-constraint formulation;
5. reconstruction of the endogenous OIP start state at `t_min`;
6. passenger recourse and the lower/upper-bound certificate;
7. explicit heuristic limitations and failure statuses.

The central correctness statement is limited to retained constraints:

> A uniform earlier shift of an event set that is predecessor-closed for
> movement and an order ideal for every retained resource order cannot create
> a new retained movement or headway violation.

Final feasibility still relies on complete separation of every original
headway family and full passenger validation. The method must not be described
as Logic-Based Benders, CBS, or an exact alternative-graph algorithm.

Report negative results as useful evidence. In particular, distinguish:

- merge constraints are not the dominant solver bottleneck;
- the relaxed MILP is easy but its solutions are structurally unrepairable;
- movement repair succeeds but passenger quality degrades;
- the complete method scales and produces a useful certified heuristic gap.

## Expected Implementation Boundaries

Reuse:

- `EanMovementNetwork`, route options, resources, and conflict index;
- current candidate expressions and waiting-aware headway semantics;
- the complete headway separator;
- current movement extraction and validation;
- fixed-movement passenger optimization;
- OIP symmetry and initial-state types;
- existing sparse-matrix Gurobi construction and progress infrastructure.

Add focused components rather than another monolithic optimizer:

```text
EanMergeConflictClassifier
EanMergeConflictFamilyIndex
EanMergeRelaxedArtifactBuilder
EanActiveEventDependencyGraph
EanBackwardMergeRepairer
EanInitialStateRebaser
EanMergeRepairCertificate
EanFixedKMergeRepairEvaluator
EanFixedKOptunaStudyRunner
```

The classifier and repairer must be solver-independent. The continuous
slack-minimal backend may use Gurobi initially, but its input and output remain
plain immutable domain records. No passenger-model type should leak into the
movement repair layer.

## Assumptions

- The first target topologies use deterministic circulation patterns and
  finite unrolled event sequences.
- OIP permits the repaired complete fleet state to become the start state.
- Every omitted pair has topology-derived merge provenance; unknown pairs stay
  constrained.
- Retained corridor order is proven, not inferred from cabin IDs alone.
- Waiting and occupancy expressions are included in both classification and
  repair.
- The normalized `t_min` state is reconstructible for every active cabin.
- Passenger demand is translated with the evaluation clock when preserving the
  original instance.
- Repair failure is a heuristic failure, never an infeasibility certificate.
- Fleet selection compares exact-K repaired passenger results; the relaxed
  optional-fleet solution is not a fleet-sizing recommendation.
- `K_epsilon` is relative to the best repaired solution found unless stronger
  fixed-K optimality certificates are available.
- The eager full formulation remains available as the safety and comparison
  baseline throughout the experiment.

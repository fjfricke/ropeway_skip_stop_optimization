# Zero-Wait Passenger Master with Timing-Feasibility Cuts

Status: **proposed research and implementation plan**

## Decision Summary

Test a deliberately simple two-level matheuristic before implementing full
rotation-occurrence generation:

```text
fixed K + physical network + demand
    -> zero-wait passenger master
    -> selected stop/skip template sequence
    -> complete no-wait check
    -> exact waiting-enabled timing subproblem
    -> infeasibility core cut or realized movement plan
    -> exact fixed-movement passenger evaluation
    -> validated incumbent
```

The master chooses a possibly different structural rotation template after
every rotation and optimizes passenger assignment under nominal minimum-time,
zero-wait operation. It retains the complete non-merge physical core but does
not carry arbitrary waiting variables or the full inter-cabin merge-order
model.

The timing subproblem fixes the selected template sequence and decides only:

- legal waiting;
- continuous event times;
- unresolved merge precedence;
- delay propagation into later rotations;
- horizon and tail feasibility.

If the waiting-enabled subproblem proves infeasibility, it returns a valid
logic-based feasibility cut over the responsible master decisions. If it is
feasible, the realized movement plan is validated and passenger assignment is
re-solved on the actual event times.

The first version is an incumbent-producing search method, not a global
optimality algorithm. It distinguishes valid feasibility cuts from heuristic
enumeration cuts and never maps master-pool exhaustion or subproblem timeout
to mathematical infeasibility.

## Relationship to the Rotation-Flow Hybrid

This plan is the smaller first experiment for
[`rotation_passenger_flow_hybrid.md`](rotation_passenger_flow_hybrid.md).

The larger plan dynamically maintains complete timed rotation occurrences and
an anonymous occurrence-flow master. This plan instead keeps only structural
template choices in the passenger master and delegates all additional waiting
and continuous merge timing to a fixed-template subproblem.

If the zero-wait approximation ranks repaired plans well, its evaluated plans
can seed the timed occurrence pool later. If repair repeatedly reverses the
master ranking, move to the richer occurrence formulation rather than adding
increasingly inaccurate corrections to the zero-wait master.

## Core Hypothesis

The passenger value of a skip-stop plan is determined mainly by:

- which stations each rotation serves;
- how templates alternate across rotations;
- available cabin capacity;
- nominal travel and service durations.

Waiting is primarily local recourse for headway conflicts created when
different stop/skip streams reconverge. If such conflicts are sparse and
required delays are small, the optimized zero-wait objective \(z_0(P)\) for
template plan \(P\) should rank plans similarly to the realized objective
\(z_{\mathrm{real}}(P)\):

\[
z_{\mathrm{real}}(P)
\approx
z_0(P).
\]

This is an empirical hypothesis, not a theorem. It may fail near capacity,
under long delay propagation, or when delayed service materially improves
boarding for released demand.

Measure the repair distortion:

\[
\Delta_{\mathrm{repair}}(P)
=
z_{\mathrm{real}}(P)-z_0(P),
\]

and the rank correlation between zero-wait and realized candidate objectives.

## Scope

The first implementation supports:

- fixed \(K\);
- fixed initial placement;
- current deterministic ring circulation;
- one freely chosen stop/skip template per completed rotation;
- a finite horizon with current tail semantics;
- the current aggregate demand and passenger objective;
- existing station waiting rules;
- complete current movement and headway validation;
- exact fixed-movement passenger re-evaluation.

The first implementation does not include:

- optimized initial placement;
- variable fleet cardinality;
- dynamic turnbacks or rope transfers;
- arbitrary timed occurrence pricing;
- generalized Benders optimality cuts;
- a claim of global skip-stop optimality;
- a mathematical infeasibility result for the unrestricted full problem.

## Zero-Wait Passenger Master

### Template variables

For cabin path \(c\), rotation slot \(r\), and compatible structural template
\(p\), define:

\[
x_{c,r,p}\in\{0,1\}.
\]

Each active rotation chooses exactly one template:

\[
\sum_{p\in P_{c,r}}x_{c,r,p}=a_{c,r}.
\]

The first prototype may use explicit fixed-start cabin paths to reduce
implementation risk. A later anonymous-flow version may replace cabin IDs
once the experiment validates the decomposition.

Cabins are never forced to repeat the same template. Template compatibility
only requires that the end state of rotation \(r\) can start the chosen
template at rotation \(r+1\).

### Nominal timing

Each template \(p\) supplies minimum relative event offsets
\(\bar\tau_{p,e}\) and minimum duration \(\bar T_p\). With master waiting fixed
to zero:

\[
t^0_{c,r,e}
=
s^0_{c,r}+\bar\tau_{p,e}
\qquad\text{when }x_{c,r,p}=1,
\]

\[
s^0_{c,r+1}
=
s^0_{c,r}+\sum_p \bar T_p x_{c,r,p}.
\]

The master contains no arbitrary station-waiting variables.

### Constraints retained in the master

Keep:

- one compatible template per active rotation;
- fixed-\(K\) path continuity;
- initial-state compatibility;
- route-option and stop/skip consistency;
- nominal horizon activation;
- passenger boarding and alighting only at served stations;
- passenger flow conservation;
- cabin capacity;
- demand coverage and unserved-demand semantics;
- topology-proven deterministic order and other inexpensive exact core
  constraints;
- any physical constraint required to make the nominal passenger service
  meaningful.

Omit from the first master:

- additional waiting;
- unresolved cross-stream merge precedence;
- pairwise merge Big-\(M\) disjunctions;
- continuous timing repair.

Unknown or non-merge safety constraints must not be silently omitted merely
because they are expensive. Reuse the conservative conflict provenance from
the delayed-merge plan.

### Passenger objective

Optimize the current passenger objective on nominal event times. Use
lexicographic tie-breaking:

1. primary configured passenger objective;
2. number of nominal merge conflicts;
3. total nominal violation magnitude;
4. deterministic template signature.

The merge metrics are search guidance, not physical feasibility constraints.
They prefer easier-to-repair plans among passenger-equivalent alternatives.

## Two-Stage Feasibility Evaluation

### Stage A: complete no-wait check

Construct the nominal movement plan with every template and event time fixed.
Run the complete current movement and headway validators.

If no violation exists:

```text
FEASIBLE_WITHOUT_WAITING
```

Re-solve the exact fixed-movement passenger assignment and record a validated
incumbent.

If a violation exists, do not cut the template plan. No-wait infeasibility
does not imply infeasibility when waiting is permitted.

### Stage B: exact waiting-enabled timing subproblem

Fix:

- initial placement;
- active rotations;
- selected template per rotation;
- route and stop/skip decisions;
- physical rotation continuity.

Optimize:

- continuous event times;
- waiting at legal holding points;
- unresolved merge order;
- propagated delay across following rotations.

Use a lexicographic timing objective:

1. establish feasibility;
2. minimize total additional waiting;
3. minimize the latest completion time;
4. deterministically break remaining timing ties.

Passenger assignment is not fixed during movement feasibility. After a
feasible timing plan is found, passenger routing is solved again on realized
times. A later passenger-aware repair subproblem is considered only if
movement-minimal waiting systematically produces poor passenger results.

Subproblem statuses:

```text
FEASIBLE_WITH_WAITING
INFEASIBLE_FIXED_TEMPLATE_PLAN
UNKNOWN
INVALID_INTERNAL
```

Only `INFEASIBLE_FIXED_TEMPLATE_PLAN` proven by the complete waiting-enabled
subproblem authorizes a feasibility cut.

## Cut Taxonomy and Validity

Every returned constraint records:

```text
cut_id
cut_kind
master_literal_ids
subproblem_status
proof_source
resource_ids
rotation_slots
core_size
generation_round
```

### 1. Complete-plan feasibility cut

For the selected master literals \(S\):

\[
\sum_{i\in S}x_i\leq |S|-1.
\]

This cut is valid after proven waiting-enabled infeasibility, but weak because
it excludes only the complete evaluated plan.

### 2. Infeasible-core cut

Prefer a subset \(C\subseteq S\) that is itself infeasible:

\[
\sum_{i\in C}x_i\leq |C|-1.
\]

This excludes every future plan containing the same impossible core. Core
minimization may greedily test literal deletion within a separate bounded
budget, but the unreduced proven core remains valid if minimization times out.

### 3. Impossible-transition cut

If adjacent selected templates cannot be connected under any legal waiting:

\[
x_{c,r,p}+x_{c,r+1,q}\leq1,
\]

or set the corresponding transition variable to zero in an anonymous-flow
master.

### 4. Local merge-core cut

If a set \(C_M\) of rotations cannot jointly traverse a resource and its
available timing window:

\[
\sum_{i\in C_M}x_i\leq |C_M|-1.
\]

Resource-local generalization requires a proof that the conflict does not
depend on omitted external decisions.

### 5. Cumulative resource-window cut

When every selected usage is forced into \([l,u]\), a headway \(h_r\) implies
a capacity bound such as:

\[
\sum_i \rho_{i,r,[l,u]}x_i
\leq
\left\lfloor\frac{u-l}{h_r}\right\rfloor+1.
\]

The exact endpoint convention must match checkpoint clearance semantics.
Introduce this cut only after an independently tested derivation; it is not
part of the minimal first implementation.

### 6. Evaluated-pattern search cut

A feasible pattern may be excluded from subsequent heuristic enumeration
after its exact realized value is stored:

\[
\sum_{i\in S}x_i\leq |S|-1.
\]

This has the same algebraic form as a complete-plan feasibility cut but a
different meaning. It must be classified as:

```text
EVALUATED_PATTERN_CUT
```

It is a search-management decision, not a proof that the physical plan is
infeasible. The stored realized incumbent remains eligible as the final
solution.

### Invalid cuts

Never generate a mathematical feasibility cut from:

- no-wait conflict alone;
- subproblem `UNKNOWN`;
- a heuristic repair failure;
- incomplete separator output;
- a fixed passenger assignment that prevented otherwise feasible movement;
- an IIS or UNSAT core containing artificial restrictions not represented in
  the master cut.

## Core Extraction

### Preferred CP-SAT experiment

Associate each fixed master decision with a CP-SAT assumption literal.
Conditional timing and movement constraints are active only under their
corresponding assumptions. When the complete subproblem returns infeasible,
extract its assumption UNSAT core and map it to master literals.

Advantages:

- direct explanation over selected decisions;
- native interval and no-overlap scheduling constructs;
- no need to solve the complete passenger problem in CP-SAT;
- natural bounded core minimization.

The CP-SAT timing model must reproduce current continuous semantics closely
enough for a valid cut. A discretized or rounded infeasibility proof is not
valid for the continuous master unless the discretization is conservative and
the implication is proven.

### Gurobi alternative

Build the fixed-template timing subproblem with activation indicators for
master decisions. On proven infeasibility, compute an IIS and translate the
participating activation constraints back to master literals.

Validate every derived cut by re-solving the isolated core and by checking
that removing at least one core literal restores the possibility of
feasibility where claimed by a minimal core.

## Feedback from Feasible Repairs

For template plan \(P\), let:

\[
Q(P)
=
\operatorname{PassengerOpt}
\left(
\operatorname{TimingRepair}(P)
\right).
\]

Store:

- nominal objective \(z_0(P)\);
- realized passenger objective \(Q(P)\);
- total and maximum waiting;
- changed boarding and transfer opportunities;
- conflict count and repair rounds;
- complete validation certificate.

### Minimal implementation

Keep the best validated \(Q(P)\) as the incumbent, add an
`EVALUATED_PATTERN_CUT`, and ask the master for the next distinct or diverse
plan.

Use a solution pool or explicit diversity constraints so that evaluation is
not limited to tiny permutations of one stop/skip signature.

### Pointwise recourse correction

A later master may contain a recourse-objective variable \(\eta\). For a plan
\(\bar x\) whose timing and passenger subproblems were solved exactly:

\[
\eta
\geq
Q(\bar x)-M\,d(x,\bar x),
\]

where \(d(x,\bar x)\) is binary Hamming distance.

This cut is strong only at \(\bar x\). It is valid only with a safe \(M\) and
an exact value \(Q(\bar x)\). Generalized optimality cuts require separate
research and are not necessary for the first heuristic.

### Realized occurrence feedback

Export every repaired rotation with concrete event times and waiting as an
`EanRotationOccurrence`. These occurrences seed the richer rotation-flow
hybrid and may also provide a MIP start to the current EAN R&C model.

## Bounds and Claims

### Zero-wait objective is not generally a lower bound

Setting waiting to zero restricts timing, while omitting merge conflicts
relaxes safety. The effects have opposite directions. Moreover, waiting may
allow released passengers to catch a later service or preserve a connection.
Therefore:

\[
z_0(P)
\]

is a surrogate score unless additional assumptions prove monotonicity. Export
it as `zero_wait_surrogate_objective`, never as a certified bound.

### Valid incumbent upper bound

Every completely validated repaired solution provides:

\[
z^*_{\mathrm{skip}}\leq UB_{\mathrm{skip}}
\]

for minimization.

### Recommended lower bounds

Compute independently:

1. an ideal passenger shortest-path bound that ignores conflicts, indivisible
   cabins, and competition for capacity;
2. a stronger fractional cabin/passenger-flow relaxation with conservative
   aggregate resource capacity;
3. the current EAN root lower bound when available within a separate budget.

Use:

\[
LB_{\mathrm{skip}}
=
\max
\left\{
LB_{\mathrm{ideal}},
LB_{\mathrm{fractional-flow}},
LB_{\mathrm{EAN-root}}
\right\}.
\]

Every component included in the maximum must have a separately documented
mapping from every full feasible solution into the relaxed model.

### Sufficient proof that Skip-Stop helps

The main application claim does not require solving the skip-stop problem to
optimality. If the all-stop benchmark is solved optimally and:

\[
UB_{\mathrm{skip}}
<
z^*_{\mathrm{all-stop}},
\]

then:

\[
z^*_{\mathrm{skip}}
<
z^*_{\mathrm{all-stop}}.
\]

Thus one validated skip-stop plan better than the optimal all-stop plan
already proves that skip-stop can improve the chosen passenger objective.

When a valid skip-stop lower bound is available, also report:

\[
\operatorname{gap}
=
\frac{UB_{\mathrm{skip}}-LB_{\mathrm{skip}}}
{\max(1,\lvert UB_{\mathrm{skip}}\rvert)}.
\]

Do not use the zero-wait surrogate in this gap.

## Search Algorithm

```text
best_validated = none
evaluated_patterns = {}
feasibility_cuts = {}

while total budget remains:
    solve zero-wait passenger master

    if master has no solution:
        return best_validated with POOL_SEARCH_EXHAUSTED

    P = selected template plan

    run complete fixed-time no-wait validation

    if P is feasible without waiting:
        Q = exact fixed-movement passenger optimum
        update best_validated
        store P -> Q
        add evaluated-pattern search cut
        continue

    solve complete waiting-enabled timing subproblem

    if subproblem is INFEASIBLE_FIXED_TEMPLATE_PLAN:
        extract and verify assumption core C
        add feasibility-core cut for C
        continue

    if subproblem is UNKNOWN:
        store unresolved P
        add no mathematical feasibility cut
        use a temporary search exclusion only if explicitly configured
        continue

    if subproblem is FEASIBLE_WITH_WAITING:
        validate realized movement completely
        solve exact fixed-movement passenger assignment
        update best_validated
        store nominal and realized metrics
        export realized rotation occurrences
        add evaluated-pattern search cut
        continue
```

After the outer search, optionally run current fixed-\(K\) EAN R&C refinement
from `best_validated`.

## Public API and Metrics

Add a separate optimizer selection:

```text
ZERO_WAIT_PASSENGER_TIMING_CUTS
```

Configuration:

```text
fixed_k
initial_placement
total_time_limit_seconds
master_time_limit_seconds
timing_subproblem_time_limit_seconds
core_minimization_time_limit_seconds
maximum_evaluated_patterns
solution_pool_size
diversity_policy
allow_waiting_repair
subproblem_solver
ean_refinement_time_limit_seconds
random_seed
```

Per outer iteration report:

- master round and status;
- zero-wait surrogate objective;
- selected template signature;
- nominal merge-conflict count and magnitude;
- no-wait validation status;
- timing-subproblem status and duration;
- total and maximum repaired waiting;
- core and generated-cut size;
- realized passenger objective;
- best validated incumbent;
- independent lower bounds and certified source;
- remaining total budget.

## Implementation Phases

### Phase 0: Baseline and experiment contract

- fix Three- and Five-Station Skip+Wait examples, \(K\), starts, demand,
  horizon, objective, seeds, and wall-clock budgets;
- record current EAN R&C build, first incumbent, objective, bound, and
  validation;
- define machine-readable surrogate, repair, cut, and certificate metrics.

### Phase 1: Structural zero-wait master

- derive compatible one-rotation templates from `EanMovementNetwork`;
- permit a different template after every rotation;
- build nominal zero-wait event and passenger service data;
- solve integrated template selection and passenger assignment;
- export several distinct candidate plans.

### Phase 2: No-wait validation and exact passenger evaluation

- construct nominal movement plans;
- run complete movement and headway validation;
- verify passenger objective agreement with the existing fixed-movement model
  on no-wait feasible cases.

### Phase 3: Waiting-enabled timing subproblem

- fix template decisions and implement legal continuous waiting;
- include all required headway and horizon semantics;
- jointly propagate delay across subsequent rotations;
- return the explicit four-state subproblem status;
- validate every feasible realization independently.

### Phase 4: Feasibility cores and cuts

- implement full-plan no-good feasibility cuts first;
- add CP-SAT assumption cores or Gurobi IIS mapping;
- separate mathematical feasibility cuts from evaluated-pattern search cuts;
- verify every core on isolated small cases;
- optionally minimize cores within a bounded budget.

### Phase 5: Outer search and EAN handoff

- iterate master, subproblem, passenger re-evaluation, and cuts;
- retain all validated incumbents;
- export repaired occurrences;
- warm-start current EAN R&C with the best plan.

### Phase 6: Bounds

- implement and prove the ideal passenger bound;
- add the fractional cabin/passenger-flow bound only with a formal relaxation
  mapping;
- collect the current EAN root bound;
- report the maximum certified lower bound separately from every surrogate.

Optimized initial placement and the richer anonymous occurrence-flow master
are later phases in the linked rotation hybrid plan.

## Tests

### Unit tests

- free template changes between consecutive rotations;
- nominal zero-wait time propagation;
- no-wait conflict does not generate a feasibility cut;
- waiting-enabled infeasibility does generate a cut;
- `UNKNOWN` never generates a mathematical cut;
- complete no-good algebra;
- assumption-core to master-literal mapping;
- impossible-transition cut;
- distinction between feasibility and evaluated-pattern cuts;
- downstream delay propagation;
- passenger re-evaluation after waiting;
- zero-wait surrogate never exported as a bound.

### Exact small cases

Enumerate all template combinations on tiny instances and verify:

- every subproblem-infeasible combination is removed by at least one valid cut;
- no feasible combination is removed by a feasibility cut;
- repeated master solves terminate after finite enumeration;
- best enumerated realized objective matches direct eager EAN optimization;
- all reported movement plans pass complete validation.

### Experimental tests

For predefined Three- and Five-Station fixed-start cases record:

- zero-wait versus realized objective scatter;
- rank correlation;
- repair distortion distribution;
- fraction feasible without waiting;
- fraction feasible only with waiting;
- fraction proven infeasible;
- fraction unresolved;
- core sizes and plans eliminated per cut;
- time to first and best validated incumbent;
- comparison against EAN R&C at equal total time.

## Acceptance and Stop Conditions

Continue toward the richer rotation-flow hybrid when:

- candidate plans are generated materially faster than integrated EAN
  incumbents;
- a useful fraction can be repaired and validated;
- zero-wait ranking remains informative after repair;
- core cuts remove more than isolated full plans;
- the method finds a validated Skip-Stop improvement over the optimal
  All-Stop benchmark on at least one target case.

Stop or redesign when:

- almost every promising zero-wait plan requires large propagated waiting;
- realized ranking is effectively unrelated to nominal ranking;
- timing subproblems are as difficult as the full EAN;
- most subproblems end `UNKNOWN`;
- only complete-plan no-goods are obtainable and enumeration stagnates;
- passenger re-evaluation dominates total runtime without improving plans.

## Thesis Integration

Describe the implemented first version as:

> a zero-wait passenger-service master with logic-based timing-feasibility
> cuts and exact fixed-movement passenger recourse

It may be called a Logic-Based-Benders-style matheuristic because a master
selects discrete service decisions and a complete timing subproblem returns
logical feasibility cuts. Do not call it an exact Logic-Based Benders
algorithm unless:

- the master is a valid relaxation;
- the subproblem is solved completely;
- all returned cuts are globally valid;
- recourse optimality is represented sufficiently to prove convergence.

The empirical analysis must separate:

- nominal passenger quality;
- repair cost;
- physical feasibility;
- final realized passenger quality;
- comparison with optimal All-Stop;
- any certified global Skip-Stop bound.

## Assumptions

- Fixed-\(K\), fixed-start operation is the first target.
- Cabins may change structural templates after every rotation.
- Waiting is absent only in the passenger master, not in the physical
  feasibility definition.
- Only the complete waiting-enabled subproblem may prove a selected template
  plan infeasible.
- Passenger assignment is always re-solved after event times change.
- Every accepted incumbent passes the existing independent validators.
- The current EAN R&C remains the exact reference and refinement model.

# Stronger Passenger Bounds and CP-SAT Support Feedback for DDD

## Purpose

The implemented fixed-support loop currently sends the anonymous DDD master's
exact aggregate route-count vector to CP-SAT. If the vector is infeasible,
CP-SAT returns a sufficient assumption core over equalities

$$
X_{ko}=n,
$$

and the master receives an exact-count no-good. This mechanism is valid,
compact, and already produces one-literal cores in the first Three-Station
passenger-master experiment. A one-literal equality core nevertheless removes
only one value:

$$
X_{ko}\neq n.
$$

The first Five-Station passenger experiment shows that stronger cuts alone are
not enough. Two independent weaknesses have to be addressed in order:

1. the partial passenger network prices late visit layers much too early;
2. exact-count no-goods remove only isolated aggregate supports.

The next layer therefore combines a stronger but still optimistic passenger
time bound with CP-certified support regions. Point exclusions should be
replaced, where possible, by certified regions such as

$$
X_{ko}\le n-1
$$

or by small resource-cover inequalities. The goal is to reduce the number of
master--CP rounds before the first physically liftable passenger-guided
support, without weakening the global bound contract

$$
LB\le z^\star\le UB.
$$

It also introduces a nearest-feasible-support oracle. Exact passenger recourse
and the current fixed-$K$, fixed-start scope remain unchanged. Every addition
must preserve

$$
LB\le z^\star\le UB.
$$

The measurements motivating this order are recorded in
[`../findings/ddd_five_station_passenger_support.md`](../findings/ddd_five_station_passenger_support.md).

## Revised Implementation Order

The work is ordered by the diagnosed source of error, not by cut
sophistication:

1. **Layer-state earliest-time bounds (implemented).** Strengthen the
   passenger objective before asking CP-SAT to separate its supports.
2. **Independent primal bootstrap.** Run the existing free full-route CP-SAT
   oracle early and evaluate every result with exact passenger recourse.
3. **Nearest-feasible-support oracle.** Search around the master support and
   return a feasible neighbor plus a certified distance cut.
4. **Timed-flow threshold covers (implemented first slice).** Preserve the
   selected DDD time regions in CP and return sparse lower-threshold cores.
   Keep aggregate equality cores as the fallback.
5. **Resource-window covers.** Add physical packing rows after their
   waiting-sensitive validity is established.
6. **Passenger event refinement.** Refine objective timing only for physically
   feasible supports with a remaining master-versus-recourse mismatch.

The adaptive-master policy is orthogonal. It becomes important only when
master optimization, rather than CP support processing, dominates measured
runtime.

## Decision checkpoint after fixed-schedule diagnosis

The implemented fixed-schedule diagnostic isolates every recovered event tick,
fixes every anonymous movement-arc multiplicity, and reoptimizes only passenger
flow. On both the free bootstrap and a substantially better 10-round nearest-
support timetable, its value equaled the optimal integer passenger recourse up
to numerical tolerance. The unrestricted global lower bound nevertheless
remained 213,075 passenger-seconds below the best timetable.

Therefore revised-order item 6 (passenger-event refinement) and trajectory-preserving
passenger coupling are not the next bottleneck for the tested fixed-start
$K=19$ no-wait case. The next implementation tranche is Phase 5 resource-
window covers, with timed-flow cores retained as diagnostic provenance and
nearest-support CP retained as the primal channel. This decision must be
revisited for waiting-enabled instances using the same diagnostic; the no-wait
result is evidence, not a proof for the larger waiting feasible set.

## Implemented Foundation: Layer-State Earliest-Time Bounds

For visit layer $k$ and movement state $s$, compute a lower bound $E_{ks}$ on
the earliest physically reachable event time. Initialize every layered state
reachable through a fixed-start source arc with the minimum exact start time
of any such source; all other values begin at $+\infty$. For every route option
$o:s\rightarrow s'$ with minimum elapsed time $\tau_o^{\min}$, propagate

$$
E_{k+1,s'}=
\min_{o:s\rightarrow s'}
\left(E_{ks}+\tau_o^{\min}\right).
$$

The recurrence is evaluated on the layered acyclic movement network, so it is
a shortest-path dynamic program rather than a new MILP. Waiting is omitted in
the recurrence because waiting is nonnegative; this remains a valid earliest
time bound when waiting is later enabled.

For a partial movement arc $a$ leaving $(k,s)$ from time cell $I_a$, use

$$
\underline t_a=\max\{\inf I_a,E_{ks}\}
$$

before applying the route option's boarding or alighting offset. Passenger
service costs continue to use the existing optimistic objective definition,
but they must never use an event time below this bound.

Correctness requirements:

- every complete physical trajectory represented by a partial arc reaches its
  source event no earlier than $\underline t_a$;
- optional waiting can only increase the exact event time;
- unreachable layer-state pairs create no passenger-service arc;
- all time conversion uses the canonical exact integer tick scale;
- exhaustive tiny cases verify that the strengthened master objective never
  exceeds the exact optimum.

Expected effect: the master can no longer serve demand at a late rotation for
approximately zero elapsed time. This should improve the lower bound and make
passenger-optimal supports less interchangeable without adding order
binaries or resource conflicts.

The implemented Five-Station $K=19$ ablation increased the 50-round lower
bound from approximately 2,676 to 409,360 passenger-seconds and reduced the
initial network from 365/1,288 nodes/arcs to 348/1,232. It did not find a
physical master support in 50 rounds. The remaining next tranche therefore
starts with the independent primal bootstrap and nearest-feasible support
feedback below.

## Phase 2: Independent Primal Bootstrap

**Implemented.** The fixed-support passenger coordinator now runs the free
physical CP-SAT model once before the first master solve, validates/evaluates
feasible timetables for an early upper bound, and terminates only on a proved
unconditioned `INFEASIBLE` status. Bootstrap status, time, candidate count, and
objective are recorded separately from per-support CP calls.

The full-route CP-SAT primal oracle is already implemented. Integrate it into
the passenger coordinator as a separate primal channel:

1. run it before or alongside the first support-centered CP call under a
   bounded budget;
2. validate every movement result independently;
3. solve exact fixed-movement passenger assignment;
4. update $UB$ and retain the route/timing solution as a CP hint;
5. never use its objective or route support to update $LB$.

This phase does not require the master to choose the same support. Its purpose
is an early valid timetable, not a feasibility cut. Configuration must keep
the mode optional and report time to first validated upper bound separately.

## Phase 3: Nearest-Feasible-Support Oracle

**Implemented for the exact no-wait CP scope.** After a proved fixed-support
infeasibility, the coordinator retains the equality-core cut and optionally
solves the unrestricted physical model with the aggregate L1 objective below.
Validated primal timetables update the passenger upper bound; a positive
certified CP objective bound creates the exact threshold-linearized distance
cut. Both calls and both cut families remain independently switchable.

Let $\bar X$ be the aggregate route-count vector of the current master
incumbent. Instead of fixing every count to $\bar X_{ko}$, let CP-SAT choose a
complete physical timetable and minimize

$$
D(X,\bar X)=\sum_{k,o}w_{ko}|X_{ko}-\bar X_{ko}|,
$$

initially with $w_{ko}=1$. Route counts remain derived from exact CP route
decisions. The CP model contains the complete physical movement constraints
for the supported no-wait scope.

The call has two useful outputs:

- a feasible timetable at distance $d^P$, which is independently validated
  and sent to exact passenger recourse for a possible $UB$;
- a certified integer objective lower bound $d^D$, which proves that every
  physically feasible support satisfies

$$
D(X,\bar X)\ge \lceil d^D\rceil.
$$

When $\lceil d^D-\varepsilon\rceil>0$, add that distance-ball exclusion to the
master, using a documented numerical tolerance $\varepsilon$ when reading the
integral CP objective bound. An optimal CP result has $d^P=d^D$. A time-limited
feasible CP result may still provide a primal timetable and a weaker certified
distance cut from its solver bound. `UNKNOWN` without a trustworthy positive
bound adds no cut.

For integer master counts, encode absolute distance exactly with the existing
threshold variables

$$
\beta_{koq}=[X_{ko}\ge q].
$$

For fixed $n=\bar X_{ko}$,

$$
|X_{ko}-n|
=n-\sum_{q=1}^{n}\beta_{koq}
+\sum_{q=n+1}^{K}\beta_{koq}.
$$

This identity must be used instead of free absolute-value auxiliaries, which
could be inflated and would not define the intended excluded ball. Threshold
variables are materialized lazily for coordinates referenced by an accepted
distance cut and reused by all later cuts.

The exact equality-core call remains available as a bounded fallback when the
distance search yields neither a feasible timetable nor a positive certified
bound. Compare `equality_only` and `nearest_feasible` explicitly; do not assume
that the larger CP optimization pays for itself.

## Phase 4a: Timed-Flow Threshold Covers

**Implemented as an opt-in exact no-wait mode.** The master option
`use_cp_sat_timed_flow_covers` and CLI flag `--cp-sat-timed-flow-covers`
replace the exact aggregate-support assumptions of the primary CP call by
lower-bound assumptions over every selected positive non-sink timed flow.

For a stable region $R=(k,o,I^-,I^+,c^0)$ let

$$
Y_R=\sum_{a\subseteq R}y_a.
$$

The CP model reifies exact cabin membership $z_{cR}$ from the route choice and
the source and target event intervals, then assumes

$$
Z_R=\sum_c z_{cR}\ge \bar Y_R.
$$

All positive selected regions are included, so layered source supply and flow
conservation saturate these lower bounds and reproduce the selected anonymous
timed flow. A sufficient CP core $C$ gives the cover

$$
\sum_{(R,q)\in C}[Y_R\ge q]\le |C|-1.
$$

Only one threshold binary per distinct core literal is materialized. Regions
are stored by visit, route, optional source cabin, and half-open source/target
intervals rather than by the originating arc id. After a DDD split, $Y_R$ is
the sum of all contained child arcs, so every accepted cut remains valid.
The cut records resource ids as diagnostic provenance.

The current mode is explicitly `NO_WAIT`; its cuts must not enter a future
waiting-enabled master. Resource-local re-solves are now implemented as the
Phase 4d diagnostic below. General core shrinking and threshold lifting remain
deferred until their incremental value is measured against that evidence.

## Implemented Baseline

The following are prerequisites and are not work items in this plan:

- fixed-start structural capacity rows
  $\sum_{o:\operatorname{from}(o)=s}X_{ko}\le N_{ks}$;
- exact aggregate route-count assumptions in CP-SAT;
- sufficient CP-SAT infeasibility-core extraction;
- lazy exact equality indicators based on threshold binaries;
- exact-count core cuts;
- immediate master re-solve after a support core, without time-cell splitting;
- optimistic passenger-master lower bounds and independently validated EAN
  passenger upper bounds.

The existing equality cut remains the mandatory fallback. Every strengthening
attempt is optional and must leave this path unchanged when it times out or
returns `UNKNOWN`.

## Why Equality Infeasibility Is Not Monotone

From

$$
X_{ko}=n\quad\text{is infeasible}
$$

it is generally invalid to infer

$$
X_{ko}\ge n\quad\text{is infeasible}.
$$

Additional Stop or Skip movements can change which other routes are selected,
which resources are occupied, and which cabins remain active. A directional
cut therefore requires a separate CP proof under the directional predicate;
it must never be created from intuition about monotonic capacity.

## Canonical Master Predicates

Extend the aggregate support vocabulary from equality literals to three exact
predicate types:

$$
E_{ko}^{n}=[X_{ko}=n],
$$

$$
G_{ko}^{n}=[X_{ko}\ge n],
$$

$$
L_{ko}^{n}=[X_{ko}\le n].
$$

The existing threshold variable

$$
\beta_{koq}=[X_{ko}\ge q]
$$

represents these predicates without a new encoding:

$$
G_{ko}^{n}=\beta_{ko,n},
$$

$$
L_{ko}^{n}=1-\beta_{ko,n+1},
$$

and

$$
E_{ko}^{n}=
\begin{cases}
1-\beta_{ko,1}, & n=0,\\
\beta_{ko,n}-\beta_{ko,n+1}, & 0<n<K,\\
\beta_{ko,K}, & n=K.
\end{cases}
$$

For any CP-certified infeasible core $C$ over these predicates, add

$$
\sum_{p\in C}[p\text{ is satisfied}]\le |C|-1.
$$

Special cases are immediately interpretable:

- core $\{G_{ko}^{n}\}$ gives $X_{ko}\le n-1$;
- core $\{L_{ko}^{n}\}$ gives $X_{ko}\ge n+1$;
- core $\{E_{ko}^{n}\}$ gives the current $X_{ko}\neq n$;
- mixed cores exclude a certified combination of count regions.

## Cross-Cutting Evidence and Cut Accounting

Before changing the separator, record for every fixed-support CP call:

- equality-core size before and after optional shrinking;
- literal visit, route, state, decision, count, and predicate kind;
- CP conflicts, branches, wall time, and proof status;
- current structural upper bound $N_{ks}$;
- master count before and after the cut;
- lower-bound improvement attributable to the cut;
- whether the next support changes only the excluded count;
- rounds and wall time to first physical incumbent;
- duplicate and dominated-cut counts.

Store cuts with deterministic IDs and proof provenance. Distinguish at least:

```text
EXACT_COUNT_CORE
THRESHOLD_CORE
RESOURCE_COVER
STRUCTURAL_CAPACITY
```

The first benchmark matrix uses:

- the small exact unit probes;
- Three-Station fixed-start $K=15$ with Journey Time;
- Five-Station Circle fixed-start $K=19$ with Skip and no waiting;
- low and near-capacity fixed-$K$ movement-only cases.

The current equality-only loop is the reference for objective bounds, first-UB
time, total rounds, and total CP/master time.

## Phase 4a: Bounded Core Shrinking

CP-SAT returns a sufficient core, not necessarily an irreducible or minimum
core. Add an optional deterministic deletion filter:

1. order core literals by stable predicate ID;
2. tentatively remove one literal;
3. re-solve the CP model under the remaining assumptions with a small shared
   shrinking budget;
4. permanently remove the literal only after CP proves `INFEASIBLE`;
5. retain the last proven core on timeout or `UNKNOWN`.

The procedure cannot invalidate a cut: it only accepts a smaller core after a
new exact infeasibility proof. It should run only when the original core has
more than one literal. One-literal cores are already irreducible.

Configuration:

```text
core_shrinking = off | deletion_filter
core_shrinking_total_seconds
core_shrinking_max_cp_calls
```

Do not call the result a minimum core. Report `irreducible_under_attempted_order`
only if every deletion was tested and proved feasible or unknown-free.

Expected effect: large multi-literal no-goods become more reusable. No benefit
is expected for the currently observed one-literal Three-Station cores.

## Phase 4b: Directional Threshold Probes

When an equality core contains $E_{ko}^{n}$, launch bounded strengthening
probes around that literal.

### Upper-tail probe

Replace the exact equality assumption by

$$
G_{ko}^{n}: X_{ko}\ge n.
$$

Other core predicates may remain active, but unrelated full-support equalities
must be released. CP-SAT is then allowed to choose all unconditioned route
counts freely.

If CP proves infeasibility, extract the threshold assumption core and add its
mixed predicate cut. A standalone one-literal core yields
$X_{ko}\le n-1$.

### Lower-tail probe

Analogously test

$$
L_{ko}^{n}: X_{ko}\le n.
$$

and derive $X_{ko}\ge n+1$ only from a one-literal proof or the corresponding
mixed core.

### Search order

Prioritize probes with the greatest potential eliminated domain:

1. one-literal equality cores;
2. counts near a known structural capacity;
3. literals repeatedly selected in consecutive master solutions;
4. merge and platform-resource routes;
5. larger mixed cores only after shrinking.

Use a shared per-round strengthening budget. If both probes are unknown, add
the original equality cut immediately. Stronger-cut search must not delay
progress indefinitely.

Suggested initial configuration:

```text
threshold_strengthening = off | single_literal | all_core_literals
threshold_probe_total_seconds = 0.25
threshold_probe_max_calls = 2
```

## Phase 4c: Threshold Search Beyond the Current Count

After proving an upper-tail predicate infeasible, optionally locate the
tightest certified threshold by monotone search over the predicate parameter.
For example, if CP proves

$$
X_{ko}\ge 12\quad\text{infeasible},
$$

test smaller thresholds such as 8, 10, and 11. Predicate feasibility is
monotone in the threshold because the feasible set of the condition
$X_{ko}\ge n$ shrinks as $n$ increases. This monotonicity concerns the
explicit CP predicate, not the original equality model.

The strongest proven result is

$$
X_{ko}\le n_{\min}-1,
$$

where $n_{\min}$ is the smallest threshold for which the otherwise free CP
model is proved infeasible. Use binary search only while every intermediate
CP call returns `FEASIBLE` or `INFEASIBLE`; stop conservatively at `UNKNOWN`.

This phase is activated only if Phase 2 regularly returns one-literal
threshold cores and the extra CP time is recovered through fewer master
rounds.

## Phase 4d: Resource-local CP explainability

**Implemented as an opt-in diagnostic.** The CLI option
`--cp-sat-local-explainability` requires timed-flow covers and re-solves every
rejected timed core under progressively relaxed resource sets. All route,
integer timing, horizon, and core-threshold assumptions remain active, while
no-overlap constraints outside the tested set are removed. The result records
the complete originating support, the original and local CP cores, induced
resource-time envelopes, station/resource provenance, solve status, and time.

Let $P_0$ denote every exact CP constraint except resource no-overlap and let
$H_r$ denote no-overlap on resource $r$. For a set $S$ of resources, the local
probe uses

$$
\mathcal F_S(C)=\{x:P_0(x),\ H_r(x)\ \forall r\in S,\ C(x)\}.
$$

Because the complete feasible set is contained in every such relaxation,

$$
\mathcal F_R(C)\subseteq\mathcal F_S(C),
$$

local `INFEASIBLE` is a valid proof for the complete problem. Local `FEASIBLE`
only rejects that explanation, and `UNKNOWN` proves nothing. The diagnostic
classifies a core by the smallest proved tested scope: one resource, a
resource group, global, or unresolved.

This does not automatically turn a local contradiction into an anonymous
packing inequality. A single-resource re-solve still retains global route and
cabins-through-time consistency. The report consequently distinguishes local
cores in which every required timed literal actually uses the explaining
resource from cores that also need literals on other visits. Only the former
are immediate candidates for a resource-window/Hall derivation; the latter
need a trajectory-linking or sequence-aware cut.

The controlled Five-Station $K=19$ no-wait run with a two-second local budget
classified 18 of 20 rejected supports by one resource and two by a resource
group, with no global or unresolved case. Only nine of the 20 observations had
a local core entirely touching the explaining resource set. Nine raw timed
covers also excluded at least one other observed support, with a maximum of
five. The lower-bound plateau remained unchanged. These measurements justify
a narrow resource-window experiment, but reject the stronger claim that all
remaining infeasibility is merely anonymous local packing.

The next cut tranche is therefore:

1. derive interval-demand inequalities only for resource-touching local cores;
2. independently prove their half-open endpoint and waiting-domain validity;
3. retain the original timed cover as the exact fallback for mixed cores;
4. compare lower-bound lift per second against the current 20-round timed
   baseline before generalizing to sequence or trajectory-linking cuts.

## Phase 5: Resource-Window Cover Cuts

Threshold cuts still describe route counts indirectly. Resource-local proofs
can cut several route options together.

For a physical resource $r$, let $U$ be route occurrences whose complete
feasible entry intervals lie within a common window $[l,u]$. If headway and
clearance semantics imply at most $C_{r,[l,u]}$ compatible usages, add

$$
\sum_{(k,o)\in U}\rho_{ko,r,[l,u]}X_{ko}
\le C_{r,[l,u]}.
$$

The first implementation should use only unit coefficients and windows for
which every counted occurrence is unconditionally active. Compute capacity
with the same half-open endpoint and clearance conventions as the canonical
resource validator.

Required proof obligations:

- every counted route usage necessarily occupies $r$ in the stated window;
- the capacity formula matches point, platform-occupancy, and horizon
  semantics;
- omitted waiting cannot move an occurrence outside the window;
- the row remains valid under anonymous cabin reassignment;
- no optional Stop/Skip usage is counted without its activation predicate.

Do not infer a cover row merely from one CP core. Either derive it from proven
time envelopes and resource capacity or validate a candidate inequality with
an otherwise free CP model before adding it.

Waiting-enabled models require new waiting-aware occurrence envelopes. A
no-wait cover cut is not valid after waiting is enabled unless the same row is
reproved for the waiting model.

## Phase 6: Dominance and Cut-Pool Management

Maintain a canonical predicate-cut pool and reject:

- exact duplicate cuts;
- equality cuts dominated by a standalone directional threshold;
- weaker thresholds, for example $X\le 12$ when $X\le 11$ is active;
- mixed cores that are supersets of an already active predicate core;
- resource covers dominated by a row with a smaller right-hand side over a
  superset of nonnegative terms.

Keep proof provenance even when a cut is retired from the active master.
Threshold binaries remain lazy: materialize only thresholds referenced by an
active cut. Reuse one binary for identical $(k,o,q)$ across all cuts.

## Coordinator Order

For each master incumbent after the initial primal bootstrap:

1. solve the strengthened anonymous passenger master and update $LB$ only from
   its valid best bound;
2. run the current exact-support CP check with a short bounded budget;
3. if it is feasible, validate it and run exact passenger recourse for $UB$;
4. if it is infeasible, retain its proven core cut immediately;
5. before re-solving, optionally spend the remaining round budget on the
   nearest-feasible-support oracle centered at the same master support;
6. validate and passenger-evaluate its feasible timetable for $UB$, and add a
   positive certified distance cut when available;
7. optionally shrink the original core and probe selected directional
   thresholds;
8. keep every independently valid, nondominated cut; the original core remains
   the guaranteed fallback when stronger proofs time out;
9. add no cut after an unproved `UNKNOWN` result;
10. re-solve the unchanged DDD discretization immediately;
11. refine time cells only for a physical support whose exact timing or
    passenger cost still exposes a discretization error.

Time-cell refinement remains separate. It is used only for a support not
already excluded by CP-SAT.

## Correctness Contract

Every mathematical cut must satisfy all of the following:

- its CP source status is `INFEASIBLE`, never `UNKNOWN`;
- assumptions map exactly to master predicates;
- no artificial hint, objective cutoff, fixed passenger assignment, or
  search-only restriction participates in the proof;
- integer time scaling is exact for the modeled physical time grid;
- the cut records whether it is valid for no-wait or waiting-enabled movement;
- fixed-support infeasibility is never reported as global infeasibility;
- the master best bound remains a valid global passenger lower bound;
- upper bounds still come only from completely validated movement and exact
  passenger recourse.

Heuristic pattern exclusion may exist separately but must never enter the
proof cut pool or the reported lower bound.

## Tests

### Unit tests

- exact evaluation of equality, greater-or-equal, and less-or-equal master
  predicates for every count in $[0,K]$;
- lazy threshold reuse and deterministic IDs;
- one-literal $G^n$ core produces $X\le n-1$;
- one-literal $L^n$ core produces $X\ge n+1$;
- mixed predicate core excludes exactly the certified region;
- duplicate and dominance removal;
- shrinking never accepts a deletion after `UNKNOWN`;
- no cut from a feasible or unknown CP result.

### Exact small-model tests

Enumerate all aggregate count vectors for tiny movement models and verify that
every generated cut preserves every physically feasible vector. Compare the
remaining master vectors against exhaustive CP feasibility.

### Waiting tests

- no-wait threshold and cover cuts carry no-wait provenance;
- they are rejected by a waiting-enabled coordinator;
- waiting-enabled cuts are accepted only after proofs from the waiting model;
- increasing maximum waiting never reuses a cut proved only for a smaller
  waiting domain unless implication is explicit.

### Regression tests

- equality-only mode reproduces the implemented baseline;
- lower bounds never exceed exhaustive optima on tiny cases;
- every accepted upper bound passes the complete movement and passenger
  validators;
- all existing eager EAN and DDD tests remain unchanged and green.

## Experimental Acceptance

Compare `equality_only`, `earliest_time`, `nearest_feasible`, `threshold`, and
`threshold_plus_cover` with identical total solver budgets. Report:

- time and rounds to first physical incumbent;
- best lower and upper bounds over time;
- final absolute and relative gap;
- CP calls and strengthening overhead;
- average and maximum core size;
- count-domain values eliminated per cut;
- master variables, rows, nonzeros, and solve time;
- percentage of cuts that are equality, directional, mixed, or resource
  covers;
- proof status distribution and `UNKNOWN` rate.
- distance-oracle primal distance, dual distance, and resulting ball radius;
- lower-bound gain caused by earliest-time pricing;
- time to the first independently generated primal upper bound.

Adopt threshold strengthening as the default only if it materially reduces
median time to first upper bound or certified gap without increasing total
runtime on the small reference suite. Resource-cover cuts remain opt-in until
their endpoint semantics and waiting extension are independently validated.

## Expected Outcome

The realistic near-term gain is not one universally powerful Benders cut. It
is a hierarchy:

1. layer-state bounds prevent physically late service from being priced at
   time zero;
2. the independent primal oracle supplies a validated timetable early;
3. nearest-feasible search excludes an entire certified support neighborhood
   and can improve the timetable in the same CP call;
4. equality cores retain finite exact fallback progress;
5. threshold proofs and resource covers remove reusable physical regions.

This hierarchy preserves the current anytime certificate while targeting the
main remaining risk: equality-only support checking degenerating into a long
enumeration of adjacent aggregate counts before CP-SAT finds the first
physically liftable, passenger-relevant timetable.

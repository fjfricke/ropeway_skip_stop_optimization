# Adaptive Anytime Master for DDD Passenger Optimization

## Purpose

The implemented DDD passenger loop currently solves every anonymous master to
Gurobi status `OPTIMAL` before checking its aggregate Stop/Skip support with
CP-SAT. This is correct but increasingly inefficient: CP-SAT may reject a
support in approximately $0.01$ seconds while Gurobi spends minutes proving
that the same optimistic master support is optimal among the currently
uncut patterns.

This plan changes the coordinator from an exact-master-per-round algorithm to
an anytime decomposition that separates three objectives:

1. find the first physically feasible passenger-guided support quickly;
2. improve the certified lower and upper bounds efficiently;
3. retain an explicit exact finishing mode.

At all times the public certificate remains

$$
LB\le z^\star\le UB.
$$

The plan also strengthens the existing equality-count formulation enough to
prevent avoidable master branching. Directional and resource-based cut
generation is specified separately in
[`ddd_stronger_cp_support_cuts.md`](ddd_stronger_cp_support_cuts.md).

## Observed Baseline

On the Three-Station fixed-start Journey-Time case with $K=15$, the first five
equality-only rounds had the following behavior:

| Round | Master time | Lower bound | Active equality cuts | Threshold binaries |
|---:|---:|---:|---:|---:|
| 1 | 0.82 s | 1,165,492 | 0 | 0 |
| 2 | 0.83 s | 1,165,492 | 1 | 2 |
| 3 | 0.83 s | 1,175,084 | 2 | 4 |
| 4 | 0.81 s | 1,184,667 | 3 | 5 |
| 5 | 0.81 s | 1,194,250 | 4 | 7 |

CP-SAT returned one-literal infeasibility cores in about $0.01$ seconds. The
anonymous passenger objective responded by moving through neighboring count
patterns; optimistic served demand decreased from 2,512 to 2,488. In the
longer run, one master round took about one minute around round 21 and more
than two minutes around round 23.

The time network and passenger graph did not grow during these support-only
rounds. The likely cause is the increasingly difficult disjunctive master
created by exact exclusions

$$
X_{ko}\ne n,
$$

not model construction or CP-SAT scheduling.

This diagnosis is instance-dependent. The later Five-Station fixed-start,
$K=19$, Skip/no-wait experiment showed the opposite profile: across 50 rounds,
master build and optimization took approximately 10 seconds in total while
fixed-support CP-SAT consumed approximately 101 seconds and rejected every
support. The master also priced all 1,280 passengers at an implausibly small
journey objective. That case is governed by weak passenger event-time bounds
and local support cuts, not by master optimality proof.

Consequently, adaptive master interruption is no longer the unconditional
next implementation step. First implement the layer-state passenger-time
bound and nearest-feasible-support feedback specified in
[`ddd_stronger_cp_support_cuts.md`](ddd_stronger_cp_support_cuts.md). Activate
the adaptive policy only after live measurements show that master optimization
again dominates the configured round budget.

## Scope

This plan covers:

- per-round and live master instrumentation;
- atomic partial-result checkpoints;
- acceptance of nonoptimal Gurobi master solves;
- adaptive stopping before and after the first upper bound;
- preservation of valid Gurobi best bounds;
- explicit threshold monotonicity and warm starts;
- later collection of a small number of diverse master supports;
- exact finishing and status semantics;
- integration of the first directional threshold-cut mode.

It does not yet cover:

- waiting-enabled CP-SAT;
- optimized initial placement;
- general resource-window cover cuts;
- a persistent master across DDD discretization changes;
- callback-based branch-and-check;
- parallel Gurobi and CP-SAT execution.

## Bound Contract for an Inexact Master

Let $M_q$ be the current optimistic master after all valid cuts from earlier
rounds. Gurobi may terminate before solving $M_q$ to optimality. If it reports
a valid best bound $B_q$, then

$$
B_q\le \min M_q\le z^\star.
$$

Therefore the global lower bound update remains valid:

$$
LB\leftarrow\max\{LB,B_q\}.
$$

If Gurobi also has an integer incumbent $\bar y_q$, its aggregate support may
be sent to CP-SAT even though $\bar y_q$ is not master-optimal. CP-SAT then
either produces a completely validated movement candidate or a valid support
cut. Master optimality is not required for either operation.

An interrupted master without an incumbent can update $LB$ from its best bound
but cannot produce a support for CP-SAT. It must not be reported as master
infeasibility.

## Public Configuration

Introduce a master solve policy:

```text
DddMasterSolvePolicy
  EXACT_OPTIMALITY
  ADAPTIVE_ANYTIME
```

Default remains `EXACT_OPTIMALITY` until the experimental acceptance criteria
are satisfied.

Initial adaptive configuration:

```text
pre_incumbent_hard_limit_seconds = 30
post_first_master_incumbent_polish_seconds = 2
post_upper_bound_hard_limit_seconds = 60
master_gap_fraction_of_global_gap = 0.25
exact_finish_enabled = true
exact_finish_global_relative_gap = 0.01
master_candidate_limit = 1
```

All values belong to one master round, not the entire DDD solve. A separate
global wall-clock budget remains necessary.

## Phase 0: Live Measurements and Atomic Checkpoints

Implementation status: completed on the `ddd` branch. The exact master policy
is unchanged; the added callback is observational only. Benchmark JSON is now
atomically replaced after every completed round and marked with `complete:
false` until normal solver completion.

### Master progress metrics

Record at minimum:

- model build time and optimize time separately;
- time to first integer master incumbent;
- time and objective of every incumbent improvement;
- incumbent count;
- best incumbent and best bound at 1, 5, 10, 30, and 60 seconds;
- relative and absolute master MIP gap at those snapshots;
- explored nodes, open nodes, simplex iterations, and solution count;
- termination reason and Gurobi status;
- whether the returned support was new or already checked;
- threshold variable and row counts;
- warm-start acceptance and completion metrics.

Use a Gurobi callback only for observation and controlled termination. It must
not call CP-SAT or add variables in this phase.

### Checkpoint output

After every `ROUND_FINISHED` event, write an atomic checkpoint:

1. serialize the current result to a temporary file in the target directory;
2. flush and close it;
3. atomically replace the canonical checkpoint path;
4. set `complete: false` and include the last completed round;
5. on normal completion, write the final payload with `complete: true`.

The checkpoint contains the current cut IDs, discretization fingerprint,
bounds, incumbent summary, and every completed iteration. It need not contain
a serializable Gurobi model. A process interruption may lose the active round
but not earlier rounds.

The benchmark runner must write checkpoints even when progress rendering is
disabled.

## Phase 1: Nonoptimal Master Result Contract

Extend the anonymous flow result with:

```text
solver_status
termination_reason
has_incumbent
solution_count
objective_value
best_bound
absolute_gap
relative_gap
time_to_first_incumbent_seconds
incumbent_improvement_count
node_count
optimize_seconds
```

Supported Gurobi outcomes:

| Gurobi outcome | Bound use | Incumbent use | Coordinator meaning |
|---|---|---|---|
| `OPTIMAL` | yes | yes | exact current master |
| `TIME_LIMIT`, incumbent | yes | yes | continue with CP-SAT |
| callback `INTERRUPTED`, incumbent | yes | yes | continue with CP-SAT |
| limit/interruption, no incumbent | yes if finite | no | open certificate |
| `INFEASIBLE` | no new numeric bound required | no | relaxation infeasible |
| `INF_OR_UNBD`, numerical failure | no | no | explicit solver failure |

The flow decomposer is called only when `has_incumbent` is true. The
coordinator must never inspect `.X` otherwise.

The global lower bound uses only `best_bound`; it never uses the nonoptimal
master incumbent objective as a lower bound.

## Phase 2: Adaptive Stopping before the First Upper Bound

Before a physically valid passenger plan exists, the primary goal is support
exploration rather than proving one optimistic support master-optimal.

### Rule

1. solve the master with a hard limit of 30 seconds;
2. when the first new integer support appears, remember its time and objective;
3. permit a two-second polishing window for improved incumbents;
4. terminate after the polishing window if at least one unchecked support is
   available;
5. pass the best retained incumbent to CP-SAT;
6. update $LB$ with the Gurobi best bound at termination.

If no incumbent exists, continue until the hard limit. A previous incumbent
invalidated by a newly added support cut does not count as a feasible warm
start for the current master.

The first version retains one support. A small candidate pool is added only in
Phase 5.

### Rationale

Three ten-second support attempts are potentially more useful than one
thirty-second proof for a support that CP-SAT rejects immediately. The
polishing window avoids terminating on Gurobi's first arbitrary integer
solution while still making the stopping time solution-driven rather than a
fixed sleep.

## Phase 3: Adaptive Stopping after an Upper Bound

Once an exact passenger upper bound exists, the lower bound deserves more
master effort. Let

$$
G=UB-LB
$$

be the global absolute gap. For the active master, let

$$
G_M=z_M^{\mathrm{inc}}-B_M.
$$

Terminate the master when an unchecked incumbent exists and

$$
G_M\le \alpha G,
\qquad \alpha=0.25,
$$

or at the 60-second hard limit. This rule automatically requests more master
accuracy as the global certificate tightens.

If $UB$ and $LB$ use large objective constants, compare absolute gaps in the
canonical passenger-seconds unit. Relative Gurobi `MIPGap` alone is not the
stopping contract.

If no new support appears but the best bound materially improves, retain the
new lower bound and end the round without a CP call. Repeated bound-only rounds
without a new support trigger the stall policy rather than an infeasibility
claim.

## Phase 4: Exact Finishing

A permanently inexact master schedule does not by itself guarantee finite
exact convergence. Provide an explicit finishing phase.

Enter exact finishing when either:

- the global relative gap falls below one percent;
- no new feasible support has appeared for a configured number of rounds;
- the user selects certificate-oriented mode;
- the adaptive controller exhausts its heuristic-round budget.

In exact finishing:

- disable callback early termination;
- solve every current master to configured exact MIP tolerance;
- continue CP separation until no violated support remains;
- report `OPTIMAL` only when the certified global gap closes within tolerance;
- report `FEASIBLE_WITH_GAP` or `UNKNOWN_NO_INCUMBENT` at a global time limit.

An optional monotone master-gap schedule may precede full exactness, for
example 5%, 2%, 1%, 0.5%, and exact tolerance. The schedule must tighten and
must not be reset by a new incumbent.

## Phase 5: Strengthen the Existing Threshold Encoding

For each route-count threshold

$$
\beta_{koq}=[X_{ko}\ge q],
$$

add explicit monotonicity between every pair of consecutively materialized
thresholds:

$$
\beta_{ko,q_2}\le \beta_{ko,q_1}
\qquad\text{for }q_1<q_2.
$$

The relationship is already true for integer solutions but strengthens the
LP relaxation and makes the equality expression

$$
E_{ko}^{n}=\beta_{ko,n}-\beta_{ko,n+1}
$$

explicitly nonnegative in the relaxation.

Threshold variables remain lazy and shared across cuts. Add deterministic
starts derived from the previous count vector:

$$
\beta_{koq}^{\mathrm{start}}=
\begin{cases}
1,&\bar X_{ko}\ge q,\\
0,&\bar X_{ko}<q.
\end{cases}
$$

Where the DDD discretization and passenger arc IDs remain unchanged, also
project prior passenger-flow values. Invalid or missing projected values are
omitted rather than forced.

Record whether Gurobi accepted the complete start and whether it produced the
first incumbent.

## Phase 6: Single-Literal Directional Threshold Strengthening

Implement only the first cut-strengthening phase from
[`ddd_stronger_cp_support_cuts.md`](ddd_stronger_cp_support_cuts.md).

When exact fixed-support CP-SAT returns a one-literal equality core

$$
E_{ko}^{n}: X_{ko}=n,
$$

run up to two bounded, otherwise free CP probes:

$$
G_{ko}^{n}:X_{ko}\ge n,
$$

and

$$
L_{ko}^{n}:X_{ko}\le n.
$$

Use a small shared probe budget because the current CP model is cheap. Initial
configuration:

```text
threshold_probe_total_seconds = 0.5
threshold_probe_max_calls = 2
```

Outcomes:

- `G^n` infeasible gives the direct row $X_{ko}\le n-1$;
- `L^n` infeasible gives the direct row $X_{ko}\ge n+1$;
- feasible threshold probes produce physical schedule candidates that may be
  sent to exact passenger recourse;
- `UNKNOWN` creates no directional cut;
- if neither direction is proved infeasible, add the current equality no-good
  as the mandatory fallback.

Direct bound rows need no threshold binary. Maintain strongest lower and upper
route-count bounds and retire equality exclusions dominated by them.

This phase does not yet implement mixed threshold cores, binary search for the
tightest threshold, general core shrinking, or resource-cover cuts.

## Phase 7: Small Master Candidate Pool

Only after the single-incumbent controller is stable, retain up to three
distinct integer master supports encountered during one optimize call.

Requirements:

- deterministic support fingerprints;
- full anonymous arc-flow vectors for decomposition;
- objective-ordered storage with a minimum aggregate Hamming distance;
- no duplicate CP checks across rounds;
- one shared CP budget for the pool;
- every infeasible candidate may add a valid cut;
- every feasible candidate may update the exact passenger upper bound.

Stop after the candidate limit and polishing window, or at the hard master
limit. Do not run CP-SAT concurrently with the active Gurobi callback in this
phase.

## Stall and Budget Policy

Track separately:

- rounds with a new support cut;
- rounds with only lower-bound improvement;
- rounds with a new upper bound;
- rounds with no progress;
- master solves without an incumbent;
- CP `UNKNOWN` results.

Suggested responses:

- repeated CP `UNKNOWN`: increase CP budget, not master budget;
- repeated master no-incumbent: increase master hard limit or enter exact mode;
- many equality cuts on one count key: prioritize directional probes;
- bound-only progress: remain in post-UB gap mode;
- neither bound nor support progress: finish with the current open certificate.

No stall condition implies infeasibility.

## Progress Output

Extend the terminal line with compact master information:

```text
master=TIME_LIMIT/inc=7/first=0.8s/last=8.3s/
       obj=.../bound=.../gap=.../nodes=...
policy=pre_ub/polish=2.0s/hard=30.0s
checkpoint=round_23
```

Keep Gurobi console logging mutually exclusive with the tqdm renderer. The
JSON checkpoint stores full incumbent histories; the terminal displays only
the first and last improvement.

## API and Result Changes

Add or extend:

- `DddMasterSolvePolicy`;
- `DddAdaptiveMasterConfig`;
- `DddMasterTerminationReason`;
- `DddMasterProgressSnapshot`;
- `DddAnonymousFlowResult` solver and incumbent fields;
- `DddNetworkTimeRefinementIteration` master-history summary;
- `DddNetworkTimeRefinementResult.complete` or equivalent benchmark metadata;
- checkpoint callback or benchmark result sink;
- CLI flags for exact/adaptive policy and all soft/hard limits.

The core solver should not write benchmark files. Checkpoint persistence stays
in the benchmark/export layer and consumes immutable progress snapshots.

## Tests

### Master-result tests

- optimal solve with incumbent and bound;
- time limit with incumbent;
- callback interruption with incumbent;
- time limit without incumbent;
- infeasible master;
- no `.X` access without a solution;
- finite best bound updates the global lower bound;
- incumbent objective is never used as the lower bound.

### Adaptive-controller tests

- first incumbent starts the polishing window;
- improved incumbent resets or updates the retained best but does not extend
  beyond the hard limit;
- no incumbent runs to the hard limit;
- post-UB absolute-gap rule;
- entry into exact finishing;
- deterministic behavior under simulated progress events.

Implement controller logic independently from Gurobi callbacks so most tests
use synthetic event sequences and have no wall-clock flakiness.

### Threshold tests

- threshold monotonicity rows;
- threshold-start projection;
- one-literal upper- and lower-tail proofs;
- feasible threshold-probe schedule reuse;
- equality fallback after `UNKNOWN`;
- directional-bound dominance;
- exhaustive tiny count vectors preserve every physically feasible support.

### Checkpoint tests

- one atomic checkpoint per finished round;
- valid JSON after simulated interruption;
- `complete: false` during the run and `true` at completion;
- no partially written canonical file;
- final payload contains every checkpointed iteration.

### Regression tests

- `EXACT_OPTIMALITY` reproduces the implemented solver behavior;
- all lower bounds remain below exhaustive tiny optima;
- all upper bounds pass complete movement and passenger validation;
- no-wait and future waiting cut provenance cannot mix;
- the complete repository test suite remains green.

## Experimental Sequence

Run all variants under identical global wall-clock budgets rather than only
equal round counts:

1. exact equality-only baseline;
2. adaptive master with equality cuts;
3. adaptive master plus threshold monotonicity and projected starts;
4. adaptive master plus single-literal directional probes;
5. optional three-support master pool.

Primary case:

- `three_station_half_no_skip_no_wait_v0`, fixed-start $K=15$,
  Journey Time, anonymous passenger LP master.

Secondary case after the first upper bound is reliably found:

- `five_station_circle_cw_half_skip_no_wait_v0`, fixed-start $K=19$.

Report:

- time and round of first master incumbent;
- time and round of first physically valid upper bound;
- best $LB$, $UB$, and gap over time;
- primal and dual integrals;
- master time, CP time, and passenger-recourse time;
- supports checked per minute;
- equality and directional cut counts;
- threshold variables, rows, and monotonicity rows;
- master node counts and time spent after the last incumbent improvement;
- checkpoint overhead;
- exact finishing time when requested.

## Acceptance Criteria

The adaptive mode may become the benchmark default only if:

- every reported bound passes the exact small-model tests;
- time to first upper bound improves materially over equality-only exact
  rounds on the primary case;
- no single master round silently exceeds its configured hard limit;
- checkpoints survive interruption;
- the exact finishing mode reproduces the exact reference result;
- threshold strengthening does not remove any exhaustively feasible support;
- total runtime or primal-dual integral improves on the reference matrix.

Do not require every adaptive master incumbent to be better than the previous
master incumbent. New valid cuts change the master feasible region, and an
inferior optimistic objective may be the first physically liftable support.

## Recommended Implementation Order

1. master progress data and atomic checkpoints;
2. nonoptimal result/status contract;
3. pre-UB polishing-window controller;
4. post-UB gap controller and exact finishing;
5. threshold monotonicity and warm starts;
6. single-literal directional probes with equality fallback;
7. benchmark variants 1--4;
8. only then evaluate a small master candidate pool;
9. defer persistent-master and branch-and-check architecture until the cut
   representation is predominantly linear and the measured bottleneck still
   justifies it.

This order first prevents unbounded master rounds and preserves experimental
evidence, then strengthens the exact formulation, and only afterward introduces
more invasive solver integration.

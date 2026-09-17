# Greedy reservoir insertion with own Exit-Waiting

**Correction, 15 September:** the first performance campaign unintentionally inherited
ALL_STOP from its reference. Conclusions about free STOP/SKIP are withdrawn. See the
correction section below and `reservoir_greedy_journey_20260915_v2` for the corrected
comparison.

Status: implemented; 49 targeted tests passed and frontend production build passed,
15 September 2026. The comparison campaign was started after the existing solver
processes exited. Results are pending; no performance advantage is claimed.

Implementation verification covers the small enumeration, waiting necessity,
label/retry translation and shared-port boundary cases listed below. It does not
constitute a complete enumeration of the historical large domains. Their reference
certificates are independently checked during campaign preparation.

Artifacts: `benchmarks/output/reservoir_greedy_20260915_v1/`; progress and outcomes
are recorded in `campaign.json`, per-run JSONL events and final `report.md`.

## Contract and algorithm

R0/R2: historical five-station geometry, 3074 people, current shared port, single use.
Every new cabin chooses a dispatch anywhere in 0–300 seconds, before/between/after
existing dispatches. Construction order and labels do not prescribe temporal order.
STOP/SKIP is free per visit, with no mask catalog. Exit-Waiting is bounded by 60 seconds
per STOP and allowed from time zero, at exact microsecond resolution.
A cabin continues until its first complete return at/after service end; return must
fit the operational horizon. No FIFO, earlier returns or existing movement repairs.
Maximum fleet comes from the instance (50 for these frozen historical cases only).

Start empty. Optimize one complete additional trajectory and integer passengers on
all cabins, with existing movements fixed. Accept only increased validated service
and a new cabin carrying passengers. Repeat until full service, fleet limit, deadline,
or an insertion fails after its allotted retry. No deletion or shortening of old trips.
No global optimality or capacity conclusion follows from construction failure.

## Architecture and interfaces

`reservoir_greedy` composes the existing reservoir movement builder, hybrid calendar
translation, passenger builder and independent certificate validator. The shared
integer-event structure is built once per attempt; Gurobi translates its linear,
Boolean and interval statements without running CP-SAT. Unsupported statements fail.
This deliberate implementation refinement avoids copying physical equations between
backends. Its extra translation time is included in Gurobi build time.

CP-SAT uses native intervals. Gurobi uses free-window selectors against constant
reservations and indicator order constraints for remaining variable pairs. Exact
arrival/departure semantics, self-conflicts, port passage/return and protection beyond
the horizon remain. Safe time bounds account for inactive tails equal to return time.
Old rides are pruned only against their fixed exact endpoints; new rides retain all
canonical possibilities. No journey-time products or enumeration of waiting ticks.

The independent validator uses the original domain, never the prepared calendar.
After insertion, IDs and positive rides are translated together by actual dispatch.
ID permutation must preserve feasible sets and optimum, not solver timing or a
particular optimizer solution.

CLI: `benchmarks/run_reservoir_greedy.py`, `--backend cp_sat|gurobi`,
`--mode insert|construct`, `--reference-checkpoint`, separate `--initial-checkpoint`,
`--maximum-cabins`, `--maximum-wait-seconds`, `--dispatch-window-end`, `--time-limit`,
`--insertion-time-limit`, `--extended-time-limit`, `--workers`, `--memory-limit-gib`,
`--seed`, `--output`, `--build-only`, `--live-snapshot`, `--wait-for-solvers`.
An instance checkpoint is never an implicit seed. Default construct starts empty.

## Budgets, observations and bounds

Initial insertion: 10 seconds total (7 build/search, 2 assignment, 1 reserve).
Unresolved failure: one further 60-second call (55 build/search, 3 assignment, 2 reserve).
An available candidate provides movement and passenger hints for the retry; starts do
not fix decisions. A retry is a restart, not continued branch-and-bound.
The constructor requires positive passenger use on the new cabin; standalone physical
insertion controls do not. This distinction is part of the model fingerprint.

Twelve workers/threads, Gurobi MIPFocus=0, automatic root, zero early relative-gap
termination. Fixed passenger IP: one thread. Outer supervisor: 32 GiB process-tree RSS,
critical memory pressure for 30 seconds, hard civil deadline including suspend.
No overlapping solver jobs. Queue time does not consume campaign time.

Save independent native candidates immediately in `latest_insertion.json`, accepted
plans in `best.json`; JSONL events separate native service, passenger refinement and
accepted insertion. Record build/search/validation/assignment, model sizes, root/search
statistics, native engine version, physical and backend model fingerprints and hashes.
Local bounds are only for fixed outside plus one new cabin. Raw native bounds are not
numerically certified global bounds. INVALID/UNKNOWN/timeout never mean infeasible.

## Correctness gates

- Independent small enumeration and backend equality, with old passengers free.
- Dispatch before and between existing cabins; label invariance and lossless rides.
- Exact resource/window boundaries, overlapping/adjacent reservations, self-conflicts,
  overtaking, shared port passage and terminal return, horizon-neighbor ticks.
- Zero/positive/max Waiting and warmup; a fixture infeasible without origin Waiting
  and feasible with it, independently validated for both backends.
- First-return lifecycle, variable lap count, inactive tails and empty return.
- Full seats, simultaneous boarding/alighting, releases during waiting, integer rides
  and existing integer-assignment regressions.
- Replay by removing/fixing/reinserting a cabin; free insertion must include that replay.
- Retry hint uniqueness, invalid seeds, fleet exhaustion, timeout/resource outcomes,
  monotone accepted service and physically unchanged outside trips.
- At least one small unhinted positive-service insertion for each backend before scale.

## Historical comparisons and 60-minute campaign

Do not repeat old baseline searches. Read recorded Evolution interval No-Wait/Waiting,
fixed-K38, pattern-only and reservoir phase arc-flow artifacts, including follow-up logs.
Labelled fixed-start and corridor arc-flow belong to a structural comparison, not an
unqualified reservoir performance ranking.

Compare demand, geometry, windows, port, lifecycle, fleet, waiting, starts, mask
restriction, objective, budget and clocks. A 1200-second historical Waiting plan must
validate at 60 seconds to transfer; never truncate it. A transferable certificate does
not make its historical search time a matched comparison. Restricted arc-flow bounds
are local. Missing timing origins remain unavailable. Seed uptake is not improvement.

The checked regular All-Stop certificates validate in the new contract: recorded
R2 service 2496, R0 service 2789. These are valid reference plans, not an asserted global
All-Stop capacity proof. The old 36-cabin instance seed has early returns and is excluded
as a line-lifecycle start. Greedy constructors receive neither reference.

| Stage | Budget |
|---|---:|
| Freeze, reference/assignment checking and archive comparison | 6 min |
| R0/R2 × outside K=0/10/20/37 × both backends × 60 s | 16 min |
| R2 × both backends × seeds 0/1 × 8 min, starting empty | 32 min |
| Report and progress comparisons | 6 min |
| Maximum actual elapsed | 60 min |

Outside fleets are deterministic subsets of the same regular reference. Their fixed
passengers are independently optimized before testing; otherwise a service gain could
merely reflect a zero baseline assignment. Each standalone insertion gets 55/3/2 seconds.
Each backend proceeds to construction only after a useful K>=20 insertion with positive
new-cabin service. Alternate backend order. Missing/failed gates do not reallocate time.

Report service versus elapsed time and K, first native feasible solution, true gains,
last improvement, route/Waiting structure, open status and build/root/search bottlenecks.
A backend advantage requires both construction seeds: ten extra people, or matching
other end quality in half the time without a worse end value. Otherwise remain undecided.
No FIFO, neighborhood repair, global-gap controller or large thesis campaign is added.

Research context: continuous-flow transport insertion and joint scheduling,
https://informs-sim.org/wsc17papers/includes/files/300.pdf and
https://www.informs-sim.org/wsc18papers/includes/files/311.pdf.
This pilot uses native whole-deployment optimization, not their exact scheduling
algorithm; earlier weak reservoir-hybrid and reservation results remain relevant risks.


## Correction and Journey-Time experiment — 15 September 2026

The original `reservoir_greedy_20260915_v1` campaign inherited `operating_mode=all_stop`
from its reference checkpoints. Its claims about free STOP/SKIP construction are
withdrawn. Certificates remain valid All-Stop results; they are not evidence that
an unrestricted greedy optimizer prefers All-Stop. The pilot now explicitly selects
SKIP_STOP while retaining the source geometry and validating reference movements.
The physical fingerprint changes accordingly. A regression covers this import path.

`--objective unserved|journey_time` defaults to unserved. Journey time minimizes the
existing exact sum of arrival-minus-release for served passengers plus
service-end-minus-release for unserved passengers. Native unary amount/time linking
keeps both CP-SAT and Gurobi translation linear/Boolean without general nonlinear
products. All existing passenger assignments remain free. A lower validated time cost
accepts an insertion even with equal or lower served count; the new cabin must carry
passengers. Full service alone does not stop a journey construction. A capacity-only
assignment postprocessor is not applied to journey candidates. Local cost bounds are
separate from local unserved bounds; no global bound is claimed.

Tests: 54 targeted checks pass, including independent waiting enumeration for both
objectives/backends, full-service timing improvement without increased service,
horizon-penalty ties and All-Stop-reference mode regression. Frontend adds time cost
with its unserved penalty explicitly labelled. Served count is that of the cost-best
plan and is not asserted monotone.

The interrupted journey v1 run inherited the same mode error and is excluded.
Corrected experiment: `benchmarks/output/reservoir_greedy_journey_20260915_v2`,
CP-SAT, R2, both objectives, seeds 0/1, alternating objective order, 120 seconds each,
10/60-second insertion/retry limits, 12 workers, 32 GiB supervised RSS limit. The
comparison starts empty and uses no historical good-plan hint. Four runs are bounded
by ten minutes total. This is a short objective comparison, not a backend ranking.


Corrected comparison completed: both objectives built 17 cabins in approximately
117 seconds. Journey Time served 1464/1440, versus 1408/1408 for unserved (seeds 0/1).
Every run improved through its last insertion; no accepted insertion was proven
optimal. More waiting under Journey Time shows that waiting minimization is not an
equivalent substitute. See the corrected campaign report and progress figure. No
longer run or default change followed automatically.


## Persistent progress and dashboard (2026-09-15)

The existing `/evolution-live` page now displays greedy fleet construction and
individual insertion attempts. Four corrected Journey-Time comparison runs are
loaded without rerunning optimization. Select a run and K/attempt for validated
UB, native LB and relative gap over elapsed time, including model construction.
Separate charts show served demand and exact journey-time costs against accepted K.
The dashed reference is the independently validated regular All-Stop K38 plan,
not an optimum for each K. Its stored passenger assignment was not subsequently
reoptimized for journey time. Unserved penalties remain part of journey-time costs.

Each new run retains:

- `events.jsonl`: every reported event, including pure bound updates for both engines;
- `iterations/<id>.json`: the completed attempt with times, model sizes and result;
- `progress.json`: compact UB/LB/gap traces for all attempts;
- `plans/k_XXX.json`: independently validated accepted fleet plans;
- `best.json` and `result.json`: incumbent checkpoint and final run result.

`--all-stop-reference` supplies a separately validated comparison, never a search
hint. Existing campaign runners pass their frozen reference automatically. The
live projection is throttled; the raw event archive is not. Bound scope is always
fixed outside trajectories plus one new cabin, not a global fleet bound. Missing
bounds remain missing. Old Gurobi logs cannot recover unrecorded pure bound changes.
Historical event/step count mismatches are not positionally joined.

The solver-free `benchmarks/export_reservoir_greedy_progress.py` publisher accepts
`--campaign`, `--live-directory` and `--all-stop-reference` to import existing
archives. Historical result files and raw logs remain unchanged. Small native
CP-SAT/Gurobi tests verify terminal traces, retries, missing values and exact cost
ticks; the dashboard is also checked through its actual browser controls.


## Linear outside costs and 120-second waiting run (2026-09-15)

Fixed outside arrivals now have singleton domains and direct linear passenger
costs, with passenger counts still free. Only variable arrival events require
amount/time encodings. Gurobi native diagnostic logging is enabled.
34 targeted tests pass, including exact cost export and free outside counts.

The prior comparison was stopped by user request. New CP-SAT run: R2, 3074
people, empty start, fleet maximum 50, Waiting 120 s/STOP including warmup,
dispatch 0–300 s, 12 workers, 32 GiB supervised RSS. Insertion budget 30 s;
unresolved unsuccessful attempts receive one 120 s retry. Proven OPTIMAL or
INFEASIBLE still terminates the unsuccessful insertion. The 7800 s safety
deadline exceeds the 50 × (30+120) nominal maximum.
Output: `benchmarks/output/reservoir_greedy_cp_sat_linear_w120_20260915_185009`.

# EAN Passenger Optimization Benchmark Findings

Date: 2026-05-13

Relevant implementation commits:

```text
86094dd Add benchmark optimization toggles
1c1ac54 Fix EAN platform-exit wait headways
```

## Setup

Benchmark command shape:

```bash
uv run python benchmarks/run_ean_passenger_benchmark.py \
  --example three_station_v0 \
  --artifact-set ean_passenger_journey_time \
  --ean-solver-policy exact_optimality \
  --time-limit 300 \
  --sample-interval 5 \
  --ean-optimizations <selection> \
  --label <label>
```

Scenario and objective:

```text
example: three_station_v0
artifact set: ean_passenger_journey_time
solver policy: exact_optimality
time limit: 300 seconds
sample interval: 5 seconds
```

Compared optimization selections:

```text
all:
  candidate_horizon_pruning
  single_ring_dominated_ride_pruning
  slot_time_relaxation_strengthening

none:
  no benchmark optimizations enabled

candidate pruning only:
  candidate_horizon_pruning
  single_ring_dominated_ride_pruning

slot strengthening only:
  slot_time_relaxation_strengthening
```

The benchmark JSON files are local machine outputs under
`benchmarks/output/results/` and are intentionally not committed.

## Result Summary

| Run | Active optimizations | Vars | Constraints | Ride candidates | Slots | Objective (h) | Best bound (s) | Gap | Nodes | Served | Unserved |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `opt_all_5min` | candidate horizon pruning, single-ring dominated ride pruning, slot-time relaxation strengthening | 82,398 | 232,560 | 958 | 7,664 | 751.26 | 2,532,474 | 6.36% | 2,027 | 2,429 | 1,051 |
| `opt_none_5min` | none | 151,974 | 484,989 | 3,857 | 30,856 | 751.54 | 2,502,419 | 7.51% | 662 | 2,416 | 1,064 |
| `no_slot_strengthening_5min` | candidate horizon pruning, single-ring dominated ride pruning | 82,398 | 209,568 | 958 | 7,664 | 751.35 | 2,495,863 | 7.73% | 8,496 | 2,416 | 1,064 |
| `no_candidate_pruning_5min` | slot-time relaxation strengthening | 151,974 | 577,557 | 3,857 | 30,856 | 752.90 | 2,530,207 | 6.65% | 1 | 2,400 | 1,080 |

## Comparison Against No Optimizations

Baseline `opt_none_5min`:

```text
variables:       151,974
constraints:     484,989
ride candidates:   3,857
slots:            30,856
objective:        751.54 passenger-hours
best bound:     2,502,419 seconds
gap:               7.51%
nodes:              662
```

| Run | Vars | Constraints | Rides/slots | Objective delta | Bound delta | Gap delta | Nodes |
|---|---:|---:|---:|---:|---:|---:|---:|
| `opt_all_5min` | -45.8% | -52.0% | -75.2% | -0.28 h | +1.20% | -1.15 pp | 2,027 |
| `no_slot_strengthening_5min` | -45.8% | -56.8% | -75.2% | -0.19 h | -0.26% | +0.22 pp | 8,496 |
| `no_candidate_pruning_5min` | 0.0% | +19.1% | 0.0% | +1.36 h | +1.11% | -0.86 pp | 1 |

## Gap Timing

| Run | <=20% gap | <=10% gap | <=8% gap | <=7% gap |
|---|---:|---:|---:|---:|
| `opt_all_5min` | 22.9s | 34.1s | 69.0s | 80.6s |
| `opt_none_5min` | 105.1s | 105.1s | 105.1s | - |
| `no_slot_strengthening_5min` | 15.2s | 21.6s | 38.0s | - |
| `no_candidate_pruning_5min` | 80.3s | 121.5s | 144.8s | 248.0s |

## Findings

The historical `all` independent-optimization configuration gives the smallest final gap, the best
objective, and a much smaller model than the unoptimized benchmark. Relative to
`none`, it reduces variables by 45.8%, constraints by 52.0%, ride candidates by
75.2%, and slots by 75.2%, while improving the final bound by 1.20 percentage
points and the final MIP gap by 1.15 percentage points.

Candidate pruning is the dominant model-size improvement. With only candidate
pruning enabled, ride candidates drop from 3,857 to 958 and slots drop from
30,856 to 7,664. This also makes the model much easier to branch on: the run
explores 8,496 nodes in five minutes, compared with 662 nodes for `none`.
However, without slot-time strengthening the bound is slightly worse than
`none`, and the final gap is slightly worse.

Slot-time relaxation strengthening is the dominant bound improvement. With only
slot strengthening enabled, the best bound improves by 1.11% relative to
`none`, and the gap improves from 7.51% to 6.65%. The downside is model size:
without candidate pruning, the strengthening constraints increase constraints
from 484,989 to 577,557 and the solver only explores one node in five minutes.

The two optimizations are complementary. Candidate pruning makes the model
small enough for useful search, while slot-time strengthening improves the
relaxation. Together, they outperform either isolated optimization.

## Tight Big-M Follow-Up

Two follow-up experiments tested the opt-in `tight_big_m_bounds` toggle against
the current `all` default. The output directory still contained older runs, so
only the matching latest pairs were compared for each phase.

### Phase 1: Passenger Slot Release Big-M

Phase 1 tightened only:

```text
board_time >= release_time - M * (1 - slot)
```

using:

```text
M = group.release_time_seconds
```

This is mathematically safe, but it only affects a narrow lower-bound
constraint on inactive or fractional passenger slots.

| Run | Objective (h) | Best bound (s) | Gap | Nodes | Notes |
|---|---:|---:|---:|---:|---|
| `opt_all_5min` | 751.2602 | 2,532,474 | 6.36% | 2,019 | historical baseline |
| `tight_big_m_phase1_5min` | 751.2331 | 2,526,600 | 6.58% | 657 | release Big-M only |

Phase 1 improved some early time-to-gap thresholds, but the five-minute final
bound and gap were worse than `all`. This supports keeping Phase 1 behind an
opt-in toggle rather than enabling it by default.

### Phase 2: Stop/Skip Timing Big-M

Phase 2 also tightened the stop/skip timing implications:

```text
service_exit_ub_m = max(0, skip_time - service_time)
service_exit_lb_m = max(0, service_time - skip_time)
skip_exit_ub_m    = max(0, min(service_time + wait_upper_bound - skip_time,
                               time_upper_bound - skip_time))
skip_exit_lb_m    = max(0, skip_time - service_time)
```

These bounds are derived from the opposite active branch:

```text
service constraints inactive -> skip timing active
skip constraints inactive    -> service timing active
```

| Run | Objective (h) | Best bound (s) | Gap | Nodes | Served | Unserved |
|---|---:|---:|---:|---:|---:|---:|
| `opt_all_5min` | 751.2646 | 2,532,474 | 6.36% | 718 | 2,429 | 1,051 |
| `tight_big_m_phase2_5min` | 751.3952 | 2,563,000 | 5.25% | 7,924 | 2,418 | 1,062 |

Phase 2 clearly strengthens the proof side of the solve. The best bound
improves by about 30,527 seconds, and the final gap improves from 6.36% to
5.25%, a relative gap reduction of about 17.5%.

The tradeoff is incumbent quality in the five-minute run. The best found
solution is slightly worse: objective increases by about 470 seconds, served
passengers decrease by 11, and unserved passengers increase by 11. The solver
also explores many more nodes. This does not indicate changed model semantics;
it indicates a different search trajectory from the stronger formulation.

Time-to-gap for Phase 2:

| Gap threshold | `all` | `tight_big_m_phase2_5min` |
|---|---:|---:|
| <=10% | 49.9s | 71.1s |
| <=8% | 108.0s | 71.4s |
| <=7% | 129.1s | 75.3s |
| <=6.5% | 154.0s | 75.3s |
| <=6.4% | 215.6s | 75.3s |
| <=6.0% | not reached | 79.2s |

Interpretation: Phase 2 is promising for gap closure and proof progress, but a
single five-minute run is not enough evidence to make it the default for
export-oriented workflows where incumbent quality matters.

## Decision

Keep all three optimizations enabled by default:

```text
candidate_horizon_pruning
single_ring_dominated_ride_pruning
slot_time_relaxation_strengthening
```

Keep `tight_big_m_bounds` available as an opt-in benchmark/proof-oriented
toggle, but do not include it in `all` yet.

The benchmark runner should continue to expose `--ean-optimizations` so future
formulation changes can be compared against `all` and `none`.

## Horizon and Time-Bound Formulation Matrix

Date: 2026-07-14

Implementation baseline:

```text
git commit: 8c4b248cb36ce8c2f81306776a31a9c4648cc176
worktree: dirty with the horizon/time-bound implementation under evaluation
```

The six runs used the same Three-Station journey-time setup, 300-second time
limit, five-second progress interval, and the three default independent
optimizations. The matrix varied one horizon formulation and one time-bound
formulation:

```text
horizon:
  horizon_legacy
  horizon_conservative_free_suffix
  horizon_exact_time_activation

time bounds:
  time_bounds_legacy_plus_10
  time_bounds_derived_visit_bounds
```

These horizon alternatives define different finite feasible sets. Their
objective values must therefore not be interpreted as same-model performance
deltas.

| Horizon | Time bounds | Vars | Constraints | Objective (h) | Best bound (s) | Gap | Nodes | Served | Skips |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| legacy | legacy + 10 | 82,398 | 233,193 | 751.303 | 2,528,472 | 6.52% | 574 | 2,428 | 57 |
| legacy | derived visit bounds | 82,398 | 233,193 | 751.802 | 2,499,307 | 7.66% | 1 | 2,400 | 31 |
| conservative free suffix | legacy + 10 | 82,398 | 233,193 | 751.331 | 2,528,219 | 6.53% | 782 | 2,424 | 51 |
| conservative free suffix | derived visit bounds | 82,398 | 233,193 | 751.572 | 2,500,681 | 7.58% | 1 | 2,429 | 52 |
| exact time activation | legacy + 10 | 83,908 | 237,723 | 954.240 | 1,381,005 | 59.80% | 1 | 1,353 | 0 |
| exact time activation | derived visit bounds | 83,908 | 237,723 | 751.508 | 2,491,525 | 7.91% | 208 | 2,432 | 23 |

The legacy and conservative horizon cases behave almost identically when they
use the historical time domain. Their final objectives differ by about 102
passenger-seconds and their gaps differ by 0.01 percentage points. This is
evidence that the conservative free suffix is computationally viable on this
instance, although it does not establish equivalence of the different horizon
semantics.

The derived visit bounds are not a general relaxation improvement in their
current form. With either the legacy or conservative horizon, they reduce the
five-minute best bound by about 28,000 seconds, leave the solver at one
processed node, and worsen the final gap from about 6.52% to about 7.6%.
The fallback of one complete operational horizon of waiting per eligible visit
creates a much larger propagated global domain than the historical cumulative
ten-second allowance. On this artifact, the global upper bound grows from
1,595.82 seconds to 19,585.82 seconds because each waiting-enabled visit may
add up to the 1,200-second operational horizon. The visit-specific lower and
upper bounds do not compensate for that larger domain in these two
formulations.

Exact time activation has the opposite interaction. With the historical
all-visits global domain, the activation binaries have a very weak relaxation:
after five minutes the solver has found only two solutions, no skip, a 59.80%
gap, and an incumbent close to the initial MIP start. With propagated visit
bounds, the same activation formulation reaches a normal-quality incumbent
after about 108 seconds, crosses 8% gap after about 153 seconds, and processes
208 nodes. The propagated lower bounds expose which prefixes can reach the
operational horizon and give presolve substantially more structure around the
activation variables.

The combined exact/derived case is still weaker on the proof side than the
legacy baseline: its final best bound is about 36,947 seconds lower and its gap
is 1.39 percentage points larger. Its incumbent is nevertheless close to the
other usable runs and serves the largest number of passengers in this matrix.
This confirms that exact activation is functioning, but not that it is ready
to replace the current default.

The matrix supports retaining `horizon_legacy` with
`time_bounds_legacy_plus_10` as the default. Neither
`time_bounds_derived_visit_bounds` nor `horizon_exact_time_activation` is
promoted by this experiment. The exact activation formulation should be
evaluated only together with meaningful propagated event bounds; the
historical global domain is an unsuitable companion formulation.

## Affine Stop/Skip Timing

Date: 2026-07-14

Implementation baseline:

```text
git commit: 5db36ecbe6bf26a4ba2e21d7a4014eb40d72d834
worktree: dirty with the affine timing implementation under evaluation
```

Both runs used `three_station_v0`, the journey-time objective, the
`exact_optimality` solver policy, the three default independent optimizations,
the legacy horizon and time bounds, a 300-second limit, and five-second
callback sampling. The only model difference was the stop/skip timing
formulation.

| Timing | Vars | Constraints | Objective (h) | Best bound (s) | Gap | Nodes | Served | Unserved | Skips |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Big-M | 82,398 | 233,193 | 751.303 | 2,528,472 | 6.52% | 586 | 2,428 | 1,052 | 57 |
| affine | 82,398 | 231,900 | 751.425 | 2,574,514 | 4.83% | 9,063 | 2,424 | 1,056 | 58 |

The affine formulation removes exactly 1,293 rows: three net rows for each of
the 431 visits. Variables, ride candidates, slots, horizon semantics, and time
bounds are unchanged.

The proof-side improvement is substantial. The best bound increases by 46,042
passenger-seconds, or 1.82%, and the final gap decreases by 1.69 percentage
points. This is a relative gap reduction of 25.9%. The solver processes about
15.5 times as many nodes.

| Gap threshold | Big-M | affine |
|---|---:|---:|
| <=10% | 38.4s | 47.2s |
| <=8% | 43.8s | 47.2s |
| <=7% | 87.7s | 47.2s |
| <=6% | not reached | 49.1s |
| <=5% | not reached | 286.5s |

The affine run initially reaches 10% and 8% slightly later, but then closes the
proof gap much more effectively. Its best incumbent is 441 passenger-seconds,
or 0.123 passenger-hours, worse than Big-M and serves four fewer passengers.
This is consistent with a changed time-limited search trajectory, not changed
integer semantics: exact small-instance tests preserve both waiting-time and
journey-time objectives.

At this stage, the affine formulation remained opt-in after the individual
long run. The result was strong evidence that it is a better proof
formulation, but did not by itself justify replacing Big-M while incumbent
quality was also important. The later combined comparison changed that
Journey-Time default decision.

## Compact Unary-Slot Activation

Date: 2026-07-15

Implementation baseline:

```text
base commit: 103d9b8
worktree: compact unary-slot activation implementation under evaluation
```

The comparison used six `three_station_v0` journey-time runs: three with the
historical per-slot activation and three with exact first-slot activation. Every
run used the `exact_optimality` policy, a 300-second limit, five-second
callback sampling, the default independent optimizations, and no resumed
checkpoint. Execution order alternated between the two cases.

| Activation | Runs | Vars | Rows | Nonzeros | Mean setup (s) | Objective (h) | Bound (s) | Gap | Mean nodes |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| per slot | 3 | 82,398 | 233,193 | 858,970 | 1.93 | 751.303 | 2,528,472 | 6.52% | 574 |
| first slot | 3 | 82,398 | 183,377 | 752,632 | 1.71 | 751.351 | 2,531,673 | 6.40% | 561 |

First-slot activation removes 49,816 rows (21.4%) and 106,338 nonzeros
(12.4%) without changing the variable count. Mean Gurobi model setup time
decreases by about 11.4%. Presolve retains 4,246 fewer rows and 16,277 fewer
nonzeros in the compact case.

All three runs of each formulation reached the same final incumbent, bound,
and gap. The compact formulation improves the bound by 3,201
passenger-seconds and lowers the final gap by 0.11 percentage points. Its
incumbent is 174 passenger-seconds, or 0.048 passenger-hours, worse. The
branch-and-bound node counts are similar.

The repeated equality of final values indicates that these runs are
effectively deterministic under the fixed machine, MIP start, and solver
configuration. The result supports the compact formulation as an exact
proof-side and model-size improvement, but not yet as the default for
export-oriented solves where the best time-limited incumbent also matters.

## Projected Selected Boarding Times

Date: 2026-07-15

Implementation baseline:

```text
git commit: 5872075e9d803b1a6c16e83a2935ce529209bade
worktree: unrelated documentation plan edits were present
```

The comparison used two matched `three_station_v0` journey-time runs with the
default independent optimizations, legacy horizon and time bounds, Big-M
stop/skip timing, per-slot activation, a 300-second limit, and five-second
callback sampling. The only difference was whether selected boarding time was
represented explicitly or eliminated by the exact Fourier--Motzkin projection.

| Board time | Vars | Rows | Nonzeros | Setup (s) | Objective (h) | Bound (s) | Gap | Nodes | Served | Unserved |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| explicit | 82,398 | 233,193 | 858,970 | 2.005 | 751.303 | 2,528,472 | 6.52% | 586 | 2,428 | 1,052 |
| projected | 74,734 | 202,537 | 789,994 | 1.847 | 751.380 | 2,525,912 | 6.62% | 8,967 | 2,424 | 1,056 |

Projection removes 7,664 variables (9.3%), 30,656 rows (13.1%), and 68,976
nonzeros (8.0%). Gurobi model setup becomes 0.158 seconds, or 7.9%, faster.
The removed variables equal the 7,664 passenger slots of the artifact.

Despite the exact projection and preserved LP relaxation in the remaining
variables, the single five-minute projected run has a 280 passenger-second
worse incumbent, a 2,560 passenger-second lower bound decrease, and a 0.10
percentage-point larger gap. It processes 15.3 times as many nodes and serves
four fewer passengers. This is a time-limited search outcome, not evidence of
changed passenger-model semantics. This individual result did not justify
promotion by itself; the later combined experiment below did.

## Combined Exact Formulations

Date: 2026-07-15

Implementation baseline:

```text
git commit: 3d4eb3e527df42c066f410eeb7533dffda6fe3ec
worktree: dirty with the exact first-slot projected-release reduction
```

All runs used `three_station_v0`, the journey-time objective,
`exact_optimality`, legacy horizon and time bounds, the three default
independent optimizations, no checkpoint resume, and five-second callback
sampling. The combined projected case additionally used:

```text
stop_skip_timing_affine
slot_activation_first_slot
board_time_projected_journey_time
```

The first two changes are exact timing and unary-slot reformulations. The third
is the exact Fourier--Motzkin board-time projection. Therefore all three
configurations preserve the same intended integer model for this journey-time
case.

### Five-Minute Comparison

| Formulation | Vars | Rows | Nonzeros | Setup (s) | Objective (h) | Best bound (s) | Gap | Nodes | Served | Unserved |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `all` | 82,398 | 233,193 | 858,970 | 2.262 | 751.303 | 2,528,472 | 6.52% | 574 | 2,428 | 1,052 |
| affine + first slot | 82,398 | 182,084 | 748,108 | 1.693 | 751.300 | 2,565,551 | 5.14% | 8,971 | 2,432 | 1,048 |
| affine + first slot + projected board time | 74,734 | 166,756 | 702,124 | 1.545 | 751.245 | 2,582,536 | 4.51% | 9,160 | 2,440 | 1,040 |

The full combination improves every recorded five-minute result relative to
`all`: it has the best incumbent, bound, gap, and service count, while also
using the smallest model and least setup time.

### Fifteen-Minute Confirmation

| Formulation | Vars | Rows | Nonzeros | Setup (s) | Objective (h) | Best bound (s) | Gap | Nodes | Served | Unserved |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `all` | 82,398 | 233,193 | 858,970 | 1.906 | 751.277 | 2,528,801 | 6.50% | 8,960 | 2,436 | 1,044 |
| affine + first slot + projected board time | 74,734 | 166,756 | 702,124 | 1.530 | 751.229 | 2,620,817 | 3.09% | 9,316 | 2,448 | 1,032 |

After fifteen minutes, the combined formulation reduces variables by 9.3%,
rows by 28.5%, nonzeros by 18.3%, and pre-optimize setup time by 19.7%. Its
incumbent improves by 173 passenger-seconds, its best bound improves by
92,016 passenger-seconds, and its gap falls by 3.41 percentage points, a
52.4% relative reduction.

The combined run reaches a 6% gap after 29.8 seconds, 5% after 52.6 seconds,
and 4.5% after 286.5 seconds. The baseline does not reach 6% within the
fifteen-minute limit.

This is one deterministic machine-level comparison on the journey-time
Three-Station instance. It establishes the combined configuration as the best
observed formulation for that scope, but does not establish the same result
for the waiting-time objective, `five_station_v0`, or different solver
hardware and search seeds.

As of 2026-07-15, the combination is the Journey-Time production default.
Waiting-Time retains explicit selected boarding times because they occur in
that objective.

## Passenger-Optimized All-Stop MIP Start

Date: 2026-07-15

Implementation baseline:

```text
base commit: f4f7bb743492d99cb42bd581e142c6d9e545c7c7
worktree: dirty with only the MIP-start implementation and its documentation
```

Two matched `five_station_v0` Journey-Time runs used the current production
formulation, `exact_optimality`, a 300-second main-solve limit, and five-second
callback sampling. The only difference was the MIP start. The historical case
used the direct greedy passenger assignment. The optimized case first fixed
the same deterministic all-stop movement plan and solved its passenger
assignment before transferring the complete solution to the integrated model.

| Start | Setup (s) | Objective (s) | Objective (h) | Bound (s) | Gap | Nodes | Served | Unserved |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| greedy all-stop | 5.75 | 3,155,354 | 876.487 | 1,604,228 | 49.16% | 1 | 1,480 | 1,720 |
| optimized all-stop | 12.85 | 1,947,463 | 540.962 | 1,604,228 | 17.62% | 1 | 2,544 | 656 |

The auxiliary solve adds about 7.10 seconds of setup but improves the accepted
initial incumbent by 1,207,891 passenger-seconds, or 38.3%, and serves 1,064
additional passengers. Gurobi accepts both starts after approximately 0.2
seconds of the main solve. Neither run finds a later incumbent.

The final lower bound is identical, and both runs perform essentially the same
root work before terminating at one reported node. The optimized start
therefore repairs a large primal-quality defect without changing the observed
dual progress. This isolates the remaining Five-Station bottleneck to the root
relaxation and integrated movement--passenger coupling rather than start
quality.

## Root-Relaxation Variable Families

Date: 2026-07-15

Implementation commit:

```text
659b005 fix(benchmarks): add raw LP diagnostic fallback
```

The diagnostic used `five_station_v0`, the production Journey-Time
formulation, the optimized all-stop MIP start, the exact-optimality policy, and
a 300-second main-solve limit. The integrated model contained 252,844
variables and 601,181 rows. The separately labelled raw continuous relaxation
used barrier without crossover and solved optimally in 68.67 seconds.

| Metric | Raw LP | Five-minute MIP |
|---|---:|---:|
| Objective or lower bound (s) | 312,738 | 1,604,228 |
| Incumbent (s) | n/a | 1,947,463 |
| Gap | n/a | 17.62% |
| Reported nodes | n/a | 1 |

The MIP did not expose an optimal `MIPNODE` relaxation vector within the time
limit, so the raw-LP family values below are not post-cut root values:

| Variable family | Integer variables | Fractional | Share | Fractional distance |
|---|---:|---:|---:|---:|
| Stop/skip | 989 | 739 | 74.7% | 183.45 |
| Headway order | 166,692 | 50,609 | 30.4% | 23,806.04 |
| Passenger slot | 41,088 | 16,528 | 40.2% | 3,018.41 |
| Unserved demand | 20 | 2 | 10.0% | 0.62 |

The raw LP is much weaker than the bound obtained during MIP root processing:
Gurobi raises the lower bound by approximately 1.29 million passenger-seconds
before the five-minute termination. Therefore the large raw headway
fractionality cannot be interpreted directly as the remaining post-cut
bottleneck.

A matched Three-Station smoke comparison demonstrates the distinction. Its raw
LP contained 14,317 fractional headway-order variables, while a later
`MIPNODE` sample contained only seven. Passenger slots remained heavily
fractional: 5,848 in the raw LP and 3,686 after root processing. This is
evidence that Gurobi cuts can almost eliminate headway-order fractionality on
the smaller case while substantial passenger and stop/skip coupling remains.
It does not prove that the Five-Station post-cut relaxation has the same family
distribution.

## Compact Fixed-Movement Passenger Optimizer

Date: 2026-07-15

Software baseline:

```text
base commit: 08ac095
worktree: dirty with the independent fixed-movement optimizer implementation
```

Matched `three_station_v0` and `five_station_v0` Journey-Time diagnostics used
the production formulation, exact-optimality policy, and a 300-second limit per
case. The fixed integer and LP cases used the same movement incumbent extracted
from the integrated case and exactly the same filtered ride candidates.

| Instance | Case | Objective (s) | Runtime (s) | Variables | Rows | Nonzeros | Fractional rides |
|---|---|---:|---:|---:|---:|---:|---:|
| three station | integer | 2,704,563.2 | 0.0048 | 737 | 332 | 2,192 | 0 |
| three station | LP | 2,704,563.2 | 0.0028 | 737 | 332 | 2,192 | 0 |
| five station | integer | 1,947,463.3 | 0.0203 | 3,550 | 681 | 16,942 | 0 |
| five station | LP | 1,947,463.3 | 0.0082 | 3,550 | 681 | 16,942 | 0 |

Both practical LPs are integral and have zero observed LP/IP objective gap.
This does not contradict the direct-ride odd-cycle counterexample: it shows
only that these two particular movement incumbents do not expose the general
nonintegrality.

The compact integer model reproduces the integrated incumbent objective on the
Five-Station all-stop movement and improves the Three-Station passenger
assignment by approximately 284 passenger-seconds. Compared with the
integrated models, it removes all movement, timing, headway, selected-time, and
unary-slot variables. Exact fixed-movement passenger evaluation is therefore
negligible for these instances; the computational bottleneck remains the joint
movement--passenger search.

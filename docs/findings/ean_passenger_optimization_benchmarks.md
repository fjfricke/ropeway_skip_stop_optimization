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

`all` is the best current default. It gives the smallest final gap, the best
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
| `opt_all_5min` | 751.2602 | 2,532,474 | 6.36% | 2,019 | current default |
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

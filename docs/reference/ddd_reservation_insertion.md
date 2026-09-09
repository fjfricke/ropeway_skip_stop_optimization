# DDD reservation insertion pilot

Status: **implemented diagnostic prototype**, 9 September 2026. Results and limitations: [K39 finding](../findings/ddd_reservation_insertion_gate.md). Implementation and decision: [completed follow-up](../plans/reservation_insertion_implementation.md). Research rationale: [design](../plans/reservation_insertion_kernel.md).

## Public API and ownership

The lazy `optimization.ddd` facade exposes `DddReservationInsertionOptimizer`, `DddReservationInsertionConfig`, `DddServiceInsertionIntent`, `DddReservationInsertionResult`, `DddReservationAttemptStatus`, `DddFixedKPrimalValidator`, `DddValidatedFixedKPlan`, `DddReservationCheckpointAdapter`, and `build_ddd_fixed_k_domain_manifest`.

```python
from ropeway_skip_stop_optimization.optimization.ddd import (
    DddReservationInsertionConfig,
    DddReservationInsertionOptimizer,
)

result = DddReservationInsertionOptimizer(
    DddReservationInsertionConfig(
        total_time_limit_seconds=30,
        attempt_time_limit_seconds=0.25,
        maximum_affected_cabins=4,
        beam_width=8,
    )
).optimize(problem=prepared.problem, initial_plan=seed, intents=intents)
```

Inputs reuse `DddFixedKTrajectoryProblem`, `DddReferenceSolution` and canonical ride-candidate IDs. No new physical scenario representation or movement model is introduced. The optimizer composes the following services in `src/ropeway_skip_stop_optimization/optimization/ddd/`:

| Module | Responsibility |
|---|---|
| `fixed_k_certificate.py` | Shared solver-free domain manifest and physical/integer passenger certificate. Existing CP functions wrap it, preserving checkpoint schema and domain identity. |
| `reservation_models.py` | Config, typed intents, statuses, attempt/result records. |
| `reservation_calendar.py` | Resource index, private suffix-removal transactions, boundary retention, stale-revision rejection and rollback. |
| `reservation_waiting.py` | Exact local forbidden-wait intervals against given reservations, individual headways, wait grid and horizon activation. Uses existing half-open `DddTickInterval`. |
| `reservation_repair.py` | Bounded beam search over suffixes, legal exit waits, coupled service endpoints, future-boundary proposals and conflict-driven cabin release. |
| `reservation_passenger.py` | Deterministic OD requests and integer assignment repair using existing EAN direct rides. |
| `reservation_optimizer.py` | Deadline, service attempts, validation, best-plan tracking and optional improvement acceptance. |
| `reservation_refinement.py` | Optional composed fixed-movement assignment IP, canonical universe check, shared remaining budget and independent recertification. |
| `reservation_checkpoint.py` | Heuristic schema plus explicit import/export through existing CP checkpoint interfaces. |

Each run owns its calendar. Candidate suffix changes remain private; the original plan is never edited. If a validated improvement is accepted, the optimizer publishes a newly constructed calendar and plan together. Calendar transactions additionally support revision-checked commit, but the optimizer uses replacement after validation. No inner Gurobi or CP model is built. Benchmark preparation and persistence stay in `benchmarking/ddd_reservation_insertion.py`; the CLI remains thin.

## Physical contract

The pilot shares the current fixed-start, immutable-ring, Journey-Time, integer-tick domain with the integrated CP certificate. Existing restrictions are retained, including rejection of boundary-only reduced resources at the domain boundary. Unsupported domains fail explicitly.

The [accepted finite horizon](finite_horizon_contract.md) applies: new resource entries after H are excluded, while active occupancies retain full clearance. No additional post-H continuation requirement is imposed. Changed paths cover H, respect visit bounds, preserve physical starts and reconstruct required boundary reservations from the problem.

Wait intervals are calculated for a fixed route, entry tick and external calendar; resource entry/clearance retain their shared dependence on the same wait. SKIP cannot wait. Station wait limits, grid step and earliest legal waiting boundary are respected without enumerating the microsecond grid. The calendar uses sorted entry ticks and prefix maxima of clearance plus headway to prune impossible conflict partners; long earlier occupancies remain visible. Immutable horizon/resource data are cached by the run-owned solver. Cross-visit self-conflicts are checked against already materialized visits as well as frozen reservations.

The full suffix search is **heuristic**. It keeps a bounded number of timed paths and uses the previous wait, interval boundaries and nearby future resource boundaries as proposals. It does not implement complete SIPP-IP or certify the absence of a feasible repair. `NO_FEASIBLE_REPAIR_FOUND` refers only to the explored neighborhood.

## Repair and passenger behavior

A request identifies a canonical ride and positive integer passenger count. Both endpoint visits must STOP. The initial repair scope opens at the nearest preceding STOP, or the fixed start if no such STOP exists. Subsequent conflicts can release other cabins at a corresponding suffix boundary. Each enlarged scope tries its insertion order and reversed order; repaired trajectories are inserted into the private calendar before planning the next cabin.

The implementation opens one additional blocker at a time, up to `maximum_affected_cabins`. It does not exhaust all blocker combinations, priority orders or earlier prefix choices. Future boundary lookahead defaults to three visits and ends at the next STOP. This is the current restriction to investigate before broadening the heuristic.

Changed routes may create additional active visits, which are reconstructed from the existing route domain. The heuristic may remove future STOPs; assignment repair must account for their consequences. Services whose boarding lies in a frozen prefix remain mandatory. Other future assignments can change. All unassigned people remain explicitly unserved.

The fast evaluator uses `build_ean_fixed_movement_rides`, preserves feasible prior assignments, inserts the requested quantity, and fills residual capacity by increasing alighting time. It is not an optimal passenger assignment. Accepted results pass the shared integer certificate and the existing DDD→EAN adapter and full EAN movement validation. The adapter and certificate currently repeat some reference validation; the observed validation cost is reported, not hidden.

## Benchmark and artifacts

Run from the software repository:

```sh
.venv/bin/python benchmarks/run_ddd_reservation_insertion.py \
  benchmarks/output/ddd_integrated_cp_sat_waiting/k39/w1200_600s_seed0 \
  --output-dir benchmarks/output/ddd_reservation_insertion/my_fresh_trial \
  --seconds 40 --attempt-seconds .25 --cabins 4 --beam 8 --requests 100
```

The output directory must be fresh. `--attempt-seconds` limits **repair search**, while complete acceptance checks are separately timed. `--seconds` is the overall deadline including preparation; already-running validation/checkpoint publication may overrun and this is reported. Expiration always retains the validated seed/best plan. The CLI performs no automatic follow-up campaign. `--passenger-seconds 5` enables the existing integer assignment evaluator after search, on up to three distinct native finalists and then the original movement as a control (at most four solves). Up to 25% of the remaining budget, capped at four times this per-IP limit, is reserved before search. Solver time limits exclude adapter/model construction and final validation, so this is a reported soft wall deadline. An expired budget never starts another IP. Assignment OPTIMAL never means globally optimal movement.

Default request selection takes the three groups with most unserved people and early existing visit pairs missing at least one STOP. It interleaves groups and tries quantity 1 and the maximum group/cabin quantity. It is deterministic and currently restricts requests to visits present in the seed. `requests.json` captures the exact selected requests. Diagnostic trials evaluate them against an unchanged baseline. `--accept-improvements` optionally enables sequential improvement; it has unit coverage through shared components but was not part of the reported K39 comparison.

Each successful run also writes `cp_seed.json`. The result separates `native_upper_bound` from the final bound and records each assignment outcome. New run configs preserve `physical_source_config` to resume their own checkpoints without guessing the physical setup.

Files: `config.json`, `requests.json`, `initial.json`, `attempts.jsonl`, `events.jsonl`, `incumbent.json`, `result.json`, or `error.json` on failure. Config records domain, source hashes and search restrictions; new runs additionally record a reservation-module implementation digest. The original three pilot runs preceded that metadata addition. Events use existing `OptimizationProgressEvent`/`OptimizationLiveStore`. Memory is process-lifetime RSS; attempt measurements split repair, passenger evaluation and validation.

The checkpoint schema is `reservation_insertion_v1`. `DddReservationCheckpointAdapter.export_cp_seed` revalidates the result and writes a compatible CP checkpoint. No global LB or optimality claim is derived from the heuristic. The optional `DddReservationAssignmentRefiner` composes the existing `DddEanPassengerPrimalEvaluator`, whose public `passenger_candidate_build` injection preserves the exact fixed-K candidate universe. It certifies returned ride counts and can only improve its input plan. The optimizer retains the three distinct movements with the lowest native objectives for optional refinement. This bounded selection can miss a movement with a worse native score but a better optimized assignment.

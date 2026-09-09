# Integrated Fixed-K CP-SAT with integer passengers

Implementation: `integrated_cp_sat_v1`, September 2026. This is a separate optimizer; the existing CP primal oracle remains available and shares the extracted movement builder. Performance findings are recorded separately in `docs/findings/ddd_integrated_cp_sat_gate.md`.

## Supported problem

The solver accepts the canonical `DddFixedKTrajectoryProblem` for one directed ring, fixed starts and exact fleet size, No-Wait, one STOP route per state, deterministic route durations, integer homogeneous OD/release demand and integer cabin capacity. Its objective is Journey Time with the existing finite-service unserved cost. All-Stop is supported through `resolved_trajectory_problem`.

The implementation rejects Waiting, other objectives, inconsistent EAN/DDD movement data, non-ring transitions, ambiguous STOP routes, insufficient visit bounds and boundary-only reduced resources. It does not optimize initial placement, dispatch from a reservoir or impose periodic operation. Multiple future loops of cabin movement are allowed up to the canonical operational horizon. Passenger rides come from the exact supplied structural candidate list; the solver does not add or remove multi-loop passenger rides.

`T` is the passenger service cutoff; `H` is the operational horizon. These happen to coincide at 1,200 seconds in the current Five-Station B reference. All physical times use the existing one-million-ticks-per-second DDD representation. Releases and horizons must already lie on this grid; sub-tick values are rejected rather than shifting the original Arc-Flow cost constant. This does not create a variable or arc per microsecond.

## Formulation and equivalence argument

For each cabin and visit there are event time, active-visit and route-selection variables. A visit is active exactly when its event time is at most H. Exactly one route is selected at an active visit. Its duration determines the next time; inactive continuation leaves time unchanged. The final event must be inactive. A minimum-duration traversal verifies that the supplied visit bound covers even the fastest route sequence.

Each selected resource usage creates the existing protected interval `[event + follower_offset, event + leader_offset + separation_after)`. A usage is present exactly when its entry is at most H. Its protected end is not clipped at H. Fixed boundary occupancies use the same interval convention with the start clipped at zero. `NoOverlap` applies to each configured resource. This represents the current constant and predecessor-behavior headway rules, not a generic pair-dependent matrix or exclusive occupancy of the whole station.

For a canonical candidate q, `y[q]` is an integer between zero and `min(group_count, capacity)`. Its `used` literal is equivalent to `y[q] >= 1`. Positive assignments require STOP at boarding and alighting, boarding after release and zero, ordered boarding/alighting, and both events by T. Boarding uses platform exit, alighting platform entry. Unused candidates impose no temporal restrictions on movement. Demand is partitioned into assigned and unserved quantities.

For each cabin interval v, all `y[q]` with `board(q) <= v < alight(q)` share its capacity. This permits seats to be reused after alighting and passengers to remain aboard through intermediate STOP or SKIP visits.

Let `A[e]` be the total number alighting at event e with time `tau[e]`, and

`F0 = sum_g count[g] * max(0, T - release[g])`.

The integer-tick objective is `F0 + sum_e A[e] * (tau[e] - T)`. This equals the direct served/unserved cost sum because every served candidate obeys release <= boarding <= alighting <= T. Two encodings implement this same expression:

- `product`: one multiplication equality per alighting event.
- `unary`: at most C ordered Boolean levels per event, each with a conditionally activated event-time cost.

The movement recurrence establishes a mapping between route sequences and their unique No-Wait event times. The headway intervals encode the same two-way separation disjunctions as the reference model. The structural y variables then represent exactly the integer ride assignment and capacity constraints for that movement. Conversely, every feasible movement/assignment in the declared domain can populate these CP variables; the derived alighting aggregates and either cost encoding add no restriction. This argument depends on the stated domain checks and the supplied candidate list. It is not a claim about continuous-time variants, other initial placements or passenger paths omitted from that list.

## Validation and identity

`cp_sat_certificate.py` is independent of CP variables. It verifies canonical reference trajectories, restores boundary occupancies from the problem, checks protected intervals in integer ticks, checks every positive ride count, endpoint, release, demand balance and shared capacity, and recomputes the original served/unserved objective. Invalid exported assignments cannot become validated upper bounds or checkpoints.

Historical `problem_fingerprint` values remain unchanged. They do not include all timing, capacity and candidate data. The additional solver-independent `domain_manifest` and `domain_fingerprint` contain the actual movement core, tick timing data, starts, boundaries, demand, capacity and candidates. `model_fingerprint` also identifies the constructed CP model. Native checkpoint imports require the domain fingerprints to match. Legacy timetable imports are independently revalidated and reassigned; they contribute no historical lower bound.

Global search results use `FIXED_K_GLOBAL`. A solve with a fixed movement plan uses `FIXED_MOVEMENT`; its bound is only for that restricted assignment problem. Hints alone do not change the global scope. There are no route exclusions, Hamming constraints, top-N passenger preferences or first-solution stopping rules in the integrated global solver.

Both solver gap limits are zero. A time-limited native floating bound is conservatively converted with downward rounding and the analytic zero floor. Objective expression magnitudes are limited to below 2^53 for exact integer reporting, and OR-Tools model validation also checks integer-expression validity. An `OPTIMAL` result additionally requires independent objective validation and agreement with the native bound to within 1/4 tick, allowing floating error from the solver's internal objective normalization. The integer optimal objective is then the closing bound; this rule never promotes a time-limited result to optimality.

## Files

| File under `src/ropeway_skip_stop_optimization/` | Responsibility |
|---|---|
| `optimization/ddd/cp_sat_movement.py` | Shared movement construction, including legacy bounded-wait support |
| `optimization/ddd/cp_sat_passenger.py` | Complete structural integer assignments, capacity and both cost encodings |
| `optimization/ddd/cp_sat_certificate.py` | Domain checks, independent incumbent validation and atomic checkpoints |
| `optimization/ddd/cp_sat_integrated.py` | Search, hints, fixed-movement diagnostics, bounds and result extraction |
| `benchmarking/ddd_fixed_k_cp_sat.py` | Canonical instance preparation, imports, shared budget and artifact writing |

## CLI

Run from the software repository with its Python environment:

```sh
.venv/bin/python benchmarks/run_ddd_fixed_k_cp_sat.py \
  --example five_station_circle_cw_half_skip_no_wait_headway_b_v0 \
  --cabins 20 --start-policy balanced_reference \
  --time-limit 300 --num-workers 8 --cost-encoding product \
  --output-dir benchmarks/output/ddd_integrated_cp_sat/k20/example_run
```

Use `--build-only` for model statistics without a solve. `--cost-encoding unary` selects the alternative exact encoding. Optional seed sources are mutually exclusive:

- `--primal-seed-result PATH`: complete Arc-Flow result or native CP result/checkpoint.
- `--primal-seed-checkpoint PATH`: existing Root-CG checkpoint.
- `--resume-checkpoint PATH`: native CP checkpoint, validated against the full domain manifest.
- `--fixed-movement-result PATH`: Arc-Flow result or native CP result/checkpoint, with restricted proof scope.

Native `result.json` also exposes the existing Arc-Flow timetable schema at the top level, so the Arc-Flow runner can consume it through `--primal-seed-result`. A native checkpoint is a warm start, not persistence of the search tree. Older no-wait Arc-Flow exports without a `wait_seconds` array are accepted only if their complete times reconstruct a valid no-wait trajectory. This path does not infer unobserved waiting or reuse a source lower bound.

Outputs: `config.json`, `result.json`, `events.jsonl`, `incumbent.json` and, for optimization, `solver.log`. Enable `--log-search-progress` for the detailed native log. Failures produce `error.json`. Checkpoint writes are atomic. Solver callbacks capture assignments and periodically validate/checkpoint them without starting Gurobi; a worse CP candidate cannot replace a better saved external seed. The final result retains the best validated external or native incumbent even if CP reports UNKNOWN. A validated seed contradicting CP infeasibility is treated as an error.

The runner charges preparation, imports and passenger seed evaluation to the total time budget, then gives the remaining time to build/solve. CP-SAT checks its limit cooperatively; solver shutdown, final validation and atomic writes may create a small measured overrun. This is not a hard process-kill deadline. Callback validation is included in solve wall time, not added a second time. `peak_rss_mb` is the process-lifetime high-water mark, not isolated allocation by a single run. Raw solver incumbent/bound events are distinguished from the final independently validated result.

## Tests and remaining experimental work

The new tests compare both encodings with exhaustive route enumeration plus the independent Passenger-IP and complete Arc-Flow on small cases. They exercise release boundaries, service cutoff ticks, shared capacity, seat reuse, overlapping platform passages, bypass overtaking, headway interval contact, resource activity at and after H, unserved demand, hints, fixed scope, checkpoint tampering and fingerprint omissions. Existing CP primal/round, Fixed-K, EAN passenger and Reservoir tests are also run.

A faster K=39 solve or stronger native CP lower bound is an empirical question. Passing these tests and obtaining a compact model does not establish a performance advantage. See the gate findings before launching a larger campaign.

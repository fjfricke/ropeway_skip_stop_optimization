# Benchmarks

This folder contains runnable benchmark entry points. Benchmark outputs are
machine-specific and are written under `benchmarks/output/` by default.

## DDD Phase-0 movement census

Build a read-only structural census for all registered fixed-start examples:

```bash
uv run python benchmarks/run_ddd_phase0_census.py
```

The census builds sparse EAN artifacts, so it counts headway candidates and
the exact complete pair universe without materializing the pair objects. It
also estimates movement-only full-grid sizes for 0.5, 1, and 5 second quanta.
These are structural estimates before reachability pruning, not measured MILP
sizes or eager-EAN build times. JSON and Markdown outputs are written below
`benchmarks/output/ddd_phase0_census/`.

Run the solver-free exhaustive reference oracle on a fixed-start/no-wait
proof fixture and retain all of its feasible supports:

```bash
uv run python benchmarks/run_ddd_phase0_reference.py \
  --case three_station_two_cabin_stop_skip_merge_v0 \
  --enumerate-all
```

The runner converts the sparse network artifact into the solver-independent
DDD movement domain, enumerates exact trajectories, converts the first
feasible result back to `EanMovementPlan`, and runs complete sparse headway
validation. `--enumerate-all` is intended only for genuinely tiny cases.
Waiting, OIP, and dynamic routing fail before enumeration.
Registered fixed-start/no-wait examples remain selectable with `--example`.

Measure the complete whole-horizon trajectory root relaxation on a small,
Passenger-relevant physical case:

```bash
.venv/bin/python benchmarks/run_ddd_trajectory_bound_reference.py \
  --cabins 3 \
  --horizon 250 \
  --objective journey_time
```

This reference explicitly enumerates every local No-Wait trajectory and every
cross-cabin incompatibility pair, then solves both the complete factorized LP
and its integer master. Its LP value is therefore a certified lower bound for
the declared fixed-start/no-wait problem, and the reported LP--MIP gap measures
the intrinsic relaxation strength. Hard trajectory and pair-check limits make
the runner fail instead of silently returning a restricted-pool value. It is a
small-instance research gate for exact pricing, not the scalable algorithm.

Run the exact single-cabin pricing loop without enumerating the trajectory
universe:

```bash
.venv/bin/python benchmarks/run_ddd_trajectory_root_column_generation.py \
  --cabins 3 \
  --horizon 250 \
  --objective journey_time \
  --pricing-time-limit 10 \
  --conflict-row-mode resource_windows_with_pair_fallback
```

The restricted factorized Passenger LP starts from one all-stop trajectory per
cabin. Every round solves an exact no-wait route-and-load pricing MILP per
cabin, adds negative-reduced-cost trajectories, rebuilds all incompatibility
rows for the current pool, and solves the restricted integer master for an
upper bound. The LP is certified only when every pricing solve is optimal and
no negative column remains. Use `--example` for a registered fixed-start,
no-wait network case; a pricing timeout retains completed bounds but cannot
certify root convergence. The optional resource-window mode separates
capacity-one clique rows, passes their dual prices into future-column pricing,
and still rebuilds every incompatibility pair as the exact fallback. The
default `pair_only` reproduces the previous implementation.

The default exact No-Wait pricer uses a time-expanded route path and continuous
Passenger flows on the same path. This removes event-time products and proves
each Five-Station single-cabin pricing problem in roughly half a second in the
current reference run. Reproduce one frozen all-stop-RMP pricing call with:

```bash
.venv/bin/python benchmarks/run_ddd_frozen_trajectory_pricing.py \
  --example five_station_circle_cw_half_skip_no_wait_v0 \
  --cabin-id 0 \
  --pricing-time-limit 2
```

Use `--pricing-formulation legacy_indicators` or `tight_convex_hull` only for
matched formulation ablations. Resource-window pricing remains experimental;
the scalable certified reference uses the default Pair-only master because
hundreds of active windows currently dominate pricing setup.

The research-runner defaults are 30 total rounds, five seconds per cabin
proof-pricing call, one pricing thread, `MIPFocus=2`, one generated column per
cabin and round, default simplex master duals, Pair-only conflicts, and no
diversity pass. The Five-Station reference already solved all 399 pricing calls
exactly with a two-second limit; five seconds is the less brittle general
default. Larger budgets should be used only when the diagnostics report
non-exact pricing, not pre-emptively.

The runner atomically writes a complete checkpoint after every finished round
to `<output-dir>/<case>__<objective>.checkpoint.json`. Continue a run by raising
the total round limit and passing that file back in:

```bash
.venv/bin/python benchmarks/run_ddd_trajectory_root_column_generation.py \
  --example five_station_circle_cw_half_skip_no_wait_v0 \
  --max-iterations 30 \
  --pricing-time-limit 2 \
  --resume-checkpoint benchmarks/output/ddd_trajectory_root_cg/five_station_circle_cw_half_skip_no_wait_v0__journey_time.checkpoint.json
```

`--max-iterations` is the total limit, not the number of additional rounds.
The checkpoint contains the trajectory pool, certified global bounds, best
integer selection, its positive Passenger ride values, complete round history,
and optional resource windows. It
is rejected when its instance, objective, or conflict-row mode differs. Use
`--checkpoint-path` to select another destination or `--no-checkpoint` for
short disposable ablations.

Export a validated root-CG incumbent to the scenario frontend with:

```bash
.venv/bin/python benchmarks/export_ddd_root_cg_frontend.py \
  --example five_station_circle_cw_half_skip_no_wait_v0 \
  --checkpoint benchmarks/output/ddd_trajectory_root_cg/passenger_flow_pair_only_30r/five_station_circle_cw_half_skip_no_wait_v0__journey_time.checkpoint.json
```

New checkpoints already contain the Passenger assignment, so this conversion
does not solve an optimization problem. For a legacy checkpoint without ride
values, the exporter solves the small integer Passenger Assignment on the
already fixed incumbent trajectories exactly once and upgrades the checkpoint.
It writes a separate `ddd_root_cg_journey_time` EAN artifact set and makes that
set the frontend default for the exported variant.

Run the first closed delayed-conflict loop on the physical two-cabin fixture:

```bash
uv run python benchmarks/run_ddd_phase0_conflict_loop.py
```

The optimistic support master deliberately selects the fixture's invalid
Cabin-0-Stop/Cabin-1-Skip combination. Exact lifting detects the exit-switch
headway violation, adds one valid no-good row over the two exact route
prefixes, and re-solves to one of the three feasible supports. The final plan
must pass the complete sparse EAN validator. This runner is an executable
correctness proof for delayed resource rows; it is not a performance solver.

Run the first genuine time-cell refinement and bound-contract proof:

```bash
uv run python benchmarks/run_ddd_phase0_time_refinement.py
```

The initial master combines an exact Stop arrival with an outgoing arc whose
existential witness uses an earlier time in the same coarse cell. Its valid
optimistic bound is zero. The cell lift returns
`EVENT_CELL_INCONSISTENCY`, while cell-free support recovery immediately
produces and validates a full schedule with objective one. Splitting the
shared state cell at the derived boundary raises the master bound to one and
closes `LB = UB = 1` in round two. This is a correctness and bound-contract
fixture, not a runtime or scaling benchmark.

Run the same two-round bound proof on the physical Three-Station movement
network with an anonymous integer-flow master:

```bash
.venv/bin/python benchmarks/run_ddd_phase0_network_time_refinement.py
```

The builder derives reachable visit layers and partial timed arcs from the
network-backed DDD movement problem. The first flow solve has three reachable
nodes, six arcs, and lower bound zero. Cell lifting derives a split at the
physical `R_entry_lr` state while cell-free recovery supplies objective one.
After rebuilding, the second flow solve proves `LB = UB = 1`; the reconstructed
paths pass complete horizon/resource validation and the final two-visit
trajectory passes complete sparse EAN validation. This closes the
physical anonymous-flow Phase-0 gate, but it does not yet combine multiple
cabins with delayed merge-conflict rows.

Run the combined physical multi-cabin refinement gate:

```bash
.venv/bin/python benchmarks/run_ddd_phase0_combined_refinement.py
```

The two-cabin Three-Station fixture first removes two optimistic time-cell
artifacts, then separates two exact resource conflicts. One conflict reaches
visit one, so the final master creates six binary prefix-flow variables for the
two affected cabins while all remaining flow stays anonymous. The four-round
trace closes `LB = UB = 4`, and the final plan passes complete sparse EAN
validation. This proves the combined refinement plumbing; it is not yet a
scaling benchmark.

Measure Gate G9 on larger fixed-start/no-wait examples:

```bash
.venv/bin/python benchmarks/run_ddd_phase0_scaling.py
```

The runner builds the coarse anonymous DDD network, counts the exact additional
prefix variables for a local two-cabin/depth-two activation and for the
fully-labelled limit, counts the pre-resource trajectory universe without
enumerating it, and actually builds the best configured eager EAN reference.
The resulting Gate G9 statement concerns structural model size only. It does
not claim faster solving or assume that every large case needs only local cuts.

Run the first conflict-driven scaling experiment with a live terminal display:

```bash
.venv/bin/python benchmarks/run_ddd_fixed_start_refinement.py
```

The default is the 19-cabin Five-Station ring with Skip, fixed starts, and no
Waiting. The single `tqdm` line reports the active stage and, after every round,
bounds, network/model size, tracked cabins, prefix variables/depth, conflicts,
projected warm-start coverage, transition-cache hits/misses, new/total cuts,
the number and first member of the selected time-split batch, and round time.
The benchmark admits up to 10,000 deterministic,
tolerance-safe time splits per round; use `--max-new-time-splits 1` to replay
the single-split reference strategy. Use `--no-reuse-network-fragments` and
`--no-projected-warm-start` for controlled ablations. Gurobi logging is off in
progress mode so both renderers do not corrupt each other; use the
`--no-progress --gurobi-log` combination for the raw solver log. All
completed-round metrics are written to JSON when the run finishes.

DDD converts physical seconds once at its boundary to canonical integer
microsecond ticks. Time-cell membership, shifted interval intersections,
duration accumulation, split equality, IDs, and fingerprints then use exact
integer arithmetic. Exported metrics and movement plans remain expressed in
seconds. The maximum quantization error of one imported time value is half a
microsecond.

Run one EAN passenger benchmark:

```bash
uv run python benchmarks/run_ean_passenger_benchmark.py \
  --example three_station_v0 \
  --artifact-set ean_passenger_journey_time \
  --ean-solver-policy exact_optimality \
  --time-limit 300 \
  --ean-optimizations all \
  --ean-mip-start optimized_all_stop \
  --sample-interval 5
```

`--ean-mip-start` accepts `none`, `greedy_all_stop`, or
`optimized_all_stop`. The production default fixes the deterministic all-stop
movement plan in a bounded auxiliary solve, optimizes its passenger assignment,
and transfers the complete solution into the integrated model. The greedy
variant remains available as the historical baseline.

`--ean-optimizations` accepts `all`, `none`, or a comma-separated list of
active optimizations:

```text
candidate_horizon_pruning
single_ring_dominated_ride_pruning
slot_time_relaxation_strengthening
tight_big_m_bounds
slot_activation_per_slot
slot_activation_first_slot
board_time_explicit
board_time_projected_journey_time
```

The two slot-activation values are mutually exclusive formulation cases.
`slot_activation_per_slot` is the legacy default. The exact
`slot_activation_first_slot` case removes candidate-level implications that
are implied by unary slot ordering; it may be combined with `all`.

The board-time values are mutually exclusive formulation cases.
`board_time_projected_journey_time` is available only for journey-time
artifacts. It removes selected boarding-time variables through an exact
Fourier--Motzkin projection and may be combined with `all`.

Default output layout:

```text
benchmarks/output/results/<run_id>.json
benchmarks/output/plots/*.svg
benchmarks/output/checkpoints/<run_id>/*.sol
```

Plot existing benchmark JSON files:

```bash
uv run python benchmarks/plot_ean_passenger_benchmarks.py \
  --input-dir benchmarks/output/results \
  --output-dir benchmarks/output/plots
```

The generated SVG set includes separate bars for model nonzeros and
pre-optimize model setup time in addition to rows, variables, candidates, and
solver-progress metrics. Setup time covers Gurobi model creation, variables,
constraints, objective, MIP-start/checkpoint loading, and the final
`model.update()`. It excludes EAN/passenger candidate construction and
`optimize()`, including presolve and branch-and-bound.

Checkpoint resume means Gurobi receives a prior incumbent solution as a MIP
start. It does not resume the previous branch-and-bound tree.

## EAN Bottleneck Diagnosis

Run the four-case Phase-0 diagnosis with the selected production formulation:

```bash
uv run python benchmarks/run_ean_bottleneck_diagnostic.py \
  --examples three_station_v0 five_station_v0 \
  --objective journey_time \
  --ean-solver-policy quick_good_solution \
  --time-limit 300 \
  --ean-optimizations all \
  --sample-interval 5 \
  --root-diagnostics
```

The time limit applies separately to:

```text
integrated
movement_only
fixed_movement_passenger
fixed_movement_passenger_lp
```

The two fixed-movement cases reuse the integrated run's extracted movement
plan and build only the compact direct-ride passenger model. The integer case
is the exact passenger evaluator; the LP case relaxes the same ride-count
variables and reports fractionality and the LP/IP objective gap. If the
integrated run produces no incumbent, both cases are marked unavailable.

With `--root-diagnostics`, the same Gurobi callback additionally samples the
actual MIP root relaxation through `cbGetNodeRel()`. It records fractionality
and linear-objective contributions for typed movement, headway, activation,
passenger-slot, selected-time, and unserved variable families. It does not
parse the solver log or change the mathematical model. Cases solved entirely
in presolve may legitimately contain no root samples.

Before the integrated MIP solve, the diagnostic also solves a separately
labelled continuous relaxation of the same built model, using barrier without
crossover and the configured per-case time limit. This raw LP provides
fractionality when the MIP root does not finish far enough to expose
`MIPNODE` values. It does not contain Gurobi's later MIP cuts and must not be
reported as the post-cut root bound. The additional LP runtime is stored
separately and increases total wall-clock time only when root diagnostics are
enabled.

Each run writes one JSON plus seven base SVG comparisons under
`benchmarks/output/bottleneck_diagnostics/`. The JSON includes scenario and
artifact construction, passenger-candidate construction, movement and
passenger model construction, movement fixing, MIP-start time, presolve,
root-relaxation timing when observed, first-incumbent time, current-memory
peak observed during the case, and normal final solver diagnostics.
When root samples are available, two additional SVGs compare fractional
variable counts by family and lower-bound development over root runtime.

Movement-only has objective zero. Its construction and feasibility behavior
are diagnostic, but its objective bound and gap are not comparable to the
passenger cases.

## DDD Reservoir Fleet Sweep

Run the matched architecture-B, half-demand All-Stop/Skip-Stop fixed-K
campaign with live frontend snapshots:

```bash
.venv/bin/python benchmarks/run_ddd_reservoir_fleet_sweep.py \
  --config benchmarks/configs/five_station_b_no_wait_fleet_sweep.json \
  --progress \
  --frontend-live
```

The canonical event log, checkpoints, and results are written below
`benchmarks/output/ddd_fleet_sweeps/`. The derived live snapshots are mirrored
below `frontend/public/generated/optimization/`; open `/optimization` in the
Vite frontend to inspect them. The All-Stop policy uses the same physical
skip-capable architecture-B network and restricts only the admissible DDD
route options, so its headway assumptions remain matched to Skip-Stop.

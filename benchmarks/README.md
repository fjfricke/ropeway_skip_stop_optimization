# Benchmarks

This folder contains runnable benchmark entry points. Benchmark outputs are
machine-specific and are written under `benchmarks/output/` by default.

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

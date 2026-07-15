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
  --sample-interval 5
```

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

# Benchmarks

This folder contains runnable benchmark entry points. Benchmark outputs are
machine-specific and are written under `benchmarks/output/` by default.

Run one EAN passenger benchmark:

```bash
uv run python benchmarks/run_ean_passenger_benchmark.py \
  --example three_station_v0 \
  --artifact-set ean_passenger_journey_time \
  --ean-solver-policy quick_good_solution \
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
```

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

Checkpoint resume means Gurobi receives a prior incumbent solution as a MIP
start. It does not resume the previous branch-and-bound tree.

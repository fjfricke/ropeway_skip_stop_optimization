# EAN Passenger Benchmarking and Plots

Status: **implemented initial benchmark runner**

## Goal

Create a repeatable benchmark workflow for EAN passenger optimization runs that
captures solver progress through Gurobi callbacks and produces comparison
plots without parsing solver logs.

The benchmark workflow should answer:

```text
Which formulation or solver policy gives better incumbents faster?
Which formulation closes the MIP gap faster?
Which scenarios become too large, and why?
How do objective, bound, gap, nodes, variables, constraints, candidates, and
slots change across model variants?
```

## Non-Goals

- Do not put long benchmarks into normal pytest runs.
- Do not parse Gurobi text logs for core metrics.
- Do not change the mathematical model just to make plotting easier.
- Do not make frontend exports depend on benchmark tooling.
- Do not require a benchmark to finish optimally before writing useful data.

## Proposed Folder Structure

Use a small amount of package-level structure so the benchmark scripts stay
thin and the callback/result/plot logic can be tested. Avoid a large benchmark
framework or deep class hierarchy.

```text
benchmarks/
  README.md
  run_ean_passenger_benchmark.py
  plot_ean_passenger_benchmarks.py
  output/                 # ignored, default local benchmark output
    results/
    plots/
    checkpoints/

src/ropeway_skip_stop_optimization/benchmarking/
  __init__.py
  ean_passenger.py
  plots.py
```

Recommended git policy:

```text
benchmarks/output/             ignored
```

The scripts should be committed. Large or machine-specific output should not be
committed unless explicitly needed for a report.

## Structure and Abstractions

Keep the implementation lightly object-oriented. The useful stable objects are:

```text
BenchmarkRunConfig
BenchmarkRunResult
GurobiMipProgressSample
GurobiMipProgressRecorder
PlotBuilder
```

Do not introduce one class per metric or per chart unless the code genuinely
needs it. Simple functions are fine for loading JSON, writing SVG primitives,
and building small derived tables.

Responsibilities:

```text
benchmarks/run_ean_passenger_benchmark.py
  CLI parsing and thin orchestration.

benchmarks/plot_ean_passenger_benchmarks.py
  CLI parsing for one or more result JSON files and plot output paths.

src/.../benchmarking/ean_passenger.py
  BenchmarkRunConfig, BenchmarkRunResult, result serialization, Gurobi progress
  recorder, and EAN passenger benchmark execution.

src/.../benchmarking/plots.py
  Reusable SVG helpers and plot builders for time series and summary bars.
```

This split keeps long-running benchmark behavior outside tests and frontend
exports while still making the core logic importable and unit-testable.

## Benchmark Inputs

The benchmark runner accepts:

```text
--example
--artifact-set
--ean-solver-policy
--time-limit
--sample-interval
--label
--output-dir
--result-dir
--plot-dir
--checkpoint-dir
--resume-checkpoint
--resume-latest-checkpoint
--export-frontend-artifacts
--frontend-output-root
--clean-frontend-output
--progress / --no-progress
```

Initial target command:

```bash
uv run python benchmarks/run_ean_passenger_benchmark.py \
  --example three_station_v0 \
  --artifact-set ean_passenger_journey_time \
  --ean-solver-policy exact_optimality \
  --output-dir benchmarks/output \
  --sample-interval 5
```

The plot script accepts:

```text
--input
--input-dir
--output-dir
--format
--include
--label-field
```

## Callback Metrics

Use a Gurobi MIP callback instead of log parsing.

Default sampling:

```text
sample_interval_seconds = 5.0
sample_on_new_incumbent = true
sample_final = true
```

Collect samples periodically:

```text
runtime_seconds
node_count
incumbent_objective
best_bound
mip_gap
solution_count
work
```

Sampling rule:

```text
record when runtime - last_sample_runtime >= sample_interval
record immediately when a new incumbent appears
record final diagnostics after optimize()
```

Do not sample every callback invocation. Gurobi callbacks can be frequent, and
excessive Python work can distort benchmark runtime.

Allow `--sample-interval 1` for short debug runs. Treat `--sample-interval 0`
as an explicit debug mode only if needed later; it should not be the default.

## Summary Metrics

Each benchmark run should write one JSON file containing:

```text
run_id
timestamp
git_commit
git_dirty
hostname
python_version
gurobi_version
example_id
family_id
variant_id
artifact_set_id
objective
solver_policy
model_variable_count
model_constraint_count
demand_group_count
ride_candidate_count
slot_variable_count
objective_value_seconds
objective_passenger_hours
best_bound
mip_gap
runtime_seconds
node_count
solution_count
served_passenger_count
unserved_passenger_count
skipped_visit_count
visible_skipped_visit_count
checkpoint_read_path
checkpoint_final_solution_path
progress_samples
```

JSON is the source of truth. CSV can be generated as a convenience format for
spreadsheet inspection.

## Plot Outputs

The plot script should read one or more benchmark JSON files and write SVG
plots.

Initial plots:

```text
gap_over_time.svg
objective_and_bound_over_time.svg
nodes_over_time.svg
runtime_by_run.svg
final_gap_by_run.svg
objective_by_run.svg
model_size_by_run.svg
candidate_size_by_run.svg
```

For gap-over-time:

```text
x-axis: runtime_seconds
y-axis: mip_gap in percent
one line per run
```

For incumbent/bound-over-time:

```text
x-axis: runtime_seconds
y-axis: passenger hours or passenger seconds
lines: incumbent objective and best bound
```

For model-size plots:

```text
bars: variables, constraints, ride candidates, slots
grouped by run label
```

## Dependency Choice

Prefer no heavy plotting dependency for the first implementation:

```text
write simple SVG directly from Python standard library
```

This keeps the benchmark workflow runnable in the current `uv` environment
without adding matplotlib/pandas. If plots become too complex, add optional dev
dependencies later:

```text
matplotlib
pandas
```

## Integration With Existing Export Code

The normal frontend export path should stay unchanged.

The benchmark runner can call the existing export pipeline but must enable an
optional progress recorder in the EAN passenger optimizer. This keeps the
regular CLI simple and keeps benchmark-specific callback sampling out of normal
exports.

Likely implementation files:

```text
src/ropeway_skip_stop_optimization/optimization/ean/optimizers/passenger_service.py
src/ropeway_skip_stop_optimization/benchmarking/ean_passenger.py
src/ropeway_skip_stop_optimization/benchmarking/plots.py
benchmarks/run_ean_passenger_benchmark.py
benchmarks/plot_ean_passenger_benchmarks.py
benchmarks/README.md
```

The optimizer config should accept an optional recorder:

```python
progress_recorder: GurobiMipProgressRecorder | None = None
progress_sample_interval_seconds: float = 5.0
```

When no recorder is provided, there should be no callback overhead and no
benchmark output.

## Checkpoints

Benchmark runs should support the checkpoint options already planned for the
CLI:

```text
checkpoint_dir
resume_latest_checkpoint
resume_checkpoint_path
```

Clarify terminology in benchmark output:

```text
checkpoint resume = incumbent MIP-start resume
not a persisted branch-and-bound-tree resume
```

This matters when interpreting plots. A resumed run may start with a strong
incumbent, but its best-bound progress starts from a newly built solve.

## Benchmark Protocol

For each formulation-preserving optimization:

1. Run current baseline with the same example, artifact set, solver policy, and
   time limit.
2. Run the modified formulation.
3. Compare JSON summaries and plots.
4. Keep both result files until the decision is documented.

Minimum comparison table:

```text
run label
variables
constraints
ride candidates
slots
first incumbent time
first incumbent objective
root relaxation bound
time to 10% gap
time to 5% gap
time to 1% gap
final objective
final bound
final gap
runtime
nodes
visible skips
served / unserved
```

## First Benchmark Set

Start with three runs:

```text
three_station_v0 + ean_passenger_journey_time + quick_good_solution
three_station_v0 + ean_passenger_journey_time + paper_benchmark
three_station_v0 + ean_passenger_journey_time + exact_optimality
```

Then repeat after the next formulation experiment:

```text
stop/skip timing indicators
```

## Defaults

Benchmark outputs default to:

```text
results:     benchmarks/output/results
plots:       benchmarks/output/plots
checkpoints: benchmarks/output/checkpoints/<run_id>
```

The benchmark runner generates plots for the current JSON result immediately.
The separate plot command compares one or more existing JSON files.

Frontend artifacts are not exported by default. They are written only when
`--export-frontend-artifacts` is set, with `--frontend-output-root` defaulting
to the normal frontend generated artifact directory.

# Ropeway Skip-Stop Optimization

Tools and experiments for modeling ropeway systems, mapping them into
optimization representations, benchmarking solver formulations, and visualizing
scenarios, optimization results, and replays.

The project is currently focused on small reproducible ropeway examples,
legacy discrete-time replay/MILP work, and a continuous-time EAN optimization
path with passenger-service objectives.

## Thesis headways

Current thesis scenarios use geometric entry/exit and platform headways only.
There are no mechanical-cycle or fault-response constraints in this path.
`HeadwayPhysicalParameters` contains geometry; historical fault inputs belong
only to the existing legacy mechanism classes. `HeadwayDesign.schema_version`
is now 2. Import saved headway configurations with
`exports.json_codec.decode_headway_design`: v1 fault values are moved explicitly,
and unused historical values are reported with a warning rather than silently dropped.
Old result files remain unchanged. Rebuild prepared legacy models; revalidate
primal certificates before reuse and do not transfer their solver bounds.

Implementation and checks: [headway cleanup](docs/plans/geometric_headway_cleanup_20260918.md)
and [build measurements](docs/findings/geometric_headway_cleanup_20260918.md).

## What Is Implemented

- Physical scenario models for stations, nodes, track segments, station routes, cabins, demand, and operating parameters.
- Discretization into graph-like nodes, movement arcs, wait arcs, and typed constraints.
- A greedy all-stop cabin circulation baseline.
- Passenger replay with fixed demand arrivals and greedy boarding into compatible cabins.
- Replay metrics for arrivals, boardings, alightings, in-transit passengers, waiting queues, and cumulative waiting time.
- Discrete-time MILP feasibility and passenger waiting-time prototypes for Gurobi.
- EAN build artifacts, skip-stop feasibility optimization, passenger waiting-time and journey-time optimization, checkpointable Gurobi runs, and physical EAN replay exports.
- Benchmark tooling for comparing EAN optimization toggles, solver policies, progress metrics, incumbent checkpoints, and generated plots.
- A local React/Vite viewer for scenario line/physical views, discrete graph and slack views, replay metrics, EAN diagnostics, cabin/passenger replay, and figure/video export.

## Not Yet Implemented

- Production-scale calibration and validation on larger real-world instances.
- A polished public API around solver experiment presets.
- Long-running benchmark automation beyond local scripts.

Project decisions and supervision-oriented daily progress are recorded in
`docs/progress/development_log.md`.

## Example Scenario

`build_three_station_scenario()` creates a ring-like `L <-> M <-> R` ropeway:

- `L` and `R` are terminal stations with turnaround service paths.
- `M` is a middle service station with service and skip routes in both directions.
- Cabins in the baseline never use skip routes; they follow the all-stop cycle.
- Passengers board at the last platform node of a service stop and alight at the first platform node.
- Brake, accelerate, approach, and depart sections are modeled as connector segments, not platform/station segments.
- The bundled demand scenario is intentionally near capacity: 3,480 passengers, split evenly across all six OD pairs (`L->M`, `L->R`, `M->L`, `M->R`, `R->L`, `R->M`) at 08:00.

Generated frontend artifacts are written to:

```text
frontend/public/generated/examples/
```

That directory is intentionally ignored by git. After a fresh clone, run the
export command below before starting the viewer.

## Setup

Requires Python 3.12, `uv`, and Node.js/npm for the frontend.

```bash
uv sync
cd frontend
npm install
```

## Generate Frontend Artifacts

From the repo root, generate the default greedy replay artifacts:

```bash
uv run python -m ropeway_skip_stop_optimization.exports.cli \
  --example three_station_v0 \
  --artifact-set greedy_all_stop \
  --output-root frontend/public/generated/examples \
  --clean
```

This writes the physical scenario, discrete scenario, movement plan, passenger
replay, replay metrics, and `manifest.json` used by the frontend.

To generate EAN passenger optimization artifacts for the viewer:

```bash
uv run python -m ropeway_skip_stop_optimization.exports.cli \
  --example three_station_v0 \
  --artifact-set ean_passenger_journey_time \
  --ean-solver-policy quick_good_solution \
  --output-root frontend/public/generated/examples \
  --progress \
  --clean
```

Useful EAN export options:

```text
--ean-artifact-construction legacy_ring|network
--ean-solver-policy default|debug_short|quick_good_solution|paper_benchmark|exact_optimality
--ean-time-limit <seconds>
--ean-build-only
--ean-optimizations all|none|<comma-separated selections>
--ean-checkpoint-dir <path>
--ean-resume-checkpoint <file.sol-or-file.mst>
--ean-resume-latest-checkpoint
```

`network` is the only supported artifact-construction path.

`--ean-build-only` constructs the selected EAN artifact and complete Gurobi
model, writes `ean_model_build_profile.json`, and exits without calling
`optimize()`. Combine it with `--progress` to see artifact pairing, headway-row
construction, model sizes, elapsed time, and peak RSS while the model is built.
The default `auto` MIP start is disabled in this mode; an explicit
`optimized_all_stop` start is rejected because it would launch an auxiliary
solve.

The four standard construction baselines can be reproduced with:

```text
.venv/bin/python benchmarks/run_ean_build_baselines.py all --progress
```

The single `--ean-optimizations` list accepts independently combinable
optimizations and at most one value from each formulation category:

| Kind | Selections |
|---|---|
| Independent optimizations | `candidate_horizon_pruning`, `single_ring_dominated_ride_pruning`, `slot_time_relaxation_strengthening`, `tight_big_m_bounds`, `fixed_start_headway_precedence` |
| Horizon formulation | `horizon_legacy`, `horizon_conservative_free_suffix`, `horizon_exact_time_activation` |
| Time-bound formulation | `time_bounds_legacy_plus_10`, `time_bounds_derived_visit_bounds` |
| Stop/skip timing formulation | `stop_skip_timing_big_m`, `stop_skip_timing_affine` |
| Unary-slot activation formulation | `slot_activation_per_slot`, `slot_activation_first_slot` |
| Journey board-time formulation | `board_time_explicit`, `board_time_projected_journey_time` |

`fixed_start_headway_precedence` is an opt-in exact reduction for fixed-start
artifacts. It uses conservative propagated visit bounds to replace provably
directed headway disjunctions by one directed row without an order binary. It
does not impose a global cabin order. Optimized initial placement is not yet
supported because its proof requires bounds over selectable boundary states.

`all` means the current production configuration: the three independent
reductions, affine stop/skip timing, and first-slot activation. For the
journey-time objective it also resolves to projected boarding time; for
waiting time it resolves to explicit boarding time. `none` disables only the
independent reductions and keeps these formulation defaults.
`all` may be combined with formulation overrides such as
`all,stop_skip_timing_big_m`. In an explicit list without `all`, omitted
optimizations are disabled and omitted formulation categories use the current
defaults.

The horizon cases have different finite-horizon meanings:

- `horizon_legacy` gives every generated safety visit normal route and headway
  decisions.
- `horizon_conservative_free_suffix` retains every visit that could start by
  the operational horizon under conservative earliest times. The retained
  suffix remains fully constrained even when its realized events occur later.
- `horizon_exact_time_activation` activates visits and checkpoint entries from
  their optimized times. A visit entering by the closed operational horizon is
  completed, including resource occupancy that clears after the horizon; later
  visits receive no route decision.

The legacy time bound uses the longest no-wait chain plus ten seconds as one
global bound. Derived visit bounds propagate per-visit lower and upper bounds
and use an explicit station maximum wait when configured, otherwise one
operational horizon as a finite terminal waiting cap.

The Big-M timing case uses four conditional service/skip inequalities per
visit. The affine case replaces them, for every active visit, with:

```text
exit = switch + skip_duration
       + (service_duration - skip_duration) * stop
       + wait
```

Under exact horizon activation, the affine equality is enabled by the visit
activation binary. `stop_skip_timing_affine` is the production default.
`stop_skip_timing_big_m` remains selectable as the historical formulation
comparator.

The legacy unary-slot case repeats candidate stop, release, and service-cutoff
implications for every interchangeable passenger slot. The exact
`slot_activation_first_slot` case attaches them only to the first slot. Unary
ordering makes every later slot no larger than the first, so the omitted rows
are implied even in the LP relaxation. The compact case also removes
the zero-release implication and, when slot-time strengthening is enabled,
selected-time lower bounds that are algebraically redundant. First-slot
activation is the production default for passenger solves; per-slot activation
remains selectable as the historical comparator.

For journey time, `board_time_projected_journey_time` eliminates each selected
boarding-time variable through the exact Fourier--Motzkin projection of its
linearization, release, and minimum-trip-time constraints. It preserves the
integer model and LP relaxation, but cannot be selected for waiting time because
selected boarding time appears directly in that objective. A dedicated
five-minute comparison reduced model size and setup time but slightly worsened
the time-limited incumbent and proof bound in isolation. The combined
Journey-Time configuration promoted the exact projection, affine timing, and
first-slot activation together; Waiting-Time continues to use the explicit
formulation by default.

Checkpoint resume loads a prior incumbent solution as a Gurobi MIP start. It
does not resume the previous branch-and-bound tree.

The frontend loads only:

```text
/generated/examples/manifest.json
```

All concrete JSON artifact paths come from that manifest.

## Run Tests

```bash
uv run pytest
```

## Run The Viewer

```bash
cd frontend
npm run dev
```

Then open the printed local Vite URL, typically:

```text
http://127.0.0.1:5173/
```

Useful frontend checks:

```bash
cd frontend
npm run build
```

The viewer supports:

- Scenario line and physical views with layer toggles.
- Discrete optimization graph, slack, metrics, and replay views when those artifacts are present.
- EAN diagnostics, passenger metrics, and continuous physical replay when EAN artifacts are present.
- Scenario SVG export and EAN replay frame/video export. Figure sizing supports A4 width, A4 height, and report text width (`147 mm`).

Video exports are silent; they contain a video track only.

## Run Benchmarks

Benchmark outputs are machine-specific and ignored under `benchmarks/output/`.

```bash
uv run python benchmarks/run_ean_passenger_benchmark.py \
  --example three_station_v0 \
  --artifact-set ean_passenger_journey_time \
  --ean-solver-policy exact_optimality \
  --time-limit 300 \
  --ean-optimizations all \
  --sample-interval 5 \
  --progress
```

The benchmark runner writes JSON results, SVG plots, and optional checkpoints.
See `benchmarks/README.md` for plotting existing results and checkpoint layout.

## Current thesis experiments

The [thesis experiment README](docs/experiments/README.md) defines the current
20 Journey calibrations and 104 Journey comparisons, alongside the completed
OIP mixture series under the geometric short-horizon contract. It documents
settings, reference gates, CLI commands and live views.
Use that document to prepare new thesis runs.

### Earlier experiment pipeline

The following examples describe earlier exploratory workflows. They do not
launch the current Journey matrix.

The T5R/T6R experiment pipeline keeps topology, geometry, demand and solver
configuration explicit. A single supervised run is started with, for example:

```bash
uv run python benchmarks/run_thesis_experiment.py \
  --topology t5r --geometry g800 \
  --demand-family f2 --demand-profile p0 \
  --objective unserved --demand 2000 \
  --method line_planning --formulation shared_rides --catalog relevant \
  --max-cabins 84 \
  --time-limit 300 --workers 12 --memory-limit-gib 32 \
  --output-dir results/thesis_example
```

Methods are `all_stop_phase`, `line_planning`, and `labelled_arc_flow`.
`all_stop_phase --capacity-search` brackets and bisects nested demand without
treating a timeout as infeasibility. Labelled Arc-Flow accepts
`--operating-mode all_stop|skip_stop` for comparisons with identical fixed
starts. Every run stores the case and problem fingerprints, source hashes,
events, native bounds, independently validated certificates, and process-tree
resource measurements.

The bounded calibration driver is:

```bash
uv run python benchmarks/run_thesis_calibration.py \
  --output-dir results/thesis_calibration_YYYYMMDD_vN \
  --wall-limit-seconds 7200 --workers 12 --memory-limit-gib 32
```

It runs one solver process at a time and never starts the later full thesis
campaign automatically. The new cases derive `K_AS` and a separate reservoir
port-throughput upper bound from each geometry; the historical Max50 cap is not
reused. The first completed calibration and its open questions are documented
in `docs/findings/thesis_calibration_results_20260914.md`.

## Common Workflow

From a clean checkout:

```bash
uv sync
cd frontend
npm install
cd ..
uv run python -m ropeway_skip_stop_optimization.exports.cli \
  --example three_station_v0 \
  --artifact-set greedy_all_stop \
  --output-root frontend/public/generated/examples \
  --clean
cd frontend
npm run dev
```

## Project Structure

```text
src/ropeway_skip_stop_optimization/
  models/          domain, discrete, plan, and replay dataclasses
  mapping/         mappings from physical scenarios to derived representations
  examples/        built-in reproducible scenarios
  exports/         artifact builders, manifest generation, and export CLI
  baselines/       simple all-stop circulation baseline
  optimization/
    discrete_time/ legacy discrete-time MILP models
    ean/           continuous-time EAN models and builders
  replay/          demand and passenger replay logic
  validation/      scenario validation rules

frontend/
  src/             React/Vite scenario viewer
  public/generated ignored generated JSON artifacts

benchmarks/        benchmark entry points and ignored local outputs
docs/findings/     dated empirical and structural observations
docs/plans/        future work and research roadmaps
docs/reference/    concise documentation of the current implementation
tests/             Python regression tests
```

# Ropeway Skip-Stop Optimization

Tools and experiments for modeling ropeway systems, mapping them into
optimization representations, benchmarking solver formulations, and visualizing
scenarios, optimization results, and replays.

The project is currently focused on small reproducible ropeway examples,
legacy discrete-time replay/MILP work, and a continuous-time EAN optimization
path with passenger-service objectives.

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
--ean-solver-policy default|debug_short|quick_good_solution|paper_benchmark|exact_optimality
--ean-optimizations all|none|candidate_horizon_pruning,single_ring_dominated_ride_pruning,slot_time_relaxation_strengthening,tight_big_m_bounds
--ean-checkpoint-dir <path>
--ean-resume-checkpoint <file.sol-or-file.mst>
--ean-resume-latest-checkpoint
```

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

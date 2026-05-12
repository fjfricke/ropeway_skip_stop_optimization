# Ropeway Skip-Stop Optimization

Tools and experiments for modeling ropeway systems, mapping them into optimization representations, and visualizing scenarios and replays.

The project is currently focused on a compact three-station example, legacy discrete-time replay/MILP work, and a newer continuous-time EAN optimization path.

## What Is Implemented

- Physical scenario models for stations, nodes, track segments, station routes, cabins, demand, and operating parameters.
- Discretization into graph-like nodes, movement arcs, wait arcs, and typed constraints.
- A greedy all-stop cabin circulation baseline.
- Passenger replay with fixed demand arrivals and greedy boarding into compatible cabins.
- Replay metrics for arrivals, boardings, alightings, in-transit passengers, waiting queues, and cumulative waiting time.
- Discrete-time MILP feasibility and passenger waiting-time prototypes for Gurobi.
- EAN dataclasses and builder components for the next continuous-time solver.
- A local React/Vite viewer for the physical scenario, discrete graph, slack view, replay metrics, and cabin/passenger replay.

## Not Yet Implemented

- A complete continuous-time EAN solver.
- Projection of optimized EAN solutions back to physical replay.
- Frontend selection between multiple examples and artifact sets.

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

From the repo root:

```bash
uv run python -m ropeway_skip_stop_optimization.exports.cli \
  --artifact-set greedy_all_stop \
  --output-root frontend/public/generated/examples \
  --clean
```

This writes the physical scenario, discrete scenario, movement plan, passenger
replay, replay metrics, and `manifest.json` used by the frontend.

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

## Common Workflow

From a clean checkout:

```bash
uv sync
cd frontend
npm install
cd ..
uv run python -m ropeway_skip_stop_optimization.exports.cli \
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

docs/plans/        design notes and implementation plans
tests/             Python regression tests
```

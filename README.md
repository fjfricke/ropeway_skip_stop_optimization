# Ropeway Skip-Stop Optimization

Tools and experiments for modeling ropeway systems, discretizing them for optimization, and visualizing scenarios and replays.

The project is currently focused on a compact three-station example and a reusable modeling base for later MILP/Gurobi work.

## What Is Implemented

- Physical scenario models for stations, nodes, track segments, station routes, cabins, demand, and operating parameters.
- Discretization into graph-like nodes, movement arcs, wait arcs, and typed constraints.
- A greedy all-stop cabin circulation baseline.
- Passenger replay with fixed demand arrivals and greedy boarding into compatible cabins.
- A local React/Vite viewer for the physical scenario, discrete graph, slack view, and cabin/passenger replay.

## Example Scenario

`build_three_station_scenario()` creates a ring-like `L <-> M <-> R` ropeway:

- `L` and `R` are terminal stations with turnaround service paths.
- `M` is a middle service station with service and skip routes in both directions.
- Cabins in the baseline never use skip routes; they follow the all-stop cycle.
- Passengers board at the last platform node of a service stop and alight at the first platform node.
- Brake, accelerate, approach, and depart sections are modeled as connector segments, not platform/station segments.
- The bundled demand scenario is intentionally near capacity: 3,480 passengers, split evenly across all six OD pairs (`L->M`, `L->R`, `M->L`, `M->R`, `R->L`, `R->M`) at 08:00.

Static exports for this example live in:

```text
frontend/public/scenarios/
```

## Setup

Requires Python 3.12, `uv`, and Node.js/npm for the frontend.

```bash
uv sync
cd frontend
npm install
```

## Generate Scenario JSON

From the repo root:

```bash
uv run python -m ropeway_skip_stop_optimization.export_scenarios --output-dir frontend/public/scenarios
```

This writes the physical scenario, discrete scenario, movement plan, and passenger replay JSON used by the frontend.

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

## Project Structure

```text
src/ropeway_skip_stop_optimization/
  models/          domain, discrete, plan, and replay dataclasses
  preprocessing/   scenario discretization
  baselines/       simple all-stop circulation baseline
  replay/          demand and passenger replay logic
  validation/      scenario validation rules
  examples.py      built-in three-station scenario
  export_scenarios.py

frontend/
  src/             React/Vite scenario viewer
  public/scenarios static JSON exports

docs/plans/        design notes and implementation plans
tests/             Python regression tests
```

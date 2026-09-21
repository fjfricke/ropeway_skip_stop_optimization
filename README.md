# Ropeway skip-stop optimization

> AI-generated documentation.

Python models and solvers for ropeways with optional station stops, passenger
assignment and resource constraints. A web viewer displays systems and timetables.

**Thesis reviewers: start with the [reviewer guide](docs/REVIEWER_GUIDE.md)**
for the reported experiments, selected results and relevant model code.

## Install

Use Python 3.12+, [uv](https://docs.astral.sh/uv/), and Node.js 22.12+ with npm
for the viewer. Dependencies are pinned in `uv.lock` and `frontend/package-lock.json`.

```sh
uv sync --frozen
```

Gurobi requires a license for optimization. CP-SAT, the baseline export below
and viewing saved results do not require a commercial solver license.

## Try an existing system

Export an all-stop timetable, then start the viewer:

```sh
uv run ropeway-skip-stop-optimization \
  --example five_station_circle_cw_half_skip_no_wait_v0 \
  --artifact-set ean_all_stop_baseline
cd frontend
npm ci
npm run dev -- --port 5174 --strictPort
```

Open **http://127.0.0.1:5174/** and select the example and artifact set.
This creates a deterministic baseline; it does not optimize passenger service.

## Define and optimize your own system

Systems are defined in Python under `src/ropeway_skip_stop_optimization/examples/`
and registered in `examples/registry.py`. Define geometry, speeds, demand and
operating rules there; select the fleet and solver through the relevant runner.
The frontend is a viewer, not a system editor.

[Usage guide](docs/USAGE.md): available examples, a new ring-system template,
configuration locations and runnable optimization commands.

| Task | Entry point |
|---|---|
| Fixed starts: optimize STOP/SKIP and passengers with Gurobi | `benchmarks/run_ddd_fixed_k_arc_flow.py` |
| Free initial positions: optimize movement and passengers with CP-SAT | `benchmarks/run_oip.py` |
| Repeat the reported studies | [Experiment guide](docs/experiments/README.md) |

## View the submitted results

Extract the separate raw-data ZIP here, preserving `results/`. The tracked
manifest alone does not contain the raw data. From the repository root:

```sh
python3 benchmarks/verify_submission.py
uv run python benchmarks/thesis_publication.py \
  --submission-manifest results/submission_manifest.json
```

With the viewer running, open **http://127.0.0.1:5174/thesis**. Export checks
file hashes and rebuilds the result views without optimization. The raw package
is about 20 GiB uncompressed; allow extra space and several minutes for export.

## Further reading

- [Submission checks](docs/results/submission_check_20260921.md): validation and known historical warning.
- [Benchmark index](benchmarks/README.md): current runners and historical experiments.
- Code: `src/ropeway_skip_stop_optimization/`; tests: `tests/`; viewer: `frontend/`.
- Checks: `uv run pytest`; in `frontend/`, `npm test` and `npm run build`.

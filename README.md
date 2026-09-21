# Ropeway skip-stop optimization

Code and experiment tools for the IDP thesis on skip-stop urban ropeways.
The reported studies compare journey time with fixed cabin starts (labelled
arc-flow, Gurobi) and passengers served with fixed stopping patterns and free
initial positions (event-based model, OR-Tools CP-SAT).

## Install

Use Python 3.12 or newer, [uv](https://docs.astral.sh/uv/), and Node.js 22.12+
with npm. Dependencies are pinned in `uv.lock` and `frontend/package-lock.json`.

```sh
uv sync --frozen
```

Gurobi needs a license to solve its models. Reading and exporting saved results
does not require a solver license. CP-SAT requires no commercial license.

## View the submitted results

Extract the separate raw-data ZIP **into this directory**. Check that
`results/submission_manifest.json` exists; do not nest another `results/` folder.

```sh
uv run python benchmarks/thesis_publication.py \
  --submission-manifest results/submission_manifest.json
cd frontend
npm ci
npm run dev -- --port 5174 --strictPort
```

Open **http://127.0.0.1:5174/thesis** for the reported results, solver progress,
references and available timetable replays. The export checks the raw files and
builds viewer data without solving. It takes several minutes and additional disk
space. Missing files or changed checksums stop the export.

## Reproduce

[Experiment guide](docs/experiments/README.md): result sources, new solver runs,
and regenerating thesis tables and figures. New runs use new output directories;
parallel search and wall-clock limits may produce different incumbents.

Verify the raw package without installing dependencies:

```sh
python3 benchmarks/verify_submission.py
```

## Repository map

| Directory | Contents |
|---|---|
| `src/ropeway_skip_stop_optimization/` | Domains, solvers, validation and exports |
| `benchmarks/` | Experiment and publication runners |
| `frontend/` | Result browser and timetable replay |
| `tests/` | Model, validation and export tests |
| `results/` | Separate raw-data package; large outputs are not tracked |
| `docs/experiments/` | Reproduction instructions and historical context |

The current thesis is in the neighbouring `../idp_report/version_2/` directory.
Earlier solver investigations remain available; start with
[experiment history](docs/experiments/HISTORY.md) and [benchmark tools](benchmarks/README.md).

Checks: `uv run pytest`; in `frontend/`, `npm test` and `npm run build`.

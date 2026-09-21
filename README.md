# Ropeway skip-stop optimization

> AI-generated documentation.

Code and raw-result tools for an IDP thesis on skip-stop urban ropeways.
Two studies examine journey-time minimization and passenger-service maximization
on a five-station ring with synthetic demand.

**Reviewing the thesis? Start with the [reviewer guide](docs/REVIEWER_GUIDE.md).**
It identifies the reported experiments, selected results, model code and limitations.

## View the submitted results

Requirements: Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js 22.12+ and npm.
Run from this repository root. Extract the separate raw-data ZIP here so its
campaigns are under `results/` (no second nested `results/` directory).
The tracked manifest alone does not contain the raw data.

```sh
uv sync --frozen
uv run python benchmarks/thesis_publication.py \
  --submission-manifest results/submission_manifest.json
cd frontend
npm ci
npm run dev -- --port 5174 --strictPort
```

Open **http://127.0.0.1:5174/thesis**. The viewer shows results, solver progress
and available timetable replays. Export verifies file hashes and rebuilds viewer
data without optimization or a solver license. The raw package is about 20 GiB
uncompressed; allow additional space and several minutes for export.

To check the raw package only, without installing dependencies:

```sh
python3 benchmarks/verify_submission.py
```

## Reproduce or inspect the code

- [Experiment guide](docs/experiments/README.md): regenerate tables/figures or start **new** solver runs.
- [Submission checks](docs/results/submission_check_20260921.md): validation and the excluded historical replay warning.
- [Benchmark entry points](benchmarks/README.md): current runners and historical tools.

Gurobi optimization requires a separate license; CP-SAT has no commercial
license requirement. Saved results can be inspected without either solver running.
Dependencies are pinned in `uv.lock` and `frontend/package-lock.json`.

| Directory | Contents |
|---|---|
| `src/ropeway_skip_stop_optimization/` | Models, solvers, validation and exporters |
| `benchmarks/` | Experiment and publication runners |
| `frontend/` | Result browser and timetable replay |
| `tests/` | Model and tooling tests |
| `results/` | Raw-data ZIP destination and tracked submission inventory |
| `docs/`, `archive/` | Current instructions and earlier research material |

The thesis sources are a separate repository, `../idp_report/version_2/` in the
original layout. They are needed to regenerate thesis figures, not to use the viewer.

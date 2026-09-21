# Reproduce the thesis experiments

Run the commands from the optimization repository root. Install with
`uv sync --frozen`; the viewer also needs Node.js 22.12+ and `npm ci` in `frontend/`.
Gurobi requires a license for optimization, not for inspecting saved data.

## Submitted data

Extract the raw-data ZIP into the repository root, preserving `results/`.
`results/submission_manifest.json` fixes the reported selection and file hashes.

| Study / evidence | Directory under `results/` |
|---|---|
| Journey originals | `thesis_journey_geometric_20260919` |
| Journey: 22 MIP-start replacements | `thesis_journey_all_stop_mip_start_20260920` |
| Service K62 | `oip_fixed_mixes_geometric_120_20260918` |
| Service K50 | `oip_fixed_mixes_geometric_k50_20260919` |
| Regular all-stop capacity calibration | `oip_exact_phase_short_k62_20260918` |
| Regular all-stop K50 references | `oip_k50_phase_references_20260919` |

The reported Journey selection has 64 comparisons; 22 use the replacement
campaign. Earlier attempts remain available separately. Service includes all
30 mixtures, including runs without an incumbent. Code family F0 is thesis F1.
All use T5R/G500, geometric headways and No-Wait. Input files and manifests
contain the exact time grids, stopping patterns, demands and solver settings.
Service permits later destination STOPs in the same cabin before the deadline;
Journey uses the first destination visit. The four additional service-contract
checks are included in the ZIP. A timeout without a solution is not infeasibility.

## Inspect, without optimization

```sh
python3 benchmarks/verify_submission.py
uv run python benchmarks/thesis_publication.py \
  --submission-manifest results/submission_manifest.json
cd frontend
npm ci
npm run dev -- --port 5174 --strictPort
```

Open http://127.0.0.1:5174/thesis. Export regenerates all submission views from
raw data; old viewer files cannot substitute for missing evidence. The reported
Journey view combines the selected attempts. Historical executions stay separate.
No optimization is performed. Allow several minutes and space for derived data.

## Regenerate thesis tables and figures

Run `uv sync --frozen --extra analysis`. Then follow the short command block in
[the report README](../../../idp_report/version_2/README.md). Keep the report and
optimization directories beside each other. `make pdf` additionally needs the
LaTeX tools listed by the report Makefile. Source hashes are retained in CSVs;
PDF timestamps and absolute provenance paths are not numerical results.

## Run new experiments

Use new output directories. Do not resume a historical submission campaign.
The second invocation below resumes **your newly prepared** campaign only.
Saved configurations record solver versions and source identities; historical
source hashes remain provenance and are not rewritten. Parallel solves and
wall-clock limits do not guarantee identical incumbents or runtimes.

Journey (Gurobi; calibrations followed by comparisons):

```sh
uv run python benchmarks/run_thesis_revised_journey_campaign.py --output-dir results/my_journey --build-only
uv run python benchmarks/run_thesis_revised_journey_campaign.py --output-dir results/my_journey --resume --run
uv run python benchmarks/run_journey_mip_start_campaign.py --source results/my_journey --output-dir results/my_journey_starts --build-only
uv run python benchmarks/run_journey_mip_start_campaign.py --output-dir results/my_journey_starts --resume --run
```

The follow-up selects unresolved comparisons from the new execution, so its
number of cases can differ from the submitted 22. It may have nothing to repeat.
Journey jobs allow 1,800 s including preparation, 12 workers and 32 GiB RSS.

Service (CP-SAT mixtures; Gurobi regular references):

```sh
uv run python benchmarks/run_oip_fixed_mix_campaign.py --output results/my_oip_k62 --calibration results/oip_exact_phase_short_k62_20260918/references.json --build-only
uv run python benchmarks/run_oip_fixed_mix_campaign.py --output results/my_oip_k62 --calibration results/oip_exact_phase_short_k62_20260918/references.json --resume
uv run python benchmarks/run_oip_fixed_mix_campaign.py --fixed-k 50 --comparison-campaign results/my_oip_k62 --output results/my_oip_k50 --build-only
uv run python benchmarks/run_oip_fixed_mix_campaign.py --fixed-k 50 --comparison-campaign results/my_oip_k62 --output results/my_oip_k50 --resume
uv run python benchmarks/run_oip_k50_phase_references.py --source-campaign results/my_oip_k50 --output results/my_k50_references --build-only
uv run python benchmarks/run_oip_k50_phase_references.py --source-campaign results/my_oip_k50 --output results/my_k50_references --run --resume
```

Service budgets are 300 s per comparison/reference, 12 workers, 32 GiB RSS.
K50 uses the same absolute loads as K62. Regular all-stop references optimize
only the common phase, not individual cabin positions. Original K62 mixtures
can stop when their bound cannot beat the reference; the recorded F1 pure
skip-stop follow-up disabled this cutoff. Repeat it with
`benchmarks/repeat_oip_without_reference_cutoff.py --campaign results/my_oip_k62 --trial f0_mix_0_31_31_k62`
if its selected attempt ended with `cannot_beat_reference`.

To repeat the calibration itself, use `benchmarks/run_oip_phase_calibration.py
--output results/my_calibration --build-only`, then the same command with
`--resume` instead of `--build-only`. Use its completed `references.json` via
`--calibration` in both K62 and K50 preparation/resume commands.

Submission checks and the documented superseded replay warning:
[submission check](../results/submission_check_20260921.md).

Earlier proposals and exploratory runs: [HISTORY.md](HISTORY.md).

## Package the raw data (maintainer)

After freezing the code and checking the results, run
`python3 benchmarks/prepare_submission.py` to refresh the inventory.
Create the ZIP from the repository root with
`zip -@ ../ropeway-results.zip < results/submission_files.txt`.
This includes only the selected raw campaigns and their package metadata.
To refresh replay evidence after a new audit, pass
`--replay-audit frontend/public/generated/study/replay-audit.json` to the preparation script.

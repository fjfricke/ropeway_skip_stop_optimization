# Thesis result data

Extract the ZIP into `ropeway_skip_stop_optimization/`.
The manifest must then be at `results/submission_manifest.json`.
Keep the original campaign directory names; do not add another `results/` level.

The package contains Journey originals and 22 MIP-start replacements, service
experiments at K50/K62, and their all-stop calibrations and references.
`submission_manifest.json` records the reported selection, file hashes and
historical source identities. Original attempts and logs are retained.

From the optimization repository root:

```sh
uv sync --frozen
uv run python benchmarks/thesis_publication.py \
  --submission-manifest results/submission_manifest.json
cd frontend
npm ci
npm run dev -- --port 5174 --strictPort
```

Open http://127.0.0.1:5174/thesis. Export verifies all packaged files before
building the views; no optimization or solver license is needed.
Allow several minutes and additional disk space for generated viewer data.
To check files only: `python3 benchmarks/verify_submission.py` (Python 3.12+).

Service assignment allows a later destination STOP in the same cabin before
the deadline. Journey assignment uses the first destination visit. The four
additional service-contract checks are included in `oip_service_contract_checks.json`.
Missing incumbents are not infeasibility proofs; bounds and solutions are separate.

One superseded Journey attempt has a replay-spacing warning and is excluded
from the reported selection; see `replay_checks.json`.

Reproduction commands: `docs/experiments/README.md` in the code repository.
The ZIP contains raw data only; derived frontend files are regenerated.

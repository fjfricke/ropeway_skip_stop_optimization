# Benchmark entry points

> AI-generated documentation.

Thesis reviewers: start with the [reviewer guide](../docs/REVIEWER_GUIDE.md).
For your own systems and single runs, use the [usage guide](../docs/USAGE.md).
For submitted data sources and study-run commands, use the
[experiment guide](../docs/experiments/README.md).

| Purpose | Entry point |
|---|---|
| Check the raw ZIP, without solvers | [verify_submission.py](verify_submission.py) |
| Build the submitted viewer data | [thesis_publication.py](thesis_publication.py), with `--submission-manifest` |
| Journey calibration and comparisons | [run_thesis_revised_journey_campaign.py](run_thesis_revised_journey_campaign.py) |
| Journey MIP-start follow-ups | [run_journey_mip_start_campaign.py](run_journey_mip_start_campaign.py) |
| Service mixtures, K50/K62 | [run_oip_fixed_mix_campaign.py](run_oip_fixed_mix_campaign.py) |
| Regular all-stop capacity calibration | [run_oip_phase_calibration.py](run_oip_phase_calibration.py) |
| Additional K50 phase references | [run_oip_k50_phase_references.py](run_oip_k50_phase_references.py) |
| Freeze a raw-data package (maintainer) | [prepare_submission.py](prepare_submission.py) |

Use new output directories for optimization; never resume the submitted campaigns.
The [historical catalogue](HISTORY.md) preserves earlier DDD, reservoir and EAN
commands. Their defaults and conclusions do not describe the reported studies.

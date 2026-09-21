# Submission check — 21 September 2026

The raw package contains six campaigns, 64 selected Journey comparisons
(including 22 replacements), 30 service comparisons and their references.
`results/submission_manifest.json` records the exact files and source hashes.
The ZIP itself is created by the author using `results/submission_files.txt`.

## Checks

- Fresh checkout directory with spaces and a different absolute path.
  A Python audit hook rejected reads from the original checkout, except its
  initially reused dependency environment. A separate `uv sync --frozen
  --extra analysis` environment was subsequently installed successfully.
- All packaged files passed size and SHA-256 checks. Campaign, argument,
  case and preparation metadata had no missing or external result-file dependencies.
- Full frontend export completed without optimization; original data was unchanged.
  The reported Journey view uses the same replacements as the thesis.
- From an empty figure directory, all 64 Journey rows, 30 service rows,
  48 STOP/SKIP counts, 64 model-size rows and six reference rows reproduced
  the existing numerical values. Only provenance paths changed to portable paths.
- The four later-destination service certificates passed independent checks.
- Gurobi labelled arc-flow and CP-SAT OIP smoke tests both passed;
  their native solve limits were 30 s and 10 s respectively.
- Frontend dependency installation, production build, unit tests and manual
  Journey/service result navigation and animated timetable replays passed.

## Replay check and historical warning

109 distinct saved timetables were checked: 108 passed; one historical
Journey attempt has a geometric-spacing violation at the end of operation:
`relative_75_f2_k30_skip_stop`, original campaign, attempt 1.
It is replaced in the reported selection and is retained with an explicit warning.
All 64 reported Journey incumbents and 19 service incumbents pass the replay check.
The complete records and raw-file hashes are in `results/replay_checks.json`.
An all-history replay audit therefore exits nonzero for this documented old case.

The viewer previously also checked resource entries *after* operation ended.
It now follows the existing finite-event-entry contract: include entry at H,
exclude entry after H, retain full clearance. Tests cover H and H + 1 microsecond.
This removes an out-of-scope warning on the selected F2/K30 constant-demand run;
no timetable, headway value or solver result was modified.

Service assignment permits later destination STOPs in the same cabin within
the service deadline; Journey uses the first destination visit. The included
service-contract checks document this difference rather than silently equating them.

Timing and parallel search remain machine-dependent. These checks reproduce
stored evidence and output values, not identical fresh MIP search trajectories.

# Thesis frontend publication — acceptance

Baseline commit before the change: `04f3a19` (code and experiment documentation;
no raw runs, thesis or presentation).

Published series: Journey, OIP K62, OIP K50. Journey retains 20 calibrations and
64 final comparisons; deferred historical cases are not part of the fresh matrix.
All original attempt records remain in raw results. Repeating the documented
runner registers a separate execution; preparing a fresh Journey execution was
tested with 84 jobs in a temporary directory without starting a solver.

85 available validated attempt/reference certificates were exported: Journey 62
(including an earlier attempt), K62 eight (five solutions + three references),
K50 fifteen (twelve solutions + three references). Runs without a certificate
remain unknown, with no replay link. All exported artifacts resolve and every
replay contains the expected fleet at 0, 15, 1464, 2364 and 2664 seconds.

The original Scenario Viewer examples and raw result directories were retained.
Unregistered optimization/thesis frontend exports and the evolution live export
were pruned. The active Journey export is approximately 5.1 GiB; the additional
shared publication/replay package is approximately 135 MiB. Large source result
JSON remains downloadable for the selected Journey runs.

## Replay corrections

- Journey demand is reconstructed from the solver's actual demand manifest,
  not the base `scenario.json`. Preserve seconds in release times; the generic
  JSON codec's minute precision is insufficient for 15-second groups.
- Circular layout recognizes topology metadata, including OIP scenario IDs.
- OIP rope starts carry the actual event before zero and the following arrival;
  logical initial-placement markers do not replace interpolation endpoints.
- Reference events are aligned to their stored millisecond grid, preventing
  floating-point epsilon differences from sorting switch entry before arrival.
- The physical safety adapter includes the complete geometric headway policy.
  The frontend checker now handles shared entry-switch resources explicitly.

## Additional finding: Journey tail boundary

The complete frontend physical replay check reports **84 safe exports and one
export with three conflicts**, with no missing artifacts or indeterminate checks.
The flagged run is `relative_75_f2_k30_skip_stop`, attempt 1, in the original
Journey campaign. Cabins 20 and 29 approach S3 near the end of the operating window.
The reported spacing at t=2664 s is approximately 3.180 m versus 3.5 m required;
platform-entry separation is 7.94 s, with the following entry at 2665.263333 s.
The third reported event is a platform-exit headway after the operating end.

This is an additional physical replay finding, not a change to the stored
solver result or its original independent certificate. The frontend displays a
warning and the replay exposes the conflict. The exporter does not repair the
optimized timetable, suppress the warning, change the solver formulation or
rerun the thesis experiment. A separate review of the Journey terminal-visit
contract is required before claiming physical safety of this one timetable.

## Checks

- 19 Python tests: publication, final matrix, uncertainty/resume, Journey live export,
  K50 reference publication and shared index tests.
- TypeScript type check and 20 frontend dashboard, geometric-headway and replay tests.
- 129 campaign and attempt detail links resolve without missing exports.
- Browser checks: three-series overview, Journey detail→viewer, OIP K50 physical
  replay with 50 visible cabins and independent safety status.
- `frontend/scripts/checkThesisPublication.ts` checks every published replay and
  writes `generated/study/replay-audit.json`. It deliberately exits nonzero for
  the original Journey tail finding; that result is not hidden as a passing check.

No new optimization or capacity-calibration runs were started.

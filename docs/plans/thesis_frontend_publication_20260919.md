# Thesis frontend consolidation

Accepted scope: Journey (48 relative + 16 constant), OIP K62 and OIP K50;
used capacity calibrations and regular phase evaluations. One best checked
incumbent per run/attempt is replayable in the existing Scenario Viewer.
Historical viewer examples stay; historical optimization navigation and derived
run exports are removed. Raw results and original proofs are immutable.

Implementation: shared publication catalogue with three series and separate
execution IDs; original executions remain the default. Runner publication hooks
register fresh executions and resume updates without overwriting other executions.
Journey preparation uses the final 64-run matrix and all 20 calibration jobs.

The solver-free replay adapter uses the actual Journey demand manifest and OIP
portable certificates. Preserve exact release times, zero-boundary interpolation,
STOP/SKIP visits, passenger quantities and finite continuation. No passenger
reoptimization. Invalid or missing certificates have no replay link.

Acceptance: type checking; publication/idempotence/unknown tests; final matrix;
replay passenger timing and 15-second releases; browser navigation and physical
replay for all three series; old examples still load. Cleanup runs only after
all export errors have been resolved. No large solver runs during this change.

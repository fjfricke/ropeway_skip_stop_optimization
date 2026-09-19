# Geometric thesis headways

Implemented on 2026-09-18. No new parameter class; no campaign or calibration started.

- Shared physical parameters contain geometry only. Stop-on-fault inputs and
  their provenance live in the existing legacy mechanism; historical examples
  keep their original numerical rules.
- Thesis scenarios construct the geometric design directly. Shared entry/exit
  headways are constant across STOP/SKIP combinations; platform separation remains.
- No mechanical resources or fault-only solver terms are generated. Geometric
  CP-SAT models reconstruct preceding route history for export; templates derive
  it from type and initial position. No separate history auxiliaries remain.
- Geometric conflicts, order decisions, type parity and boundary protection remain.
- Headway JSON schema v2 separates these inputs. The explicit decoder migrates
  unversioned legacy data, rejects conflicting/unknown inputs, and warns with the
  values when obsolete global fault inputs have no consuming mechanism.
- Saved results remain untouched. Prepared thesis arc-flow runs reject a legacy
  headway contract. Certificate/bound identity checks remain in force.
- Frontend validates geometric inputs without emergency parameters, hides absent
  mechanisms and displays geometric entry/exit and platform headways.

## Acceptance

Tests cover schema round trips, old numerical rules, constant geometric rules,
initial STOP/SKIP history and hints, millisecond boundaries, full protected intervals,
independent passenger certificates, model-variable absence and old prepared-run rejection.
Arc-flow graphs and conflict groups match the previous geometric construction.
Representative K62 OIP and K10 journey models are built without optimization.

[Measurements and test commands](../findings/geometric_headway_cleanup_20260918.md).

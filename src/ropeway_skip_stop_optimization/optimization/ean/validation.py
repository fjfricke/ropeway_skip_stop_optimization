from __future__ import annotations

from dataclasses import dataclass

from ropeway_skip_stop_optimization.optimization.ean.artifact import EanBuildArtifact
from ropeway_skip_stop_optimization.optimization.ean.headway_semantics import (
    PLATFORM_EXIT_WAIT_OCCUPANCY_SEMANTICS,
    POINT_HEADWAY_SEMANTICS,
    headway_semantics_label,
    uses_platform_exit_wait_occupancy,
)
from ropeway_skip_stop_optimization.optimization.ean.formulation_config import (
    EanHorizonFormulation,
    EanTimeBoundFormulation,
)
from ropeway_skip_stop_optimization.optimization.ean.models import (
    EanActivationReference,
    EanCabinStart,
    EanCabinStartKind,
    EanFleetMode,
    EanHeadwayPairScope,
    EanTimeReference,
    HeadwayCandidate,
    HeadwayCheckpointDefinition,
    HeadwayPair,
    SkipStopTiming,
    StationEanConfig,
    SwitchVisitDefinition,
)
from ropeway_skip_stop_optimization.optimization.ean.headway_separator import (
    separate_all_headway_violations,
)
from ropeway_skip_stop_optimization.optimization.ean.plan import (
    EanCabinTrajectory,
    EanCabinVisit,
    EanMovementPlan,
    EanRouteDecision,
)
from ropeway_skip_stop_optimization.optimization.ean.time_bounds import (
    build_ean_model_time_bounds,
)
from ropeway_skip_stop_optimization.validation import (
    ValidationIssue,
    ValidationReport,
    ValidationSeverity,
)


@dataclass(frozen=True)
class HeadwayTimes:
    leader_clear_time: float
    follower_enter_time: float
    semantics_label: str


def validate_ean_movement_plan_against_artifact(
    artifact: EanBuildArtifact,
    plan: EanMovementPlan,
    tolerance_seconds: float = 1e-6,
) -> ValidationReport:
    issues: list[ValidationIssue] = []
    if tolerance_seconds < 0:
        raise ValueError("tolerance_seconds must be nonnegative")

    try:
        artifact.validate()
    except ValueError as exc:
        _add_issue(issues, "EAN_ARTIFACT_STRUCTURE_ERROR", str(exc), "ean_artifact", artifact.scenario_id)
    try:
        plan.validate()
    except ValueError as exc:
        _add_issue(issues, "EAN_PLAN_STRUCTURE_ERROR", str(exc), "ean_plan", plan.scenario_id)

    _validate_plan_identity(artifact, plan, issues, tolerance_seconds)

    starts_by_cabin_id = _starts_by_cabin_id(artifact.cabin_starts)
    timing_by_switch_id = _timings_by_switch_id(artifact.timings)
    station_config_by_id = _station_config_by_id(artifact.config.station_configs)
    visit_by_key = _plan_visit_by_key(plan.trajectories, issues)
    expected_visit_by_key = _expected_plan_visit_by_key(
        artifact,
        plan.horizon_formulation,
        actual_keys=set(visit_by_key),
    )
    checkpoint_by_id = _checkpoint_by_id(artifact.headway_checkpoints)
    candidate_by_id = _candidate_by_id(artifact.headway_candidates)

    _validate_trajectory_cabin_set(starts_by_cabin_id, plan.trajectories, issues)
    if artifact.fleet_mode is EanFleetMode.FIXED_STARTS:
        for key, visit in visit_by_key.items():
            if _has_negative_event_time(visit):
                _add_issue(
                    issues,
                    "EAN_TIME_WINDOW_VIOLATION",
                    f"visit {key!r} contains a negative event time",
                    "ean_visit",
                    _visit_entity_id(key),
                )
    _validate_visits_against_artifact(
        visit_by_key=visit_by_key,
        expected_visit_by_key=expected_visit_by_key,
        timing_by_switch_id=timing_by_switch_id,
        station_config_by_id=station_config_by_id,
        horizon_formulation=plan.horizon_formulation,
        model_end_seconds=artifact.config.model_end_seconds,
        issues=issues,
        tolerance_seconds=tolerance_seconds,
    )
    if artifact.fleet_mode is EanFleetMode.FIXED_STARTS:
        _validate_start_times(
            starts_by_cabin_id,
            plan.trajectories,
            issues,
            tolerance_seconds,
        )
    _validate_trajectory_chains(plan.trajectories, issues, tolerance_seconds)
    _validate_checkpoint_modes(checkpoint_by_id, station_config_by_id, issues)
    if artifact.headway_pair_scope is EanHeadwayPairScope.SPARSE:
        for violation in separate_all_headway_violations(
            artifact, plan, tolerance_seconds=tolerance_seconds
        ):
            _add_issue(
                issues,
                "EAN_HEADWAY_VIOLATION",
                f"headway pair {violation.pair.id!r} has violation_seconds="
                f"{violation.violation_seconds}",
                "ean_headway_pair",
                violation.pair.id,
            )
    else:
        _validate_headways(
            pairs=artifact.headway_pairs,
            candidate_by_id=candidate_by_id,
            checkpoint_by_id=checkpoint_by_id,
            station_config_by_id=station_config_by_id,
            timing_by_switch_id=timing_by_switch_id,
            visit_by_key=visit_by_key,
            model_end_seconds=artifact.config.model_end_seconds,
            horizon_formulation=plan.horizon_formulation,
            issues=issues,
            tolerance_seconds=tolerance_seconds,
        )

    return ValidationReport(tuple(issues))


def _validate_plan_identity(
    artifact: EanBuildArtifact,
    plan: EanMovementPlan,
    issues: list[ValidationIssue],
    tolerance_seconds: float,
) -> None:
    if plan.scenario_id != artifact.scenario_id:
        _add_issue(
            issues,
            "EAN_PLAN_ID_MISMATCH",
            f"plan scenario_id {plan.scenario_id!r} does not match artifact {artifact.scenario_id!r}",
            "ean_plan",
            plan.scenario_id,
        )
    if plan.fleet_mode is not artifact.fleet_mode:
        _add_issue(
            issues,
            "EAN_PLAN_FLEET_MODE_MISMATCH",
            f"plan fleet mode {plan.fleet_mode.value!r} does not match artifact "
            f"{artifact.fleet_mode.value!r}",
            "ean_plan",
            plan.scenario_id,
        )
    if not _close(plan.horizon_seconds, artifact.config.horizon_seconds, tolerance_seconds):
        _add_issue(
            issues,
            "EAN_PLAN_HORIZON_MISMATCH",
            "plan horizon_seconds does not match artifact config",
            "ean_plan",
            plan.scenario_id,
        )
    if not _close(plan.model_end_seconds, artifact.config.model_end_seconds, tolerance_seconds):
        _add_issue(
            issues,
            "EAN_PLAN_HORIZON_MISMATCH",
            "plan model_end_seconds does not match artifact config",
            "ean_plan",
            plan.scenario_id,
        )


def _validate_trajectory_cabin_set(
    starts_by_cabin_id: dict[int, EanCabinStart],
    trajectories: tuple[EanCabinTrajectory, ...],
    issues: list[ValidationIssue],
) -> None:
    expected_cabin_ids = set(starts_by_cabin_id)
    actual_cabin_ids = {trajectory.cabin_id for trajectory in trajectories}
    if actual_cabin_ids != expected_cabin_ids:
        _add_issue(
            issues,
            "EAN_TRAJECTORY_CABIN_MISMATCH",
            f"trajectory cabins mismatch: missing={expected_cabin_ids - actual_cabin_ids}, "
            f"extra={actual_cabin_ids - expected_cabin_ids}",
            "ean_plan",
            None,
        )


def _validate_visits_against_artifact(
    visit_by_key: dict[tuple[int, int], EanCabinVisit],
    expected_visit_by_key: dict[tuple[int, int], SwitchVisitDefinition],
    timing_by_switch_id: dict[str, SkipStopTiming],
    station_config_by_id: dict[str, StationEanConfig],
    horizon_formulation: EanHorizonFormulation,
    model_end_seconds: float,
    issues: list[ValidationIssue],
    tolerance_seconds: float,
) -> None:
    actual_keys = set(visit_by_key)
    expected_keys = set(expected_visit_by_key)
    if actual_keys != expected_keys:
        _add_issue(
            issues,
            "EAN_VISIT_MISMATCH",
            f"plan visit keys mismatch: missing={expected_keys - actual_keys}, extra={actual_keys - expected_keys}",
            "ean_plan",
            None,
        )

    for key in sorted(actual_keys & expected_keys):
        visit = visit_by_key[key]
        expected_visit = expected_visit_by_key[key]
        timing = timing_by_switch_id.get(visit.switch_id)
        if visit.switch_id != expected_visit.switch_id:
            _add_issue(
                issues,
                "EAN_VISIT_MISMATCH",
                f"visit {key!r} switch {visit.switch_id!r} does not match expected {expected_visit.switch_id!r}",
                "ean_visit",
                _visit_entity_id(key),
            )
            continue
        if timing is None:
            _add_issue(
                issues,
                "EAN_VISIT_MISMATCH",
                f"visit {key!r} references switch without timing {visit.switch_id!r}",
                "ean_visit",
                _visit_entity_id(key),
            )
            continue
        if visit.station_id != timing.station_id:
            _add_issue(
                issues,
                "EAN_VISIT_STATION_MISMATCH",
                f"visit {key!r} station {visit.station_id!r} does not match timing station {timing.station_id!r}",
                "ean_visit",
                _visit_entity_id(key),
            )

        station_config = station_config_by_id.get(timing.station_id)
        if station_config is None:
            continue
        _validate_visit_decision_and_timing(visit, timing, station_config, issues, tolerance_seconds)
        if (
            horizon_formulation is EanHorizonFormulation.EXACT_TIME_ACTIVATION
            and visit.switch_time_seconds > model_end_seconds + tolerance_seconds
        ):
            _add_issue(
                issues,
                "EAN_VISIT_AFTER_OPERATIONAL_HORIZON",
                f"active visit {key!r} starts at {visit.switch_time_seconds}, "
                f"after operational horizon {model_end_seconds}",
                "ean_visit",
                _visit_entity_id(key),
            )


def _validate_visit_decision_and_timing(
    visit: EanCabinVisit,
    timing: SkipStopTiming,
    station_config: StationEanConfig,
    issues: list[ValidationIssue],
    tolerance_seconds: float,
) -> None:
    if visit.decision is EanRouteDecision.SKIP and not timing.skip_allowed:
        _add_issue(
            issues,
            "EAN_SKIP_NOT_ALLOWED",
            f"visit {visit.cabin_id!r}/{visit.visit_index!r} skips at switch {visit.switch_id!r}, "
            "but skip is not physically allowed",
            "ean_visit",
            _visit_entity_id((visit.cabin_id, visit.visit_index)),
        )

    if visit.wait_seconds > tolerance_seconds and station_config.waiting_mode.value == "no_waiting":
        _add_issue(
            issues,
            "EAN_WAIT_NOT_ALLOWED",
            f"visit {visit.cabin_id!r}/{visit.visit_index!r} waits at no-waiting station {visit.station_id!r}",
            "ean_visit",
            _visit_entity_id((visit.cabin_id, visit.visit_index)),
        )

    if visit.decision is EanRouteDecision.STOP:
        _validate_stop_timing(visit, timing, issues, tolerance_seconds)
    elif visit.decision is EanRouteDecision.SKIP:
        _validate_skip_timing(visit, timing, issues, tolerance_seconds)


def _validate_stop_timing(
    visit: EanCabinVisit,
    timing: SkipStopTiming,
    issues: list[ValidationIssue],
    tolerance_seconds: float,
) -> None:
    if visit.platform_entry_time_seconds is None or visit.platform_exit_time_seconds is None:
        _add_issue(
            issues,
            "EAN_TIMING_MISMATCH",
            f"STOP visit {visit.cabin_id!r}/{visit.visit_index!r} needs platform times",
            "ean_visit",
            _visit_entity_id((visit.cabin_id, visit.visit_index)),
        )
        return

    expected_platform_entry = visit.switch_time_seconds + timing.entry_to_platform_entry_seconds
    expected_platform_exit = (
        visit.platform_entry_time_seconds
        + timing.min_platform_entry_to_platform_exit_seconds
        + visit.wait_seconds
    )
    expected_exit_switch = visit.platform_exit_time_seconds + timing.platform_exit_to_exit_switch_seconds
    expected_next_switch = visit.exit_switch_time_seconds + timing.rope_to_next_switch_seconds
    _validate_time_equals(visit, "platform_entry_time_seconds", visit.platform_entry_time_seconds, expected_platform_entry, issues, tolerance_seconds)
    _validate_time_equals(visit, "platform_exit_time_seconds", visit.platform_exit_time_seconds, expected_platform_exit, issues, tolerance_seconds)
    _validate_time_equals(visit, "exit_switch_time_seconds", visit.exit_switch_time_seconds, expected_exit_switch, issues, tolerance_seconds)
    _validate_time_equals(visit, "next_switch_time_seconds", visit.next_switch_time_seconds, expected_next_switch, issues, tolerance_seconds)


def _validate_skip_timing(
    visit: EanCabinVisit,
    timing: SkipStopTiming,
    issues: list[ValidationIssue],
    tolerance_seconds: float,
) -> None:
    if visit.platform_entry_time_seconds is not None or visit.platform_exit_time_seconds is not None:
        _add_issue(
            issues,
            "EAN_TIMING_MISMATCH",
            f"SKIP visit {visit.cabin_id!r}/{visit.visit_index!r} must not set platform times",
            "ean_visit",
            _visit_entity_id((visit.cabin_id, visit.visit_index)),
        )
    if abs(visit.wait_seconds) > tolerance_seconds:
        _add_issue(
            issues,
            "EAN_TIMING_MISMATCH",
            f"SKIP visit {visit.cabin_id!r}/{visit.visit_index!r} must not wait",
            "ean_visit",
            _visit_entity_id((visit.cabin_id, visit.visit_index)),
        )
    expected_exit_switch = visit.switch_time_seconds + timing.skip_entry_to_exit_switch_seconds
    expected_next_switch = visit.exit_switch_time_seconds + timing.rope_to_next_switch_seconds
    _validate_time_equals(visit, "exit_switch_time_seconds", visit.exit_switch_time_seconds, expected_exit_switch, issues, tolerance_seconds)
    _validate_time_equals(visit, "next_switch_time_seconds", visit.next_switch_time_seconds, expected_next_switch, issues, tolerance_seconds)


def _validate_start_times(
    starts_by_cabin_id: dict[int, EanCabinStart],
    trajectories: tuple[EanCabinTrajectory, ...],
    issues: list[ValidationIssue],
    tolerance_seconds: float,
) -> None:
    for trajectory in trajectories:
        if not trajectory.visits:
            continue
        start = starts_by_cabin_id.get(trajectory.cabin_id)
        if start is None:
            continue
        first_visit = trajectory.visits[0]
        if start.kind is EanCabinStartKind.FIXED:
            if not _close(first_visit.switch_time_seconds, start.time_seconds, tolerance_seconds):
                _add_issue(
                    issues,
                    "EAN_START_TIME_VIOLATION",
                    f"fixed start for cabin {trajectory.cabin_id!r} is at {start.time_seconds}, "
                    f"but plan starts at {first_visit.switch_time_seconds}",
                    "ean_visit",
                    _visit_entity_id((trajectory.cabin_id, 0)),
                )
        elif first_visit.switch_time_seconds + tolerance_seconds < start.time_seconds:
            _add_issue(
                issues,
                "EAN_START_TIME_VIOLATION",
                f"earliest start for cabin {trajectory.cabin_id!r} is {start.time_seconds}, "
                f"but plan starts at {first_visit.switch_time_seconds}",
                "ean_visit",
                _visit_entity_id((trajectory.cabin_id, 0)),
            )


def _validate_trajectory_chains(
    trajectories: tuple[EanCabinTrajectory, ...],
    issues: list[ValidationIssue],
    tolerance_seconds: float,
) -> None:
    for trajectory in trajectories:
        for previous_visit, next_visit in zip(trajectory.visits, trajectory.visits[1:]):
            if not _close(
                next_visit.switch_time_seconds,
                previous_visit.next_switch_time_seconds,
                tolerance_seconds,
            ):
                _add_issue(
                    issues,
                    "EAN_TRAJECTORY_CHAIN_MISMATCH",
                    f"cabin {trajectory.cabin_id!r} visit {next_visit.visit_index!r} starts at "
                    f"{next_visit.switch_time_seconds}, expected {previous_visit.next_switch_time_seconds}",
                    "ean_visit",
                    _visit_entity_id((trajectory.cabin_id, next_visit.visit_index)),
                )


def _validate_checkpoint_modes(
    checkpoint_by_id: dict[str, HeadwayCheckpointDefinition],
    station_config_by_id: dict[str, StationEanConfig],
    issues: list[ValidationIssue],
) -> None:
    for checkpoint in checkpoint_by_id.values():
        station_config = station_config_by_id.get(checkpoint.station_id)
        if station_config is None:
            continue
        if station_config.waiting_mode not in checkpoint.waiting_modes:
            _add_issue(
                issues,
                "EAN_CHECKPOINT_MODE_MISMATCH",
                f"checkpoint {checkpoint.id!r} does not apply to station waiting mode "
                f"{station_config.waiting_mode.value!r}",
                "ean_checkpoint",
                checkpoint.id,
            )


def _validate_headways(
    pairs: tuple[HeadwayPair, ...],
    candidate_by_id: dict[str, HeadwayCandidate],
    checkpoint_by_id: dict[str, HeadwayCheckpointDefinition],
    station_config_by_id: dict[str, StationEanConfig],
    timing_by_switch_id: dict[str, SkipStopTiming],
    visit_by_key: dict[tuple[int, int], EanCabinVisit],
    model_end_seconds: float,
    horizon_formulation: EanHorizonFormulation,
    issues: list[ValidationIssue],
    tolerance_seconds: float,
) -> None:
    for pair in pairs:
        first_candidate = candidate_by_id.get(pair.first_candidate_id)
        second_candidate = candidate_by_id.get(pair.second_candidate_id)
        checkpoint = checkpoint_by_id.get(pair.checkpoint_id)
        if first_candidate is None or second_candidate is None or checkpoint is None:
            continue
        station_config = station_config_by_id.get(checkpoint.station_id)
        if station_config is not None and station_config.waiting_mode not in checkpoint.waiting_modes:
            continue

        first_visit = visit_by_key.get((first_candidate.cabin_id, first_candidate.visit_index))
        second_visit = visit_by_key.get((second_candidate.cabin_id, second_candidate.visit_index))
        if first_visit is None or second_visit is None:
            continue
        if not _candidate_is_active(first_candidate, checkpoint, first_visit):
            continue
        if not _candidate_is_active(second_candidate, checkpoint, second_visit):
            continue
        first_times = _candidate_headway_times(
            first_candidate,
            checkpoint,
            station_config,
            first_visit,
            timing_by_switch_id,
        )
        second_times = _candidate_headway_times(
            second_candidate,
            checkpoint,
            station_config,
            second_visit,
            timing_by_switch_id,
        )
        if first_times is None or second_times is None:
            continue
        if horizon_formulation is EanHorizonFormulation.EXACT_TIME_ACTIVATION:
            if (
                first_times.follower_enter_time > model_end_seconds + tolerance_seconds
                or second_times.follower_enter_time > model_end_seconds + tolerance_seconds
            ):
                continue
        forward_gap = second_times.follower_enter_time - first_times.leader_clear_time
        reverse_gap = first_times.follower_enter_time - second_times.leader_clear_time
        if max(forward_gap, reverse_gap) + tolerance_seconds < pair.headway_seconds:
            semantics_label = headway_semantics_label(checkpoint, station_config)
            _add_issue(
                issues,
                "EAN_HEADWAY_VIOLATION",
                f"headway pair {pair.id!r} at checkpoint {checkpoint.id!r} "
                f"uses {semantics_label!r}: forward leader_clear_time={first_times.leader_clear_time}, "
                f"forward follower_enter_time={second_times.follower_enter_time}, "
                f"reverse leader_clear_time={second_times.leader_clear_time}, "
                f"reverse follower_enter_time={first_times.follower_enter_time}, "
                f"needs headway_seconds={pair.headway_seconds}",
                "ean_headway_pair",
                pair.id,
            )


def _candidate_is_active(
    candidate: HeadwayCandidate,
    checkpoint: HeadwayCheckpointDefinition,
    visit: EanCabinVisit,
) -> bool:
    if candidate.activation_reference is EanActivationReference.SERVE:
        return visit.decision is EanRouteDecision.STOP and checkpoint.applies_to_serve
    if candidate.activation_reference is EanActivationReference.SKIP:
        return visit.decision is EanRouteDecision.SKIP and checkpoint.applies_to_skip
    if candidate.activation_reference is EanActivationReference.ACTIVE:
        if visit.decision is EanRouteDecision.STOP:
            return checkpoint.applies_to_serve
        if visit.decision is EanRouteDecision.SKIP:
            return checkpoint.applies_to_skip
    return False


def _candidate_time(candidate: HeadwayCandidate, visit: EanCabinVisit) -> float | None:
    if candidate.time_reference is EanTimeReference.ENTRY_TIME:
        return visit.switch_time_seconds
    if candidate.time_reference is EanTimeReference.PLATFORM_ENTRY_TIME:
        return visit.platform_entry_time_seconds
    if candidate.time_reference is EanTimeReference.PLATFORM_EXIT_TIME:
        return visit.platform_exit_time_seconds
    if candidate.time_reference is EanTimeReference.EXIT_SWITCH_TIME:
        return visit.exit_switch_time_seconds
    return None


def _candidate_headway_times(
    candidate: HeadwayCandidate,
    checkpoint: HeadwayCheckpointDefinition,
    station_config: StationEanConfig | None,
    visit: EanCabinVisit,
    timing_by_switch_id: dict[str, SkipStopTiming],
) -> HeadwayTimes | None:
    if uses_platform_exit_wait_occupancy(checkpoint, station_config):
        if visit.platform_exit_time_seconds is None:
            return None
        timing = timing_by_switch_id.get(visit.switch_id)
        if timing is None:
            return None
        wait_entry_time = (
            visit.switch_time_seconds
            + timing.entry_to_platform_entry_seconds
            + timing.min_platform_entry_to_platform_exit_seconds
        )
        return HeadwayTimes(
            leader_clear_time=visit.platform_exit_time_seconds,
            follower_enter_time=wait_entry_time,
            semantics_label=PLATFORM_EXIT_WAIT_OCCUPANCY_SEMANTICS,
        )

    candidate_time = _candidate_time(candidate, visit)
    if candidate_time is None:
        return None
    return HeadwayTimes(
        leader_clear_time=candidate_time,
        follower_enter_time=candidate_time,
        semantics_label=POINT_HEADWAY_SEMANTICS,
    )


def _validate_time_equals(
    visit: EanCabinVisit,
    field_name: str,
    actual: float,
    expected: float,
    issues: list[ValidationIssue],
    tolerance_seconds: float,
) -> None:
    if not _close(actual, expected, tolerance_seconds):
        _add_issue(
            issues,
            "EAN_TIMING_MISMATCH",
            f"visit {visit.cabin_id!r}/{visit.visit_index!r} {field_name} is {actual}, expected {expected}",
            "ean_visit",
            _visit_entity_id((visit.cabin_id, visit.visit_index)),
        )


def _starts_by_cabin_id(cabin_starts: tuple[EanCabinStart, ...]) -> dict[int, EanCabinStart]:
    return {start.cabin_id: start for start in cabin_starts}


def _timings_by_switch_id(timings: tuple[SkipStopTiming, ...]) -> dict[str, SkipStopTiming]:
    return {timing.switch_id: timing for timing in timings}


def _station_config_by_id(station_configs: tuple[StationEanConfig, ...]) -> dict[str, StationEanConfig]:
    return {station_config.station_id: station_config for station_config in station_configs}


def _expected_plan_visit_by_key(
    artifact: EanBuildArtifact,
    horizon_formulation: EanHorizonFormulation,
    *,
    actual_keys: set[tuple[int, int]],
) -> dict[tuple[int, int], SwitchVisitDefinition]:
    all_visits = {
        (visit.cabin_id, visit.visit_index): visit
        for visit in artifact.switch_visits
    }
    if horizon_formulation is EanHorizonFormulation.LEGACY:
        return all_visits
    if horizon_formulation is EanHorizonFormulation.CONSERVATIVE_FREE_SUFFIX:
        earliest_bounds = build_ean_model_time_bounds(
            artifact,
            EanTimeBoundFormulation.DERIVED_VISIT_BOUNDS,
        )
        return {
            key: visit
            for key, visit in all_visits.items()
            if earliest_bounds.by_visit[key].switch_lower
            <= artifact.config.operational_end_seconds
        }
    if horizon_formulation is EanHorizonFormulation.EXACT_TIME_ACTIVATION:
        return {
            key: visit
            for key, visit in all_visits.items()
            if key in actual_keys
        }
    raise ValueError(f"unsupported EAN horizon formulation: {horizon_formulation}")


def _plan_visit_by_key(
    trajectories: tuple[EanCabinTrajectory, ...],
    issues: list[ValidationIssue],
) -> dict[tuple[int, int], EanCabinVisit]:
    result: dict[tuple[int, int], EanCabinVisit] = {}
    duplicates: set[tuple[int, int]] = set()
    for trajectory in trajectories:
        for visit in trajectory.visits:
            key = (visit.cabin_id, visit.visit_index)
            if key in result:
                duplicates.add(key)
            result[key] = visit
    for duplicate in duplicates:
        _add_issue(
            issues,
            "EAN_VISIT_MISMATCH",
            f"duplicate plan visit key {duplicate!r}",
            "ean_visit",
            _visit_entity_id(duplicate),
        )
    return result


def _checkpoint_by_id(
    checkpoints: tuple[HeadwayCheckpointDefinition, ...],
) -> dict[str, HeadwayCheckpointDefinition]:
    return {checkpoint.id: checkpoint for checkpoint in checkpoints}


def _candidate_by_id(candidates: tuple[HeadwayCandidate, ...]) -> dict[str, HeadwayCandidate]:
    return {candidate.id: candidate for candidate in candidates}


def _has_negative_event_time(visit: EanCabinVisit) -> bool:
    event_times = (
        visit.switch_time_seconds,
        visit.platform_entry_time_seconds,
        visit.platform_exit_time_seconds,
        visit.exit_switch_time_seconds,
        visit.next_switch_time_seconds,
        visit.wait_seconds,
    )
    return any(value is not None and value < 0 for value in event_times)


def _close(left: float, right: float, tolerance_seconds: float) -> bool:
    return abs(left - right) <= tolerance_seconds


def _visit_entity_id(key: tuple[int, int]) -> str:
    return f"cabin_{key[0]}::visit_{key[1]}"


def _add_issue(
    issues: list[ValidationIssue],
    code: str,
    message: str,
    entity_type: str | None,
    entity_id: str | int | None,
) -> None:
    issues.append(
        ValidationIssue(
            code=code,
            severity=ValidationSeverity.ERROR,
            message=message,
            entity_type=entity_type,
            entity_id=entity_id,
        )
    )

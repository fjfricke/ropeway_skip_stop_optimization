from __future__ import annotations

from dataclasses import replace

from ropeway_skip_stop_optimization.examples.three_station import build_three_station_scenario
from ropeway_skip_stop_optimization.examples.three_station_ean import (
    build_three_station_ean_config,
    build_three_station_ean_ring_switch_order,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    EarliestAllStopEanMovementPlanBuilder,
    EanBuildArtifact,
    EanCabinTrajectory,
    EanCabinVisit,
    EanMovementPlan,
    EanRouteDecision,
    RingEanBuildArtifactBuilder,
    StationWaitingMode,
    validate_ean_movement_plan_against_artifact,
)


def test_ean_movement_plan_validator_accepts_three_station_baseline_timing_shape() -> None:
    artifact, plan = _artifact_and_plan()

    report = validate_ean_movement_plan_against_artifact(artifact, plan)

    assert "EAN_TIMING_MISMATCH" not in _error_codes(report)
    assert "EAN_VISIT_MISMATCH" not in _error_codes(report)
    assert "EAN_VISIT_STATION_MISMATCH" not in _error_codes(report)


def test_ean_movement_plan_validator_reports_timing_mismatch() -> None:
    artifact, plan = _artifact_and_plan()
    visit = _first_visit(plan)
    mutated_plan = _replace_visit(
        plan,
        replace(visit, platform_entry_time_seconds=visit.platform_entry_time_seconds + 1.0),
    )

    report = validate_ean_movement_plan_against_artifact(artifact, mutated_plan)

    assert "EAN_TIMING_MISMATCH" in _error_codes(report)


def test_ean_movement_plan_validator_reports_plan_structure_error() -> None:
    artifact, plan = _artifact_and_plan()
    duplicated_trajectory_plan = replace(
        plan,
        trajectories=(*plan.trajectories, plan.trajectories[0]),
    )

    report = validate_ean_movement_plan_against_artifact(artifact, duplicated_trajectory_plan)

    assert "EAN_PLAN_STRUCTURE_ERROR" in _error_codes(report)


def test_ean_movement_plan_validator_reports_skip_not_allowed() -> None:
    artifact, plan = _artifact_and_plan()
    terminal_visit = _first_visit_with_switch(plan, "R_entry_lr")
    mutated_plan = _replace_visit(
        plan,
        replace(
            terminal_visit,
            decision=EanRouteDecision.SKIP,
            platform_entry_time_seconds=None,
            platform_exit_time_seconds=None,
        ),
    )

    report = validate_ean_movement_plan_against_artifact(artifact, mutated_plan)

    assert "EAN_SKIP_NOT_ALLOWED" in _error_codes(report)


def test_ean_movement_plan_validator_reports_wait_not_allowed() -> None:
    artifact, plan = _artifact_and_plan()
    visit = _first_visit_with_switch(plan, "R_entry_lr")
    mutated_plan = _replace_visit(
        plan,
        replace(
            visit,
            wait_seconds=1.0,
        ),
    )

    report = validate_ean_movement_plan_against_artifact(artifact, mutated_plan)

    assert "EAN_WAIT_NOT_ALLOWED" in _error_codes(report)


def test_ean_movement_plan_validator_reports_station_mismatch() -> None:
    artifact, plan = _artifact_and_plan()
    visit = _first_visit(plan)
    mutated_plan = _replace_visit(plan, replace(visit, station_id="R"))

    report = validate_ean_movement_plan_against_artifact(artifact, mutated_plan)

    assert "EAN_VISIT_STATION_MISMATCH" in _error_codes(report)


def test_ean_movement_plan_validator_reports_start_time_violation() -> None:
    artifact, plan = _artifact_and_plan()
    visit = _first_visit(plan)
    mutated_plan = _replace_visit(
        plan,
        replace(
            visit,
            switch_time_seconds=visit.switch_time_seconds - 1.0,
            platform_entry_time_seconds=visit.platform_entry_time_seconds - 1.0,
            platform_exit_time_seconds=visit.platform_exit_time_seconds - 1.0,
            exit_switch_time_seconds=visit.exit_switch_time_seconds - 1.0,
            next_switch_time_seconds=visit.next_switch_time_seconds - 1.0,
        ),
    )

    report = validate_ean_movement_plan_against_artifact(artifact, mutated_plan)

    assert "EAN_START_TIME_VIOLATION" in _error_codes(report)


def test_ean_movement_plan_validator_reports_time_window_violation() -> None:
    artifact, plan = _artifact_and_plan()
    visit = _first_visit(plan)
    mutated_plan = _replace_visit(
        plan,
        replace(
            visit,
            switch_time_seconds=-1.0,
            platform_entry_time_seconds=0.0,
            platform_exit_time_seconds=1.0,
            exit_switch_time_seconds=2.0,
            next_switch_time_seconds=3.0,
        ),
    )

    report = validate_ean_movement_plan_against_artifact(artifact, mutated_plan)

    assert "EAN_TIME_WINDOW_VIOLATION" in _error_codes(report)


def test_ean_movement_plan_validator_reports_checkpoint_mode_mismatch() -> None:
    artifact, plan = _artifact_and_plan()
    checkpoint = artifact.headway_checkpoints[0]
    mutated_artifact = replace(
        artifact,
        headway_checkpoints=(
            replace(checkpoint, waiting_modes=(StationWaitingMode.NO_WAITING,)),
            *artifact.headway_checkpoints[1:],
        ),
    )

    report = validate_ean_movement_plan_against_artifact(mutated_artifact, plan)

    assert "EAN_CHECKPOINT_MODE_MISMATCH" in _error_codes(report)


def test_ean_movement_plan_validator_reports_headway_violation() -> None:
    artifact, plan = _artifact_and_plan()
    cabin_0_first = _first_visit_with_cabin(plan, 0)
    cabin_2_first = _first_visit_with_cabin(plan, 2)
    mutated_plan = _replace_visit(
        plan,
        replace(
            cabin_2_first,
            switch_time_seconds=cabin_0_first.switch_time_seconds,
            platform_entry_time_seconds=cabin_0_first.platform_entry_time_seconds,
            platform_exit_time_seconds=cabin_0_first.platform_exit_time_seconds,
            exit_switch_time_seconds=cabin_0_first.exit_switch_time_seconds,
            next_switch_time_seconds=cabin_0_first.next_switch_time_seconds,
        ),
    )

    report = validate_ean_movement_plan_against_artifact(artifact, mutated_plan)

    assert "EAN_HEADWAY_VIOLATION" in _error_codes(report)


def _artifact_and_plan() -> tuple[EanBuildArtifact, EanMovementPlan]:
    scenario = build_three_station_scenario()
    config = build_three_station_ean_config(scenario)
    artifact = RingEanBuildArtifactBuilder(
        switch_cycle=build_three_station_ean_ring_switch_order(scenario),
    ).build(scenario, config)
    plan = EarliestAllStopEanMovementPlanBuilder().build(artifact)
    return artifact, plan


def _first_visit(plan: EanMovementPlan) -> EanCabinVisit:
    return plan.trajectories[0].visits[0]


def _first_visit_with_cabin(plan: EanMovementPlan, cabin_id: int) -> EanCabinVisit:
    for trajectory in plan.trajectories:
        if trajectory.cabin_id == cabin_id:
            return trajectory.visits[0]
    raise AssertionError(f"missing trajectory for cabin {cabin_id}")


def _first_visit_with_switch(plan: EanMovementPlan, switch_id: str) -> EanCabinVisit:
    for trajectory in plan.trajectories:
        for visit in trajectory.visits:
            if visit.switch_id == switch_id:
                return visit
    raise AssertionError(f"missing visit for switch {switch_id}")


def _replace_visit(plan: EanMovementPlan, replacement: EanCabinVisit) -> EanMovementPlan:
    trajectories: list[EanCabinTrajectory] = []
    for trajectory in plan.trajectories:
        if trajectory.cabin_id != replacement.cabin_id:
            trajectories.append(trajectory)
            continue
        trajectories.append(
            replace(
                trajectory,
                visits=tuple(
                    replacement if visit.visit_index == replacement.visit_index else visit
                    for visit in trajectory.visits
                ),
            )
        )
    return replace(plan, trajectories=tuple(trajectories))


def _error_codes(report) -> set[str]:
    return {issue.code for issue in report.errors}

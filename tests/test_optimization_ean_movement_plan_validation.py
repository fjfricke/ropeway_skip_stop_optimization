from __future__ import annotations

from dataclasses import replace

from ropeway_skip_stop_optimization.examples.three_station import build_three_station_scenario
from ropeway_skip_stop_optimization.examples.three_station_ean import (
    build_three_station_ean_config,
    build_three_station_ean_ring_switch_order,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    EarliestAllStopEanMovementPlanBuilder,
    EanActivationReference,
    EanBuildArtifact,
    EanCabinStart,
    EanCabinStartKind,
    EanCabinTrajectory,
    EanCabinVisit,
    EanConfig,
    EanHorizonFormulation,
    EanHeadwayPairScope,
    EanMovementPlan,
    EanRouteDecision,
    EanTimeReference,
    HeadwayCandidate,
    HeadwayCheckpointDefinition,
    HeadwayCheckpointKind,
    HeadwayPair,
    RingEanBuildArtifactBuilder,
    SkipStopTiming,
    StationEanConfig,
    StationWaitingMode,
    SwitchTransition,
    SwitchVisitDefinition,
    validate_ean_movement_plan_against_artifact,
)
from ropeway_skip_stop_optimization.optimization.ean.headway_separator import (
    EanHeadwayViolation,
    select_headway_violation_batch,
    separate_all_headway_violations,
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


def test_ean_movement_plan_validator_checks_platform_exit_wait_occupancy() -> None:
    artifact, plan = _platform_exit_wait_occupancy_artifact_and_plan()

    report = validate_ean_movement_plan_against_artifact(artifact, plan)

    assert "EAN_HEADWAY_VIOLATION" in _error_codes(report)
    assert "platform_exit_wait_occupancy" in report.issues[0].message
    assert "leader_clear_time" in report.issues[0].message
    assert "follower_enter_time" in report.issues[0].message


def test_exact_horizon_validates_occupancy_clearing_after_horizon() -> None:
    artifact, plan = _horizon_crossing_headway_artifact_and_plan()

    report = validate_ean_movement_plan_against_artifact(artifact, plan)

    assert "EAN_HEADWAY_VIOLATION" in _error_codes(report)


def test_sparse_separator_finds_point_headway_violation() -> None:
    artifact, plan = _artifact_and_plan()
    cabin_0_first = _first_visit_with_cabin(plan, 0)
    cabin_2_first = _first_visit_with_cabin(plan, 2)
    plan = _replace_visit(
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
    sparse = replace(
        artifact, headway_pairs=(), headway_pair_scope=EanHeadwayPairScope.SPARSE
    )

    violations = separate_all_headway_violations(sparse, plan)

    assert violations
    assert all(item.violation_seconds > 1e-5 for item in violations)


def test_sparse_separator_uses_platform_wait_occupancy() -> None:
    artifact, plan = _platform_exit_wait_occupancy_artifact_and_plan()
    sparse = replace(
        artifact, headway_pairs=(), headway_pair_scope=EanHeadwayPairScope.SPARSE
    )

    violations = separate_all_headway_violations(sparse, plan)

    assert len(violations) == 1
    assert violations[0].semantics_label == "platform_exit_wait_occupancy"


def test_sparse_separator_respects_stop_skip_activation() -> None:
    artifact, plan = _platform_exit_wait_occupancy_artifact_and_plan()
    skip_only = tuple(
        replace(candidate, activation_reference=EanActivationReference.SKIP)
        for candidate in artifact.headway_candidates
    )
    sparse = replace(
        artifact,
        headway_candidates=skip_only,
        headway_pairs=(),
        headway_pair_scope=EanHeadwayPairScope.SPARSE,
    )

    assert separate_all_headway_violations(sparse, plan) == ()


def test_sparse_separator_filters_candidates_after_operational_horizon() -> None:
    artifact, plan = _horizon_crossing_headway_artifact_and_plan()
    shifted_trajectories = tuple(
        replace(
            trajectory,
            visits=tuple(
                replace(
                    visit,
                    switch_time_seconds=visit.switch_time_seconds + 10.0,
                    platform_entry_time_seconds=visit.platform_entry_time_seconds + 10.0,
                    platform_exit_time_seconds=visit.platform_exit_time_seconds + 10.0,
                    exit_switch_time_seconds=visit.exit_switch_time_seconds + 10.0,
                    next_switch_time_seconds=visit.next_switch_time_seconds + 10.0,
                )
                for visit in trajectory.visits
            ),
        )
        for trajectory in plan.trajectories
    )
    sparse = replace(
        artifact, headway_pairs=(), headway_pair_scope=EanHeadwayPairScope.SPARSE
    )

    assert separate_all_headway_violations(
        sparse, replace(plan, trajectories=shifted_trajectories)
    ) == ()


def test_violation_batch_is_deterministic_by_strength_then_pair_id() -> None:
    artifact, _ = _platform_exit_wait_occupancy_artifact_and_plan()
    pair = artifact.headway_pairs[0]
    weaker_pair = replace(pair, id="a")
    stronger_pair = replace(pair, id="z")
    violations = (
        EanHeadwayViolation(weaker_pair, 0.0, 0.0, 1.0, "point_headway"),
        EanHeadwayViolation(stronger_pair, 0.0, 0.0, 2.0, "point_headway"),
    )

    selected = select_headway_violation_batch(violations, limit=2)

    assert tuple(item.pair.id for item in selected) == ("z", "a")


def _artifact_and_plan() -> tuple[EanBuildArtifact, EanMovementPlan]:
    scenario = build_three_station_scenario()
    config = build_three_station_ean_config(scenario)
    artifact = RingEanBuildArtifactBuilder(
        switch_cycle=build_three_station_ean_ring_switch_order(scenario),
    ).build(scenario, config)
    plan = EarliestAllStopEanMovementPlanBuilder().build(artifact)
    return artifact, plan


def _platform_exit_wait_occupancy_artifact_and_plan() -> tuple[EanBuildArtifact, EanMovementPlan]:
    artifact = EanBuildArtifact(
        scenario_id="platform_exit_wait_occupancy",
        config=EanConfig(
            horizon_seconds=100.0,
            tail_seconds=1.0,
            cabin_capacity=1,
            station_configs=(
                StationEanConfig(station_id="S", waiting_mode=StationWaitingMode.END_OF_PLATFORM_WAIT),
            ),
        ),
        switch_cycle=("S_entry",),
        timings=(
            SkipStopTiming(
                switch_id="S_entry",
                station_id="S",
                entry_to_platform_entry_seconds=1.0,
                min_platform_entry_to_platform_exit_seconds=1.0,
                platform_exit_to_exit_switch_seconds=1.0,
                skip_entry_to_exit_switch_seconds=3.0,
                rope_to_next_switch_seconds=5.0,
                skip_allowed=False,
            ),
        ),
        cabin_starts=(
            EanCabinStart(
                cabin_id=0,
                first_switch_id="S_entry",
                kind=EanCabinStartKind.FIXED,
                time_seconds=0.0,
            ),
            EanCabinStart(
                cabin_id=1,
                first_switch_id="S_entry",
                kind=EanCabinStartKind.FIXED,
                time_seconds=7.0,
            ),
        ),
        switch_visits=(
            SwitchVisitDefinition(cabin_id=0, visit_index=0, switch_id="S_entry"),
            SwitchVisitDefinition(cabin_id=1, visit_index=0, switch_id="S_entry"),
        ),
        switch_transitions=(
            SwitchTransition(from_switch_id="S_entry", to_switch_id="S_entry", min_seconds=5.0, max_seconds=5.0),
        ),
        headway_checkpoints=(
            HeadwayCheckpointDefinition(
                id="platform_exit::S_entry",
                kind=HeadwayCheckpointKind.PLATFORM_EXIT,
                switch_id="S_entry",
                station_id="S",
                headway_seconds=2.0,
                applies_to_serve=True,
                applies_to_skip=False,
                waiting_modes=(StationWaitingMode.END_OF_PLATFORM_WAIT,),
            ),
        ),
        headway_candidates=(
            HeadwayCandidate(
                id="candidate::platform_exit::S_entry::cabin_0::visit_0",
                checkpoint_id="platform_exit::S_entry",
                cabin_id=0,
                visit_index=0,
                time_reference=EanTimeReference.PLATFORM_EXIT_TIME,
                activation_reference=EanActivationReference.SERVE,
            ),
            HeadwayCandidate(
                id="candidate::platform_exit::S_entry::cabin_1::visit_0",
                checkpoint_id="platform_exit::S_entry",
                cabin_id=1,
                visit_index=0,
                time_reference=EanTimeReference.PLATFORM_EXIT_TIME,
                activation_reference=EanActivationReference.SERVE,
            ),
        ),
        headway_pairs=(
            HeadwayPair(
                id="headway::platform_exit::S_entry::0::1",
                checkpoint_id="platform_exit::S_entry",
                first_candidate_id="candidate::platform_exit::S_entry::cabin_0::visit_0",
                second_candidate_id="candidate::platform_exit::S_entry::cabin_1::visit_0",
                headway_seconds=2.0,
            ),
        ),
    )
    plan = EanMovementPlan(
        scenario_id=artifact.scenario_id,
        horizon_seconds=artifact.config.horizon_seconds,
        model_end_seconds=artifact.config.model_end_seconds,
        trajectories=(
            EanCabinTrajectory(
                cabin_id=0,
                visits=(
                    EanCabinVisit(
                        cabin_id=0,
                        visit_index=0,
                        switch_id="S_entry",
                        station_id="S",
                        decision=EanRouteDecision.STOP,
                        switch_time_seconds=0.0,
                        platform_entry_time_seconds=1.0,
                        platform_exit_time_seconds=10.0,
                        exit_switch_time_seconds=11.0,
                        next_switch_time_seconds=16.0,
                        wait_seconds=8.0,
                    ),
                ),
            ),
            EanCabinTrajectory(
                cabin_id=1,
                visits=(
                    EanCabinVisit(
                        cabin_id=1,
                        visit_index=0,
                        switch_id="S_entry",
                        station_id="S",
                        decision=EanRouteDecision.STOP,
                        switch_time_seconds=7.0,
                        platform_entry_time_seconds=8.0,
                        platform_exit_time_seconds=12.0,
                        exit_switch_time_seconds=13.0,
                        next_switch_time_seconds=18.0,
                        wait_seconds=3.0,
                    ),
                ),
            ),
        ),
    )
    return artifact, plan


def _horizon_crossing_headway_artifact_and_plan() -> tuple[EanBuildArtifact, EanMovementPlan]:
    artifact, plan = _platform_exit_wait_occupancy_artifact_and_plan()
    cabin_0_visit = replace(
        plan.trajectories[0].visits[0],
        switch_time_seconds=98.0,
        platform_entry_time_seconds=99.0,
        platform_exit_time_seconds=105.0,
        exit_switch_time_seconds=106.0,
        next_switch_time_seconds=111.0,
        wait_seconds=5.0,
    )
    cabin_1_visit = replace(
        plan.trajectories[1].visits[0],
        switch_time_seconds=99.0,
        platform_entry_time_seconds=100.0,
        platform_exit_time_seconds=103.0,
        exit_switch_time_seconds=104.0,
        next_switch_time_seconds=109.0,
        wait_seconds=2.0,
    )
    artifact = replace(
        artifact,
        cabin_starts=(
            replace(artifact.cabin_starts[0], time_seconds=98.0),
            replace(artifact.cabin_starts[1], time_seconds=99.0),
        ),
    )
    plan = replace(
        plan,
        horizon_formulation=EanHorizonFormulation.EXACT_TIME_ACTIVATION,
        trajectories=(
            replace(plan.trajectories[0], visits=(cabin_0_visit,)),
            replace(plan.trajectories[1], visits=(cabin_1_visit,)),
        ),
    )
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

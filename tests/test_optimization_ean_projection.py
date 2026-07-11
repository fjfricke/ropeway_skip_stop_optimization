from __future__ import annotations

from dataclasses import replace

import pytest

from ropeway_skip_stop_optimization.examples.three_station import build_three_station_scenario
from ropeway_skip_stop_optimization.examples.three_station_ean import (
    build_three_station_ean_config,
    build_three_station_ean_ring_switch_order,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    EarliestAllStopEanMovementPlanBuilder,
    EanCabinTrajectory,
    EanCabinVisit,
    EanMovementPlan,
    EanPhysicalEventKind,
    EanRouteDecision,
    RingEanBuildArtifactBuilder,
    StationEanConfig,
    StationWaitingMode,
    project_ean_movement_plan_to_physical_replay,
)


def test_ean_projection_maps_stop_visit_to_physical_events() -> None:
    scenario, artifact, plan = _scenario_artifact_plan()

    replay = project_ean_movement_plan_to_physical_replay(scenario, artifact, plan)

    first_visit_events = [
        event
        for event in replay.events
        if event.cabin_id == 0 and event.visit_index == 0
    ]
    assert tuple(event.event_kind for event in first_visit_events) == (
        EanPhysicalEventKind.ENTER_SWITCH,
        EanPhysicalEventKind.ENTER_PLATFORM,
        EanPhysicalEventKind.EXIT_PLATFORM,
        EanPhysicalEventKind.EXIT_SWITCH,
        EanPhysicalEventKind.REACH_NEXT_SWITCH,
    )
    assert tuple(event.physical_node_id for event in first_visit_events) == (
        "M_entry_lr",
        "M_platform_entry_lr",
        "M_platform_exit_lr",
        "M_exit_lr",
        "R_entry_lr",
    )
    assert first_visit_events[1].source_segment_ids == ("M_lr_approach_fast", "M_lr_brake")
    assert first_visit_events[2].source_segment_ids == ("M_lr_platform",)
    assert first_visit_events[3].source_segment_ids == ("M_lr_accelerate", "M_lr_depart_fast")
    assert first_visit_events[4].source_segment_ids == ("M_exit_lr_to_R_entry_lr",)
    assert replay.events == tuple(sorted(replay.events, key=lambda event: event.time_seconds))


def test_ean_projection_maps_skip_visit_without_platform_events() -> None:
    scenario, artifact, plan = _scenario_artifact_plan()
    visit = _first_visit(plan)
    skipped_visit = replace(
        visit,
        decision=EanRouteDecision.SKIP,
        platform_entry_time_seconds=None,
        platform_exit_time_seconds=None,
        exit_switch_time_seconds=visit.switch_time_seconds + 20 / 5,
        next_switch_time_seconds=visit.switch_time_seconds + 20 / 5 + 150 / 5,
    )
    skipped_plan = _replace_visit(plan, skipped_visit)

    replay = project_ean_movement_plan_to_physical_replay(scenario, artifact, skipped_plan)

    first_visit_events = [
        event
        for event in replay.events
        if event.cabin_id == visit.cabin_id and event.visit_index == visit.visit_index
    ]
    assert tuple(event.event_kind for event in first_visit_events) == (
        EanPhysicalEventKind.ENTER_SWITCH,
        EanPhysicalEventKind.EXIT_SWITCH,
        EanPhysicalEventKind.REACH_NEXT_SWITCH,
    )
    assert first_visit_events[1].source_segment_ids == ("M_lr_skip_bypass",)


def test_ean_projection_emits_platform_exit_wait_events_for_end_wait() -> None:
    scenario, artifact, plan = _scenario_artifact_plan()
    visit = _first_visit(plan)
    waited_visit = replace(
        visit,
        wait_seconds=5.0,
        platform_exit_time_seconds=visit.platform_exit_time_seconds + 5.0,
        exit_switch_time_seconds=visit.exit_switch_time_seconds + 5.0,
        next_switch_time_seconds=visit.next_switch_time_seconds + 5.0,
    )
    waited_plan = _replace_visit_and_shift_following(plan, waited_visit, shift_seconds=5.0)
    waited_artifact = replace(
        artifact,
        config=replace(
            artifact.config,
            station_configs=tuple(
                replace(config, waiting_mode=StationWaitingMode.END_OF_PLATFORM_WAIT)
                if config.station_id == visit.station_id
                else config
                for config in artifact.config.station_configs
            ),
        ),
    )

    replay = project_ean_movement_plan_to_physical_replay(scenario, waited_artifact, waited_plan)

    first_visit_events = [
        event
        for event in replay.events
        if event.cabin_id == visit.cabin_id and event.visit_index == visit.visit_index
    ]
    wait_events = [
        event
        for event in first_visit_events
        if event.event_kind in {EanPhysicalEventKind.ENTER_WAIT, EanPhysicalEventKind.EXIT_WAIT}
    ]
    assert tuple(event.event_kind for event in wait_events) == (
        EanPhysicalEventKind.ENTER_WAIT,
        EanPhysicalEventKind.EXIT_WAIT,
    )
    assert all(event.physical_node_id == "M_platform_exit_lr" for event in wait_events)
    assert wait_events[0].time_seconds == pytest.approx(visit.platform_exit_time_seconds)
    assert wait_events[1].time_seconds == pytest.approx(waited_visit.platform_exit_time_seconds)
    exit_platform_event = next(
        event
        for event in first_visit_events
        if event.event_kind is EanPhysicalEventKind.EXIT_PLATFORM
    )
    assert exit_platform_event.source_segment_ids == ()


def test_ean_projection_rejects_fifo_waits_until_position_traces_exist() -> None:
    scenario, artifact, plan = _scenario_artifact_plan()
    visit = _first_visit(plan)
    waited_visit = replace(
        visit,
        wait_seconds=5.0,
        platform_exit_time_seconds=visit.platform_exit_time_seconds + 5.0,
        exit_switch_time_seconds=visit.exit_switch_time_seconds + 5.0,
        next_switch_time_seconds=visit.next_switch_time_seconds + 5.0,
    )
    waited_plan = _replace_visit_and_shift_following(plan, waited_visit, shift_seconds=5.0)
    fifo_artifact = replace(
        artifact,
        config=replace(
            artifact.config,
            station_configs=tuple(
                StationEanConfig(
                    station_id=config.station_id,
                    waiting_mode=StationWaitingMode.STATION_FIFO_BUFFER,
                    fifo_capacity=4,
                )
                if config.station_id == visit.station_id
                else config
                for config in artifact.config.station_configs
            ),
        ),
    )

    with pytest.raises(NotImplementedError, match="station FIFO position traces"):
        project_ean_movement_plan_to_physical_replay(scenario, fifo_artifact, waited_plan)


def test_ean_projection_keeps_one_post_horizon_event_per_cabin_for_interpolation() -> None:
    scenario, artifact, plan = _scenario_artifact_plan()

    replay = project_ean_movement_plan_to_physical_replay(scenario, artifact, plan)

    events_after_horizon_by_cabin: dict[int, list] = {}
    for event in replay.events:
        if event.time_seconds > replay.model_end_seconds:
            events_after_horizon_by_cabin.setdefault(event.cabin_id, []).append(event)

    assert set(events_after_horizon_by_cabin) == {trajectory.cabin_id for trajectory in plan.trajectories}
    assert all(len(events) == 1 for events in events_after_horizon_by_cabin.values())


def _scenario_artifact_plan():
    scenario = build_three_station_scenario()
    config = build_three_station_ean_config(scenario)
    artifact = RingEanBuildArtifactBuilder(
        switch_cycle=build_three_station_ean_ring_switch_order(scenario),
    ).build(scenario, config)
    plan = EarliestAllStopEanMovementPlanBuilder().build(artifact)
    return scenario, artifact, plan


def _first_visit(plan: EanMovementPlan) -> EanCabinVisit:
    return plan.trajectories[0].visits[0]


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


def _replace_visit_and_shift_following(
    plan: EanMovementPlan,
    replacement: EanCabinVisit,
    shift_seconds: float,
) -> EanMovementPlan:
    trajectories: list[EanCabinTrajectory] = []
    for trajectory in plan.trajectories:
        if trajectory.cabin_id != replacement.cabin_id:
            trajectories.append(trajectory)
            continue
        shifted_visits: list[EanCabinVisit] = []
        for visit in trajectory.visits:
            if visit.visit_index == replacement.visit_index:
                shifted_visits.append(replacement)
            elif visit.visit_index > replacement.visit_index:
                shifted_visits.append(_shift_visit(visit, shift_seconds))
            else:
                shifted_visits.append(visit)
        trajectories.append(replace(trajectory, visits=tuple(shifted_visits)))
    return replace(plan, trajectories=tuple(trajectories))


def _shift_visit(visit: EanCabinVisit, shift_seconds: float) -> EanCabinVisit:
    return replace(
        visit,
        switch_time_seconds=visit.switch_time_seconds + shift_seconds,
        platform_entry_time_seconds=(
            visit.platform_entry_time_seconds + shift_seconds
            if visit.platform_entry_time_seconds is not None
            else None
        ),
        platform_exit_time_seconds=(
            visit.platform_exit_time_seconds + shift_seconds
            if visit.platform_exit_time_seconds is not None
            else None
        ),
        exit_switch_time_seconds=visit.exit_switch_time_seconds + shift_seconds,
        next_switch_time_seconds=visit.next_switch_time_seconds + shift_seconds,
    )

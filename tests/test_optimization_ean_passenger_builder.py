from __future__ import annotations

import logging
from dataclasses import replace
from datetime import time

from ropeway_skip_stop_optimization.examples.three_station import build_three_station_scenario
from ropeway_skip_stop_optimization.models import Demand, OperatingParameters, Scenario
from ropeway_skip_stop_optimization.optimization.ean import (
    EanBuildArtifact,
    EanCabinStart,
    EanCabinStartKind,
    EanConfig,
    EanPassengerCandidateBuilder,
    EanPassengerCandidateBuildResult,
    EanOptimizationConfig,
    EanActivationReference,
    EanTimeReference,
    HeadwayCandidate,
    HeadwayCheckpointDefinition,
    HeadwayCheckpointKind,
    SkipStopTiming,
    StationEanConfig,
    StationWaitingMode,
    SwitchTransition,
    SwitchVisitDefinition,
)


def test_ean_passenger_candidate_builder_expands_demand_groups_and_rides() -> None:
    scenario = replace(
        build_three_station_scenario(),
        demands=(Demand(arrival_time=time(8, 1), origin="L", destination="R", count=3),),
    )
    example_config = _three_station_artifact(scenario)

    result = EanPassengerCandidateBuilder().build(scenario, example_config)

    assert len(result.demand_groups) == 1
    group = result.demand_groups[0]
    assert group.id == "demand::0"
    assert group.origin_station_id == "L"
    assert group.destination_station_id == "R"
    assert group.release_time_seconds == 60.0
    assert group.count == 3
    assert result.ride_candidates
    assert all(candidate.demand_group_id == "demand::0" for candidate in result.ride_candidates)
    assert all(candidate.board_visit_index < candidate.alight_visit_index for candidate in result.ride_candidates)


def test_ean_passenger_candidate_builder_prunes_full_ring_span_candidates() -> None:
    scenario = _minimal_scenario(
        demands=(Demand(arrival_time=time(8, 0), origin="A", destination="B", count=1),),
    )
    artifact = _two_station_artifact(non_ring=False, horizon_seconds=30.0)

    result = EanPassengerCandidateBuilder().build(scenario, artifact)

    assert _candidate_spans(result) == [1, 1]


def test_ean_passenger_candidate_builder_can_disable_single_ring_dominated_ride_pruning() -> None:
    scenario = _minimal_scenario(
        demands=(Demand(arrival_time=time(8, 0), origin="A", destination="B", count=1),),
    )
    artifact = _two_station_artifact(non_ring=False, horizon_seconds=30.0)

    result = EanPassengerCandidateBuilder(
        optimization_config=EanOptimizationConfig(enable_single_ring_dominated_ride_pruning=False),
    ).build(scenario, artifact)

    assert _candidate_spans(result) == [1, 1, 3]


def test_ean_passenger_candidate_builder_warns_when_ring_span_pruning_cannot_apply(caplog) -> None:
    scenario = _minimal_scenario(
        demands=(Demand(arrival_time=time(8, 0), origin="A", destination="B", count=1),),
    )
    artifact = _two_station_artifact(non_ring=True, horizon_seconds=30.0)

    with caplog.at_level(logging.WARNING):
        result = EanPassengerCandidateBuilder().build(scenario, artifact)

    assert _candidate_spans(result) == [1, 1, 3]
    assert "ring-span pruning skipped" in caplog.text


def test_ean_passenger_candidate_builder_prunes_candidates_that_cannot_alight_within_horizon() -> None:
    scenario = _minimal_scenario(
        demands=(Demand(arrival_time=time(8, 0), origin="A", destination="B", count=1),),
    )
    artifact = _two_station_artifact(non_ring=False, horizon_seconds=20.0)

    result = EanPassengerCandidateBuilder().build(scenario, artifact)

    assert _candidate_spans(result) == [1]


def test_ean_passenger_candidate_builder_prunes_candidates_released_after_horizon() -> None:
    scenario = _minimal_scenario(
        demands=(Demand(arrival_time=time(8, 1), origin="A", destination="B", count=1),),
    )
    artifact = _two_station_artifact(non_ring=False, horizon_seconds=20.0)

    result = EanPassengerCandidateBuilder().build(scenario, artifact)

    assert result.ride_candidates == ()


def test_ean_passenger_candidate_builder_can_disable_horizon_pruning() -> None:
    scenario = _minimal_scenario(
        demands=(Demand(arrival_time=time(8, 1), origin="A", destination="B", count=1),),
    )
    artifact = _two_station_artifact(non_ring=False, horizon_seconds=20.0)

    result = EanPassengerCandidateBuilder(
        optimization_config=EanOptimizationConfig(enable_candidate_horizon_pruning=False),
    ).build(scenario, artifact)

    assert _candidate_spans(result) == [1, 1]


def test_ean_optimization_config_parses_cli_selection() -> None:
    assert EanOptimizationConfig.from_selection("all") == EanOptimizationConfig()
    assert EanOptimizationConfig.from_selection("none") == EanOptimizationConfig.none()
    assert not EanOptimizationConfig.from_selection("all").enable_tight_big_m_bounds
    assert EanOptimizationConfig.from_selection("all").selection_label() == "all"
    assert EanOptimizationConfig.from_selection(
        "candidate_horizon_pruning,slot_time_relaxation_strengthening"
    ) == EanOptimizationConfig(
        enable_candidate_horizon_pruning=True,
        enable_single_ring_dominated_ride_pruning=False,
        enable_slot_time_relaxation_strengthening=True,
    )
    assert EanOptimizationConfig.from_selection("tight_big_m_bounds") == EanOptimizationConfig(
        enable_candidate_horizon_pruning=False,
        enable_single_ring_dominated_ride_pruning=False,
        enable_slot_time_relaxation_strengthening=False,
        enable_tight_big_m_bounds=True,
    )


def _three_station_artifact(scenario):
    from ropeway_skip_stop_optimization.examples.three_station import ThreeStationExample

    example = ThreeStationExample()
    config = example.build_ean_config(scenario)
    return example.build_ean_artifact_builder(scenario, config).build(scenario, config)


def _candidate_spans(result: EanPassengerCandidateBuildResult) -> list[int]:
    return sorted(
        candidate.alight_visit_index - candidate.board_visit_index
        for candidate in result.ride_candidates
    )


def _minimal_scenario(demands: tuple[Demand, ...]) -> Scenario:
    return Scenario(
        id="minimal_ean_candidate_builder",
        service_start_time=time(8, 0),
        service_end_time=time(8, 1),
        stations=(),
        physical_nodes=(),
        track_segments=(),
        station_routes=(),
        cabins=(),
        cabin_initial_states=(),
        demands=demands,
        operating=OperatingParameters(
            rope_speed_m_per_s=5.0,
            station_speed_m_per_s=0.5,
            cabin_capacity=2,
            cabin_length_m=3.0,
            min_clearance_m=0.5,
        ),
    )


def _two_station_artifact(non_ring: bool, horizon_seconds: float) -> EanBuildArtifact:
    transition_pairs = (("A_entry", "A_entry"), ("B_entry", "B_entry")) if non_ring else (
        ("A_entry", "B_entry"),
        ("B_entry", "A_entry"),
    )
    return EanBuildArtifact(
        scenario_id="minimal_ean_candidate_builder",
        config=EanConfig(
            horizon_seconds=horizon_seconds,
            tail_seconds=0.0,
            cabin_capacity=2,
            station_configs=(
                StationEanConfig(station_id="A", waiting_mode=StationWaitingMode.NO_WAITING),
                StationEanConfig(station_id="B", waiting_mode=StationWaitingMode.NO_WAITING),
            ),
        ),
        state_ids=("A_entry", "B_entry"),
        timings=(
            SkipStopTiming(
                switch_id="A_entry",
                station_id="A",
                entry_to_platform_entry_seconds=1.0,
                min_platform_entry_to_platform_exit_seconds=1.0,
                platform_exit_to_exit_switch_seconds=1.0,
                skip_entry_to_exit_switch_seconds=3.0,
                rope_to_next_switch_seconds=5.0,
                skip_allowed=False,
            ),
            SkipStopTiming(
                switch_id="B_entry",
                station_id="B",
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
                first_switch_id="A_entry",
                kind=EanCabinStartKind.FIXED,
                time_seconds=0.0,
            ),
        ),
        switch_visits=tuple(
            SwitchVisitDefinition(
                cabin_id=0,
                visit_index=visit_index,
                switch_id=("A_entry", "B_entry")[visit_index % 2],
            )
            for visit_index in range(4)
        ),
        switch_transitions=tuple(
            SwitchTransition(from_switch_id=from_switch_id, to_switch_id=to_switch_id, min_seconds=5.0, max_seconds=5.0)
            for from_switch_id, to_switch_id in transition_pairs
        ),
        headway_checkpoints=(
            HeadwayCheckpointDefinition(
                id="platform_entry::A_entry",
                kind=HeadwayCheckpointKind.PLATFORM_ENTRY,
                switch_id="A_entry",
                station_id="A",
                headway_seconds=1.0,
                applies_to_serve=True,
                applies_to_skip=False,
                waiting_modes=(StationWaitingMode.NO_WAITING,),
            ),
        ),
        headway_candidates=(
            HeadwayCandidate(
                id="candidate::platform_entry::A_entry::cabin_0::visit_0",
                checkpoint_id="platform_entry::A_entry",
                cabin_id=0,
                visit_index=0,
                time_reference=EanTimeReference.PLATFORM_ENTRY_TIME,
                activation_reference=EanActivationReference.SERVE,
            ),
        ),
        headway_pairs=(),
    )

from __future__ import annotations

from ropeway_skip_stop_optimization.examples.circular_skip_stop import (
    FiveStationCircleCwFullNoSkipNoWaitExample,
    FiveStationCircleCwFullSkipNoWaitExample,
    FiveStationCircleCwHalfNoSkipNoWaitExample,
    FiveStationCircleCwHalfSkipNoWaitExample,
    FiveStationCircleCwHalfSkipWaitExample,
    build_five_station_circle_cw_ean_pattern_definition,
    build_five_station_circle_cw_full_no_skip_no_wait_ean_config,
    build_five_station_circle_cw_full_no_skip_no_wait_scenario,
    build_five_station_circle_cw_full_skip_no_wait_ean_config,
    build_five_station_circle_cw_full_skip_no_wait_scenario,
    build_five_station_circle_cw_half_no_skip_no_wait_ean_config,
    build_five_station_circle_cw_half_no_skip_no_wait_scenario,
    build_five_station_circle_cw_half_skip_no_wait_ean_config,
    build_five_station_circle_cw_half_skip_no_wait_scenario,
    build_five_station_circle_cw_half_skip_wait_ean_config,
    build_five_station_circle_cw_half_skip_wait_scenario,
)
from ropeway_skip_stop_optimization.examples.registry import get_example
from ropeway_skip_stop_optimization.models import StationKind
from ropeway_skip_stop_optimization.optimization.ean import (
    ContinuousAllStopMaxCabinStartBuilder,
    StationWaitingMode,
)


def test_five_station_circle_cw_scenarios_validate() -> None:
    scenario_cases = (
        (build_five_station_circle_cw_full_no_skip_no_wait_scenario(), 128),
        (build_five_station_circle_cw_full_skip_no_wait_scenario(), 128),
        (build_five_station_circle_cw_half_no_skip_no_wait_scenario(), 64),
        (build_five_station_circle_cw_half_skip_no_wait_scenario(), 64),
        (build_five_station_circle_cw_half_skip_wait_scenario(), 64),
    )

    for scenario, expected_demand_count in scenario_cases:
        assert tuple(station.id for station in scenario.stations) == ("A", "B", "C", "D", "E")
        assert {station.kind for station in scenario.stations} == {StationKind.SERVICE}
        assert len(scenario.demands) == 20
        assert {demand.arrival_time for demand in scenario.demands} == {scenario.service_start_time}
        assert {demand.count for demand in scenario.demands} == {expected_demand_count}
        assert {
            (demand.origin, demand.destination)
            for demand in scenario.demands
        } == {
            (origin, destination)
            for origin in ("A", "B", "C", "D", "E")
            for destination in ("A", "B", "C", "D", "E")
            if origin != destination
        }


def test_five_station_circle_cw_skip_route_variants() -> None:
    no_skip_scenarios = (
        build_five_station_circle_cw_full_no_skip_no_wait_scenario(),
        build_five_station_circle_cw_half_no_skip_no_wait_scenario(),
    )
    skip_scenarios = (
        build_five_station_circle_cw_full_skip_no_wait_scenario(),
        build_five_station_circle_cw_half_skip_no_wait_scenario(),
        build_five_station_circle_cw_half_skip_wait_scenario(),
    )

    for scenario in no_skip_scenarios:
        assert len([route for route in scenario.station_routes if route.kind.value == "skip"]) == 0
    for scenario in skip_scenarios:
        assert len([route for route in scenario.station_routes if route.kind.value == "skip"]) == 5


def test_five_station_circle_cw_ean_waiting_modes() -> None:
    no_wait_configs = (
        build_five_station_circle_cw_full_no_skip_no_wait_ean_config(),
        build_five_station_circle_cw_full_skip_no_wait_ean_config(),
        build_five_station_circle_cw_half_no_skip_no_wait_ean_config(),
        build_five_station_circle_cw_half_skip_no_wait_ean_config(),
    )
    wait_configs = (build_five_station_circle_cw_half_skip_wait_ean_config(),)

    for config in no_wait_configs:
        assert {station_config.waiting_mode for station_config in config.station_configs} == {StationWaitingMode.NO_WAITING}
    for config in wait_configs:
        assert {station_config.waiting_mode for station_config in config.station_configs} == {
            StationWaitingMode.END_OF_PLATFORM_WAIT
        }


def test_five_station_circle_cw_pattern_has_stable_state_order() -> None:
    scenario = build_five_station_circle_cw_full_no_skip_no_wait_scenario()

    assert (
        build_five_station_circle_cw_ean_pattern_definition(scenario).state_node_ids
        == (
        "A_entry_cw",
        "B_entry_cw",
        "C_entry_cw",
        "D_entry_cw",
        "E_entry_cw",
        )
    )
    assert any(
        segment.id == "E_exit_cw_to_A_entry_cw"
        and segment.from_node_id == "E_exit_cw"
        and segment.to_node_id == "A_entry_cw"
        for segment in scenario.track_segments
    )


def test_five_station_circle_cw_full_examples_build_ean_artifacts_with_all_start_cabins() -> None:
    for example in (
        FiveStationCircleCwFullNoSkipNoWaitExample(),
        FiveStationCircleCwFullSkipNoWaitExample(),
    ):
        scenario = example.build_scenario()
        config = example.build_ean_config(scenario)
        pattern_definition = build_five_station_circle_cw_ean_pattern_definition(scenario)
        artifact = example.build_ean_artifact_builder(scenario, config).build(scenario, config)
        assert artifact.movement_network is not None
        pattern = artifact.movement_network.pattern(artifact.circulation_pattern_ids[0])
        max_starts = ContinuousAllStopMaxCabinStartBuilder().build(
            scenario=scenario,
            config=config,
            network=artifact.movement_network,
            pattern=pattern,
        )

        assert artifact.scenario_id == scenario.id
        assert artifact.circulation_state_ids == pattern_definition.state_node_ids
        assert len(artifact.timings) == 5
        assert artifact.cabin_starts == max_starts
        assert artifact.cabin_starts


def test_five_station_circle_cw_half_examples_build_ean_artifacts_with_every_second_start_cabin() -> None:
    for example in (
        FiveStationCircleCwHalfNoSkipNoWaitExample(),
        FiveStationCircleCwHalfSkipNoWaitExample(),
        FiveStationCircleCwHalfSkipWaitExample(),
    ):
        scenario = example.build_scenario()
        config = example.build_ean_config(scenario)
        pattern_definition = build_five_station_circle_cw_ean_pattern_definition(scenario)
        artifact = example.build_ean_artifact_builder(scenario, config).build(scenario, config)
        assert artifact.movement_network is not None
        pattern = artifact.movement_network.pattern(artifact.circulation_pattern_ids[0])
        max_starts = ContinuousAllStopMaxCabinStartBuilder().build(
            scenario=scenario,
            config=config,
            network=artifact.movement_network,
            pattern=pattern,
        )

        assert artifact.scenario_id == scenario.id
        assert artifact.circulation_state_ids == pattern_definition.state_node_ids
        assert len(artifact.timings) == 5
        assert artifact.cabin_starts == max_starts[::2]
        assert artifact.cabin_starts


def test_five_station_circle_cw_demand_just_reaches_all_stop_capacity() -> None:
    _assert_uniform_demand_reaches_all_stop_capacity(
        example=FiveStationCircleCwFullNoSkipNoWaitExample(),
        expected_bottleneck_section_seats=1280,
        expected_demand_count=128,
    )


def test_five_station_circle_cw_half_demand_just_reaches_half_all_stop_capacity() -> None:
    _assert_uniform_demand_reaches_all_stop_capacity(
        example=FiveStationCircleCwHalfNoSkipNoWaitExample(),
        expected_bottleneck_section_seats=640,
        expected_demand_count=64,
    )


def _assert_uniform_demand_reaches_all_stop_capacity(
    example: FiveStationCircleCwFullNoSkipNoWaitExample,
    expected_bottleneck_section_seats: int,
    expected_demand_count: int,
) -> None:
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    artifact = example.build_ean_artifact_builder(scenario, config).build(scenario, config)
    transition_by_switch_id = {transition.from_switch_id: transition for transition in artifact.switch_transitions}
    switch_index_by_id = {switch_id: index for index, switch_id in enumerate(artifact.circulation_state_ids)}
    complete_traversals_by_switch_id = {switch_id: 0 for switch_id in artifact.circulation_state_ids}

    for start in artifact.cabin_starts:
        switch_index = switch_index_by_id[start.first_switch_id]
        elapsed_seconds = start.time_seconds
        visit_offset = 0
        while elapsed_seconds <= config.model_end_seconds:
            switch_id = artifact.circulation_state_ids[(switch_index + visit_offset) % len(artifact.circulation_state_ids)]
            transition = transition_by_switch_id[switch_id]
            if elapsed_seconds + transition.min_seconds <= config.model_end_seconds:
                complete_traversals_by_switch_id[switch_id] += 1
            elapsed_seconds += transition.min_seconds
            visit_offset += 1

    bottleneck_section_seats = min(complete_traversals_by_switch_id.values()) * scenario.operating.cabin_capacity
    section_load_per_od_count = len(scenario.stations) * (len(scenario.stations) - 1) // 2
    demand_count = next(iter({demand.count for demand in scenario.demands}))

    assert bottleneck_section_seats == expected_bottleneck_section_seats
    assert section_load_per_od_count == 10
    assert demand_count == expected_demand_count
    assert demand_count * section_load_per_od_count == bottleneck_section_seats


def test_five_station_circle_cw_examples_are_registered() -> None:
    assert isinstance(
        get_example("five_station_circle_cw_full_no_skip_no_wait_v0"),
        FiveStationCircleCwFullNoSkipNoWaitExample,
    )
    assert isinstance(
        get_example("five_station_circle_cw_full_skip_no_wait_v0"),
        FiveStationCircleCwFullSkipNoWaitExample,
    )
    assert isinstance(
        get_example("five_station_circle_cw_half_no_skip_no_wait_v0"),
        FiveStationCircleCwHalfNoSkipNoWaitExample,
    )
    assert isinstance(
        get_example("five_station_circle_cw_half_skip_no_wait_v0"),
        FiveStationCircleCwHalfSkipNoWaitExample,
    )
    assert isinstance(
        get_example("five_station_circle_cw_half_skip_wait_v0"),
        FiveStationCircleCwHalfSkipWaitExample,
    )

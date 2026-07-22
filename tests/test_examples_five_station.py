from __future__ import annotations

from ropeway_skip_stop_optimization.examples.linear_skip_stop import (
    FiveStationExample,
    FiveStationHalfNoSkipNoWaitExample,
    FiveStationNoWaitExample,
    build_five_station_ean_config,
    build_five_station_ean_ring_switch_order,
    build_five_station_half_no_skip_no_wait_ean_config,
    build_five_station_half_no_skip_no_wait_scenario,
    build_five_station_no_wait_ean_config,
    build_five_station_no_wait_scenario,
    build_five_station_scenario,
)
from ropeway_skip_stop_optimization.examples.registry import get_example
from ropeway_skip_stop_optimization.models import StationKind
from ropeway_skip_stop_optimization.optimization.ean import ContinuousAllStopMaxCabinStartBuilder, StationWaitingMode


def test_five_station_scenario_validates_with_three_middle_skip_stations() -> None:
    scenario = build_five_station_scenario()

    assert scenario.id == "five_station_v0"
    assert tuple(station.id for station in scenario.stations) == ("L", "A", "B", "C", "R")
    assert tuple(station.kind for station in scenario.stations) == (
        StationKind.TERMINAL,
        StationKind.SERVICE,
        StationKind.SERVICE,
        StationKind.SERVICE,
        StationKind.TERMINAL,
    )
    assert len([route for route in scenario.station_routes if route.kind.value == "skip"]) == 6
    assert len(scenario.demands) == 20
    assert {demand.arrival_time for demand in scenario.demands} == {scenario.service_start_time}
    assert {demand.count for demand in scenario.demands} == {160}
    assert {
        (demand.origin, demand.destination)
        for demand in scenario.demands
    } == {
        (origin, destination)
        for origin in ("L", "A", "B", "C", "R")
        for destination in ("L", "A", "B", "C", "R")
        if origin != destination
    }


def test_five_station_terminal_platform_exits_do_not_allow_waiting() -> None:
    scenario = build_five_station_scenario()
    waiting_node_ids = {node.id for node in scenario.physical_nodes if node.allows_waiting}

    assert "L_platform_exit" not in waiting_node_ids
    assert "R_platform_exit" not in waiting_node_ids


def test_five_station_ean_config_waits_only_at_middle_stations() -> None:
    config = build_five_station_ean_config()

    waiting_mode_by_station_id = {
        station_config.station_id: station_config.waiting_mode
        for station_config in config.station_configs
    }
    assert waiting_mode_by_station_id == {
        "L": StationWaitingMode.NO_WAITING,
        "A": StationWaitingMode.END_OF_PLATFORM_WAIT,
        "B": StationWaitingMode.END_OF_PLATFORM_WAIT,
        "C": StationWaitingMode.END_OF_PLATFORM_WAIT,
        "R": StationWaitingMode.NO_WAITING,
    }


def test_five_station_no_wait_ean_config_keeps_skip_and_disables_all_station_waiting() -> None:
    scenario = build_five_station_no_wait_scenario()
    config = build_five_station_no_wait_ean_config(scenario)

    assert scenario.id == "five_station_no_wait_v0"
    assert len([route for route in scenario.station_routes if route.kind.value == "skip"]) == 6
    assert len(scenario.demands) == 20
    assert {demand.count for demand in scenario.demands} == {160}
    assert {
        station_config.station_id: station_config.waiting_mode
        for station_config in config.station_configs
    } == {
        "L": StationWaitingMode.NO_WAITING,
        "A": StationWaitingMode.NO_WAITING,
        "B": StationWaitingMode.NO_WAITING,
        "C": StationWaitingMode.NO_WAITING,
        "R": StationWaitingMode.NO_WAITING,
    }


def test_five_station_ean_ring_order_matches_physical_ring() -> None:
    assert build_five_station_ean_ring_switch_order() == (
        "A_entry_lr",
        "B_entry_lr",
        "C_entry_lr",
        "R_entry_lr",
        "C_entry_rl",
        "B_entry_rl",
        "A_entry_rl",
        "L_entry_rl",
    )


def test_five_station_example_builds_ean_artifact() -> None:
    example = FiveStationExample()
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    artifact = example.build_ean_artifact_builder(scenario, config).build(scenario, config)

    assert artifact.scenario_id == "five_station_v0"
    assert artifact.circulation_state_ids == build_five_station_ean_ring_switch_order(scenario)
    assert len(artifact.timings) == 8
    assert {
        timing.switch_id
        for timing in artifact.timings
        if timing.skip_allowed
    } == {
        "A_entry_lr",
        "B_entry_lr",
        "C_entry_lr",
        "A_entry_rl",
        "B_entry_rl",
        "C_entry_rl",
    }
    assert len(artifact.cabin_starts) > 0


def test_five_station_example_uses_every_second_max_start_cabin() -> None:
    example = FiveStationExample()
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    switch_cycle = build_five_station_ean_ring_switch_order(scenario)

    max_starts = ContinuousAllStopMaxCabinStartBuilder(switch_cycle=switch_cycle).build(
        scenario=scenario,
        config=config,
        target_switch_ids=frozenset(switch_cycle),
    )
    artifact = example.build_ean_artifact_builder(scenario, config).build(scenario, config)

    assert artifact.cabin_starts == max_starts[::2]


def test_five_station_no_wait_example_uses_all_max_start_cabins_with_skip_but_no_platform_exit_headways() -> None:
    example = FiveStationNoWaitExample()
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    switch_cycle = build_five_station_ean_ring_switch_order(scenario)

    max_starts = ContinuousAllStopMaxCabinStartBuilder(switch_cycle=switch_cycle).build(
        scenario=scenario,
        config=config,
        target_switch_ids=frozenset(switch_cycle),
    )
    artifact = example.build_ean_artifact_builder(scenario, config).build(scenario, config)

    assert artifact.cabin_starts == max_starts
    assert {
        timing.switch_id
        for timing in artifact.timings
        if timing.skip_allowed
    } == {
        "A_entry_lr",
        "B_entry_lr",
        "C_entry_lr",
        "A_entry_rl",
        "B_entry_rl",
        "C_entry_rl",
    }
    assert not {
        checkpoint.id
        for checkpoint in artifact.headway_checkpoints
        if checkpoint.kind.value == "platform_exit"
    }


def test_five_station_half_no_skip_no_wait_config_disables_skip_and_all_station_waiting() -> None:
    scenario = build_five_station_half_no_skip_no_wait_scenario()
    config = build_five_station_half_no_skip_no_wait_ean_config(scenario)

    assert scenario.id == "five_station_half_no_skip_no_wait_v0"
    assert len([route for route in scenario.station_routes if route.kind.value == "skip"]) == 0
    assert len(scenario.demands) == 20
    assert {demand.count for demand in scenario.demands} == {160}
    assert {
        station_config.station_id: station_config.waiting_mode
        for station_config in config.station_configs
    } == {
        "L": StationWaitingMode.NO_WAITING,
        "A": StationWaitingMode.NO_WAITING,
        "B": StationWaitingMode.NO_WAITING,
        "C": StationWaitingMode.NO_WAITING,
        "R": StationWaitingMode.NO_WAITING,
    }


def test_five_station_half_no_skip_no_wait_example_uses_half_max_start_cabins_without_skips() -> None:
    example = FiveStationHalfNoSkipNoWaitExample()
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    switch_cycle = build_five_station_ean_ring_switch_order(scenario)

    max_starts = ContinuousAllStopMaxCabinStartBuilder(switch_cycle=switch_cycle).build(
        scenario=scenario,
        config=config,
        target_switch_ids=frozenset(switch_cycle),
    )
    artifact = example.build_ean_artifact_builder(scenario, config).build(scenario, config)

    assert artifact.cabin_starts == max_starts[::2]
    assert not {timing.switch_id for timing in artifact.timings if timing.skip_allowed}
    assert not {
        checkpoint.id
        for checkpoint in artifact.headway_checkpoints
        if checkpoint.kind.value == "platform_exit"
    }


def test_five_station_examples_are_registered() -> None:
    assert isinstance(get_example("five_station_v0"), FiveStationExample)
    assert isinstance(get_example("five_station_no_wait_v0"), FiveStationNoWaitExample)
    assert isinstance(get_example("five_station_half_no_skip_no_wait_v0"), FiveStationHalfNoSkipNoWaitExample)

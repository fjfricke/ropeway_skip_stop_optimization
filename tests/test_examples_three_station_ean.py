from __future__ import annotations

from dataclasses import replace

import pytest

from ropeway_skip_stop_optimization.examples.three_station import (
    ThreeStationExample,
    ThreeStationFullNoSkipNoWaitExample,
    ThreeStationHalfNoSkipNoWaitExample,
    build_three_station_no_skip_no_wait_scenario,
    build_three_station_scenario,
)
from ropeway_skip_stop_optimization.examples.three_station_ean import (
    build_three_station_ean_config,
    build_three_station_ean_ring_switch_order,
)
from ropeway_skip_stop_optimization.models import PhysicalNodeKind
from ropeway_skip_stop_optimization.optimization.ean import StationWaitingMode


def test_three_station_ean_config_allows_end_of_platform_waiting_at_middle_station() -> None:
    config = build_three_station_ean_config()

    assert config.horizon_seconds == 20 * 60
    assert config.tail_seconds == 0.0
    assert config.model_end_seconds == config.horizon_seconds
    assert config.cabin_capacity == 8
    assert {
        station_config.station_id: station_config.waiting_mode
        for station_config in config.station_configs
    } == {
        "L": StationWaitingMode.NO_WAITING,
        "M": StationWaitingMode.END_OF_PLATFORM_WAIT,
        "R": StationWaitingMode.NO_WAITING,
    }


def test_three_station_no_skip_no_wait_ean_config_disables_all_station_waiting() -> None:
    example = ThreeStationFullNoSkipNoWaitExample()
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)

    assert scenario.id == "three_station_full_no_skip_no_wait_v0"
    assert {
        station_config.station_id: station_config.waiting_mode
        for station_config in config.station_configs
    } == {
        "L": StationWaitingMode.NO_WAITING,
        "M": StationWaitingMode.NO_WAITING,
        "R": StationWaitingMode.NO_WAITING,
    }


def test_three_station_no_skip_no_wait_ean_artifact_disallows_middle_skips() -> None:
    example = ThreeStationFullNoSkipNoWaitExample()
    scenario = build_three_station_no_skip_no_wait_scenario(example.metadata.id)
    config = example.build_ean_config(scenario)
    artifact = example.build_ean_artifact_builder(scenario, config).build(scenario, config)

    assert not {timing.switch_id for timing in artifact.timings if timing.skip_allowed}


def test_three_station_full_and_half_variants_use_expected_ean_start_counts() -> None:
    full_example = ThreeStationFullNoSkipNoWaitExample()
    full_scenario = full_example.build_scenario()
    full_config = full_example.build_ean_config(full_scenario)
    full_artifact = full_example.build_ean_artifact_builder(full_scenario, full_config).build(
        full_scenario,
        full_config,
    )

    half_no_skip_example = ThreeStationHalfNoSkipNoWaitExample()
    half_no_skip_scenario = half_no_skip_example.build_scenario()
    half_no_skip_config = half_no_skip_example.build_ean_config(half_no_skip_scenario)
    half_no_skip_artifact = half_no_skip_example.build_ean_artifact_builder(
        half_no_skip_scenario,
        half_no_skip_config,
    ).build(half_no_skip_scenario, half_no_skip_config)

    skip_wait_example = ThreeStationExample()
    skip_wait_scenario = skip_wait_example.build_scenario()
    skip_wait_config = skip_wait_example.build_ean_config(skip_wait_scenario)
    skip_wait_artifact = skip_wait_example.build_ean_artifact_builder(skip_wait_scenario, skip_wait_config).build(
        skip_wait_scenario,
        skip_wait_config,
    )

    assert len(full_artifact.cabin_starts) == 30
    assert len(half_no_skip_artifact.cabin_starts) == 15
    assert len(skip_wait_artifact.cabin_starts) == 15


def test_three_station_ean_ring_order_matches_physical_ring() -> None:
    assert build_three_station_ean_ring_switch_order() == (
        "M_entry_lr",
        "R_entry_lr",
        "M_entry_rl",
        "L_entry_rl",
    )


def test_three_station_ean_ring_order_is_validated_against_physical_nodes() -> None:
    scenario = build_three_station_scenario()
    broken_nodes = tuple(
        replace(node, kind=PhysicalNodeKind.CONNECTOR) if node.id == "M_entry_lr" else node
        for node in scenario.physical_nodes
    )
    broken_scenario = replace(scenario, physical_nodes=broken_nodes)

    with pytest.raises(ValueError, match="not an entry switch"):
        build_three_station_ean_ring_switch_order(broken_scenario)

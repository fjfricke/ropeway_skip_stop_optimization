from __future__ import annotations

from dataclasses import replace

import pytest

from ropeway_skip_stop_optimization.examples.three_station import build_three_station_scenario
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

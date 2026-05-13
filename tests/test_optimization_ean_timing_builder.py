from __future__ import annotations

from dataclasses import replace

import pytest

from ropeway_skip_stop_optimization.examples.three_station import build_three_station_scenario
from ropeway_skip_stop_optimization.examples.three_station_ean import build_three_station_ean_ring_switch_order
from ropeway_skip_stop_optimization.models import PhysicalNodeKind, TrackSegmentKind
from ropeway_skip_stop_optimization.optimization.ean import PhysicalSkipStopTimingBuilder


def test_physical_skip_stop_timing_builder_derives_three_station_timings() -> None:
    scenario = build_three_station_scenario()
    switch_cycle = build_three_station_ean_ring_switch_order(scenario)

    timings = PhysicalSkipStopTimingBuilder().build(scenario, switch_cycle)

    timing_by_switch = {timing.switch_id: timing for timing in timings}
    assert tuple(timing_by_switch) == switch_cycle

    middle_lr = timing_by_switch["M_entry_lr"]
    assert middle_lr.station_id == "M"
    assert middle_lr.skip_allowed is True
    assert middle_lr.entry_to_platform_entry_seconds == pytest.approx(5 / 5 + 3 / 2.75)
    assert middle_lr.min_platform_entry_to_platform_exit_seconds == pytest.approx(10 / 0.5)
    assert middle_lr.platform_exit_to_exit_switch_seconds == pytest.approx(3 / 2.75 + 5 / 5)
    assert middle_lr.skip_entry_to_exit_switch_seconds == pytest.approx(20 / 5)
    assert middle_lr.rope_to_next_switch_seconds == pytest.approx(150 / 5)

    right_terminal = timing_by_switch["R_entry_lr"]
    assert right_terminal.station_id == "R"
    assert right_terminal.skip_allowed is False
    assert right_terminal.entry_to_platform_entry_seconds == pytest.approx(3 / 2.75)
    assert right_terminal.min_platform_entry_to_platform_exit_seconds == pytest.approx(10 / 0.5)
    assert right_terminal.platform_exit_to_exit_switch_seconds == pytest.approx(3 / 2.75)
    assert right_terminal.skip_entry_to_exit_switch_seconds == pytest.approx(
        right_terminal.entry_to_platform_entry_seconds
        + right_terminal.min_platform_entry_to_platform_exit_seconds
        + right_terminal.platform_exit_to_exit_switch_seconds
    )
    assert right_terminal.rope_to_next_switch_seconds == pytest.approx(150 / 5)


def test_physical_skip_stop_timing_builder_rejects_service_route_without_station_segment() -> None:
    scenario = build_three_station_scenario()
    broken_segments = tuple(
        replace(segment, kind=TrackSegmentKind.CONNECTOR) if segment.id == "M_lr_platform" else segment
        for segment in scenario.track_segments
    )
    broken_scenario = replace(scenario, track_segments=broken_segments)

    with pytest.raises(ValueError, match="needs at least one station segment"):
        PhysicalSkipStopTimingBuilder().build(
            broken_scenario,
            build_three_station_ean_ring_switch_order(scenario),
        )


def test_physical_skip_stop_timing_builder_rejects_unknown_switch_cycle_node() -> None:
    scenario = build_three_station_scenario()

    with pytest.raises(ValueError, match="unknown physical node"):
        PhysicalSkipStopTimingBuilder().build(scenario, ("unknown_switch",))


def test_physical_skip_stop_timing_builder_rejects_non_entry_switch_cycle_node() -> None:
    scenario = build_three_station_scenario()
    broken_nodes = tuple(
        replace(node, kind=PhysicalNodeKind.CONNECTOR) if node.id == "M_entry_lr" else node
        for node in scenario.physical_nodes
    )
    broken_scenario = replace(scenario, physical_nodes=broken_nodes)

    with pytest.raises(ValueError, match="not an entry switch"):
        PhysicalSkipStopTimingBuilder().build(
            broken_scenario,
            build_three_station_ean_ring_switch_order(scenario),
        )

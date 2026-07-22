from __future__ import annotations

import pytest

from ropeway_skip_stop_optimization.examples.three_station import build_three_station_scenario
from ropeway_skip_stop_optimization.examples.three_station_ean import build_three_station_ean_ring_switch_order
from ropeway_skip_stop_optimization.optimization.ean import (
    EanCirculationPatternDefinition,
    NetworkSkipStopTimingBuilder,
    OperatingSpeedHeadwayDurationBuilder,
    PhysicalMovementNetworkBuilder,
    SkipStopTiming,
)


def test_operating_speed_headway_duration_builder_uses_required_spacing_and_operating_speeds() -> None:
    scenario = build_three_station_scenario()
    definition = EanCirculationPatternDefinition(
        id="test_pattern",
        state_node_ids=build_three_station_ean_ring_switch_order(scenario),
    )
    network = PhysicalMovementNetworkBuilder().build(scenario, definition)
    timings = NetworkSkipStopTimingBuilder().build(
        scenario, network, network.pattern(definition.id)
    )

    durations = OperatingSpeedHeadwayDurationBuilder().build(scenario, timings)

    required_spacing_m = scenario.operating.required_cabin_spacing_m
    assert set(durations.station_headway_seconds_by_station_id) == {"L", "M", "R"}
    assert set(durations.exit_switch_headway_seconds_by_switch_id) == {
        "M_entry_lr",
        "R_entry_lr",
        "M_entry_rl",
        "L_entry_rl",
    }
    assert all(
        seconds == pytest.approx(required_spacing_m / scenario.operating.station_speed_m_per_s)
        for seconds in durations.station_headway_seconds_by_station_id.values()
    )
    assert all(
        seconds == pytest.approx(required_spacing_m / scenario.operating.rope_speed_m_per_s)
        for seconds in durations.exit_switch_headway_seconds_by_switch_id.values()
    )


def test_operating_speed_headway_duration_builder_rejects_empty_or_duplicate_timings() -> None:
    scenario = build_three_station_scenario()

    with pytest.raises(ValueError, match="at least one timing"):
        OperatingSpeedHeadwayDurationBuilder().build(scenario, ())

    timing = _timing("sw_a", "A")
    with pytest.raises(ValueError, match="duplicate timing switch"):
        OperatingSpeedHeadwayDurationBuilder().build(scenario, (timing, timing))


def _timing(switch_id: str, station_id: str) -> SkipStopTiming:
    return SkipStopTiming(
        switch_id=switch_id,
        station_id=station_id,
        entry_to_platform_entry_seconds=2.0,
        min_platform_entry_to_platform_exit_seconds=5.0,
        platform_exit_to_exit_switch_seconds=3.0,
        skip_entry_to_exit_switch_seconds=4.0,
        rope_to_next_switch_seconds=10.0,
    )

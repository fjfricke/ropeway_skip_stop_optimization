from __future__ import annotations

import math

import pytest

from ropeway_skip_stop_optimization.optimization.ean import (
    EanCabinStart,
    EanCabinStartKind,
    EanConfig,
    RingSwitchVisitBuilder,
    SkipStopTiming,
    StationEanConfig,
    StationWaitingMode,
    build_ring_switch_transitions,
    calculate_min_max_switch_to_next_seconds,
    count_visits_by_cabin,
)


def test_calculate_min_max_switch_to_next_seconds_for_no_waiting_station() -> None:
    timing = _timing("sw_a", "A")
    station_config = StationEanConfig(station_id="A", waiting_mode=StationWaitingMode.NO_WAITING)

    min_seconds, max_seconds = calculate_min_max_switch_to_next_seconds(timing, station_config)

    assert min_seconds == 14.0
    assert max_seconds == 20.0


def test_calculate_min_max_switch_to_next_seconds_for_waiting_station() -> None:
    timing = _timing("sw_a", "A")
    station_config = StationEanConfig(station_id="A", waiting_mode=StationWaitingMode.END_OF_PLATFORM_WAIT)

    min_seconds, max_seconds = calculate_min_max_switch_to_next_seconds(timing, station_config)

    assert min_seconds == 14.0
    assert math.isinf(max_seconds)


def test_build_ring_switch_transitions_wraps_cycle() -> None:
    transitions = build_ring_switch_transitions(
        timings=(_timing("sw_a", "A"), _timing("sw_b", "B"), _timing("sw_c", "C")),
        station_configs=_station_configs("A", "B", "C"),
        switch_cycle=("sw_a", "sw_b", "sw_c"),
    )

    assert tuple((transition.from_switch_id, transition.to_switch_id) for transition in transitions) == (
        ("sw_a", "sw_b"),
        ("sw_b", "sw_c"),
        ("sw_c", "sw_a"),
    )
    assert tuple(transition.min_seconds for transition in transitions) == (14.0, 14.0, 14.0)


def test_ring_switch_visit_builder_builds_full_rotation_plus_boundary_visit() -> None:
    builder = RingSwitchVisitBuilder(switch_cycle=("sw_a", "sw_b", "sw_c"), safety_visit_margin=0)

    result = builder.build(
        config=_config(horizon_seconds=42.0),
        cabin_starts=(EanCabinStart(0, "sw_a", EanCabinStartKind.FIXED, 0.0),),
        timings=(_timing("sw_a", "A"), _timing("sw_b", "B"), _timing("sw_c", "C")),
    )

    assert tuple(visit.switch_id for visit in result.visits) == ("sw_a", "sw_b", "sw_c", "sw_a")
    assert tuple(visit.visit_index for visit in result.visits) == (0, 1, 2, 3)
    assert count_visits_by_cabin(result.visits) == {0: 4}


def test_ring_switch_visit_builder_respects_start_switch_and_margin() -> None:
    builder = RingSwitchVisitBuilder(switch_cycle=("sw_a", "sw_b", "sw_c"), safety_visit_margin=1)

    result = builder.build(
        config=_config(horizon_seconds=41.0),
        cabin_starts=(
            EanCabinStart(0, "sw_b", EanCabinStartKind.FIXED, 0.0),
            EanCabinStart(1, "sw_c", EanCabinStartKind.EARLIEST, 14.0),
        ),
        timings=(_timing("sw_a", "A"), _timing("sw_b", "B"), _timing("sw_c", "C")),
    )

    visits_by_cabin = {
        cabin_id: tuple(visit.switch_id for visit in result.visits if visit.cabin_id == cabin_id)
        for cabin_id in (0, 1)
    }
    assert visits_by_cabin[0] == ("sw_b", "sw_c", "sw_a", "sw_b")
    assert visits_by_cabin[1] == ("sw_c", "sw_a", "sw_b")
    assert count_visits_by_cabin(result.visits) == {0: 4, 1: 3}


def test_ring_switch_visit_builder_rejects_invalid_inputs() -> None:
    builder = RingSwitchVisitBuilder(switch_cycle=("sw_a", "sw_a"), safety_visit_margin=0)
    with pytest.raises(ValueError, match="duplicate switch_cycle"):
        builder.build(
            config=_config(horizon_seconds=42.0),
            cabin_starts=(EanCabinStart(0, "sw_a", EanCabinStartKind.FIXED, 0.0),),
            timings=(_timing("sw_a", "A"),),
        )

    builder = RingSwitchVisitBuilder(switch_cycle=("sw_a", "sw_b"), safety_visit_margin=0)
    with pytest.raises(ValueError, match="duplicate cabin"):
        builder.build(
            config=_config(horizon_seconds=42.0),
            cabin_starts=(
                EanCabinStart(0, "sw_a", EanCabinStartKind.FIXED, 0.0),
                EanCabinStart(0, "sw_b", EanCabinStartKind.FIXED, 0.0),
            ),
            timings=(_timing("sw_a", "A"), _timing("sw_b", "B")),
        )

    with pytest.raises(ValueError, match="outside switch_cycle"):
        builder.build(
            config=_config(horizon_seconds=42.0),
            cabin_starts=(EanCabinStart(0, "sw_x", EanCabinStartKind.FIXED, 0.0),),
            timings=(_timing("sw_a", "A"), _timing("sw_b", "B")),
        )

    with pytest.raises(ValueError, match="unknown timing"):
        builder.build(
            config=_config(horizon_seconds=42.0),
            cabin_starts=(EanCabinStart(0, "sw_a", EanCabinStartKind.FIXED, 0.0),),
            timings=(_timing("sw_a", "A"),),
        )


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


def _station_configs(*station_ids: str) -> tuple[StationEanConfig, ...]:
    return tuple(
        StationEanConfig(station_id=station_id, waiting_mode=StationWaitingMode.NO_WAITING)
        for station_id in station_ids
    )


def _config(horizon_seconds: float) -> EanConfig:
    return EanConfig(
        horizon_seconds=horizon_seconds,
        tail_seconds=0.0,
        cabin_capacity=8,
        station_configs=_station_configs("A", "B", "C"),
    )
